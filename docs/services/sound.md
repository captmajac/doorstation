**English** | [Deutsch](../de/dienste/sound.md)

# Service `sound`

Plays named sounds and announcements on the speaker – on command of the home automation (e.g. "you have mail", "door opening") or the RFID service (read beep). The home automation only picks **names**; which file is behind a name is defined in `sound.yaml` alone.

Unit: `doorstation-sound` · Configuration: `/etc/doorstation/sound.yaml` · Playback: `pw-play` via the PipeWire echo cancellation (`ec_sink`) – announcements during a call are removed from the microphone signal.

## Configuration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
default_volume: 0.8       # 0.0–1.0
queue_size: 3             # waiting sounds; the oldest is dropped
max_play_s: 120           # forced end of a sound
target: ec_sink           # PipeWire output
sounds:
  beep:                { file: /var/lib/doorstation/sounds/beep.wav, volume: 0.6 }
  you_have_mail:       { file: /var/lib/doorstation/sounds/you_have_mail.wav }
  door_opening:        { file: /var/lib/doorstation/sounds/door_opening.wav }
  parcel_dropoff:      { file: /var/lib/doorstation/sounds/parcel_dropoff.wav }
  easteregg_halloween: { file: /var/lib/doorstation/sounds/easteregg_halloween.wav, volume: 1.0 }
```

- Names: `a–z`, `0–9`, `_`. Formats: WAV, FLAC, OGG.
- Copy sound files to `/var/lib/doorstation/sounds/` (owner `doorstation`, 644). Only `beep.wav` (read beep) is shipped.
- New sound: copy the file, add a line, `sudo systemctl restart doorstation-sound`.
- If a file is missing, the service starts anyway; the name is then missing in `sound/available`, and at start there is one message per missing file on `sound/error`.
- Without the node `ec_sink` (echo cancellation off or PipeWire module not loaded) `pw-play` plays to the default output – then without echo cancellation: an announcement during a call is audible as an echo on the phone.

## MQTT

**Commands** to `doorstation/sound/cmd`:

| Command | Effect |
|---|---|
| `{"action":"play","name":"you_have_mail"}` | play, or add to the queue |
| `{"action":"play","name":"you_have_mail","volume":0.5}` | with a different volume |
| `{"action":"play","name":"door_opening","interrupt":true}` | stop the current sound, clear the queue, play immediately |
| `{"action":"stop"}` | stop, clear the queue |

Volume: command → entry in `sound.yaml` → `default_volume`.

| Topic | Content |
|---|---|
| `doorstation/sound/state` (retained) | `{"ts","state":"playing","name":"you_have_mail"}` or `{"ts","state":"idle"}` |
| `doorstation/sound/available` (retained) | `{"ts","names":[…]}` |
| `doorstation/sound/error` | unknown name, invalid volume, playback error |
| `doorstation/sound/status` | `online` / `degraded` (three playback errors in a row) / `offline` |

Several `play` commands in quick succession are played one after another (up to `queue_size` waiting).

## Testing

```bash
mosquitto_pub -t doorstation/sound/cmd -m '{"action":"play","name":"beep"}'
mosquitto_sub -v -t 'doorstation/sound/#'
```
