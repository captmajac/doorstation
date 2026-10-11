"""Dauerhaft gespeichertes Anrufziel (None = stumm)."""

import json
import logging
import os
from pathlib import Path

from .config import valid_target

log = logging.getLogger(__name__)


class TargetStore:
    def __init__(self, path: Path, default: str | None) -> None:
        self.path = Path(path)
        self.default = default

    def load(self) -> str | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self.default
        except (OSError, ValueError) as exc:
            log.warning("Ziel-Datei %s unlesbar (%s) – verwende %s", self.path, exc, self.default)
            return self.default
        if not isinstance(data, dict) or "target" not in data:
            log.warning("Ziel-Datei %s ohne 'target' – verwende %s", self.path, self.default)
            return self.default
        target = data["target"]
        if target is None or valid_target(target):
            return target
        log.warning("Ziel '%s' in %s ungültig – verwende %s", target, self.path, self.default)
        return self.default

    def save(self, target: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"target": target}), encoding="utf-8")
        os.replace(tmp, self.path)
