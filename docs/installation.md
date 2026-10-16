**English** | [Deutsch](de/installation.md)

# Installation and operation

## 1. Prepare the SD card

With the Raspberry Pi Imager:

- Operating system: **Raspberry Pi OS Lite (64-bit)** (Debian 13 "Trixie").
- Host name, user, time zone, keyboard as you like.
- **Enable SSH**, preferably "public key only" with your own key (`ssh-keygen -t ed25519`, paste the content of `~/.ssh/id_ed25519.pub`).
- LAN recommended; Wi-Fi works as well.

The card runs unchanged on Pi 3 and Pi 4.

## 2. Install

Copy the repo to the Pi (e.g. `git clone` or `rsync`) and run as root:

```bash
sudo ./install.sh
```

`install.sh` can be run any number of times (also for updates: `git pull`, then run it again). It

- installs the packages (Mosquitto, PipeWire, WirePlumber, baresip, Python),
- creates the system user `doorstation`, the directories and one venv per service,
- sets up the local Mosquitto (`127.0.0.1` only) and – if configured – the bridge,
- loads the packet filter `doorstation-firewall`: SIP/RTP from the FritzBox only (other ports untouched),
- enables the UART for the PN532, disables Bluetooth and the serial console, disables the onboard audio outputs,
- creates missing configurations in `/etc/doorstation/` from `config-examples/` (**existing ones are never overwritten**),
- installs and starts the systemd units `doorstation-firewall`, `-gpio`, `-baresip`, `-sip`, `-sound`, `-rfid` and `doorstation-baresip-restart.path`.

If it says "please reboot", run `sudo reboot` once. On the first run the SIP password is still missing: SIP is then skipped with a warning and everything else is set up – run `install.sh` again after section 4. Warnings are repeated in a summary at the end.

## 3. Configure

All files are in `/etc/doorstation/`; after changes restart the respective service (`sudo systemctl restart doorstation-<service>`). If the configuration is invalid, the service stays stopped (`systemctl status` or `journalctl -u doorstation-<service>` names the file and field).

| File | Service | Description |
|---|---|---|
| `gpio.yaml` | `doorstation-gpio` | [services/gpio.md](services/gpio.md) |
| `sip.yaml` | `doorstation-sip` | [services/sip.md](services/sip.md) |
| `audio.yaml` | `doorstation-baresip` | [services/sip.md](services/sip.md#audio) |
| `sound.yaml` | `doorstation-sound` | [services/sound.md](services/sound.md) |
| `rfid.yaml` | `doorstation-rfid` | [services/rfid.md](services/rfid.md) |
| `bridge.yaml` | Mosquitto | section 5 below |
| `secrets/sip_password` | baresip | SIP password |
| `secrets/bridge_password` | Mosquitto | password of the home automation's MQTT server |

Every service configuration has an `mqtt` block (`host`, `port`, `prefix`, `heartbeat_s`). `prefix` is a single topic level (A–Z, a–z, 0–9, `_`, `-`). Duplicate keys in a YAML file are an error.

YAML note: quote values starting with `*` (`"**701"`).

## 4. Store the secrets

Enter passwords hidden so they end up neither in the shell history nor in logs:

```bash
read -rsp "SIP password: " pw; echo; printf "%s\n" "$pw" | sudo install -m 600 /dev/stdin /etc/doorstation/secrets/sip_password; unset pw
```

Then run `sudo ./install.sh` (it generates the baresip configuration from it). The same for the bridge password with `bridge_password`. The files belong to root (600); no service reads them at runtime.

## 5. Bridge to the home automation

`/etc/doorstation/bridge.yaml` (template `config-examples/bridge.yaml`):

```yaml
host: 192.168.178.10      # MQTT server of the home automation
port: 1026
username: doorstation
prefix: doorstation
```

Password in `/etc/doorstation/secrets/bridge_password`, then `sudo ./install.sh`. Without `bridge.yaml` or password no bridge is set up (an existing one is removed). Check:

```bash
mosquitto_sub -v -t '$SYS/broker/connection/#' -W 2     # → …/doorstation-bridge/state 1
```

Setup on the IP-Symcon side: [ip-symcon.md](ip-symcon.md).

## 6. Pair the Home Key

See [services/rfid.md](services/rfid.md#pairing-the-home-key). **Back up after pairing** (section 7) – without the pairing data you have to pair again and all Home Key IDs change.

## 7. Backup

```bash
sudo ./install.sh backup  /root/doorstation-backup.tar.gz
sudo ./install.sh restore /root/doorstation-backup.tar.gz
```

The backup contains `/etc/doorstation` (configuration, secrets) and `/var/lib/doorstation` (SIP target, HomeKit pairing, sound files). It is readable by root only (600). After `restore` run `sudo ./install.sh` once – only then do the bridge, baresip account and packet filter from the backup take effect. An existing Home Key pairing can also be taken over on its own: `sudo ./install.sh rfid-import <directory with hap.state and homekey.json>`.

## 8. Monitoring and troubleshooting

```bash
systemctl status 'doorstation-*'
journalctl -u doorstation-sip -f
mosquitto_sub -v -t 'doorstation/#'
```

- `doorstation/<service>/status`: `online`, `degraded` (running, but cannot do its job) or `offline`. Repeated every `heartbeat_s` (300 s).
- `sudo ./install.sh audio-info` shows sound cards and control names.
