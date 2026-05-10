from typing import Optional
import logging
import os
import json
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Response

# Configuração de Logging para monitoramento
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

FILE_AUTH = "auth.json"


class CPFLScraper:
    """Classe responsável por realizar o scraping e extração de dados da CPFL."""

    def __init__(self):
        self.url_login = "https://www.cpfl.com.br/login"
        self.url_historico = "https://www.cpfl.com.br/agencia-virtual/pagina-inicial"
        self.consumo_valor: Optional[float] = None

    def _intercept_response(self, response: Response) -> None:
        """Filtra as respostas de rede para encontrar o JSON de consumo."""
        if "historico-consumo" in response.url or "validar-situacao" in response.url:
            try:
                data = response.json()
                if "Graficos" in data and data["Graficos"]:
                    # Obtém o último registro do primeiro gráfico
                    ultimo_registro = data["Graficos"][0]["Dados"][-1]
                    self.consumo_valor = float(ultimo_registro.get("Valor", 0))
                    logger.info(
                        f"Dados interceptados: {ultimo_registro.get('Categoria')} -> {self.consumo_valor} kWh")
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
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

    def run(self) -> Optional[float]:
        """Executa o fluxo principal de automação do browser."""
        with sync_playwright() as p:
            # browser = p.firefox.launch(headless=False)
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
                page.wait_for_timeout(10000)

                return self.consumo_valor

            except Exception as e:
                logger.error(f"Falha durante a automação: {e}")
                page.screenshot(path="error_screenshot.png")
                return None
            finally:
                browser.close()


class HomeAssistant:
    """Classe para integração com o Home Assistant via API REST."""

    def __init__(self, ha_url: str, token: str):
        self.ha_url = ha_url
        self.token = token

    def enviar_para_ha(self, entity_id: str, valor: float) -> Optional[str]:
        '''Envia o valor para o Home Assistant usando a API REST.'''

        url = f"{self.ha_url}/api/services/input_number/set_value"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {"entity_id": entity_id, "value": round(valor, 2)}
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"HA atualizado: {entity_id} = {valor}")
        return str(resp.status_code)


if __name__ == "__main__":
    load_dotenv()
    CPFL_USER = os.getenv("USER_NAME")
    CPFL_PASS = os.getenv("PASSWORD_CPFL")
    HA_URL = os.getenv("HA_URL")
    TOKEN = os.getenv("HA_TOKEN")

    scraper = CPFLScraper()
    valor_final = scraper.run()

    ha = HomeAssistant(HA_URL, TOKEN)

    if valor_final is not None:
        print(valor_final)
        resp = ha.enviar_para_ha("input_number.cpfl_consumo_mensal",
                                 float(valor_final))
        print(resp)
        # No script do SAAE:
        # enviar_para_ha("input_number.saae_consumo_mensal", consumo_m3)
    else:
        logger.warning("O script terminou sem conseguir capturar o consumo.")
