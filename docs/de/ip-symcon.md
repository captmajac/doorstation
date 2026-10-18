[English](../ip-symcon.md) | **Deutsch**

# Anbindung an IP-Symcon

Die Türstation spricht nur mit ihrem lokalen Mosquitto. Eine Mosquitto-Bridge verbindet sich von dort als Client mit einer eigenen MQTT-Server-Instanz in IP-Symcon.

```
Pi (Briefkasten)                                IP-Symcon (192.168.178.10)
Dienste → Mosquitto :1883 ── Bridge ──────────→ Server Socket :1026 → MQTT Server
                           ←── nur doorstation/+/cmd ──           → MQTT-Client-Geräte
```

## 1. Einrichtung in IP-Symcon

1. *Objekt hinzufügen → Instanz → **MQTT Server***. IP-Symcon legt einen **Server Socket** als übergeordnete Instanz an.
2. Server Socket: **Port 1026**, aktiv.
3. MQTT Server: Benutzer **`doorstation`** mit Passwort.
4. Eigener Server nur für die Türstation – nicht mit Shelly & Co. mischen.

## 2. Einrichtung auf dem Pi

`/etc/doorstation/bridge.yaml`:

```yaml
host: 192.168.178.10
port: 1026
username: doorstation
prefix: doorstation
```

Passwort verdeckt ablegen und Bridge einrichten:

```bash
read -rsp "MQTT-Passwort: " pw; echo; printf "%s\n" "$pw" | sudo install -m 600 /dev/stdin /etc/doorstation/secrets/bridge_password; unset pw
sudo ./install.sh
```

Prüfen auf dem Pi: `mosquitto_sub -v -t '$SYS/broker/connection/#' -W 2` → `…/doorstation-bridge/state 1`.

## 3. Was in IP-Symcon ankommt

Im **Konfigurator** der MQTT-Server-Instanz erscheinen alle empfangenen Topics und lassen sich dort als MQTT-Client-Geräte anlegen.

| Topic | Art | Inhalt | Verwendung in IP-Symcon |
|---|---|---|---|
| `$SYS/broker/connection/doorstation-bridge/state` | Zustand | `1` verbunden, `0` getrennt | „Türstation erreichbar“ – bei `0` Meldung |
| `doorstation/<dienst>/status` | Zustand | `online` / `offline` / `degraded`, alle `heartbeat_s` (Vorgabe 5 min) wiederholt | Überwachung je Dienst; „letzte Aktualisierung“ älter als 2 × `heartbeat_s` → Dienst hängt |
| `doorstation/event/ring` | Ereignis, **QoS 0** | `{"ts","source":"bell"}` | Auslöser für Post-/Halloween-Logik, Push-Nachricht |
| `doorstation/gpio/input/bell` | Ereignis | `{"ts","event":"pressed"}`, mit `report_release: true` beim Loslassen `{"ts","event":"released"}` | Anzeige „Klingel gedrückt“ – für Automatiken `event/ring` nutzen (kommt nur beim Drücken) |
| `doorstation/gpio/input/motion` | Zustand | `{"ts","state":"idle"\|"motion"}` | Bewegung am Briefkasten |
| `doorstation/gpio/input/mail_flap` | Zustand | `{"ts","state":"closed"\|"open"}` | Briefklappe → „Post da“ |
| `doorstation/gpio/input/mail_door` | Zustand | `{"ts","state":"closed"\|"open"}` | Kastentür → „Post entnommen“ |
| `doorstation/sip/call` | Zustand | `{"ts","state","direction","peer","reason"}` | Gesprächsstatus |
| `doorstation/sip/dtmf` | Ereignis, **QoS 0** | `{"ts","key":"#"}` | `#` → Türöffner, `*` → Licht (nur im Gespräch gemeldet) |
| `doorstation/sip/target` | Zustand | `{"ts","target":"**701"\|null}` | aktuelles Anrufziel / stumm |
| `doorstation/rfid/read` | Ereignis, **QoS 0** | `{"ts","type","id"}` | Zutrittsentscheidung |

**Zustände** (retained, QoS 1) werden nach einem Ausfall nachgeliefert. **Klingel-, RFID- und DTMF-Ereignisse** (QoS 0) bewusst **nicht** – eine verspätete Klingel soll z. B. im Post-Modus nicht die Garage öffnen, ein verspätetes `#` nicht die Tür. Zusätzlich sollte IP-Symcon alte Ereignisse per `ts` verwerfen (siehe 5).

Ein Neustart des Pi oder eines Dienstes sendet unveränderte Zustände nicht erneut – sie behalten ihre Nachricht samt `ts`. Ereignisse auf Zustandsvariablen **„bei Änderung“** anlegen, nicht „bei Aktualisierung“: Die Bridge kann retained Nachrichten bei einer Wiederverbindung zu IP-Symcon erneut ausliefern.

## 4. Befehle an die Türstation

Für jedes Befehlstopic eine **MQTT-Client-Geräteinstanz von Hand** anlegen (der Konfigurator zeigt nur empfangene Topics):

- *Objekt hinzufügen → Instanz → MQTT Client*, übergeordnet: die MQTT-Server-Instanz der Türstation
- Topic: `doorstation/sip/cmd` (bzw. `doorstation/sound/cmd`), Datentyp **String**
- Senden: Wert der Variable setzen – in der Konsole oder per `RequestAction(<VariablenID>, <JSON>)`

Die Bridge lässt von IP-Symcon **nur** `doorstation/+/cmd` herein, mit QoS 0: Ist der Pi nicht erreichbar, verfällt ein Befehl, statt später nachgeliefert zu werden. Ob ein `set_target` angekommen ist, zeigt `doorstation/sip/target`.

| Topic | Befehl | Wirkung |
|---|---|---|
| `doorstation/sip/cmd` | `{"action":"set_target","target":"**701"}` | Anrufziel setzen |
| `doorstation/sip/cmd` | `{"action":"set_target","target":null}` | stumm: Klingeln ohne Anruf |
| `doorstation/sip/cmd` | `{"action":"call","ts":"…"}` | Anruf auslösen (älter als 30 s → verworfen) |
| `doorstation/sip/cmd` | `{"action":"hangup"}` | Gespräch beenden |
| `doorstation/sound/cmd` | `{"action":"play","name":"you_have_mail"}` | Ansage abspielen |

## 5. Beispielskripte

Zeitstempel für Befehle:

```php
<?php
function doorstation_ts(): string {
    return (new DateTime())->format('Y-m-d\TH:i:s.vP');
}
// Anruf an die Gruppe auslösen
RequestAction(12345 /* Variable sip/cmd */, json_encode(['action' => 'call', 'ts' => doorstation_ts()]));
// Klingel stumm schalten
RequestAction(12345, json_encode(['action' => 'set_target', 'target' => null]));
```

Klingel auswerten (Ereignis „bei Änderung“ auf der Variable von `doorstation/event/ring`), alte Klingeln verwerfen:

```php
<?php
$data = json_decode(GetValueString(23456 /* Variable event/ring */), true);
$alter = time() - (new DateTime($data['ts']))->getTimestamp();
if ($alter > 30) {
    IPS_LogMessage('Tuerstation', "Klingel verworfen, $alter s alt");
    return;
}
// Post-Modus, Halloween-Modus, Push-Nachricht …
```

Für `sip/dtmf` gilt dasselbe (30 Sekunden), für `rfid/read` 10 Sekunden. Der Pi hat keine Echtzeituhr: Nach einem Stromausfall stimmt seine Uhr erst nach der Zeitsynchronisation (meist Sekunden nach dem Netz) – kurz danach gemeldete Ereignisse können deshalb als „alt“ verworfen werden.

„Post da“ und Ansage beim Türöffnen (Variablen-IDs anpassen):

```php
<?php
// Ein Ereignis „bei Änderung“ je Variable (gpio/input/mail_flap und mail_door), beide mit diesem Skript.
// Nach der auslösenden Variable verzweigen – sonst setzt z. B. eine noch offene Klappe "Post da"
// beim Öffnen der Kastentür gleich wieder.
$data = json_decode($_IPS['VALUE'], true);
switch ($_IPS['VARIABLE']) {
    case 34567: // mail_flap: Briefklappe geöffnet → Post da
        if ($data['state'] === 'open') SetValueBoolean(45678 /* Post da */, true);
        break;
    case 34568: // mail_door: Kastentür geöffnet → Post entnommen
        if ($data['state'] === 'open') SetValueBoolean(45678, false);
        break;
}
```

```php
<?php
// nach gültigem rfid/read: Tür öffnen, dann Ansagen (werden nacheinander gespielt)
// … Schloss öffnen …
RequestAction(56789 /* Variable sound/cmd */, json_encode(['action' => 'play', 'name' => 'door_opening']));
if (GetValueBoolean(45678 /* Post da */)) {
    RequestAction(56789, json_encode(['action' => 'play', 'name' => 'you_have_mail']));
}
```

## 6. Ausfallüberwachung

Die Dienste wiederholen ihren Status alle `heartbeat_s` (300 s). Dieses Skript zyklisch (z. B. alle 5 min) ausführen und eine nicht leere Ausgabe als Push-Nachricht senden. Es meldet den ersten ausgefallenen oder hängenden Dienst:

```php
<?php
$dienste = [                 // Reihenfolge = Priorität
    'sip'   => 20873,        // Variablen von doorstation/<dienst>/status
    'gpio'  => 14858,
    'rfid'  => 52788,
    'sound' => 17728,
];
$maxAlter = 2 * 300;         // 2 × heartbeat_s

$meldung = '';
foreach ($dienste as $name => $varId) {
    $status = trim((string) GetValue($varId));
    $alter  = time() - IPS_GetVariable($varId)['VariableUpdated'];
    if ($status !== 'online') {
        $meldung = "doorstation ausfall: $name ($status)";
    } elseif ($alter > $maxAlter) {
        $meldung = "doorstation ausfall: $name (keine Meldung seit " . round($alter / 60) . " min)";
    }
    if ($meldung !== '') break;
}
echo $meldung;
```

Fällt der ganze Pi aus, meldet der IP-Symcon-Broker `$SYS/broker/connection/doorstation-bridge/state` = `0` – als erste Prüfung im Skript ergänzen (`!== '1'`).

## Quellen

- [Symcon Doku – MQTT Server](https://www.symcon.de/en/service/documentation/module-reference/devices/mqtt/mqtt-server/)
- [Symcon Doku – MQTT Client (Gerät)](https://www.symcon.de/en/service/documentation/module-reference/devices/mqtt/mqtt-client/)
