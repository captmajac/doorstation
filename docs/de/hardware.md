[English](../hardware.md) | **Deutsch**

# Hardware

## Komponenten

| Komponente | Verwendet | Hinweise |
|---|---|---|
| Raspberry Pi | Pi 3 Model B oder Pi 4 | Gleiche Stiftleiste; dieselbe SD-Karte läuft auf beiden. Netzteil Pi 3: 5 V / 2,5 A (Micro-USB), Pi 4: 5 V / 3 A (USB-C). |
| NFC-Leser | Elechouse NFC Module V3 (PN532) bzw. Nachbau | Betrieb per UART (HSU), VCC an **5 V** – vorher den Pegel der Datenleitungen prüfen (siehe unten). Bei schlechter Home-Key-Erkennung: Elechouse PN532 V4. |
| USB-Soundkarte | C-Media USB Audio (z. B. `0d8c:000c`, `0d8c:0014`) | Getrennte 3,5-mm-Buchsen für Lautsprecher und Mikrofon. |
| Lautsprecher | kleiner Lautsprecher an der Kopfhörerbuchse | Ein Klangvolumen (Gehäuse) hinter dem Lautsprecher verbessert den Klang deutlich. |
| Mikrofon | Elektret-Mikrofon mit 3,5-mm-Stecker | Abstand zum Lautsprecher so groß wie möglich (weniger Echo). |
| Klingeltaster | Taster, schaltet gegen GND | |
| Reedkontakte | 2 Stück für Briefklappe und Kastentür, schalten gegen GND | Öffner oder Schließer – die Logik stellt `active` in der Konfiguration ein. |
| Bewegungsmelder | HC-SR501 (PIR) | Versorgung 5 V, Ausgang 3,3 V. Haltezeit (Poti „Tx“) und Retrigger-Jumper am Modul. |

## Belegung der Stiftleiste

![Belegung der Stiftleiste](../images/gpio-belegung.svg)

Pin-Nummern sind physische Pins, dazu die BCM-Nummer, die die Konfiguration verwendet. **Orientierung:** Pin 1 liegt am Ende der Leiste **ohne** USB-/LAN-Buchsen in der **inneren** Reihe (eckiger Lötpunkt). Ungerade Pins = innen, gerade = Platinenrand.

| Pin | Funktion | Angeschlossen an |
|---|---|---|
| 2 | 5 V | PN532 VCC |
| 4 | 5 V | Bewegungsmelder VCC |
| 6 | GND | PN532 GND |
| 8 | BCM 14 · TXD | PN532 UART |
| 10 | BCM 15 · RXD | PN532 UART |
| 20 | GND | Bewegungsmelder GND |
| 21 | BCM 9 | Klingeltaster |
| 25 | GND | Klingeltaster |
| 26 | BCM 7 | Bewegungsmelder OUT |
| 33 | BCM 13 | Reedkontakt Kastentür |
| 34 | GND | Reedkontakte (gemeinsame Masse) |
| 35 | BCM 19 | Reedkontakt Briefklappe |

**Nie 5 V (Pin 2/4) an einen GPIO-Pin legen** – die GPIOs vertragen nur 3,3 V.

## Verschaltung je Bauteil

### PN532 (UART)

| PN532 | → | Pi-Pin |
|---|---|---|
| VCC | → | Pin 2 (5 V) – **erst nach Prüfung des Pegels, siehe unten** |
| GND | → | Pin 6 (GND) |
| TXD | → | Pin 10 (RXD) |
| RXD | → | Pin 8 (TXD) |

- **DIP-Schalter auf HSU (UART)** – bei V3-Modulen beide auf 0/OFF (Aufdruck auf der Platine).
- **TX/RX gekreuzt.** Die Beschriftung mancher Nachbauten ist vertauscht: Kommt keine Antwort vom Leser, die beiden Datenleitungen tauschen – das schadet nicht.
- **VCC an 5 V:** Der 3,3-V-Regler des Pi liefert nicht genug Strom für den PN532; an 3,3 V setzt sich das Modul gelegentlich zurück, und nach Lesevorgängen treten häufig Übertragungsfehler auf. An 5 V läuft es stabil.
- **Vor dem Anschließen den Pegel prüfen.** Module unterscheiden sich: Je nach Platine laufen die Datenleitungen mit der internen Spannung des Chips (etwa 2,7–3,3 V) oder werden von einem Pegelwandler auf dem Modul auf die Versorgungsspannung angehoben (Handbuch Elechouse V3: „Standard 5V TTL for I2C and UART“). **Die GPIOs des Pi sind nicht 5-V-fest.** Modul allein an 5 V versorgen (nur VCC und GND, TXD/RXD nicht verbunden) und TXD sowie RXD gegen GND messen:

  | Gemessen | Verdrahtung |
  |---|---|
  | **höchstens 3,3 V** | VCC an 5 V (Pin 2), TXD/RXD direkt an den Pi – wie in der Tabelle oben |
  | **über 3,3 V** | VCC an 5 V **mit bidirektionalem Pegelwandler** (BSS138-Modul, siehe unten) – oder VCC an 3,3 V (Pin 1) ohne Pegelwandler, sicher, aber weniger zuverlässig |

- **Leser nur bei ausgeschaltetem Pi an- oder abstecken.**
- Auf dem Pi: `enable_uart=1`, `dtoverlay=disable-bt`, serielle Konsole aus – erledigt `install.sh`. Der Leser ist dann `/dev/ttyAMA0`.

#### Mit Pegelwandler (BSS138, 4 Kanäle)

Ein übliches Modul mit den Beschriftungen `HV`, `HV1…HV4` (5-V-Seite) und `LV`, `LV1…LV4` (3,3-V-Seite); jeder Kanal verbindet `HVx` mit `LVx`.

| Pegelwandler | → | Angeschlossen an |
|---|---|---|
| `LV` | → | Pi Pin 1 (3,3 V) |
| `GND` (LV-Seite) | → | Pi Pin 6 (GND) |
| `LV1` | → | Pi Pin 8 (TXD) |
| `LV2` | → | Pi Pin 10 (RXD) |
| `HV` | → | Pi Pin 2 (5 V) und PN532 VCC |
| `GND` (HV-Seite) | → | PN532 GND |
| `HV1` | → | PN532 RXD |
| `HV2` | → | PN532 TXD |

Bevor `LV1`/`LV2` an den Pi kommen: alles einschalten und `LV2` gegen GND messen – etwa 3,3 V.

### Klingeltaster und Reedkontakte

Jeweils zwischen GPIO-Pin und GND. In `/etc/doorstation/gpio.yaml`: `pull: up` (interner Pull-up), `active: low` – ein geschlossener Kontakt zieht den Pin auf 0 V.

| Eingang | GPIO | GND |
|---|---|---|
| Klingel | Pin 21 (BCM 9) | Pin 25 |
| Kastentür | Pin 33 (BCM 13) | Pin 34 |
| Briefklappe | Pin 35 (BCM 19) | Pin 34 |

- **Reedkontakte:** Je nach Bauart und Montage ist der Kontakt bei geschlossener Klappe offen oder geschlossen. Die Beispielkonfiguration (`active: low`) meldet `open`, wenn der Kontakt geschlossen ist, d. h. der Pin auf 0 V liegt. Passt das nicht, `active: high` setzen. Prüfen mit `pinctrl get 13,19` (Raspberry Pi OS 13; früher `raspi-gpio`) bei offener und geschlossener Klappe.
- Externe Pull-up-Widerstände (z. B. 10 kΩ gegen 3,3 V) sind bei langen Leitungen sinnvoll; der interne Pull-up stört dabei nicht.

### Bewegungsmelder HC-SR501

| HC-SR501 | → | Pi-Pin |
|---|---|---|
| VCC | → | Pin 4 (5 V) |
| OUT | → | Pin 26 (BCM 7) |
| GND | → | Pin 20 (GND) |

Der Ausgang liefert bei Bewegung 3,3 V (`active: high`, `pull: off`). Häufiges Auslösen über die Haltezeit am Modul und `min_interval_s` dämpfen.

### Audio

USB-Soundkarte an einen USB-Port, Lautsprecher an die Kopfhörerbuchse, Mikrofon an die Mikrofonbuchse. Die eingebauten Audioausgänge des Pi (Klinke, HDMI) schaltet `install.sh` ab – die USB-Karte ist dann das einzige Audiogerät. Reglernamen unterscheiden sich je Stick: `sudo ./install.sh audio-info`, dann `/etc/doorstation/audio.yaml` anpassen (siehe [dienste/sip.md](dienste/sip.md)).
