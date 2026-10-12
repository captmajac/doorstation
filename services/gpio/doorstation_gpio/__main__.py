"""Entry point: doorstation-gpio [--config PATH] [--simulate]"""

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from doorstation_common.config import ConfigError
from doorstation_common.mqtt import ServiceMqtt

from .backend import FakeBackend, LibgpiodBackend
from .config import load_config
from .service import GpioService

log = logging.getLogger("doorstation_gpio")


def _simulate_commands(backend: FakeBackend, names: set[str], stop: threading.Event) -> None:
    """Reads commands from stdin: '<input> <0|1>', 'sleep <s>'. End of stdin stops the service."""
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "sleep" and len(parts) == 2:
            time.sleep(float(parts[1]))
        elif len(parts) == 2 and parts[0] in names and parts[1] in ("0", "1"):
            backend.set_level(parts[0], parts[1] == "1")
        else:
            print(f"unknown command: {line}", file=sys.stderr)
    time.sleep(0.5)
    stop.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-gpio")
    parser.add_argument("--config", type=Path, default=Path("/etc/doorstation/gpio.yaml"))
    parser.add_argument("--simulate", action="store_true", help="fake backend instead of GPIO, commands from stdin")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    if args.simulate:
        backend = FakeBackend({inp.name: False for inp in cfg.inputs})
        threading.Thread(
            target=_simulate_commands, args=(backend, {i.name for i in cfg.inputs}, stop), daemon=True
        ).start()
    else:
        backend = LibgpiodBackend(cfg.chip, cfg.inputs)

    # --simulate may run next to the running service: separate client ID.
    mqtt = ServiceMqtt("gpio", cfg.mqtt, client_id_suffix="-sim" if args.simulate else "")
    service = GpioService(cfg, backend, mqtt)
    mqtt.start()
    service.start()
    log.info("started with %d inputs", len(cfg.inputs))
    try:
        while not stop.is_set():
            service.step(0.2)
        service.step(0)
    finally:
        mqtt.stop()
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
