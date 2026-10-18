**English** | [Deutsch](de/ip-symcon.md)

# IP-Symcon integration

The door station only talks to its local Mosquitto. From there, a Mosquitto bridge connects as a client to a dedicated MQTT server instance in IP-Symcon.

```
Pi (mailbox)                                    IP-Symcon (192.168.178.10)
Services → Mosquitto :1883 ── Bridge ─────────→ Server Socket :1026 → MQTT Server
                           ←── only doorstation/+/cmd ──          → MQTT client devices
```

## 1. Setup in IP-Symcon

1. *Add object → Instance → **MQTT Server***. IP-Symcon creates a **Server Socket** as parent instance.
2. Server Socket: **port 1026**, active.
3. MQTT Server: user **`doorstation`** with password.
4. A dedicated server for the door station only – do not mix it with Shelly & co.

## 2. Setup on the Pi

`/etc/doorstation/bridge.yaml`:

```yaml
host: 192.168.178.10
port: 1026
username: doorstation
prefix: doorstation
```

Store the password hidden and set up the bridge:

```bash
read -rsp "MQTT password: " pw; echo; printf "%s\n" "$pw" | sudo install -m 600 /dev/stdin /etc/doorstation/secrets/bridge_password; unset pw
sudo ./install.sh
```

Check on the Pi: `mosquitto_sub -v -t '$SYS/broker/connection/#' -W 2` → `…/doorstation-bridge/state 1`.

## 3. What arrives in IP-Symcon

All received topics appear in the **configurator** of the MQTT server instance and can be created there as MQTT client devices.

| Topic | Kind | Content | Use in IP-Symcon |
|---|---|---|---|
| `$SYS/broker/connection/doorstation-bridge/state` | state | `1` connected, `0` disconnected | "door station reachable" – notify on `0` |
| `doorstation/<service>/status` | state | `online` / `offline` / `degraded`, repeated every `heartbeat_s` (default 5 min) | monitoring per service; "last update" older than 2 × `heartbeat_s` → service hangs |
| `doorstation/event/ring` | event, **QoS 0** | `{"ts","source":"bell"}` | trigger for mail/Halloween logic, push notification |
| `doorstation/gpio/input/bell` | event | `{"ts","event":"pressed"}`, with `report_release: true` also `{"ts","event":"released"}` on release | display "bell pressed" – use `event/ring` for automations (only sent on press) |
| `doorstation/gpio/input/motion` | state | `{"ts","state":"idle"\|"motion"}` | motion at the mailbox |
| `doorstation/gpio/input/mail_flap` | state | `{"ts","state":"closed"\|"open"}` | mail flap → "you have mail" |
| `doorstation/gpio/input/mail_door` | state | `{"ts","state":"closed"\|"open"}` | mailbox door → "mail collected" |
| `doorstation/sip/call` | state | `{"ts","state","direction","peer","reason"}` | call status |
| `doorstation/sip/dtmf` | event, **QoS 0** | `{"ts","key":"#"}` | `#` → door opener, `*` → light (only reported during a call) |
| `doorstation/sip/target` | state | `{"ts","target":"**701"\|null}` | current call target / muted |
| `doorstation/rfid/read` | event, **QoS 0** | `{"ts","type","id"}` | access decision |

**States** (retained, QoS 1) are delivered after an outage. **Bell, RFID and DTMF events** (QoS 0) deliberately are **not** – a late bell must not open the garage in mail mode, for example, and a late `#` must not open the door. In addition, IP-Symcon should drop old events by `ts` (see 5).

A restart of the Pi or of a service does not send unchanged states again – they keep their message and `ts`. Use events **"on change"** on state variables, not "on update": the bridge can deliver retained messages again when it reconnects to IP-Symcon.

## 4. Commands to the door station

Create an **MQTT client device instance by hand** for each command topic (the configurator only shows received topics):

- *Add object → Instance → MQTT Client*, parent: the door station's MQTT server instance
- Topic: `doorstation/sip/cmd` (or `doorstation/sound/cmd`), data type **String**
- Sending: set the variable's value – in the console or via `RequestAction(<VariableID>, <JSON>)`

The bridge lets **only** `doorstation/+/cmd` in from IP-Symcon, with QoS 0: if the Pi is not reachable, a command expires instead of being delivered later. `doorstation/sip/target` shows whether a `set_target` arrived.

| Topic | Command | Effect |
|---|---|---|
| `doorstation/sip/cmd` | `{"action":"set_target","target":"**701"}` | set the call target |
| `doorstation/sip/cmd` | `{"action":"set_target","target":null}` | mute: bell without a call |
| `doorstation/sip/cmd` | `{"action":"call","ts":"…"}` | start a call (older than 30 s → dropped) |
| `doorstation/sip/cmd` | `{"action":"hangup"}` | end the call |
| `doorstation/sound/cmd` | `{"action":"play","name":"you_have_mail"}` | play an announcement |

## 5. Example scripts

Timestamp for commands:

```php
<?php
function doorstation_ts(): string {
    return (new DateTime())->format('Y-m-d\TH:i:s.vP');
}
// call the group
RequestAction(12345 /* variable sip/cmd */, json_encode(['action' => 'call', 'ts' => doorstation_ts()]));
// mute the bell
RequestAction(12345, json_encode(['action' => 'set_target', 'target' => null]));
```

Evaluate the bell (event "on change" on the variable of `doorstation/event/ring`), drop old rings:

```php
<?php
$data = json_decode(GetValueString(23456 /* variable event/ring */), true);
$age = time() - (new DateTime($data['ts']))->getTimestamp();
if ($age > 30) {
    IPS_LogMessage('Doorstation', "bell dropped, $age s old");
    return;
}
// mail mode, Halloween mode, push notification …
```

The same applies to `sip/dtmf` (30 seconds) and to `rfid/read` with 10 seconds. The Pi has no real-time clock: after a power failure its clock is only correct after time synchronization (usually seconds after the network is up) – events reported right before may therefore be dropped as "old".

"You have mail" and announcement when opening the door (adjust the variable IDs):

```php
<?php
// One event "on change" per variable (gpio/input/mail_flap and mail_door), both using this script.
// Branch on the triggering variable - otherwise e.g. a flap that is still open would set
// "mail present" again when the mailbox door is opened.
$data = json_decode($_IPS['VALUE'], true);
switch ($_IPS['VARIABLE']) {
    case 34567: // mail_flap: flap opened → mail present
        if ($data['state'] === 'open') SetValueBoolean(45678 /* mail present */, true);
        break;
    case 34568: // mail_door: mailbox door opened → mail collected
        if ($data['state'] === 'open') SetValueBoolean(45678, false);
        break;
}
```

```php
<?php
// after a valid rfid/read: open the door, then announcements (played one after another)
// … open the lock …
RequestAction(56789 /* variable sound/cmd */, json_encode(['action' => 'play', 'name' => 'door_opening']));
if (GetValueBoolean(45678 /* mail present */)) {
    RequestAction(56789, json_encode(['action' => 'play', 'name' => 'you_have_mail']));
}
```

## 6. Outage monitoring

The services repeat their status every `heartbeat_s` (300 s). Run this script periodically (e.g. every 5 min) and send a non-empty output as push notification. It reports the first failed or hanging service:

```php
<?php
$services = [                // order = priority
    'sip'   => 20873,        // variables of doorstation/<service>/status
    'gpio'  => 14858,
    'rfid'  => 52788,
    'sound' => 17728,
];
$maxAge = 2 * 300;           // 2 × heartbeat_s

$message = '';
foreach ($services as $name => $varId) {
    $status = trim((string) GetValue($varId));
    $age    = time() - IPS_GetVariable($varId)['VariableUpdated'];
    if ($status !== 'online') {
        $message = "doorstation failure: $name ($status)";
    } elseif ($age > $maxAge) {
        $message = "doorstation failure: $name (no update for " . round($age / 60) . " min)";
    }
    if ($message !== '') break;
}
echo $message;
```

If the whole Pi fails, the IP-Symcon broker reports `$SYS/broker/connection/doorstation-bridge/state` = `0` – add this as the first check in the script (`!== '1'`).

## Sources

- [Symcon docs – MQTT Server](https://www.symcon.de/en/service/documentation/module-reference/devices/mqtt/mqtt-server/)
- [Symcon docs – MQTT Client (device)](https://www.symcon.de/en/service/documentation/module-reference/devices/mqtt/mqtt-client/)
