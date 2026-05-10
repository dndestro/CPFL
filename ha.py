"""
Importa histórico mensal de energia e água para o Home Assistant.
Execução única. Rode APÓS os sensores template já estarem criados e funcionando.

Dependências: pip install websockets
"""
import os
from dotenv import load_dotenv
import asyncio
import json
import csv
import websockets
from datetime import datetime, timezone, timedelta

# ── Configuração ──────────────────────────────────────────────────────────────
CSV_FILE = "historico.csv"
FUSO_BR = timezone(timedelta(hours=-3))
# ─────────────────────────────────────────────────────────────────────────────


def mes_para_timestamp(mes_str: str) -> str:
    """Converte '2020-01' para ISO8601 no primeiro dia do mês, meia-noite, BRT."""
    dt = datetime.strptime(mes_str, "%Y-%m").replace(
        tzinfo=FUSO_BR, hour=0, minute=0, second=0
    )
    return dt.isoformat()


def carregar_csv(caminho: str):
    energy_stats, water_stats = [], []
    with open(caminho, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            start = mes_para_timestamp(row["mes"].strip())
            kwh = float(row["cpfl_kwh"].strip())
            m3 = float(row["saae_m3"].strip())
            energy_stats.append(
                {"start": start, "mean": kwh, "min": kwh, "max": kwh})
            water_stats.append(
                {"start": start, "mean": m3,  "min": m3,  "max": m3})
    return energy_stats, water_stats


async def importar(ws, msg_id: int, statistic_id: str, name: str, unit: str, stats: list):
    payload = {
        "id": msg_id,
        "type": "recorder/import_statistics",
        "metadata": {
            "has_mean": True,
            "has_sum": False,
            "name": name,
            "source": "recorder",
            "statistic_id": statistic_id,
            "unit_of_measurement": unit,
        },
        "stats": stats,
    }
    await ws.send(json.dumps(payload))
    resp = json.loads(await ws.recv())
    if resp.get("success"):
        print(f"✓ {name}: {len(stats)} meses importados.")
    else:
        print(f"✗ Erro em {name}: {resp}")


async def main():
    load_dotenv()
    HA_WS_URL = os.getenv("HA_WS_URL")
    TOKEN = os.getenv("HA_TOKEN")

    energy_stats, water_stats = carregar_csv(CSV_FILE)

    async with websockets.connect(HA_WS_URL) as ws:
        await ws.recv()  # auth_required

        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth_resp = json.loads(await ws.recv())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError("Autenticação falhou. Verifique o TOKEN.")
        print("Autenticado no Home Assistant.")

        await importar(ws, 1,
                       statistic_id="sensor.cpfl_consumo_mensal",
                       name="CPFL Consumo Mensal",
                       unit="kWh",
                       stats=energy_stats,
                       )
        await importar(ws, 2,
                       statistic_id="sensor.saae_consumo_mensal",
                       name="SAAE Consumo Mensal",
                       unit="m³",
                       stats=water_stats,
                       )

asyncio.run(main())
