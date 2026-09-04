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
  - resource: https://hydra_ipmi.lan/redfish/v1/Systems/1
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
    url: https://hydra_ipmi.lan/redfish/v1/Systems/1/Actions/ComputerSystem.Reset
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
          {{ has_value('sensor.hydra_power_state') }}
        turn_on:
          - action: rest_command.hydra_power
            data:
              reset_type: "On"
        turn_off:
          - action: rest_command.hydra_power
            data:
              reset_type: "GracefulShutdown"

  - button:
      - name: Hydra Force On
        unique_id: hydra_force_on
        icon: mdi:power
        press:
          - action: rest_command.hydra_power
            data:
              reset_type: "ForceOn"

      - name: Hydra Graceful Restart
        unique_id: hydra_graceful_restart
        icon: mdi:restart
        press:
          - action: rest_command.hydra_power
            data:
              reset_type: "GracefulRestart"

      - name: Hydra Force Restart
        unique_id: hydra_force_restart
        icon: mdi:restart-alert
        press:
          - action: rest_command.hydra_power
            data:
              reset_type: "ForceRestart"

      - name: Hydra Power Cycle
        unique_id: hydra_power_cycle
        icon: mdi:power-cycle
        press:
          - action: rest_command.hydra_power
            data:
              reset_type: "PowerCycle"

      - name: Hydra Force Off
        unique_id: hydra_force_off
        icon: mdi:power-plug-off
        press:
          - action: rest_command.hydra_power
            data:
              reset_type: "ForceOff"
```

Keep all Redfish reset values quoted. In particular, an unquoted `On` can
be interpreted by YAML as the boolean `true`, causing the BMC to receive
`"True"` instead of the Redfish enum value `"On"`.

The BMC advertises the following reset operations:

| Redfish value | Home Assistant control |
| --- | --- |
| `On` | Turn `switch.hydra` on |
| `GracefulShutdown` | Turn `switch.hydra` off |
| `ForceOn` | `button.hydra_force_on` |
| `GracefulRestart` | `button.hydra_graceful_restart` |
| `ForceRestart` | `button.hydra_force_restart` |
| `PowerCycle` | `button.hydra_power_cycle` |
| `ForceOff` | `button.hydra_force_off` |
| `Nmi` | `button.hydra_nmi` |

`ForceRestart`, `PowerCycle`, `ForceOff`, and `Nmi` are destructive or
diagnostic operations and should require confirmation on the dashboard.

Check the Home Assistant configuration and restart it after changing
`configuration.yaml`.

## Dashboard

The following uses only built-in Home Assistant cards.

The main Hydra button performs normal power control: powering on uses the
Redfish `On` action and powering off requests a graceful shutdown.

Additional buttons expose the other reset actions supported by the BMC.

```yaml
type: vertical-stack
cards:
  - type: button
    entity: switch.hydra
    name: Hydra
    icon: mdi:server
    show_state: true
    tap_action:
      action: toggle
      confirmation:
        text: Change Hydra power state?
    hold_action:
      action: more-info

  - type: grid
    columns: 2
    square: false
    cards:
      - type: button
        entity: button.hydra_force_on
        name: Force On
        icon: mdi:power
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.hydra_force_on
          confirmation:
            text: Force Hydra on?

      - type: button
        entity: button.hydra_graceful_restart
        name: Restart
        icon: mdi:restart
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.hydra_graceful_restart
          confirmation:
            text: Gracefully restart Hydra?

      - type: button
        entity: button.hydra_force_restart
        name: Force Restart
        icon: mdi:restart-alert
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.hydra_force_restart
          confirmation:
            text: Force restart Hydra?

      - type: button
        entity: button.hydra_power_cycle
        name: Power Cycle
        icon: mdi:power-cycle
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.hydra_power_cycle
          confirmation:
            text: Power cycle Hydra?

      - type: button
        entity: button.hydra_force_off
        name: Force Off
        icon: mdi:power-plug-off
        tap_action:
          action: perform-action
          perform_action: button.press
          target:
            entity_id: button.hydra_force_off
          confirmation:
            text: Immediately force Hydra off?
```
