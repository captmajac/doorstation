"""Verbindet Eingangslogik, Hardware-Backend und MQTT."""

import logging
import threading
import time
from collections.abc import Callable

from doorstation_common.mqtt import ServiceMqtt

from .backend import InputBackend
from .config import GpioConfig
from .inputs import ButtonInput, StateInput

log = logging.getLogger(__name__)


class GpioService:
    def __init__(self, cfg: GpioConfig, backend: InputBackend, mqtt: ServiceMqtt,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.backend = backend
        self.mqtt = mqtt
        self.buttons: dict[str, ButtonInput] = {}
        self.states: dict[str, StateInput] = {}
        self._republish_due = threading.Event()
        for inp in cfg.inputs:
            if inp.kind == "button":
                self.buttons[inp.name] = ButtonInput(inp, clock)
            else:
                self.states[inp.name] = StateInput(inp, clock)

    def start(self) -> None:
        for name, button in self.buttons.items():
            button.initial(self.backend.read(name))
        for name, state in self.states.items():
            state.initial(self.backend.read(name))
        self.republish()
        # Läuft im Netzwerk-Thread von paho: nur vormerken, veröffentlicht wird in step().
        self.mqtt.on_connected(self._republish_due.set)

    def republish(self) -> None:
        for name, state in self.states.items():
            self._publish_state(name, state.current)

    def step(self, timeout_s: float = 0.2) -> None:
        if self._republish_due.is_set():
            self._republish_due.clear()
            self.republish()
        for edge in self.backend.wait_edges(timeout_s):
            if edge.name in self.buttons:
                button = self.buttons[edge.name]
                if button.on_level(edge.raw_high):
                    self._publish_press(edge.name, button.cfg.ring)
                elif button.pop_release() and self.mqtt.connected:
                    self.mqtt.publish_json(f"input/{edge.name}", {"event": "released"})
            elif edge.name in self.states:
                reported = self.states[edge.name].on_level(edge.raw_high)
                if reported is not None:
                    self._publish_state(edge.name, reported)
        for name, state in self.states.items():
            reported = state.poll()
            if reported is not None:
                self._publish_state(name, reported)
        self.mqtt.heartbeat()

    def _publish_press(self, name: str, ring: bool) -> None:
        if not self.mqtt.connected:
            # Tastendrücke ohne Broker verwerfen: nachgeliefert käme der Anruf verspätet.
            log.warning("Taster %s ohne MQTT-Verbindung gedrückt – verworfen", name)
            return
        self.mqtt.publish_json(f"input/{name}", {"event": "pressed"})
        if ring:
            self.mqtt.publish_json_abs(("event", "ring"), {"source": name})

    def _publish_state(self, name: str, state: str) -> None:
        self.mqtt.publish_json(f"input/{name}", {"state": state}, retain=True)
