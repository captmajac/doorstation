[English](../../services/gpio.md) | **Deutsch**

# Dienst `gpio`

Liest Klingeltaster, Bewegungsmelder und Briefkastenkontakte, entprellt und drosselt sie und meldet jede Änderung per MQTT. Der Dienst trifft keine fachlichen Entscheidungen – ob angerufen wird, entscheidet `sip`; was „Post da“ bedeutet, die Hausautomation.

Unit: `doorstation-gpio` · Konfiguration: `/etc/doorstation/gpio.yaml` · Technik: libgpiod v2 (Kernel-Entprellung, Flanken-Ereignisse, kein Polling).

## Konfiguration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
chip: /dev/gpiochip0
inputs:
  bell:      { pin: 9,  kind: button, trigger: press, active: low,  pull: up,  debounce_ms: 50,  min_interval_s: 2,  ring: true, report_release: true }
  motion:    { pin: 7,  kind: state,  active: high, pull: off, debounce_ms: 0,   min_interval_s: 10, states: [idle, motion] }
  mail_flap: { pin: 19, kind: state,  active: low,  pull: up,  debounce_ms: 200, min_interval_s: 1,  states: [closed, open] }
  mail_door: { pin: 13, kind: state,  active: low,  pull: up,  debounce_ms: 200, min_interval_s: 1,  states: [closed, open] }
```

| Feld | Werte | Bedeutung |
|---|---|---|
| `pin` | BCM-Nummer | Eingang |
| `kind` | `button` \| `state` | Taster (Ereignis) oder Zustand |
| `active` | `high` \| `low` | Pegel, der „gedrückt“ bzw. den **zweiten** Eintrag von `states` bedeutet |
| `pull` | `off` \| `up` \| `down` | interner Widerstand |
| `debounce_ms` | ≥ 0 | Entprellung |
| `min_interval_s` | ≥ 0 | Drosselung (siehe unten) |
| `trigger` | `press` \| `release` | nur `button`: Flanke, die das Ereignis auslöst |
| `ring` | bool | nur `button`: löst zusätzlich `doorstation/event/ring` aus |
| `report_release` | bool | nur `button`: meldet beim Loslassen zusätzlich `released` |
| `states` | `[inaktiv, aktiv]` | nur `state`: Namen der beiden Zustände |

Eine fehlerhafte Konfiguration (unbekannter oder doppelter Schlüssel, doppelter Pin, fehlende Felder) verhindert den Start; die Meldung nennt den Eingang.

## MQTT

| Topic | Inhalt |
|---|---|
| `doorstation/gpio/input/<name>` (Zustand, retained) | `{"ts","state":"open"}` |
| `doorstation/gpio/input/<name>` (Taster) | `{"ts","event":"pressed"}`, mit `report_release` beim Loslassen `{"ts","event":"released"}` |
| `doorstation/event/ring` | `{"ts","source":"bell"}` – nur beim Drücken eines Tasters mit `ring: true` |
| `doorstation/gpio/status` | `online` / `offline` |

Der Dienst nimmt keine Befehle entgegen.

## Verhalten

- **Taster:** ein Ereignis pro Flanke; Festhalten erzeugt kein weiteres. Ereignisse innerhalb `min_interval_s` werden verworfen. `released` kommt nur, wenn das zugehörige Drücken gemeldet wurde.
- **Zustand:** wird retained gemeldet – beim Start und nach jeder Wiederverbindung nur, wenn er vom Stand im Broker abweicht. Drosselung mit Nachlauf: der erste Wechsel sofort, weitere innerhalb `min_interval_s` erst danach – der gemeldete Zustand stimmt spätestens `min_interval_s` nach dem letzten Wechsel.
- **Ohne MQTT-Verbindung** werden Tastendrücke verworfen (eine verspätete Klingel wäre schlimmer als keine); Zustände werden nach der Wiederverbindung nachgemeldet.

## Testen ohne Hardware

```bash
printf 'bell 1\nbell 0\nmail_flap 1\nsleep 1\nmail_flap 0\n' | doorstation-gpio --config gpio.yaml --simulate
```

Befehle zeilenweise: `<eingang> <0|1>` setzt den Rohpegel, `sleep <s>` wartet. Die Simulation nutzt die MQTT-Client-ID `doorstation-gpio-sim` und kann neben dem laufenden Dienst gestartet werden.
