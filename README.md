# Este script busca dados de consumo no site da CPFL e atualiza o Home Assistant com estes dados

No Home Assistant, deve ser criado um sensor como segue:

```yaml
sensor:
  - name: "CPFL Consumo Mensal"
    unique_id: "cpfl_consumo_mensal"
    state: "{{ states('input_number.cpfl_consumo_mensal') | float(0) }}"
    unit_of_measurement: "kWh"
    device_class: energy
    state_class: measurement
    icon: mdi:flash
```
Para rodar o script, criar um arquivo .env na mesma pasta do arquivo cpfl.py com os seguintes dados:
```
USER_NAME="seu usuário na CPFL"
PASSWORD_CPFL="sua senha na cpfl"
HA_URL=http://IpdoHomeAssistant:8123
HA_WS_URL=ws://IpdoHomeAssistant:8123/api/websocket
HA_TOKEN="token criado no Home Assistant"
```

Caso deseje importar dados históricos para o Home Assistant, utilizar o script ha.py.
Para utilizar este script, deve haver um arquivo csv com os dados históricos a serem importados na mesma pasta que o próprio script ha.py
O script faz a importação dos dados de consumo de energia elétrica (CPFL) e água (SAAE)
Exemplo para o arquivo csv:
```
mes,cpfl_kwh,saae_m3
2026-05,200,11
2026-06,230,13

```
