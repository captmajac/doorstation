**English** | [Deutsch](../de/dienste/sip.md)

# Service `sip`

Intercom between the door and the house phones via the FritzBox:

- Bell → call to a switchable internal target (number or group), can be muted.
- Can be called from inside; calls via the FritzBox are answered automatically.
- DTMF keys during the call are reported (e.g. `#` → door opener in the home automation).
- Echo and noise cancellation via PipeWire; the FritzBox ringback tone is audible outside.

Units: `doorstation-baresip` (SIP/audio, [baresip](https://github.com/baresip/baresip) from Debian) and `doorstation-sip` (adapter with the rules) · Configuration: `/etc/doorstation/sip.yaml`, `/etc/doorstation/audio.yaml`.

## FritzBox

*Telephony → Telephony Devices → Configure New Device → Telephone → LAN/WLAN (IP telephone)*. Its own internal number (e.g. `**629`), user name **without umlauts** (the FritzBox silently drops registrations with umlauts). Password to `/etc/doorstation/secrets/sip_password` ([installation.md](../installation.md#4-store-the-secrets)), then `sudo ./install.sh`.

Recommendation: block outgoing external calls for this telephony device in the FritzBox (call barring). The door station only calls internal numbers; this way even a faulty or foreign command cannot dial premium numbers.

## Configuration `sip.yaml`

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
fritzbox: 192.168.178.1
username: Tuerstation        # no umlauts
default_target: "**701"      # initial target until one is set via set_target; null = muted
ring_timeout_s: 30           # hang up if nobody answers
max_call_s: 120              # maximum duration of every call
cooldown_s: 5                # cooldown after a call
healthcheck_s: 30            # baresip polling interval
command_max_age_s: 30        # older call commands (ts) are dropped
# time_server: 192.168.178.1 # optional: time server for the Pi; default: fritzbox, null = system default
```

The target set via `set_target` is stored in `/var/lib/doorstation/sip/target.json` and survives restarts; `default_target` is only the initial value.

## MQTT

| Topic | Content |
|---|---|
| `doorstation/sip/call` (retained) | `{"ts","state","direction","peer","reason"}` |
| `doorstation/sip/target` (retained) | `{"ts","target":"**701"}` or `null` |
| `doorstation/sip/registration` (retained) | `registered` / `failed` / `unknown` |
| `doorstation/sip/dtmf` | `{"ts","key":"#"}` |
| `doorstation/sip/status` | `online` / `degraded` (not registered or baresip not responding) / `offline` |
| `doorstation/sip/error` | invalid commands |

**Commands** to `doorstation/sip/cmd`:

| Command | Effect |
|---|---|
| `{"action":"call"}` | like ringing, to the current target |
| `{"action":"call","target":"**610"}` | call another target |
| `{"action":"hangup"}` | end the call |
| `{"action":"set_target","target":"**701"}` | set the target (stored) |
| `{"action":"set_target","target":null}` | mute: ringing triggers no call |

Targets: digits, `*`, `#`, max. 20 characters. Commands may contain `ts` (ISO 8601 **with time zone**); a `call` with a `ts` older than `command_max_age_s`, more than `command_max_age_s` in the future or without a time zone is dropped.

## Flow

```
idle ──bell/call──→ calling ──answered──→ active ──hung up/max_call_s──→ ended ──cooldown──→ idle
  │                    └──ring_timeout_s / busy / rejected──→ ended
  └──call from inside (auto answer)──→ active
```

| `state` | `reason` (with `ended`) |
|---|---|
| `idle`, `calling`, `active`, `ended` | `timeout`, `hangup`, `busy`, `rejected`, `max_duration`, `not_registered` |

- Ringing during `calling`/`active` or within the cooldown triggers no second call (`event/ring` still reaches the home automation).
- Incoming calls that do not come via the FritzBox are ended immediately. In addition, the packet filter `doorstation-firewall` only lets SIP (5060/5061, UDP and TCP) and RTP (`rtp_ports` 10000–10099) through from the FritzBox address in `sip.yaml` – direct calls from the LAN never reach baresip.
- DTMF keys are only reported during our own call (`active`).
- When the adapter starts, a still running unknown call is ended; the registration at the FritzBox is queried right away via `reginfo`.
- If baresip does not respond twice, `status` becomes `degraded`, `registration` `unknown`, and a running call is ended. The adapter then has baresip restarted (at most every 5 min, via `doorstation-baresip-restart.path`).
- The Pi has no real-time clock: after a power failure it starts with an old time and jumps forward when the time sync answers. baresip loses its MQTT connection on such a jump and does not reconnect by itself. `install.sh` sets the FritzBox as time server, so the clock is usually right within seconds. Still, baresip starts only after the time sync (`doorstation-wait-timesync`, at most 60 s – without internet it starts anyway), and the restart above covers later jumps.
- The SIP password must not contain `;`, `>`, `"` or spaces (the baresip account line would break); `install.sh` then skips SIP with a warning.

## Audio

PipeWire runs as a user service of `doorstation` with the WebRTC echo cancel module (`deploy/pipewire/60-echo-cancel.conf`: echo and noise cancellation, gain control, high-pass filter). It provides `ec_sink`/`ec_source`; baresip and the sound service use them. The onboard audio outputs are disabled, the USB card is the only audio device.

Before every start of baresip, `doorstation-audio-init` sets switches and levels from `/etc/doorstation/audio.yaml`:

```yaml
card_match: "USB"            # part of the ALSA card name (never the card number)
playback_control: Headphone  # control name of the stick (sudo ./install.sh audio-info)
playback_percent: 80
capture_control: Mic
capture_percent: 50
auto_gain_control: false     # the stick's hardware gain control (ignored if the control is missing)
mic_playback: false          # never route the microphone straight to the speaker
echo_cancel:
  enabled: true              # false: input/output directly on the card
```

Only these values count: WirePlumber is configured not to restore stored volumes over them (`deploy/wireplumber/51-doorstation-volumes.conf`).

Another USB stick only needs adjusted control names. Tuning the sound: vary levels, `auto_gain_control` and the speaker/microphone position, then `sudo systemctl restart doorstation-baresip`.
