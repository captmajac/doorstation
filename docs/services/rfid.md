**English** | [Deutsch](../de/dienste/rfid.md)

# Service `rfid`

Reads RFID cards, AirTags and **Apple Home Key** (iPhone/Apple Watch from the Wallet, even locked via Express mode) with a PN532 and reports a **stable ID** via MQTT. The home automation decides whether the door opens. After every reported read, the read beep (`sound/cmd` `beep`) is triggered locally.

Unit: `doorstation-rfid` · Configuration: `/etc/doorstation/rfid.yaml` · Based on: [kormax/apple-home-key-reader](https://github.com/kormax/apple-home-key-reader) (Apache-2.0, unchanged in `services/rfid/doorstation_rfid/vendor/`) as a library, with its own fault-tolerant read loop.

## Reported IDs

`doorstation/rfid/read` → `{"ts","type","id"}`

| Presented | `type` | `id` |
|---|---|---|
| iPhone/Watch with home key | `homekey` | 16 hex characters (first 8 bytes of SHA-256 over the device's public key) |
| RFID card/tag (e.g. MIFARE) | `card` | UID, 8/14/20 hex characters |
| AirTag | `card` | fixed 7-byte UID (14 characters) |
| Apple Pay, many bank cards | – | **not reported**: random UID (4 bytes, starts with `08`) |

- The Home Key ID stays the same as long as the key is in the Wallet and the reader's pairing is kept.
- The same ID is reported again only after a pause of `repeat_block_s`; an iPhone left on the reader produces one report.
- IDs read without an MQTT connection are **not** buffered.

## Configuration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
nfc_path: "tty:AMA0:pn532"   # other readers (USB) need a DeviceAllow in the unit
accessory_name: "Mailbox NFC Reader"
express: true              # iPhone does not need to be unlocked
finish: silver             # color of the Wallet card: silver | black | gold | tan
flow: fast                 # fast | standard | attestation
repeat_block_s: 3
feedback_sound: beep       # empty = no read beep
state_dir: /var/lib/doorstation/rfid  # do not change: the service may only write here (systemd hardening)
hap_port: 51926
```

## Pairing the Home Key

The reader registers in Apple Home as a **lock**; that is the only way to get the home key into the Wallet. The lock always stays "locked", does not change when a key is presented (no "unlocked" notification) and immediately jumps back on "Unlock".

1. Show the setup code: `journalctl -u doorstation-rfid | grep "setup code"`
2. Home app → "+" → Add Accessory → **More options** → choose the NFC lock → enter the code → "Add Anyway".
3. Accept the offered **home key into the Wallet**. All members of the home receive it.
4. Recommendation: assign the lock to its own room, remove it from the overview and favorites, turn off notifications – and give it a distinct name so Siri does not confuse it with the real door lock.
5. **Back up:** `sudo ./install.sh backup …` – the pairing is in `/var/lib/doorstation/rfid/hap.state` and `homekey.json`.

Take over an existing pairing (e.g. from another SD card): `sudo ./install.sh rfid-import <directory>`.

## MQTT

| Topic | Content |
|---|---|
| `doorstation/rfid/read` | `{"ts","type","id"}` |
| `doorstation/rfid/pairing` (retained) | `{"ts","paired":true}` |
| `doorstation/rfid/status` | `online` / `degraded` (reader not responding for a longer time) / `offline` |

## Operation and security

- Single PN532 transmission errors after a read are normal; the loop reopens the reader in less than a second. `degraded` only after three errors in a row.
- If the reader is unplugged and plugged in again, the service keeps reading without a restart.
- `homekey.json` is updated on new reads and written atomically (temp file, fsync, rename) – a power failure never leaves a partial file. HAP-python writes `hap.state` atomically as well.
- Key material is never logged (kormax logs via the root logger; it is set to WARNING). `state_dir` 700, files 600.
- Not paired: cards and AirTags are reported anyway, `rfid/pairing` is `false`.
