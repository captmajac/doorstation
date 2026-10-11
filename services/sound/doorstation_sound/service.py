"""Sound-Dienst: Befehle von MQTT in die Warteschlange, Zustände zurück."""

import logging
import queue

from doorstation_common.mqtt import ServiceMqtt

from .config import SoundConfig, available
from .queue import Job, PlayQueue

log = logging.getLogger(__name__)

DEGRADED_AFTER = 3  # aufeinanderfolgende Abspielfehler, bevor degraded gemeldet wird


class SoundService:
    def __init__(self, cfg: SoundConfig, mqtt: ServiceMqtt, play_queue: PlayQueue) -> None:
        self.cfg = cfg
        self.mqtt = mqtt
        self.queue = play_queue
        self._inbox: queue.Queue = queue.Queue()
        self._names = available(cfg)
        self._state = {"state": "idle"}
        self._failures = 0

    def start(self) -> None:
        # MQTT-Callbacks laufen im paho-Thread: nur einreihen, verarbeitet wird in step().
        self.mqtt.on_command(lambda d: self._inbox.put(("cmd", d)))
        self.mqtt.on_connected(lambda: self._inbox.put(("republish", None)))
        for name in sorted(set(self.cfg.sounds) - set(self._names)):
            # Auch an die Hausautomation (sound/error), nicht nur ins Journal.
            self.mqtt.publish_error(f"Tondatei fehlt: {name} ({self.cfg.sounds[name].file})")
        self._republish()

    def _republish(self) -> None:
        self.mqtt.publish_json("available", {"names": self._names}, retain=True)
        self.mqtt.publish_json("state", self._state, retain=True)

    def step(self, timeout_s: float = 0.1) -> None:
        try:
            item = self._inbox.get(timeout=timeout_s) if timeout_s > 0 else self._inbox.get_nowait()
            self._handle(*item)
            while True:
                self._handle(*self._inbox.get_nowait())
        except queue.Empty:
            pass
        for kind, data in self.queue.tick():
            if kind == "error":
                self.mqtt.publish_error(str(data))
                self._failures += 1
                if self._failures >= DEGRADED_AFTER and self.mqtt.status != "degraded":
                    self.mqtt.set_status("degraded")  # z. B. PipeWire dauerhaft nicht erreichbar
            elif kind == "done":
                self._failures = 0
                if self.mqtt.status != "online":
                    self.mqtt.set_status("online")
            elif kind == "playing":
                self._set_state({"state": "playing", "name": data})
            elif kind == "idle":
                self._set_state({"state": "idle"})
        self.mqtt.heartbeat()

    def _set_state(self, state: dict) -> None:
        self._state = state
        self.mqtt.publish_json("state", state, retain=True)

    def _handle(self, kind: str, data) -> None:
        if kind == "republish":
            self._republish()
            return
        action = data.get("action")
        if action == "play":
            self._play(data)
        elif action == "stop":
            self.queue.stop()
        else:
            self.mqtt.publish_error(f"unbekannte Aktion '{action}'")

    def _play(self, d: dict) -> None:
        name = d.get("name")
        if name not in self._names:
            return self.mqtt.publish_error(f"play: unbekannter oder fehlender Ton '{name}'")
        entry = self.cfg.sounds[name]
        volume = d.get("volume")
        if volume is not None and (not isinstance(volume, (int, float)) or isinstance(volume, bool)
                                   or not 0 <= volume <= 1):
            return self.mqtt.publish_error(f"play: volume muss 0.0–1.0 sein, nicht {volume!r}")
        interrupt = d.get("interrupt", False)
        if not isinstance(interrupt, bool):
            return self.mqtt.publish_error("play: interrupt muss true oder false sein")
        vol = volume if volume is not None else (entry.volume if entry.volume is not None else self.cfg.default_volume)
        self.queue.play(Job(name, entry.file, float(vol)), interrupt=interrupt)
