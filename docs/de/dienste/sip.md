[English](../../services/sip.md) | **Deutsch**

# Dienst `sip`

Sprechverbindung zwischen Tür und Haustelefonen über die FritzBox:

- Klingeln → Anruf an ein umschaltbares internes Ziel (Nummer oder Gruppe), stumm schaltbar.
- Von innen anrufbar; Anrufe über die FritzBox werden automatisch angenommen.
- DTMF-Tasten während des Gesprächs werden gemeldet (z. B. `#` → Türöffner in der Hausautomation).
- Echo- und Rauschunterdrückung über PipeWire; das Freizeichen der FritzBox ist draußen hörbar.

Units: `doorstation-baresip` (SIP/Audio, [baresip](https://github.com/baresip/baresip) aus Debian) und `doorstation-sip` (Adapter mit den Regeln) · Konfiguration: `/etc/doorstation/sip.yaml`, `/etc/doorstation/audio.yaml`.

## FritzBox

*Telefonie → Telefoniegeräte → Neues Gerät → Telefon → LAN/WLAN (IP-Telefon)*. Eigene interne Nummer (z. B. `**629`), Benutzername **ohne Umlaute** (die FritzBox verwirft Anmeldungen mit Umlaut kommentarlos). Passwort nach `/etc/doorstation/secrets/sip_password` ([installation.md](../installation.md#4-geheimnisse-ablegen)), dann `sudo ./install.sh`.

Empfehlung: Für dieses Telefoniegerät in der FritzBox ausgehende Anrufe nach extern sperren (Rufsperre). Die Türstation ruft nur interne Nummern an; so kann auch ein fehlerhafter oder fremder Befehl keine kostenpflichtigen Nummern wählen.

## Konfiguration `sip.yaml`

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
fritzbox: 192.168.178.1
username: Tuerstation        # ohne Umlaute
default_target: "**701"      # Startziel, solange keins per set_target gesetzt ist; null = stumm
ring_timeout_s: 30           # Auflegen, wenn niemand abnimmt
max_call_s: 120              # Höchstdauer jedes Gesprächs
cooldown_s: 5                # Sperrzeit nach Gesprächsende
healthcheck_s: 30            # Abfrageintervall baresip
command_max_age_s: 30        # ältere call-Befehle (ts) werden verworfen
# time_server: 192.168.178.1 # optional: Zeitserver des Pi; Vorgabe: fritzbox, null = Systemvorgabe
```

Das per `set_target` gesetzte Ziel wird in `/var/lib/doorstation/sip/target.json` gespeichert und gilt über Neustarts hinweg; `default_target` ist nur der Startwert.

## MQTT

| Topic | Inhalt |
|---|---|
| `doorstation/sip/call` (retained) | `{"ts","state","direction","peer","reason"}` |
| `doorstation/sip/target` (retained) | `{"ts","target":"**701"}` bzw. `null` |
| `doorstation/sip/registration` (retained) | `registered` / `failed` / `unknown` |
| `doorstation/sip/dtmf` | `{"ts","key":"#"}` |
| `doorstation/sip/status` | `online` / `degraded` (nicht angemeldet bzw. baresip antwortet nicht) / `offline` |
| `doorstation/sip/error` | ungültige Befehle |

**Befehle** an `doorstation/sip/cmd`:

| Befehl | Wirkung |
|---|---|
| `{"action":"call"}` | wie Klingeln, an das aktuelle Ziel |
| `{"action":"call","target":"**610"}` | Anruf an ein anderes Ziel |
| `{"action":"hangup"}` | Gespräch beenden |
| `{"action":"set_target","target":"**701"}` | Ziel setzen (gespeichert) |
| `{"action":"set_target","target":null}` | stumm: Klingeln löst keinen Anruf aus |

Ziele: Ziffern, `*`, `#`, max. 20 Zeichen. Befehle dürfen `ts` enthalten (ISO 8601 **mit Zeitzone**); `call` mit `ts` älter als `command_max_age_s`, mehr als `command_max_age_s` in der Zukunft oder ohne Zeitzone wird verworfen.

## Ablauf

```
idle ──Klingel/call──→ calling ──abgenommen──→ active ──aufgelegt/max_call_s──→ ended ──cooldown──→ idle
  │                       └──ring_timeout_s / besetzt / abgelehnt──→ ended
  └──Anruf von innen (automatische Annahme)──→ active
```

| `state` | `reason` (bei `ended`) |
|---|---|
| `idle`, `calling`, `active`, `ended` | `timeout`, `hangup`, `busy`, `rejected`, `max_duration`, `not_registered` |

- Klingeln während `calling`/`active` oder in der Sperrzeit löst keinen zweiten Anruf aus (`event/ring` erreicht die Hausautomation trotzdem).
- Eingehende Anrufe, die nicht über die FritzBox kommen, werden sofort beendet. Zusätzlich lässt der Paketfilter `doorstation-firewall` SIP (5060/5061, UDP und TCP) und RTP (`rtp_ports` 10000–10099) nur von der FritzBox-Adresse aus `sip.yaml` durch – direkte Anrufe aus dem LAN erreichen baresip gar nicht.
- DTMF-Tasten werden nur während eines eigenen Gesprächs (`active`) gemeldet.
- Beim Start des Adapters wird ein noch laufendes, unbekanntes Gespräch beendet; die Anmeldung an der FritzBox wird sofort per `reginfo` abgefragt.
- Antwortet baresip zweimal nicht, wird `status` `degraded`, `registration` `unknown` und ein laufender Anruf beendet. Der Adapter lässt baresip dann neu starten (höchstens alle 5 min, über `doorstation-baresip-restart.path`).
- Der Pi hat keine Echtzeituhr: Nach einem Stromausfall startet er mit einer alten Uhrzeit und springt vor, sobald die Zeitsynchronisation antwortet. baresip verliert bei so einem Sprung seine MQTT-Verbindung und baut sie nicht selbst wieder auf. `install.sh` trägt die FritzBox als Zeitserver ein, damit stimmt die Uhr meist nach wenigen Sekunden. Trotzdem startet baresip erst nach der Zeitsynchronisation (`doorstation-wait-timesync`, höchstens 60 s – ohne Internet startet er trotzdem), und der Neustart oben fängt spätere Sprünge ab.
- Das SIP-Passwort darf kein `;`, `>`, `"` und keine Leerzeichen enthalten (die baresip-Kontozeile würde zerlegt); `install.sh` überspringt SIP dann mit einer Warnung.

## Audio

PipeWire läuft als Benutzerdienst von `doorstation` mit dem WebRTC-Echo-Cancel-Modul (`deploy/pipewire/60-echo-cancel.conf`: Echo- und Rauschunterdrückung, Pegelregelung, Hochpass). Es stellt `ec_sink`/`ec_source` bereit; baresip und der Sound-Dienst nutzen diese. Die Onboard-Audioausgänge sind abgeschaltet, die USB-Karte ist das einzige Audiogerät.

Vor jedem Start von baresip setzt `doorstation-audio-init` Schalter und Pegel aus `/etc/doorstation/audio.yaml`:

```yaml
card_match: "USB"            # Teil des ALSA-Kartennamens (nie die Kartennummer)
playback_control: Headphone  # Reglername des Sticks (sudo ./install.sh audio-info)
playback_percent: 80
capture_control: Mic
capture_percent: 50
auto_gain_control: false     # Hardware-Pegelautomatik des Sticks (fehlt der Regler: ignoriert)
mic_playback: false          # Mikrofon nie direkt auf den Lautsprecher
echo_cancel:
  enabled: true              # false: Ein-/Ausgabe direkt auf die Karte
```

`doorstation-audio-init` setzt diese Werte vor jedem Start von baresip; WirePlumber merkt sie sich und stellt sie nach einem Neustart wieder her. PipeWire läuft nur für den Benutzer `doorstation` (`ConditionUser=`-Drop-ins unter `/etc/systemd/user/`): Eine Login-Sitzung, z. B. per SSH, würde sonst eine eigene PipeWire starten, die Soundkarte übernehmen und den Lautsprecher auf 40 % stellen. Das wirkt ab dem nächsten Login – nach der ersten Installation laufende Sitzungen einmal abmelden.

Ein anderer USB-Stick braucht nur angepasste Reglernamen. Klang abstimmen: Pegel, `auto_gain_control` und Lautsprecher-/Mikrofonposition variieren, `sudo systemctl restart doorstation-baresip`.
