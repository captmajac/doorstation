[English](../../services/rfid.md) | **Deutsch**

# Dienst `rfid`

Liest mit einem PN532 RFID-Karten, AirTags und **Apple Home Key** (iPhone/Apple Watch aus dem Wallet, auch gesperrt per Express-Modus) und meldet eine **stabile ID** per MQTT. Ob die Tür öffnet, entscheidet die Hausautomation. Nach jedem gemeldeten Lesevorgang wird lokal der Lese-Ton (`sound/cmd` `beep`) ausgelöst.

Unit: `doorstation-rfid` · Konfiguration: `/etc/doorstation/rfid.yaml` · Grundlage: [kormax/apple-home-key-reader](https://github.com/kormax/apple-home-key-reader) (Apache-2.0, unverändert unter `services/rfid/doorstation_rfid/vendor/`) als Bibliothek, mit eigener fehlertoleranter Leseschleife.

## Gemeldete IDs

`doorstation/rfid/read` → `{"ts","type","id"}`

| Vorgehalten | `type` | `id` |
|---|---|---|
| iPhone/Watch mit Hausschlüssel | `homekey` | 16 Hex-Zeichen (erste 8 Byte SHA-256 über den öffentlichen Schlüssel des Geräts) |
| RFID-Karte/-Tag (z. B. MIFARE) | `card` | UID, 8/14/20 Hex-Zeichen |
| AirTag | `card` | feste 7-Byte-UID (14 Zeichen) |
| Apple Pay, viele Bankkarten | – | **nicht gemeldet**: Zufalls-UID (4 Byte, beginnt mit `08`) |

- Die Home-Key-ID bleibt gleich, solange der Schlüssel im Wallet ist und die Paarung des Lesers erhalten bleibt.
- Dieselbe ID wird frühestens nach `repeat_block_s` Pause erneut gemeldet; ein liegengelassenes iPhone erzeugt eine Meldung.
- Ohne MQTT-Verbindung gelesene IDs werden **nicht** gepuffert.

## Konfiguration

```yaml
mqtt: { host: localhost, port: 1883, prefix: doorstation, heartbeat_s: 300 }
nfc_path: "tty:AMA0:pn532"   # andere Leser (USB) brauchen ein DeviceAllow in der Unit
accessory_name: "Mailbox NFC Reader"
express: true              # iPhone muss nicht entsperrt werden
finish: silver             # Farbe der Wallet-Karte: silver | black | gold | tan
flow: fast                 # fast | standard | attestation
repeat_block_s: 3
feedback_sound: beep       # leer = kein Lese-Ton
state_dir: /var/lib/doorstation/rfid  # nicht ändern: nur hier darf der Dienst schreiben (systemd-Härtung)
hap_port: 51926
```

## Home Key koppeln

Der Leser meldet sich in Apple Home als **Schloss** an; nur so kommt der Hausschlüssel ins Wallet. Das Schloss bleibt immer „verriegelt“, ändert sich beim Vorhalten nicht (keine Mitteilung „aufgesperrt“) und springt bei „Aufschließen“ sofort zurück.

1. Kopplungscode anzeigen: `journalctl -u doorstation-rfid | grep "setup code"`
2. Home-App → „+“ → Gerät hinzufügen → **Weitere Optionen** → NFC-Schloss wählen → Code eingeben → „Trotzdem hinzufügen“.
3. Den angebotenen **Hausschlüssel ins Wallet** übernehmen. Alle Mitglieder des Zuhauses erhalten ihn.
4. Empfehlung: das Schloss einem eigenen Raum zuordnen, aus Übersicht und Favoriten nehmen, Mitteilungen abschalten – und es eindeutig benennen, damit Siri es nicht mit dem echten Türschloss verwechselt.
5. **Sichern:** `sudo ./install.sh backup …` – die Paarung liegt in `/var/lib/doorstation/rfid/hap.state` und `homekey.json`.

Eine bestehende Paarung (z. B. von einer anderen SD-Karte) übernehmen: `sudo ./install.sh rfid-import <ordner>`.

## MQTT

| Topic | Inhalt |
|---|---|
| `doorstation/rfid/read` | `{"ts","type","id"}` |
| `doorstation/rfid/pairing` (retained) | `{"ts","paired":true}` |
| `doorstation/rfid/status` | `online` / `degraded` (Leser antwortet dauerhaft nicht) / `offline` |

## Betrieb und Sicherheit

- Einzelne Übertragungsfehler des PN532 nach einem Lesevorgang sind normal; die Schleife öffnet den Leser in unter einer Sekunde neu. `degraded` erst nach drei Fehlern in Folge.
- Wird der Leser abgezogen und wieder angesteckt, liest der Dienst ohne Neustart weiter.
- `homekey.json` wird bei neuen Lesevorgängen aktualisiert und dabei atomar geschrieben (Temp-Datei, fsync, Umbenennen) – ein Stromausfall hinterlässt nie eine halbe Datei. `hap.state` schreibt HAP-python ebenfalls atomar.
- Schlüsselmaterial wird nie geloggt (kormax loggt über den Root-Logger; dieser steht auf WARNING). `state_dir` 700, Dateien 600.
- Nicht gekoppelt: Karten und AirTags werden trotzdem gemeldet, `rfid/pairing` ist `false`.
