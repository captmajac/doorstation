"""State machine for calls - without MQTT or baresip, returns effects."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import SipConfig


@dataclass(frozen=True)
class Dial:
    uri: str


@dataclass(frozen=True)
class Hangup:
    pass


@dataclass(frozen=True)
class CallState:
    state: str
    direction: str | None = None
    peer: str | None = None
    reason: str | None = None


def peer_from_uri(uri: str) -> str:
    """'sip:**610@fritz.box' → '**610'; unknown forms unchanged."""
    if uri.startswith("sip:") and "@" in uri:
        return uri[4:].split("@", 1)[0]
    return uri


def host_from_uri(uri: str) -> str:
    """'sip:**610@fritz.box:5060;transport=udp' → 'fritz.box'."""
    rest = uri.split("@", 1)[1] if "@" in uri else ""
    return rest.split(";", 1)[0].split(":", 1)[0].strip("<>").lower()


def _close_reason(param: str) -> str:
    p = param.lower()
    if "486" in p or "busy" in p:
        return "busy"
    if "603" in p or "decline" in p or "reject" in p:
        return "rejected"
    return "hangup"


class CallMachine:
    def __init__(self, cfg: SipConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self._clock = clock
        self.state = "idle"
        self.registered = False
        self._direction: str | None = None
        self._peer: str | None = None
        self._deadline: float | None = None  # ring timeout, maximum duration or end of cooldown

    def _enter(self, state: str, reason: str | None = None) -> CallState:
        self.state = state
        now = self._clock()
        if state == "calling":
            self._deadline = now + self.cfg.ring_timeout_s
        elif state == "active":
            self._deadline = now + self.cfg.max_call_s
        elif state == "ended":
            self._deadline = now + self.cfg.cooldown_s
        else:
            self._deadline = None
            self._direction = self._peer = None
            return CallState("idle")
        return CallState(state, self._direction, self._peer, reason)

    def ring(self, target: str | None) -> list:
        if self.state != "idle" or target is None:
            return []
        self._direction, self._peer = "outgoing", target
        if not self.registered:
            return [self._enter("ended", "not_registered")]
        return [Dial(f"sip:{target}@{self.cfg.fritzbox}"), self._enter("calling")]

    def hangup(self) -> list:
        if self.state not in ("calling", "active"):
            return []
        return [Hangup(), self._enter("ended", "hangup")]

    def baresip_event(self, ev: dict) -> list:
        typ = ev.get("type")
        if typ == "REGISTER_OK":
            self.registered = True
            return []
        if typ == "REGISTER_FAIL":
            self.registered = False
            return []
        if typ == "CALL_ESTABLISHED":
            if self.state == "calling" and ev.get("direction") != "incoming":
                return [self._enter("active")]
            if ev.get("direction") == "incoming":
                uri = str(ev.get("peeruri", ""))
                # Accept calls via the FritzBox only - end direct INVITEs from the LAN immediately.
                if host_from_uri(uri) not in (self.cfg.fritzbox.lower(), "fritz.box"):
                    return [Hangup()]
                if self.state in ("idle", "ended"):
                    self._direction = "incoming"
                    self._peer = peer_from_uri(uri)
                    return [self._enter("active")]
            # Call unknown to the state machine (e.g. after an adapter restart): end it.
            return [Hangup()]
        if typ == "CALL_CLOSED" and self.state in ("calling", "active"):
            return [self._enter("ended", _close_reason(str(ev.get("param", ""))))]
        return []

    def tick(self) -> list:
        if self._deadline is None or self._clock() < self._deadline:
            return []
        if self.state == "calling":
            return [Hangup(), self._enter("ended", "timeout")]
        if self.state == "active":
            return [Hangup(), self._enter("ended", "max_duration")]
        if self.state == "ended":
            return [self._enter("idle")]
        return []

    def reset(self) -> list:
        if self.state == "idle":
            return []
        running = self.state in ("calling", "active")
        return ([Hangup()] if running else []) + [self._enter("idle")]
