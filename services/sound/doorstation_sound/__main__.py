"""Startpunkt: doorstation-sound [--config PFAD]"""

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from doorstation_common.config import ConfigError
from doorstation_common.mqtt import ServiceMqtt

from .config import load_config
from .player import PwPlayPlayer
from .queue import PlayQueue
from .service import SoundService

log = logging.getLogger("doorstation_sound")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-sound")
    parser.add_argument("--config", type=Path, default=Path("/etc/doorstation/sound.yaml"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    mqtt = ServiceMqtt("sound", cfg.mqtt)
    play_queue = PlayQueue(PwPlayPlayer(cfg.target), cfg.queue_size, cfg.max_play_s)
    service = SoundService(cfg, mqtt, play_queue)
    service.start()
    mqtt.start()
    log.info("gestartet, %d Töne verfügbar", len(service._names))
    try:
        while not stop.is_set():
            service.step(0.1)
    finally:
        play_queue.stop()
        mqtt.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
