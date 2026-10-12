**English** | [Deutsch](../de/dienste/gpio.md)

# Service `gpio`

Reads the bell button, the motion sensor and the mailbox contacts, debounces and throttles them and reports every change via MQTT. The service makes no business decisions – `sip` decides whether to call; the home automation decides what "you have mail" means.

Unit: `doorstation-gpio` · Configuration: `/etc/doorstation/gpio.yaml` · Technology: libgpiod v2 (kernel debouncing, edge events, no polling).

## Configuration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
chip: /dev/gpiochip0
inputs:
  bell:      { pin: 9,  kind: button, trigger: press, active: low,  pull: up,  debounce_ms: 50,  min_interval_s: 2,  ring: true, report_release: true }
  motion:    { pin: 7,  kind: state,  active: high, pull: off, debounce_ms: 0,   min_interval_s: 10, states: [idle, motion] }
  mail_flap: { pin: 19, kind: state,  active: low,  pull: up,  debounce_ms: 200, min_interval_s: 1,  states: [closed, open] }
  mail_door: { pin: 13, kind: state,  active: low,  pull: up,  debounce_ms: 200, min_interval_s: 1,  states: [closed, open] }
```

| Field | Values | Meaning |
|---|---|---|
| `pin` | BCM number | input |
| `kind` | `button` \| `state` | button (event) or state |
| `active` | `high` \| `low` | level that means "pressed" or the **second** entry of `states` |
| `pull` | `off` \| `up` \| `down` | internal resistor |
| `debounce_ms` | ≥ 0 | debouncing |
| `min_interval_s` | ≥ 0 | throttling (see below) |
| `trigger` | `press` \| `release` | `button` only: edge that triggers the event |
| `ring` | bool | `button` only: also triggers `doorstation/event/ring` |
| `report_release` | bool | `button` only: also reports `released` on release |
| `states` | `[inactive, active]` | `state` only: names of the two states |

An invalid configuration (unknown or duplicate key, pin used twice, missing fields) prevents the start; the message names the input.

## MQTT

| Topic | Content |
|---|---|
| `doorstation/gpio/input/<name>` (state, retained) | `{"ts","state":"open"}` |
| `doorstation/gpio/input/<name>` (button) | `{"ts","event":"pressed"}`, with `report_release` also `{"ts","event":"released"}` on release |
| `doorstation/event/ring` | `{"ts","source":"bell"}` – only when a button with `ring: true` is pressed |
| `doorstation/gpio/status` | `online` / `offline` |

The service accepts no commands.

## Behavior

- **Button:** one event per edge; holding it produces no further event. Events within `min_interval_s` are dropped. `released` only comes if the matching press was reported.
- **State:** at start and after every reconnect all states are reported retained. Throttling with a trailing update: the first change immediately, further changes within `min_interval_s` only afterwards – the reported state is correct at the latest `min_interval_s` after the last change.
- **Without an MQTT connection** button presses are dropped (a late ring would be worse than none); states are reported after reconnecting.

## Testing without hardware

```bash
printf 'bell 1\nbell 0\nmail_flap 1\nsleep 1\nmail_flap 0\n' | doorstation-gpio --config gpio.yaml --simulate
```

Commands line by line: `<input> <0|1>` sets the raw level, `sleep <s>` waits. The simulation uses the MQTT client ID `doorstation-gpio-sim` and can run next to the running service.
