from typing import Optional
import asyncio
import json
import logging
import os
import json
import requests
import websockets
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Response

# Configuração de Logging para monitoramento
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    filename="cpfl.log",
    filemode="a"
)
logger = logging.getLogger(__name__)

# ── Configuração ──────────────────────────────────────────────────────────────
FILE_AUTH = "auth.json"
STATE_FILE = "import_state.json"
ENTITY_CPFL = "input_number.cpfl_consumo_mensal"
STATISTIC_ID_CPFL = "sensor.cpfl_consumo_mensal"
FUSO_BR = timezone(timedelta(hours=-3))


def mes_atual() -> str:
    return datetime.now(FUSO_BR).strftime("%Y-%m")


def inicio_do_mes_iso(mes_str: str) -> str:
    dt = datetime.strptime(mes_str, "%m/%Y").replace(
        tzinfo=FUSO_BR,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )
    return dt.isoformat()


class CPFLScraper:
    """Classe responsável por realizar o scraping e extração de dados da CPFL."""

    def __init__(self):
        self.url_login = "https://www.cpfl.com.br/login"
        self.url_historico = "https://www.cpfl.com.br/agencia-virtual/pagina-inicial"
        self.consumo_valor: Optional[float] = None
        self.consumo_data: Optional[str] = None

    def _intercept_response(self, response: Response) -> None:
        """Filtra as respostas de rede para encontrar o JSON de consumo."""
        if "historico-consumo" in response.url or "validar-situacao" in response.url:
            try:
                data = response.json()
                if "Graficos" in data and data["Graficos"]:
                    # Obtém o último registro do primeiro gráfico
                    ultimo_registro = data["Graficos"][0]["Dados"][-1]
                    self.consumo_valor = float(ultimo_registro.get("Valor", 0))
                    self.consumo_data = ultimo_registro.get("Categoria", None)
                    logger.info(
                        f"Dados interceptados: {ultimo_registro.get('Categoria')} -> {self.consumo_valor} kWh")
            except Exception as e:
                logger.debug(
                    f"Resposta ignorada ou erro ao processar JSON: {e}")

    def _login(self, page):
        """Função dedicada a realizar o login e aceitar cookies."""

        logger.info("Realizando login...")
        page.fill('input[id="signInName"]', CPFL_USER)
        page.fill('input[id="password"]', CPFL_PASS)
        page.click('button[id="next"]')
        page.wait_for_load_state("networkidle")

        logger.info("Aguardando liberação da tela (modal/overlay)...")
        page.wait_for_selector(
            '.modal-template, .overlay, .loading', state='hidden')

        # Aceita cookies se aparecerem
        try:
            page.get_by_role(
                "button", name="Aceitar todos os cookies").click(timeout=5000)
        except Exception:
            pass

        # Espera um elemento que só existe na área logada para confirmar o sucesso
        page.wait_for_selector('a[title="Histórico de consumo"]')

        # Salva o estado para a próxima vez
        page.context.storage_state(path=FILE_AUTH)
        logger.info("Sessão salva com sucesso!")

    def run(self) -> Optional[tuple[str, float]]:
        """Executa o fluxo principal de automação do browser."""
        with sync_playwright() as p:

            browser = p.chromium.launch(headless=False, devtools=True)

            # Tenta carregar o contexto existente
            if os.path.exists(FILE_AUTH):
                context = browser.new_context(storage_state=FILE_AUTH,
                                              viewport={'width': 1280, 'height': 720})
            else:
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 720})

            page = context.new_page()

            # Registra o interceptador de rede
            page.set_default_timeout(60000)
            page.on("response", self._intercept_response)

            try:
                logger.info("Acessando ao portal CPFL...")

                page.goto(self.url_historico, wait_until="networkidle")

                if "login" in page.url or page.locator('button[id="next"]').is_visible():
                    logger.info(
                        "Sessão expirada ou inexistente. Iniciando login...")
                    self._login(page)
                else:
                    logger.info("Sessão válida! Pulando login.")

                logger.info("Aguardando histórico de consumo")
                page.wait_for_selector(
                    'a[title="Histórico de consumo"]')
                page.get_by_title("Histórico de consumo", exact=True).click()

                # Tempo de segurança para a requisição de rede ser disparada
                page.wait_for_timeout(15000)
                if self.consumo_valor is None or self.consumo_data is None:
                    raise RuntimeError(
                        "Não foi possível capturar o consumo. Verifique os logs para detalhes.")
                return self.consumo_data,   self.consumo_valor

            except Exception as e:
                logger.error(f"Falha durante a automação: {e}")
                page.screenshot(path="error_screenshot.png")
                return None
            finally:
                browser.close()


class HomeAssistant:
    """Atualiza o Home Assistant via REST e websocket."""

    def __init__(self, ha_url: str, token: str, ha_ws_url: str):
        self.ha_url = ha_url
        self.token = token
        self.ha_ws_url = ha_ws_url

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def verificar_entidade(self, entity_id: str) -> dict:
        url = f"{self.ha_url}/api/states/{entity_id}"
        resp = requests.get(url, headers=self._headers(), timeout=10)

        if resp.status_code == 404:
            raise RuntimeError(
                f"A entidade '{entity_id}' não existe no Home Assistant. "
                f"Crie o helper input_number antes de rodar o script."
            )

        resp.raise_for_status()
        return resp.json()

    def atualizar_input_number(self, entity_id: str, valor: float) -> None:
        self.verificar_entidade(entity_id)

        url = f"{self.ha_url}/api/services/input_number/set_value"
        payload = {
            "entity_id": entity_id,
            "value": round(float(valor), 2),
        }

        resp = requests.post(url, headers=self._headers(),
                             json=payload, timeout=10)
        resp.raise_for_status()

        estado = self.verificar_entidade(entity_id)
        logger.info(f"{entity_id} atualizado para: {estado['state']}")

    async def importar_estatistica_mensal(
        self,
        statistic_id: str,
        name: str,
        unit: str,
        start_iso: str,
        value: float
    ) -> None:
        async with websockets.connect(self.ha_ws_url) as ws:
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                raise RuntimeError(f"Websocket inesperado: {msg}")

            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_resp = json.loads(await ws.recv())
            if auth_resp.get("type") != "auth_ok":
                raise RuntimeError("Autenticação websocket falhou.")

            payload = {
                "id": 1,
                "type": "recorder/import_statistics",
                "metadata": {
                    "has_mean": True,
                    "has_sum": False,
                    "name": name,
                    "source": "recorder",
                    "statistic_id": statistic_id,
                    "unit_of_measurement": unit,
                },
                "stats": [
                    {
                        "start": start_iso,
                        "mean": float(value),
                        "min": float(value),
                        "max": float(value),
                    }
                ],
            }

            await ws.send(json.dumps(payload))
            resp = json.loads(await ws.recv())

            if not resp.get("success"):
                raise RuntimeError(f"Falha ao importar estatística: {resp}")

            logger.info(
                f"Estatística importada com sucesso para {statistic_id} em {start_iso}")


def main():
    load_dotenv()

    global CPFL_USER, CPFL_PASS
    CPFL_USER = os.getenv("USER_NAME")
    CPFL_PASS = os.getenv("PASSWORD_CPFL")
    HA_URL = os.getenv("HA_URL")
    HA_WS_URL = os.getenv("HA_WS_URL")
    TOKEN = os.getenv("HA_TOKEN")

    if not CPFL_USER or not CPFL_PASS or not HA_URL or not HA_WS_URL or not TOKEN:
        raise RuntimeError(
            "Verifique o .env: USER_NAME, PASSWORD_CPFL, HA_URL, HA_WS_URL e HA_TOKEN."
        )

    scraper = CPFLScraper()
    mes, consumo = scraper.run()

    if mes is None or consumo is None:
        logger.warning("O script terminou sem conseguir capturar o consumo.")
        return

    inicio_mes = inicio_do_mes_iso(mes)
    logger.info(
        f"Consumo capturado da CPFL: {mes}, {consumo} kWh")

    ha = HomeAssistant(HA_URL, TOKEN, HA_WS_URL)

    # 1) Atualiza o valor atual na interface do home assistant
    # ha.atualizar_input_number(ENTITY_CPFL, consumo)

    asyncio.run(ha.importar_estatistica_mensal(
        statistic_id=STATISTIC_ID_CPFL,
        name="CPFL Consumo Mensal",
        unit="kWh",
        start_iso=inicio_mes,
        value=consumo
    ))


if __name__ == "__main__":
    main()
