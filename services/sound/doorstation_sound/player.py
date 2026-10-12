"""Playback: pw-play via PipeWire (real Pi) or fake player (tests)."""

import logging
import subprocess
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class Player(Protocol):
    def start(self, file: Path, volume: float) -> None: ...
    def is_playing(self) -> bool: ...
    def stop(self) -> None: ...
    def failed(self) -> str | None: ...


class PwPlayPlayer:
    def __init__(self, target: str) -> None:
        self.target = target
        self._proc: subprocess.Popen | None = None
        self._stopped = False

    def start(self, file: Path, volume: float) -> None:
        self._stopped = False
        cmd = ["pw-play", "--target", self.target, "--volume", f"{volume:.2f}", str(file)]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def is_playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        if not self.is_playing():
            return
        self._stopped = True
        self._proc.terminate()
        try:
            self._proc.wait(1)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()

    def failed(self) -> str | None:
        if self._proc is None or self._stopped or self._proc.poll() in (None, 0):
            return None
        err = (self._proc.stderr.read() if self._proc.stderr else "").strip()
        return f"pw-play Exit {self._proc.returncode}: {err[:200]}"


class FakePlayer:
    def __init__(self) -> None:
        self.started: list[Path] = []
        self.volumes: list[float] = []
        self.stopped = 0
        self._playing = False
        self._failed: str | None = None

    def start(self, file: Path, volume: float) -> None:
        self.started.append(file)
        self.volumes.append(volume)
        self._playing = True
        self._failed = None

    def is_playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        if self._playing:
            self.stopped += 1
        self._playing = False

    def failed(self) -> str | None:
        return self._failed

    def finish(self, ok: bool = True) -> None:
        """Test helper: end the current sound (successfully or with an error)."""
        self._playing = False
        self._failed = None if ok else "Exit 1"
