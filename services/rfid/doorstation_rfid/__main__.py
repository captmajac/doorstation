"""Startpunkt: doorstation-rfid [--config PFAD]"""

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from doorstation_common.config import ConfigError
from doorstation_common.mqtt import ServiceMqtt

from .config import load_config

log = logging.getLogger("doorstation_rfid")

# kormax loggt über den Root-Logger bei INFO Schlüsselmaterial (Sitzungsschlüssel, Kopplungsdaten).
# Deshalb läuft der Root-Logger auf WARNING; nur unsere eigenen Logger dürfen INFO schreiben.
QUIET_LOGGERS = ("pyhap", "nfc", "zeroconf")
OWN_LOGGERS = ("doorstation_rfid", "doorstation_common")
STATE_FILES = ("hap.state", "homekey.json")
CHECK_INTERVAL_S = 10.0


def configure_logging(stream=None) -> None:
    logging.basicConfig(level=logging.WARNING, stream=stream, force=True,
                        format="%(levelname)s %(name)s: %(message)s")
    for name in OWN_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    quiet_loggers()


def quiet_loggers() -> None:
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def secure_state_files(state_dir: Path) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    for name in STATE_FILES:
        f = state_dir / name
        if f.exists():
            os.chmod(f, 0o600)


class PairingWatch:
    """Paarung melden (bei Änderung und nach Wiederverbindung), Dateirechte nachziehen.

    check() läuft zyklisch im Überwachungs-Thread und fängt jede Ausnahme ab – sonst endete
    der Thread still und Paarungsänderungen würden nicht mehr gemeldet.
    """

    def __init__(self, mqtt: ServiceMqtt, is_paired, pincode, state_dir: Path) -> None:
        self._mqtt = mqtt
        self._is_paired = is_paired
        self._pincode = pincode
        self._state_dir = state_dir
        self._paired: bool | None = None
        self._republish_due = threading.Event()

    def republish(self) -> None:
        """Aus dem paho-Thread: nur vormerken, gemeldet wird in check()."""
        self._republish_due.set()

    def check(self) -> None:
        try:
            now = self._is_paired()
            if now != self._paired or self._republish_due.is_set():
                self._republish_due.clear()
                changed = now != self._paired
                self._paired = now
                self._mqtt.publish_json("pairing", {"paired": now}, retain=True)
                if changed and not now:
                    log.warning("Leser nicht gepaart – Kopplungscode für die Home-App: %s", self._pincode())
            secure_state_files(self._state_dir)
        except Exception:
            log.exception("Überwachung der Paarung fehlgeschlagen")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-rfid")
    parser.add_argument("--config", type=Path, default=Path("/etc/doorstation/rfid.yaml"))
    args = parser.parse_args(argv)
    configure_logging()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2

    from .kormax import AccessoryDriver, BroadcastFrameContactlessFrontend, Service
    from .lock import QuietLock
    from .loop import ReaderLoop
    from .reporter import Reporter
    from .store import AtomicRepository

    secure_state_files(cfg.state_dir)
    mqtt = ServiceMqtt("rfid", cfg.mqtt)
    reporter = Reporter(mqtt, cfg)
    clf = BroadcastFrameContactlessFrontend(path=cfg.nfc_path, broadcast_enabled=True)
    repository = AtomicRepository(str(cfg.state_dir / "homekey.json"))  # kormax schreibt nicht atomar
    service = Service(clf, repository=repository, express=cfg.express, finish=cfg.finish, flow=cfg.flow)
    driver = AccessoryDriver(port=cfg.hap_port, persist_file=str(cfg.state_dir / "hap.state"))
    accessory = QuietLock(driver, cfg.accessory_name, service=service, on_homekey=lambda ep: None)
    driver.add_accessory(accessory=accessory)

    health = {"ok": None}

    def on_health(ok: bool) -> None:
        if ok != health["ok"]:
            health["ok"] = ok
            mqtt.set_status("online" if ok else "degraded")

    loop = ReaderLoop(clf, service, reporter, on_health=on_health, on_tick=mqtt.heartbeat)
    stop = threading.Event()

    pairing = PairingWatch(mqtt, lambda: loop.paired, lambda: driver.state.pincode.decode(), cfg.state_dir)
    mqtt.on_connected(pairing.republish)

    def watch() -> None:
        while not stop.is_set():
            pairing.check()
            stop.wait(CHECK_INTERVAL_S)

    def shutdown(*_):
        stop.set()
        driver.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    mqtt.start()
    threading.Thread(target=loop.run, args=(stop,), name="nfc", daemon=True).start()
    threading.Thread(target=watch, name="watch", daemon=True).start()
    log.info("gestartet, Leser %s", cfg.nfc_path)
    try:
        driver.start()  # blockiert bis shutdown()
    finally:
        stop.set()
        mqtt.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
