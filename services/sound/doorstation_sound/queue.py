"""Warteschlange: ein Ton nach dem anderen, Abbrechen, Zwangsende."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .player import Player


@dataclass(frozen=True)
class Job:
    name: str
    file: Path
    volume: float


class PlayQueue:
    def __init__(self, player: Player, queue_size: int, max_play_s: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.player = player
        self.max_play_s = max_play_s
        self._clock = clock
        self._waiting: deque[Job] = deque(maxlen=queue_size)  # voll → ältester fällt heraus
        self.current: Job | None = None
        self._started_at = 0.0
        self._reported_playing = False

    def play(self, job: Job, interrupt: bool = False) -> None:
        if interrupt:
            self._waiting.clear()
            self._stop_current()
        self._waiting.append(job)

    def stop(self) -> None:
        self._waiting.clear()
        self._stop_current()

    def _stop_current(self) -> None:
        if self.current is not None:
            self.player.stop()
            self.current = None

    def tick(self) -> list[tuple[str, object]]:
        events: list[tuple[str, object]] = []
        if self.current is not None:
            if not self.player.is_playing():
                err = self.player.failed()
                if err:
                    events.append(("error", f"{self.current.name}: {err}"))
                else:
                    events.append(("done", self.current.name))
                self.current = None
            elif self._clock() - self._started_at >= self.max_play_s:
                self.player.stop()
                events.append(("error", f"{self.current.name}: nach {self.max_play_s:.0f} s abgebrochen"))
                self.current = None
        if self.current is None and self._waiting:
            job = self._waiting.popleft()
            try:
                self.player.start(job.file, job.volume)
            except OSError as exc:  # pw-play fehlt o. Ä.: melden, Dienst läuft weiter
                events.append(("error", f"{job.name}: Abspielen nicht möglich: {exc}"))
                return events
            self.current = job
            self._started_at = self._clock()
            self._reported_playing = True
            events.append(("playing", job.name))
        elif self.current is None and self._reported_playing:
            self._reported_playing = False
            events.append(("idle", None))
        return events
