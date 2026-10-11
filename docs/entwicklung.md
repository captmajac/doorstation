# Entwicklung

## Aufbau des Repos

```
common/                     Gemeinsames Paket doorstation_common: MQTT-Hülle (Status, Last Will,
                            Lebenszeichen, Befehle, Fehler), Konfiguration, Zeitstempel, Testhilfen
services/
├── gpio/                   doorstation_gpio: Eingänge, Drosselung, libgpiod-Backend, Simulation
├── sip/                    doorstation_sip: Zustandsautomat, baresip-Anbindung, Audio-Initialisierung
│   └── baresip/            Vorlagen für baresip config/accounts
├── sound/                  doorstation_sound: Warteschlange, pw-play-Player
│   └── sounds/beep.wav     mitgelieferter Lese-Ton
└── rfid/                   doorstation_rfid: eigene Leseschleife, ID-Logik, HomeKit-Schloss
    └── doorstation_rfid/vendor/   kormax/apple-home-key-reader (unverändert, Apache-2.0)
config-examples/            Beispielkonfigurationen für /etc/doorstation/
deploy/                     systemd-Units, Mosquitto-, nftables- und PipeWire-Vorlagen
install.sh                  Installation, Update, Sicherung
scripts/pi-test.sh          Tests auf dem Raspberry Pi ausführen
tests/                      Tests für install.sh
docs/                       Dokumentation
```

## Grundsätze

- Jeder Dienst trennt **reine Logik** (Zustandsautomaten, Warteschlangen, Drosselung – mit injizierbarer Uhr) von **Hardware/Prozessen** (libgpiod, baresip, pw-play, PN532) hinter austauschbaren Schnittstellen. Die Logik ist ohne Hardware testbar.
- MQTT-Callbacks laufen im Netzwerk-Thread von paho und **reihen nur ein**; verarbeitet wird im Hauptthread des Dienstes.
- Zeitstempel (`ts`) aus der Wanduhr, Timer und Sperrzeiten aus der monotonen Uhr.
- Konfiguration wird beim Start streng geprüft; Fehler nennen Datei und Feld.

## Tests

Die Tests laufen auf einem Raspberry Pi mit Python 3.13 (Debian 13). `scripts/pi-test.sh` überträgt das Repo per `rsync` auf den Test-Pi (Host `doorstation-test`, änderbar über `DOORSTATION_TEST_HOST`), legt dort ein venv an und führt `pytest` aus:

```bash
scripts/pi-test.sh                       # alle Tests
scripts/pi-test.sh services/sip/tests    # nur ein Dienst
```

Hardware-nahe Teile werden mit Attrappen getestet (`FakeMqttClient`, `FakeBackend`, `FakePlayer`, Fake-Leser). `install.sh` lässt sich einlesen, ohne dass es etwas ausführt (`source install.sh`); `tests/test_install_sh.py` ruft so einzelne Funktionen ohne root auf. Andere Verzeichnisse: `DOORSTATION_ETC`, `DOORSTATION_VAR`, `DOORSTATION_BOOT`, z. B. `DOORSTATION_VAR=/tmp/test sudo -E ./install.sh rfid-import …`.

## Auf einem Pi ausprobieren

```bash
rsync -a --delete --exclude .git ./ doorstation-test:doorstation-dev/
ssh doorstation-test 'sudo ~/doorstation-dev/install.sh'
ssh doorstation-test 'mosquitto_sub -v -t "doorstation/#"'
```

GPIO ohne Taster: `doorstation-gpio --simulate` liest Befehle wie `bell 1` von stdin.
