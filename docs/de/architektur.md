[English](../architecture.md) | **Deutsch**

# Architektur

## Grundprinzip

- Vier **eigenständige Dienste** (`gpio`, `sip`, `sound`, `rfid`) laufen als systemd-Units auf dem Raspberry Pi. Jeder lässt sich einzeln starten, stoppen, aktualisieren und testen.
- Die Dienste sprechen **nur mit einem lokalen Mosquitto** (`127.0.0.1:1883`, von außen nicht erreichbar). Sie kennen die Hausautomation nicht.
- **Klingel → Anruf** läuft vollständig lokal (`gpio` → `doorstation/event/ring` → `sip`). Fällt die Hausautomation oder das Netz zu ihr aus, klingelt es trotzdem.
- Eine **Mosquitto-Bridge** verbindet den lokalen Broker mit einem MQTT-Server der Hausautomation (z. B. eine eigene MQTT-Server-Instanz in IP-Symcon).
- Die Hausautomation **entscheidet** (Tür öffnen, Ansage, Push-Nachricht); die Türstation **meldet** und **führt aus**.

```
                 ┌──────────────── Raspberry Pi ─────────────────┐
Klingel/PIR/Reed →│ gpio  ──┐                                     │
PN532 (UART)    ←→│ rfid  ──┼─→ Mosquitto (lokal) ←─→ Bridge ─────┼──→ MQTT-Server der Hausautomation
FritzBox (SIP)  ←→│ sip   ──┤                                     │      (nur doorstation/+/cmd zurück)
Lautsprecher/Mic←→│ sound ──┘   Audio: PipeWire + WebRTC-Echo-Cancel│
                 └───────────────────────────────────────────────┘
```

## MQTT-Schnittstelle

### Grundregeln

- Präfix aller Topics: `doorstation/` (einstellbar).
- MQTT 3.1.1. Nutzdaten JSON (UTF-8) mit `ts` (ISO 8601 mit Zeitzone und Millisekunden, z. B. `2026-10-11T17:29:27.072+02:00`).
- **Zustände** retained (QoS 1) – nach einem Neustart kennt die Hausautomation sofort den aktuellen Stand. Ein Zustand wird nur gesendet, wenn sich sein Inhalt ändert: Nach einem Neustart des Dienstes oder einer Wiederverbindung wird er mit der retained Nachricht des Brokers verglichen; ein unveränderter Zustand behält seine Nachricht samt `ts`.
- **Ereignisse** nicht retained.
- **Befehle** an `doorstation/<dienst>/cmd`. Ungültige Befehle → `doorstation/<dienst>/error` `{"ts","message"}`.
- **Status** `doorstation/<dienst>/status`: Klartext `online` | `degraded` | `offline`, retained. `offline` setzt der Broker per Last Will. Der Status wird alle `heartbeat_s` (Vorgabe 300 s) aus der Hauptschleife wiederholt – bleibt die Wiederholung aus, hängt der Dienst.

### Topics

| Topic | Art | Inhalt |
|---|---|---|
| `doorstation/<dienst>/status` | Zustand | `online` / `degraded` / `offline` |
| `doorstation/<dienst>/error` | Ereignis | `{"ts","message"}` |
| `doorstation/event/ring` | Ereignis | `{"ts","source":"bell"}` – es hat geklingelt |
| `doorstation/gpio/input/<name>` | Zustand bzw. Ereignis | Zustand: `{"ts","state":"open"}`; Taster: `{"ts","event":"pressed"\|"released"}` |
| `doorstation/sip/registration` | Zustand | `{"ts","state":"registered"\|"failed"\|"unknown"}` |
| `doorstation/sip/call` | Zustand | `{"ts","state":"idle"\|"calling"\|"active"\|"ended","direction","peer","reason"}` |
| `doorstation/sip/target` | Zustand | `{"ts","target":"**701","muted":false}`, stumm: `"target":null,"muted":true` |
| `doorstation/sip/dtmf` | Ereignis | `{"ts","key":"#"}` |
| `doorstation/sip/cmd` | Befehl | `call`, `hangup`, `set_target` |
| `doorstation/sound/state` | Zustand | `{"ts","state":"playing","name"}` bzw. `{"ts","state":"idle"}` |
| `doorstation/sound/available` | Zustand | `{"ts","names":[…]}` |
| `doorstation/sound/cmd` | Befehl | `play`, `stop` |
| `doorstation/rfid/read` | Ereignis | `{"ts","type":"card"\|"homekey","id"}` |
| `doorstation/rfid/pairing` | Zustand | `{"ts","paired":true}` |

Details zu Befehlen und Feldern in den Dienst-Dokus unter [dienste/](dienste/).

### Bridge zur Hausautomation

Mosquitto verbindet sich als Client mit dem MQTT-Server der Hausautomation und kopiert ausgewählte Topics:

- **hinaus:** `doorstation/gpio/#`, `sip/status`, `sip/error`, `sip/call`, `sip/target`, `sip/registration`, `sound/#`, `rfid/status`, `rfid/pairing`, `rfid/error` mit QoS 1 (werden nach einem Ausfall nachgeliefert); `doorstation/event/#`, `doorstation/rfid/read` und `doorstation/sip/dtmf` mit **QoS 0** (werden **nicht** nachgeliefert – eine verspätete Klingel, ein verspätetes RFID-Ereignis oder ein verspätetes `#` soll keine Tür öffnen).
- **herein:** nur `doorstation/+/cmd`, mit **QoS 0**: Während eines Ausfalls gesendete Befehle verfallen, statt später nachgeliefert zu werden (z. B. eine Ansage Stunden zu spät). Die Hausautomation kann also Befehle senden, aber keine Ereignisse vortäuschen.
- Die Bereiche sind einzeln aufgeführt statt `doorstation/#`: Mosquitto verwendet bei überlappenden Regeln die höchste QoS, `rfid/read` würde sonst doch gepuffert.
- Der Broker der Hausautomation erhält zusätzlich `$SYS/broker/connection/doorstation-bridge/state` (`1` verbunden, `0` getrennt) – ein zuverlässiges Zeichen, ob der Pi erreichbar ist.

Zusätzlich sollte die Hausautomation Ereignisse mit altem `ts` verwerfen (Klingel und DTMF > 30 s, RFID > 10 s). Das gilt auch für Taster-Ereignisse unter `gpio/input/…` (`pressed`), die mit QoS 1 nachgeliefert werden – für Automatiken `event/ring` verwenden. Befehle `sip/cmd` `call` mit `ts` älter als 30 s verwirft die Türstation selbst.

## Sicherheit

- Lokaler Broker nur auf `127.0.0.1`; von außen kommen über die Bridge nur Befehle herein.
- SIP und RTP nimmt der Pi nur von der FritzBox an (nftables-Tabelle `inet doorstation`, Unit `doorstation-firewall`; `fritzbox` in `sip.yaml` muss dafür eine IPv4-Adresse sein). Andere Ports bleiben unberührt. Kommt trotzdem ein Anruf nicht über die FritzBox, beendet der SIP-Adapter ihn sofort; DTMF-Tasten werden nur im eigenen Gespräch gemeldet.
- Geheimnisse (SIP-Passwort, Bridge-Passwort) liegen in `/etc/doorstation/secrets/` (root, 700/600) und werden nur von `install.sh` gelesen; die HomeKit-Paarung in `/var/lib/doorstation/rfid/` (700/600). Schlüsselmaterial wird nie geloggt.
- Die Home-Key-ID ist ein Hash über den öffentlichen Schlüssel des Geräts und enthält kein Geheimnis.
- Über den Zutritt entscheidet ausschließlich die Hausautomation.

## Betrieb

- Raspberry Pi OS Lite 64-bit (Debian 13 „Trixie“), Python 3.13, je Dienst ein eigenes venv unter `/opt/doorstation/venv/`.
- Alle Dienste laufen als Systembenutzer `doorstation`; PipeWire als dessen Benutzerdienst.
- Units starten bei Fehlern automatisch neu und geben nie endgültig auf. Ausnahme: Bei einem Konfigurationsfehler (Exit 2) bleibt ein Dienst stehen, statt alle 2 s neu zu starten – Status `offline`, Meldung im Journal; nach der Korrektur `sudo systemctl restart doorstation-<dienst>`.
- Die Units sind mit systemd gehärtet (`NoNewPrivileges`, `ProtectSystem=strict`, keine Capabilities, nur die nötigen Geräte und Schreibpfade, Systemaufruf-Filter). Jeder Dienst darf nur unter `/var/lib/doorstation/<dienst>` schreiben (sip, rfid).
- Logs nur im systemd-Journal (`journalctl -u doorstation-<dienst>`).

| Pfad | Inhalt |
|---|---|
| `/etc/doorstation/<dienst>.yaml` | Konfiguration je Dienst |
| `/etc/doorstation/secrets/` | Passwörter (600) |
| `/var/lib/doorstation/` | Laufzeitdaten: SIP-Ziel, baresip-Konfiguration, HomeKit-Paarung, Tondateien, PipeWire-Einstellungen |
| `/opt/doorstation/` | Code und venvs |
