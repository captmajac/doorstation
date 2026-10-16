"""Entry point: doorstation-sip [--config PATH]"""

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from doorstation_common.config import ConfigError
from doorstation_common.mqtt import ServiceMqtt

from .config import load_config
from .service import SipService
from .target_store import TargetStore

log = logging.getLogger("doorstation_sip")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-sip")
    parser.add_argument("--config", type=Path, default=Path("/etc/doorstation/sip.yaml"))
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

    mqtt = ServiceMqtt("sip", cfg.mqtt)
    store = TargetStore(cfg.state_dir / "target.json", cfg.default_target)
    # A root path unit (doorstation-baresip-restart.path) restarts baresip when this file appears;
    # the hardened adapter cannot restart system units itself.
    restart_flag = cfg.state_dir / "restart-baresip"
    service = SipService(cfg, mqtt, store, request_baresip_restart=restart_flag.touch)
    service.start()
    mqtt.start()
    log.info("started, target %s", service.target or "muted")
    try:
        while not stop.is_set():
            service.step(0.2)
    finally:
        mqtt.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
