"""SIP adapter: connects MQTT (bell, home automation), state machine and baresip."""

import json
import logging
import queue
import re
import time
from collections.abc import Callable
from datetime import datetime

from doorstation_common.mqtt import ServiceMqtt

from .config import SipConfig, valid_target
from .machine import CallMachine, CallState, Dial, Hangup
from .target_store import TargetStore

log = logging.getLogger(__name__)

BARESIP = "/baresip"
_REGINFO_OK = re.compile(r"\bOK\b")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class SipService:
    def __init__(self, cfg: SipConfig, mqtt: ServiceMqtt, store: TargetStore,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.mqtt = mqtt
        self.store = store
        self._clock = clock
        self._wall = wall
        self.machine = CallMachine(cfg, clock)
        self.target = store.load()
        self._queue: queue.Queue = queue.Queue()
        self._token = 0
        self._pending_health: str | None = None
        self._misses = 0
        self._next_health = clock()  # first query immediately: learn the registration after an adapter restart
        self._last_call = CallState("idle")
        self._registration = "unknown"

    # --- start and reconnect --------------------------------------------
    def start(self) -> None:
        # A call baresip still holds from before an adapter restart is unknown
        # (no time limit) - so hang up first.
        self._send("hangup")
        prefix = self.cfg.mqtt.prefix
        # All callbacks run in paho's thread: only enqueue, step() processes.
        self.mqtt.subscribe(f"{prefix}/event/ring", lambda t, p: self._queue.put(("ring", p)))
        self.mqtt.subscribe(f"{BARESIP}/event", lambda t, p: self._queue.put(("baresip", p)))
        self.mqtt.subscribe(f"{BARESIP}/command_resp/+", lambda t, p: self._queue.put(("resp", (t, p))))
        self.mqtt.on_command(lambda d: self._queue.put(("cmd", d)))
        self.mqtt.on_connected(lambda: self._queue.put(("republish", None)))
        self._republish()

    def _republish(self) -> None:
        self._publish_target()
        self._publish_call(self._last_call)
        self.mqtt.publish_json("registration", {"state": self._registration}, retain=True)

    # --- main loop ------------------------------------------------------
    def step(self, timeout_s: float = 0.2) -> None:
        try:
            item = self._queue.get(timeout=timeout_s) if timeout_s > 0 else self._queue.get_nowait()
            self._handle_safely(item)
            while True:
                self._handle_safely(self._queue.get_nowait())
        except queue.Empty:
            pass
        self._apply(self.machine.tick())
        self._health()
        self.mqtt.heartbeat()

    def _handle_safely(self, item) -> None:
        """A failing item must neither lose the others nor end the service."""
        try:
            self._handle(*item)
        except Exception as exc:
            log.exception("error handling %s", item[0])
            self.mqtt.publish_error(f"{item[0]}: {exc}")

    def _handle(self, kind: str, data) -> None:
        if kind == "ring":
            self._apply(self.machine.ring(self.target))
        elif kind == "baresip":
            self._baresip_event(data)
        elif kind == "resp":
            topic, payload = data
            if self._pending_health is not None and topic.rsplit("/", 1)[-1] == self._pending_health:
                self._pending_health = None
                self._misses = 0
                self._reginfo(payload)
        elif kind == "cmd":
            self._command(data)
        elif kind == "republish":
            self._republish()

    # --- baresip --------------------------------------------------------
    def _send(self, command: str, params: str = "") -> str:
        self._token += 1
        token = str(self._token)
        payload = json.dumps({"command": command, "params": params, "token": token})
        self.mqtt.publish_text_abs(f"{BARESIP}/command/{token}", payload)
        return token

    def _baresip_event(self, payload: bytes) -> None:
        try:
            ev = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            log.warning("invalid baresip event: %r", payload[:200])
            return
        if not isinstance(ev, dict):
            return
        typ = ev.get("type")
        if typ in ("REGISTER_OK", "REGISTER_FAIL"):
            self._set_registration("registered" if typ == "REGISTER_OK" else "failed")
            if self._misses < 2:
                self._set_status("online" if typ == "REGISTER_OK" else "degraded")
        elif typ == "CALL_DTMF_START":
            # Only during our own call: "#" opens the door in the home automation. A key from
            # an unknown or just rejected call must never be reported.
            if self.machine.state == "active":
                self.mqtt.publish_json("dtmf", {"key": str(ev.get("param", ""))})
            else:
                log.warning("DTMF without an active call dropped")
        self._apply(self.machine.baresip_event(ev))

    def _reginfo(self, payload: bytes) -> None:
        """Response to reginfo: shows whether baresip is registered (also after an adapter restart)."""
        try:
            data = str(json.loads(payload.decode("utf-8")).get("data", ""))
        except (UnicodeDecodeError, ValueError, AttributeError):
            data = ""
        registered = _REGINFO_OK.search(_ANSI.sub(" ", data)) is not None  # baresip colors "OK"
        self.machine.registered = registered
        self._set_registration("registered" if registered else "failed")
        self._set_status("online" if registered else "degraded")

    def _set_registration(self, state: str) -> None:
        if state != self._registration:
            self._registration = state
            self.mqtt.publish_json("registration", {"state": state}, retain=True)

    def _set_status(self, state: str) -> None:
        if state != self.mqtt.status:
            self.mqtt.set_status(state)

    def _apply(self, effects: list) -> None:
        for e in effects:
            if isinstance(e, Dial):
                self._send("dial", e.uri)
            elif isinstance(e, Hangup):
                self._send("hangup")
            elif isinstance(e, CallState):
                self._last_call = e
                self._publish_call(e)

    def _publish_call(self, e: CallState) -> None:
        data = {k: v for k, v in (("state", e.state), ("direction", e.direction),
                                  ("peer", e.peer), ("reason", e.reason)) if v is not None}
        self.mqtt.publish_json("call", data, retain=True)

    def _publish_target(self) -> None:
        self.mqtt.publish_json("target", {"target": self.target}, retain=True)

    # --- health ---------------------------------------------------------
    def _health(self) -> None:
        if self._clock() < self._next_health:
            return
        self._next_health = self._clock() + self.cfg.healthcheck_s
        if self._pending_health is not None:
            self._misses += 1
            log.warning("baresip not responding (%d)", self._misses)
            if self._misses == 2:
                self._set_status("degraded")
                self._set_registration("unknown")  # without a response the registration state is unknown
                self._apply(self.machine.reset())
        self._pending_health = self._send("reginfo")

    # --- commands from the home automation -----------------------------
    def _command(self, d: dict) -> None:
        action = d.get("action")
        if action == "set_target":
            if "target" not in d:
                return self.mqtt.publish_error("set_target: 'target' missing")
            t = d["target"]
            if t is not None and not valid_target(t):
                return self.mqtt.publish_error(f"set_target: invalid target '{t}'")
            self.store.save(t)  # save first: if that fails, the previous target stays
            self.target = t
            self._publish_target()
        elif action == "call":
            if "ts" in d and self._too_old(d["ts"]):
                return
            target = d.get("target", self.target)
            if target is None:
                return self.mqtt.publish_error("call: no target (muted)")
            if not valid_target(target):
                return self.mqtt.publish_error(f"call: invalid target '{target}'")
            if self.machine.state != "idle":
                return self.mqtt.publish_error(f"call: not possible in state {self.machine.state}")
            self._apply(self.machine.ring(target))
        elif action == "hangup":
            self._apply(self.machine.hangup())
        else:
            self.mqtt.publish_error(f"unknown action '{action}'")

    def _too_old(self, ts) -> bool:
        try:
            parsed = datetime.fromisoformat(str(ts))
            when = parsed.timestamp()
        except (ValueError, OverflowError, OSError):
            self.mqtt.publish_error(f"call: invalid timestamp '{ts}'")
            return True
        if parsed.tzinfo is None:
            self.mqtt.publish_error(f"call: timestamp '{ts}' without time zone - dropped")
            return True
        age = self._wall() - when
        if age > self.cfg.command_max_age_s:
            self.mqtt.publish_error(f"call: command {age:.0f} s old - dropped")
            return True
        if -age > self.cfg.command_max_age_s:  # home automation clock is ahead
            self.mqtt.publish_error(f"call: command {-age:.0f} s in the future - dropped")
            return True
        return False
