[English](../../services/sound.md) | **Deutsch**

# Dienst `sound`

Spielt benannte Töne und Ansagen über den Lautsprecher ab – auf Befehl der Hausautomation (z. B. „Du hast Post“, „Tür öffnet“) oder des RFID-Dienstes (Lese-Ton). Die Hausautomation wählt nur **Namen**; welche Datei dahintersteht, legt allein `sound.yaml` fest.

Unit: `doorstation-sound` · Konfiguration: `/etc/doorstation/sound.yaml` · Wiedergabe: `pw-play` über die PipeWire-Echounterdrückung (`ec_sink`) – Ansagen während eines Gesprächs werden aus dem Mikrofonsignal herausgerechnet.

## Konfiguration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
default_volume: 0.8       # 0.0–1.0
queue_size: 3             # wartende Töne; der älteste fällt heraus
max_play_s: 120           # Zwangsende eines Tons
target: ec_sink           # PipeWire-Ausgabe
sounds:
  beep:                { file: /var/lib/doorstation/sounds/beep.wav, volume: 0.6 }
  you_have_mail:       { file: /var/lib/doorstation/sounds/you_have_mail.wav }
  door_opening:        { file: /var/lib/doorstation/sounds/door_opening.wav }
  parcel_dropoff:      { file: /var/lib/doorstation/sounds/parcel_dropoff.wav }
  easteregg_halloween: { file: /var/lib/doorstation/sounds/easteregg_halloween.wav, volume: 1.0 }
```

- Namen: `a–z`, `0–9`, `_`. Formate: WAV, FLAC, OGG.
- Tondateien nach `/var/lib/doorstation/sounds/` kopieren (Besitzer `doorstation`, 644). Mitgeliefert wird nur `beep.wav` (Lese-Ton).
- Neuer Ton: Datei kopieren, Zeile ergänzen, `sudo systemctl restart doorstation-sound`.
- Fehlt eine Datei, startet der Dienst trotzdem; der Name fehlt dann in `sound/available`, und beim Start kommt je fehlender Datei eine Meldung auf `sound/error`.
- Ohne den Knoten `ec_sink` (Echounterdrückung aus oder PipeWire-Modul nicht geladen) spielt `pw-play` auf die Standardausgabe – dann ohne Echounterdrückung: eine Ansage während eines Gesprächs ist am Telefon als Echo hörbar.

## MQTT

**Befehle** an `doorstation/sound/cmd`:

| Befehl | Wirkung |
|---|---|
| `{"action":"play","name":"you_have_mail"}` | abspielen bzw. in die Warteschlange |
| `{"action":"play","name":"you_have_mail","volume":0.5}` | mit abweichender Lautstärke |
| `{"action":"play","name":"door_opening","interrupt":true}` | laufenden Ton abbrechen, Warteschlange leeren, sofort spielen |
| `{"action":"stop"}` | abbrechen, Warteschlange leeren |

Lautstärke: Befehl → Eintrag in `sound.yaml` → `default_volume`.

| Topic | Inhalt |
|---|---|
| `doorstation/sound/state` (retained) | `{"ts","state":"playing","name":"you_have_mail"}` bzw. `{"ts","state":"idle"}` |
| `doorstation/sound/available` (retained) | `{"ts","names":[…]}` |
| `doorstation/sound/error` | unbekannter Name, ungültige Lautstärke, Abspielfehler |
| `doorstation/sound/status` | `online` / `degraded` (drei Abspielfehler in Folge) / `offline` |

Mehrere `play` kurz hintereinander werden nacheinander gespielt (bis zu `queue_size` wartend).

## Testen

```bash
mosquitto_pub -t doorstation/sound/cmd -m '{"action":"play","name":"beep"}'
mosquitto_sub -v -t 'doorstation/sound/#'
```
