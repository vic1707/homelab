# Home Assistant

Manual configuration snippets until this device is managed.

## Secret

Add the Home Assistant BMC account password to `secrets.yaml`:

```yaml
hydra_bmc_password: "same password as .secrets/devices/hydra.yml"
```

## Hydra power

Add to `configuration.yaml`:

```yaml
rest:
  - resource: https://10.0.10.10/redfish/v1/Systems/1
    authentication: basic
    username: homeassistant
    password: !secret hydra_bmc_password
    verify_ssl: false
    scan_interval: 15
    sensor:
      - name: Hydra power state
        unique_id: hydra_power_state
        value_template: "{{ value_json.PowerState }}"

rest_command:
  hydra_power:
    url: https://10.0.10.10/redfish/v1/Systems/1/Actions/ComputerSystem.Reset
    method: POST
    username: homeassistant
    password: !secret hydra_bmc_password
    verify_ssl: false
    content_type: application/json
    payload: '{"ResetType": "{{ reset_type }}"}'

template:
  - switch:
      - name: Hydra
        unique_id: hydra_power
        state: >-
          {{ states('sensor.hydra_power_state') in ['On', 'PoweringOn'] }}
        availability: >-
          {{ states('sensor.hydra_power_state') not in ['unknown', 'unavailable'] }}
        turn_on:
          - action: rest_command.hydra_power
            data:
              reset_type: On
        turn_off:
          - action: rest_command.hydra_power
            data:
              reset_type: GracefulShutdown
```

Check the Home Assistant configuration and restart it after changing
`configuration.yaml`.

## Dashboard

The primary button shows the state and requests a graceful shutdown when
turning Hydra off:

```yaml
type: button
entity: switch.hydra
name: Hydra
show_state: true
tap_action:
  action: toggle
  confirmation:
    text: Change Hydra power state?
```

Forced restart:

```yaml
type: button
name: Force-restart Hydra
icon: mdi:restart-alert
tap_action:
  action: perform-action
  perform_action: rest_command.hydra_power
  data:
    reset_type: ForceRestart
  confirmation:
    text: Force-restart Hydra?
```

Forced power-off:

```yaml
type: button
name: Force-off Hydra
icon: mdi:power-plug-off
tap_action:
  action: perform-action
  perform_action: rest_command.hydra_power
  data:
    reset_type: ForceOff
  confirmation:
    text: Immediately power off Hydra?
```
