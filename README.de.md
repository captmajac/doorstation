[English](README.md) | **Deutsch**

# doorstation

Türstation für den Briefkasten auf einem Raspberry Pi: Klingel mit Sprechverbindung über die FritzBox, Briefkastenkontakte, Bewegungsmelder, Ansagen und ein NFC-Leser für RFID-Karten, AirTags und **Apple Home Key** (iPhone/Apple Watch aus dem Wallet). Alle Ereignisse gehen per MQTT an eine Hausautomation – hier [IP-Symcon](https://www.symcon.de) –, die über Türöffner, Licht oder Benachrichtigungen entscheidet.

Die Klingel funktioniert dabei **auch ohne Hausautomation**: Taster → Anruf läuft vollständig auf dem Pi.

## Funktionen

- **Klingel & Sprechen:** Klingeltaster löst einen Anruf an eine interne FritzBox-Nummer oder -Gruppe aus (SIP, HD-Telefonie G.722), mit Echo- und Rauschunterdrückung, Klingel-Timeout, Sperrzeit gegen Mehrfachklingeln und Stummschaltung. Von innen anrufbar (automatische Annahme), DTMF-Tasten (z. B. `#` = Türöffner) werden gemeldet.
- **Briefkasten:** Reedkontakte für Briefklappe und Kastentür, Bewegungsmelder.
- **Ansagen:** benannte Töne („Du hast Post“, „Tür öffnet“, Lese-Ton …) auf Befehl der Hausautomation.
- **RFID / NFC:** PN532-Leser meldet RFID-Karten, AirTags und Apple Home Key mit stabiler ID; Apple Pay & Co. (Zufalls-UIDs) werden ignoriert. Der Zutritt wird in der Hausautomation entschieden.
- **Betrieb:** eigenständige, gehärtete systemd-Dienste, Status und Lebenszeichen je Dienst, Paketfilter für SIP, Installation, Aktualisierung und Sicherung mit einem Skript.

## Aufbau

```
                 ┌──────────────── Raspberry Pi ─────────────────┐
Klingel/PIR/Reed →│ gpio  ──┐                                     │
PN532 (UART)    ←→│ rfid  ──┼─→ Mosquitto (lokal) ←─→ Bridge ─────┼──→ MQTT-Server der Hausautomation
FritzBox (SIP)  ←→│ sip   ──┤        event/ring → sip             │
Lautsprecher/Mic←→│ sound ──┘   Audio: PipeWire + Echounterdrückung│
                 └───────────────────────────────────────────────┘
```

| Dienst | Aufgabe | Doku |
|---|---|---|
| `doorstation-gpio` | Taster, Kontakte, Bewegungsmelder | [docs/de/dienste/gpio.md](docs/de/dienste/gpio.md) |
| `doorstation-sip` + `doorstation-baresip` | Sprechverbindung über die FritzBox | [docs/de/dienste/sip.md](docs/de/dienste/sip.md) |
| `doorstation-sound` | Ansagen und Töne | [docs/de/dienste/sound.md](docs/de/dienste/sound.md) |
| `doorstation-rfid` | RFID, AirTag, Apple Home Key | [docs/de/dienste/rfid.md](docs/de/dienste/rfid.md) |

## Dokumentation

- [Architektur und MQTT-Schnittstelle](docs/de/architektur.md)
- [Hardware: Komponenten und Verschaltung](docs/de/hardware.md)
- [Installation und Betrieb](docs/de/installation.md)
- [Anbindung an IP-Symcon](docs/de/ip-symcon.md)
- [Entwicklung und Tests](docs/de/entwicklung.md)

## Schnellstart

1. Raspberry Pi OS Lite (64-bit, Debian 13) auf eine SD-Karte schreiben, SSH aktivieren.
2. Hardware anschließen – [docs/de/hardware.md](docs/de/hardware.md).
3. Repo auf den Pi bringen und installieren:

   ```bash
   sudo ./install.sh
   sudo reboot
   ```

4. Konfiguration unter `/etc/doorstation/` anpassen, Geheimnisse ablegen, `sudo ./install.sh` erneut ausführen, Home Key koppeln – [docs/de/installation.md](docs/de/installation.md).

## Lizenz

[Apache License 2.0](LICENSE). Enthält [kormax/apple-home-key-reader](https://github.com/kormax/apple-home-key-reader) (Apache-2.0) unverändert unter `services/rfid/doorstation_rfid/vendor/` – siehe [NOTICE](NOTICE).
