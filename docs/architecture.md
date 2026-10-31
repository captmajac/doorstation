**English** | [Deutsch](de/architektur.md)

# Architecture

## Principles

- Four **independent services** (`gpio`, `sip`, `sound`, `rfid`) run as systemd units on the Raspberry Pi. Each can be started, stopped, updated and tested on its own.
- The services talk **only to a local Mosquitto** (`127.0.0.1:1883`, not reachable from outside). They do not know the home automation.
- **Bell → call** runs entirely locally (`gpio` → `doorstation/event/ring` → `sip`). If the home automation or the network to it fails, the bell still rings.
- A **Mosquitto bridge** connects the local broker to an MQTT server of the home automation (e.g. a dedicated MQTT server instance in IP-Symcon).
- The home automation **decides** (open the door, announcement, push notification); the door station **reports** and **executes**.

```
                 ┌──────────────── Raspberry Pi ─────────────────┐
Bell/PIR/reed    →│ gpio  ──┐                                     │
PN532 (UART)    ←→│ rfid  ──┼─→ Mosquitto (local) ←─→ Bridge ─────┼──→ MQTT server of the home automation
FritzBox (SIP)  ←→│ sip   ──┤                                     │      (only doorstation/+/cmd back)
Speaker/mic     ←→│ sound ──┘   Audio: PipeWire + WebRTC echo cancel│
                 └───────────────────────────────────────────────┘
```

## MQTT interface

### Basic rules

- Prefix of all topics: `doorstation/` (configurable).
- MQTT 3.1.1. Payloads are JSON (UTF-8) with `ts` (ISO 8601 with time zone and milliseconds, e.g. `2026-10-11T17:29:27.072+02:00`).
- **States** are retained (QoS 1) – after a restart the home automation knows the current state right away. A state is only sent when its content changes: after a service restart or reconnect it is compared with the broker's retained message, and an unchanged state keeps its message and `ts`.
- **Events** are not retained.
- **Commands** go to `doorstation/<service>/cmd`. Invalid commands → `doorstation/<service>/error` `{"ts","message"}`.
- **Status** `doorstation/<service>/status`: plain text `online` | `degraded` | `offline`, retained. The broker sets `offline` via last will. The status is repeated from the main loop every `heartbeat_s` (default 300 s) – if the repetition stops, the service hangs.

### Topics

| Topic | Kind | Content |
|---|---|---|
| `doorstation/<service>/status` | state | `online` / `degraded` / `offline` |
| `doorstation/<service>/error` | event | `{"ts","message"}` |
| `doorstation/event/ring` | event | `{"ts","source":"bell"}` – the bell rang |
| `doorstation/gpio/input/<name>` | state or event | state: `{"ts","state":"open"}`; button: `{"ts","event":"pressed"\|"released"}` |
| `doorstation/sip/registration` | state | `{"ts","state":"registered"\|"failed"\|"unknown"}` |
| `doorstation/sip/call` | state | `{"ts","state":"idle"\|"calling"\|"active"\|"ended","direction","peer","reason"}` |
| `doorstation/sip/target` | state | `{"ts","target":"**701","muted":false}`, muted: `"target":null,"muted":true` |
| `doorstation/sip/dtmf` | event | `{"ts","key":"#"}` |
| `doorstation/sip/cmd` | command | `call`, `hangup`, `set_target` |
| `doorstation/sound/state` | state | `{"ts","state":"playing","name"}` or `{"ts","state":"idle"}` |
| `doorstation/sound/available` | state | `{"ts","names":[…]}` |
| `doorstation/sound/cmd` | command | `play`, `stop` |
| `doorstation/rfid/read` | event | `{"ts","type":"card"\|"homekey","id"}` |
| `doorstation/rfid/pairing` | state | `{"ts","paired":true}` |

Details on commands and fields are in the service docs in [services/](services/).

### Bridge to the home automation

Mosquitto connects as a client to the MQTT server of the home automation and copies selected topics:

- **out:** `doorstation/gpio/#`, `sip/status`, `sip/error`, `sip/call`, `sip/target`, `sip/registration`, `sound/#`, `rfid/status`, `rfid/pairing`, `rfid/error` with QoS 1 (delivered after an outage); `doorstation/event/#`, `doorstation/rfid/read` and `doorstation/sip/dtmf` with **QoS 0** (**not** delivered after an outage – a late bell, a late RFID event or a late `#` must not open a door).
- **in:** only `doorstation/+/cmd`, with **QoS 0**: commands sent during an outage expire instead of being delivered later (e.g. an announcement hours too late). The home automation can send commands but cannot fake events.
- The areas are listed one by one instead of `doorstation/#`: with overlapping rules Mosquitto uses the highest QoS, so `rfid/read` would be buffered after all.
- The home automation's broker also receives `$SYS/broker/connection/doorstation-bridge/state` (`1` connected, `0` disconnected) – a reliable sign of whether the Pi is reachable.

In addition, the home automation should drop events with an old `ts` (bell and DTMF > 30 s, RFID > 10 s). This also applies to button events under `gpio/input/…` (`pressed`), which are delivered with QoS 1 – use `event/ring` for automations. The door station itself drops `sip/cmd` `call` commands with a `ts` older than 30 s.

## Security

- Local broker on `127.0.0.1` only; from outside, only commands come in via the bridge.
- The Pi accepts SIP and RTP from the FritzBox only (nftables table `inet doorstation`, unit `doorstation-firewall`; `fritzbox` in `sip.yaml` must be an IPv4 address for this). Other ports are left alone. If a call still arrives that did not come via the FritzBox, the SIP adapter ends it right away; DTMF keys are only reported during our own call.
- Secrets (SIP password, bridge password) live in `/etc/doorstation/secrets/` (root, 700/600) and are read by `install.sh` only; the HomeKit pairing in `/var/lib/doorstation/rfid/` (700/600). Key material is never logged.
- The Home Key ID is a hash of the device's public key and contains no secret.
- Access is decided by the home automation only.

## Operation

- Raspberry Pi OS Lite 64-bit (Debian 13 "Trixie"), Python 3.13, one venv per service in `/opt/doorstation/venv/`.
- All services run as the system user `doorstation`; PipeWire as its user service.
- Units restart automatically on errors and never give up for good. Exception: on a configuration error (exit 2) a service stays stopped instead of restarting every 2 s – status `offline`, message in the journal; after fixing it, `sudo systemctl restart doorstation-<service>`.
- The units are hardened with systemd (`NoNewPrivileges`, `ProtectSystem=strict`, no capabilities, only the required devices and write paths, system call filter). A service may only write below `/var/lib/doorstation/<service>` (sip, rfid).
- Logs go to the systemd journal only (`journalctl -u doorstation-<service>`).

| Path | Content |
|---|---|
| `/etc/doorstation/<service>.yaml` | configuration per service |
| `/etc/doorstation/secrets/` | passwords (600) |
| `/var/lib/doorstation/` | runtime data: SIP target, baresip configuration, HomeKit pairing, sound files, PipeWire settings |
| `/opt/doorstation/` | code and venvs |
