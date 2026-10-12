"""Hardware access: libgpiod v2 on the Pi, fake backend for tests and simulation."""

import queue
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from .config import InputConfig


@dataclass(frozen=True)
class Edge:
    name: str
    raw_high: bool


class InputBackend(Protocol):
    def read(self, name: str) -> bool: ...
    def wait_edges(self, timeout_s: float) -> list[Edge]: ...
    def close(self) -> None: ...


class FakeBackend:
    """Levels are set via set_level() (tests, --simulate)."""

    def __init__(self, levels: dict[str, bool]) -> None:
        self._levels = dict(levels)
        self._edges: queue.Queue[Edge] = queue.Queue()

    def read(self, name: str) -> bool:
        return self._levels[name]

    def set_level(self, name: str, raw_high: bool) -> None:
        if self._levels.get(name) != raw_high:
            self._levels[name] = raw_high
            self._edges.put(Edge(name, raw_high))

    def wait_edges(self, timeout_s: float) -> list[Edge]:
        edges: list[Edge] = []
        try:
            edges.append(self._edges.get(timeout=timeout_s) if timeout_s > 0 else self._edges.get_nowait())
        except queue.Empty:
            return edges
        while True:
            try:
                edges.append(self._edges.get_nowait())
            except queue.Empty:
                return edges

    def close(self) -> None:
        pass


class LibgpiodBackend:
    """Edge events with kernel debouncing via libgpiod v2 (python3-libgpiod)."""

    def __init__(self, chip: str, inputs: Sequence[InputConfig]) -> None:
        import gpiod
        from gpiod.line import Bias, Direction
        from gpiod.line import Edge as GpiodEdge

        self._gpiod = gpiod
        bias = {"off": Bias.DISABLED, "up": Bias.PULL_UP, "down": Bias.PULL_DOWN}
        config = {
            inp.pin: gpiod.LineSettings(
                direction=Direction.INPUT,
                edge_detection=GpiodEdge.BOTH,
                bias=bias[inp.pull],
                debounce_period=timedelta(milliseconds=inp.debounce_ms),
            )
            for inp in inputs
        }
        self._names = {inp.pin: inp.name for inp in inputs}
        self._pins = {inp.name: inp.pin for inp in inputs}
        self._request = gpiod.request_lines(chip, consumer="doorstation-gpio", config=config)

    def read(self, name: str) -> bool:
        from gpiod.line import Value

        return self._request.get_value(self._pins[name]) == Value.ACTIVE

    def wait_edges(self, timeout_s: float) -> list[Edge]:
        if not self._request.wait_edge_events(timedelta(seconds=timeout_s)):
            return []
        rising = self._gpiod.EdgeEvent.Type.RISING_EDGE
        return [
            Edge(self._names[ev.line_offset], ev.event_type == rising)
            for ev in self._request.read_edge_events()
        ]

    def close(self) -> None:
        self._request.release()
