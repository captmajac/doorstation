[English](../installation.md) | **Deutsch**

# Installation und Betrieb

## 1. SD-Karte vorbereiten

Mit dem Raspberry Pi Imager:

- Betriebssystem: **Raspberry Pi OS Lite (64-bit)** (Debian 13 „Trixie“).
- Hostname, Benutzer, Zeitzone, Tastatur nach Wunsch.
- **SSH aktivieren**, am besten „nur Public-Key“ mit dem eigenen Schlüssel (`ssh-keygen -t ed25519`, Inhalt von `~/.ssh/id_ed25519.pub` eintragen).
- LAN empfohlen; WLAN funktioniert ebenfalls.

Die Karte läuft unverändert auf Pi 3 und Pi 4.

## 2. Installieren

Repo auf den Pi bringen (z. B. `git clone` oder `rsync`) und als root ausführen:

```bash
sudo ./install.sh
```

`install.sh` kann beliebig oft ausgeführt werden (auch für Updates: `git pull`, dann erneut ausführen). Es

- installiert die Pakete (Mosquitto, PipeWire, WirePlumber, baresip, Python),
- legt den Systembenutzer `doorstation`, die Verzeichnisse und je Dienst ein venv an,
- richtet den lokalen Mosquitto (nur `127.0.0.1`) und – falls konfiguriert – die Bridge ein,
- lädt den Paketfilter `doorstation-firewall`: SIP/RTP nur von der FritzBox (andere Ports unberührt),
- nutzt die FritzBox aus `sip.yaml` als Zeitserver (der Debian-Pool bleibt als Ausweichlösung; ein anderer Server über `time_server`, `null` behält die Systemvorgabe) – der Pi hat keine Echtzeituhr, und die FritzBox antwortet nach einem Stromausfall sofort,
- schaltet die UART für den PN532 frei, Bluetooth und serielle Konsole ab, die Onboard-Audioausgänge ab,
- legt fehlende Konfigurationen aus `config-examples/` unter `/etc/doorstation/` an (**bestehende werden nie überschrieben**),
- installiert und startet die systemd-Units `doorstation-firewall`, `-gpio`, `-baresip`, `-sip`, `-sound`, `-rfid` und `doorstation-baresip-restart.path`.

Meldet es „bitte neu starten“, einmal `sudo reboot`. Beim ersten Lauf fehlt noch das SIP-Passwort: SIP wird dann mit einer Warnung übersprungen, alles andere eingerichtet – nach Abschnitt 4 `install.sh` erneut ausführen. Warnungen stehen am Ende noch einmal gesammelt.

## 3. Konfigurieren

Alle Dateien unter `/etc/doorstation/`; nach Änderungen den jeweiligen Dienst neu starten (`sudo systemctl restart doorstation-<dienst>`). Ist die Konfiguration fehlerhaft, bleibt der Dienst stehen (`systemctl status` bzw. `journalctl -u doorstation-<dienst>` nennt Datei und Feld).

| Datei | Dienst | Beschreibung |
|---|---|---|
| `gpio.yaml` | `doorstation-gpio` | [dienste/gpio.md](dienste/gpio.md) |
| `sip.yaml` | `doorstation-sip` | [dienste/sip.md](dienste/sip.md) |
| `audio.yaml` | `doorstation-baresip` | [dienste/sip.md](dienste/sip.md#audio) |
| `sound.yaml` | `doorstation-sound` | [dienste/sound.md](dienste/sound.md) |
| `rfid.yaml` | `doorstation-rfid` | [dienste/rfid.md](dienste/rfid.md) |
| `bridge.yaml` | Mosquitto | Abschnitt 5 unten |
| `secrets/sip_password` | baresip | SIP-Passwort |
| `secrets/bridge_password` | Mosquitto | Passwort des MQTT-Servers der Hausautomation |

Jede Dienst-Konfiguration hat einen `mqtt`-Block (`host`, `port`, `prefix`, `heartbeat_s`). `prefix` ist ein einzelner Topic-Abschnitt (A–Z, a–z, 0–9, `_`, `-`). Doppelte Schlüssel in einer YAML-Datei gelten als Fehler.

Hinweis YAML: Werte, die mit `*` beginnen, in Anführungszeichen setzen (`"**701"`).

## 4. Geheimnisse ablegen

Passwörter verdeckt eingeben, damit sie weder im Terminal-Verlauf noch in Logs landen:

```bash
read -rsp "SIP-Passwort: " pw; echo; printf "%s\n" "$pw" | sudo install -m 600 /dev/stdin /etc/doorstation/secrets/sip_password; unset pw
```

Danach `sudo ./install.sh` (erzeugt daraus die baresip-Konfiguration). Für das Bridge-Passwort genauso mit `bridge_password`. Die Dateien gehören root (600); kein Dienst liest sie zur Laufzeit.

## 5. Bridge zur Hausautomation

`/etc/doorstation/bridge.yaml` (Vorlage `config-examples/bridge.yaml`):

```yaml
host: 192.168.178.10      # MQTT-Server der Hausautomation
port: 1026
username: doorstation
prefix: doorstation
```

Passwort in `/etc/doorstation/secrets/bridge_password`, dann `sudo ./install.sh`. Ohne `bridge.yaml` oder Passwort wird keine Bridge eingerichtet (bzw. eine vorhandene entfernt). Prüfen:

```bash
mosquitto_sub -v -t '$SYS/broker/connection/#' -W 2     # → …/doorstation-bridge/state 1
```

Einrichtung auf der IP-Symcon-Seite: [ip-symcon.md](ip-symcon.md).

## 6. Home Key koppeln

Siehe [dienste/rfid.md](dienste/rfid.md#home-key-koppeln). **Nach dem Koppeln sichern** (Abschnitt 7) – ohne die Paarungsdaten muss neu gekoppelt werden und alle Home-Key-IDs ändern sich.

## 7. Sicherung

```bash
sudo ./install.sh backup  /root/doorstation-backup.tar.gz
sudo ./install.sh restore /root/doorstation-backup.tar.gz
```

Gesichert werden `/etc/doorstation` (Konfiguration, Geheimnisse) und `/var/lib/doorstation` (SIP-Ziel, HomeKit-Paarung, Tondateien). Die Sicherung ist nur für root lesbar (600). Nach `restore` einmal `sudo ./install.sh` ausführen – erst dann gelten Bridge, baresip-Konto und Paketfilter aus der Sicherung. Eine bestehende Home-Key-Paarung lässt sich auch einzeln übernehmen: `sudo ./install.sh rfid-import <ordner mit hap.state und homekey.json>`.

## 8. Überwachung und Fehlersuche

```bash
systemctl status 'doorstation-*'
journalctl -u doorstation-sip -f
mosquitto_sub -v -t 'doorstation/#'
```

- `doorstation/<dienst>/status`: `online`, `degraded` (läuft, kann seine Aufgabe nicht erfüllen) oder `offline`. Wird alle `heartbeat_s` (300 s) wiederholt.
- `sudo ./install.sh audio-info` zeigt Soundkarten und Reglernamen.
