"""Input logic without hardware: active level, edges, throttling with trailing update."""

import time
from collections.abc import Callable

from .config import InputConfig


class ButtonInput:
    """Button: one event per configured edge, throttled by min_interval_s."""

    def __init__(self, cfg: InputConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self._clock = clock
        self._pressed = False
        self._last_event: float | None = None
        self._press_reported = False
        self._release_pending = False

    def initial(self, raw_high: bool) -> None:
        """Take the initial level without emitting an event."""
        self._pressed = raw_high == (self.cfg.active == "high")

    def on_level(self, raw_high: bool) -> bool:
        pressed = raw_high == (self.cfg.active == "high")
        if pressed == self._pressed:
            return False
        self._pressed = pressed
        if not pressed and self._press_reported:
            self._press_reported = False
            self._release_pending = self.cfg.report_release
        if pressed != (self.cfg.trigger == "press"):
            return False
        now = self._clock()
        if self._last_event is not None and now - self._last_event < self.cfg.min_interval_s:
            return False
        self._last_event = now
        self._press_reported = pressed
        return True

    def pop_release(self) -> bool:
        """True if a reported press was released (only with report_release)."""
        due, self._release_pending = self._release_pending, False
        return due


class StateInput:
    """State: first change immediately, further changes within min_interval_s only via poll()."""

    def __init__(self, cfg: InputConfig, clock: Callable[[], float] = time.monotonic) -> None:
        assert cfg.states is not None
        self.cfg = cfg
        self._clock = clock
        self.current = cfg.states[0]
        self._latest = self.current
        self._last_report: float | None = None

    def _state(self, raw_high: bool) -> str:
        active = raw_high == (self.cfg.active == "high")
        return self.cfg.states[1] if active else self.cfg.states[0]

    def _window_open(self) -> bool:
        return self._last_report is not None and self._clock() - self._last_report < self.cfg.min_interval_s

    def _report(self, state: str) -> str:
        self.current = state
        self._last_report = self._clock()
        return state

    def initial(self, raw_high: bool) -> str:
        self.current = self._latest = self._state(raw_high)
        return self.current

    def on_level(self, raw_high: bool) -> str | None:
        self._latest = self._state(raw_high)
        if self._latest == self.current or self._window_open():
            return None
        return self._report(self._latest)

    def poll(self) -> str | None:
        if self._latest == self.current or self._window_open():
            return None
        return self._report(self._latest)
