"""Meldet gelesene IDs per MQTT – einmal pro Vorhalten, mit Lese-Ton."""

import logging
import time
from collections.abc import Callable

from doorstation_common.mqtt import ServiceMqtt

from .config import RfidConfig

log = logging.getLogger(__name__)


class Reporter:
    def __init__(self, mqtt: ServiceMqtt, cfg: RfidConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.mqtt = mqtt
        self.cfg = cfg
        self._clock = clock
        self._last_seen: dict[str, float] = {}

    def report(self, kind: str, id_: str) -> bool:
        now = self._clock()
        last = self._last_seen.get(id_)
        if last is not None and now - last < self.cfg.repeat_block_s:
            self._last_seen[id_] = now  # liegt noch im Feld: Sperre verlängern
            return False
        if not self.mqtt.connected:
            # RFID-Ereignisse nie puffern – eine verspätete Meldung könnte die Tür öffnen.
            log.warning("%s %s gelesen, aber keine MQTT-Verbindung – verworfen", kind, id_)
            return False
        self._last_seen[id_] = now
        self.mqtt.publish_json("read", {"type": kind, "id": id_}, qos=0)
        if self.cfg.feedback_sound:
            self.mqtt.publish_json_abs(("sound", "cmd"), {"action": "play", "name": self.cfg.feedback_sound})
        log.info("%s %s gemeldet", kind, id_)
        return True
