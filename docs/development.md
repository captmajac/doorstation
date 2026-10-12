**English** | [Deutsch](de/entwicklung.md)

# Development

## Repository layout

```
common/                     shared package doorstation_common: MQTT wrapper (status, last will,
                            heartbeat, commands, errors), configuration, timestamps, test helpers
services/
├── gpio/                   doorstation_gpio: inputs, throttling, libgpiod backend, simulation
├── sip/                    doorstation_sip: state machine, baresip integration, audio initialization
│   └── baresip/            templates for baresip config/accounts
├── sound/                  doorstation_sound: queue, pw-play player
│   └── sounds/beep.wav     shipped read beep
└── rfid/                   doorstation_rfid: own read loop, ID logic, HomeKit lock
    └── doorstation_rfid/vendor/   kormax/apple-home-key-reader (unchanged, Apache-2.0)
config-examples/            example configurations for /etc/doorstation/
deploy/                     systemd units, Mosquitto, nftables and PipeWire templates
install.sh                  installation, update, backup
scripts/pi-test.sh          run the tests on the Raspberry Pi
tests/                      tests for install.sh, language and documentation checks
docs/                       documentation (English; German in docs/de/)
```

## Principles

- Every service separates **pure logic** (state machines, queues, throttling – with an injectable clock) from **hardware/processes** (libgpiod, baresip, pw-play, PN532) behind exchangeable interfaces. The logic can be tested without hardware.
- MQTT callbacks run in paho's network thread and **only enqueue**; processing happens in the service's main thread.
- Timestamps (`ts`) come from the wall clock, timers and cooldowns from the monotonic clock.
- The configuration is checked strictly at start; errors name the file and the field.
- Code, comments, log and error messages are in English (`tests/test_language.py` checks this).
- The documentation exists in English and German: change both versions together. `tests/test_docs.py` checks that every document has its counterpart, the language switcher and all links and anchors.

## Tests

The tests run on a Raspberry Pi with Python 3.13 (Debian 13). `scripts/pi-test.sh` copies the repo to the test Pi via `rsync` (host `doorstation-test`, change with `DOORSTATION_TEST_HOST`), creates a venv there and runs `pytest`:

```bash
scripts/pi-test.sh                       # all tests
scripts/pi-test.sh services/sip/tests    # one service only
```

Hardware-related parts are tested with fakes (`FakeMqttClient`, `FakeBackend`, `FakePlayer`, fake reader). `install.sh` can be sourced without running anything (`source install.sh`); `tests/test_install_sh.py` calls single functions this way without root. Other directories: `DOORSTATION_ETC`, `DOORSTATION_VAR`, `DOORSTATION_BOOT`, e.g. `DOORSTATION_VAR=/tmp/test sudo -E ./install.sh rfid-import …`.

## Trying it on a Pi

```bash
rsync -a --delete --exclude .git ./ doorstation-test:doorstation-dev/
ssh doorstation-test 'sudo ~/doorstation-dev/install.sh'
ssh doorstation-test 'mosquitto_sub -v -t "doorstation/#"'
```

GPIO without buttons: `doorstation-gpio --simulate` reads commands like `bell 1` from stdin.
