**English** | [Deutsch](README.de.md)

# doorstation

Door station for a mailbox on a Raspberry Pi: doorbell with intercom via a FritzBox, mailbox contacts, motion sensor, announcements and an NFC reader for RFID cards, AirTags and **Apple Home Key** (iPhone/Apple Watch from the Wallet). All events go via MQTT to a home automation system – here [IP-Symcon](https://www.symcon.de) – which decides about the door opener, lights or notifications.

The doorbell works **without the home automation as well**: button → call runs entirely on the Pi.

## Features

- **Doorbell & intercom:** the bell button calls an internal FritzBox number or group (SIP, HD voice G.722), with echo and noise cancellation, ring timeout, cooldown against repeated ringing and mute. Can be called from inside (auto answer); DTMF keys (e.g. `#` = door opener) are reported.
- **Mailbox:** reed contacts for the mail flap and the mailbox door, motion sensor.
- **Announcements:** named sounds ("you have mail", "door opening", read beep …) on command of the home automation.
- **RFID / NFC:** a PN532 reader reports RFID cards, AirTags and Apple Home Key with a stable ID; Apple Pay & co. (random UIDs) are ignored. Access is decided in the home automation.
- **Operation:** independent, hardened systemd services, status and heartbeat per service, packet filter for SIP, installation, update and backup with one script.

## Overview

```
                 ┌──────────────── Raspberry Pi ─────────────────┐
Bell/PIR/reed    →│ gpio  ──┐                                     │
PN532 (UART)    ←→│ rfid  ──┼─→ Mosquitto (local) ←─→ Bridge ─────┼──→ MQTT server of the home automation
FritzBox (SIP)  ←→│ sip   ──┤        event/ring → sip             │
Speaker/mic     ←→│ sound ──┘   Audio: PipeWire + echo cancel      │
                 └───────────────────────────────────────────────┘
```

| Service | Purpose | Docs |
|---|---|---|
| `doorstation-gpio` | buttons, contacts, motion sensor | [docs/services/gpio.md](docs/services/gpio.md) |
| `doorstation-sip` + `doorstation-baresip` | intercom via the FritzBox | [docs/services/sip.md](docs/services/sip.md) |
| `doorstation-sound` | announcements and sounds | [docs/services/sound.md](docs/services/sound.md) |
| `doorstation-rfid` | RFID, AirTag, Apple Home Key | [docs/services/rfid.md](docs/services/rfid.md) |

## Documentation

- [Architecture and MQTT interface](docs/architecture.md)
- [Hardware: components and wiring](docs/hardware.md)
- [Installation and operation](docs/installation.md)
- [IP-Symcon integration](docs/ip-symcon.md)
- [Development and tests](docs/development.md)

## Quick start

1. Write Raspberry Pi OS Lite (64-bit, Debian 13) to an SD card, enable SSH.
2. Connect the hardware – [docs/hardware.md](docs/hardware.md).
3. Copy the repo to the Pi and install:

   ```bash
   sudo ./install.sh
   sudo reboot
   ```

4. Adjust the configuration in `/etc/doorstation/`, store the secrets, run `sudo ./install.sh` again, pair the Home Key – [docs/installation.md](docs/installation.md).

## License

[Apache License 2.0](LICENSE). Contains [kormax/apple-home-key-reader](https://github.com/kormax/apple-home-key-reader) (Apache-2.0) unchanged in `services/rfid/doorstation_rfid/vendor/` – see [NOTICE](NOTICE).
