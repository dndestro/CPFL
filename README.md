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
Para rodar o script, criar um arquivo .env com os seguintes dados:
```
USER_NAME="seu usuário na CPFL"
PASSWORD_CPFL="sua senha na cpfl"
HA_URL=http://IpdoHomeAssistant:8123
HA_WS_URL=ws://IpdoHomeAssistant:8123/api/websocket
HA_TOKEN="token criado no Home Assistant"
