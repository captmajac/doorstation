"""Konfiguration des Sound-Dienstes (/etc/doorstation/sound.yaml)."""

import re
from dataclasses import dataclass
from pathlib import Path

from doorstation_common.config import ConfigError, MqttSettings, load_yaml

NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass(frozen=True)
class SoundEntry:
    name: str
    file: Path
    volume: float | None


@dataclass(frozen=True)
class SoundConfig:
    mqtt: MqttSettings
    default_volume: float = 0.8
    queue_size: int = 3
    max_play_s: float = 120
    target: str = "ec_sink"
    sounds: dict = None  # Name → SoundEntry


def _volume(v, where: str) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1:
        raise ConfigError(f"{where}: volume muss eine Zahl 0.0–1.0 sein")
    return float(v)


def load_config(path: Path) -> SoundConfig:
    data = load_yaml(path)
    unknown = sorted(set(data) - {"mqtt", "default_volume", "queue_size", "max_play_s", "target", "sounds"})
    if unknown:
        raise ConfigError(f"{path}: unbekannte Schlüssel {', '.join(unknown)}")
    kw: dict = {}
    if "default_volume" in data:
        kw["default_volume"] = _volume(data["default_volume"], "default_volume")
    if "queue_size" in data:
        q = data["queue_size"]
        if not isinstance(q, int) or isinstance(q, bool) or q < 1:
            raise ConfigError(f"{path}: queue_size muss eine ganze Zahl ≥ 1 sein")
        kw["queue_size"] = q
    if "max_play_s" in data:
        m = data["max_play_s"]
        if not isinstance(m, (int, float)) or isinstance(m, bool) or m <= 0:
            raise ConfigError(f"{path}: max_play_s muss eine Zahl > 0 sein")
        kw["max_play_s"] = float(m)
    if "target" in data:
        if not isinstance(data["target"], str) or not data["target"]:
            raise ConfigError(f"{path}: target muss ein PipeWire-Knotenname sein")
        kw["target"] = data["target"]
    raw = data.get("sounds") or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: sounds muss ein Mapping sein")
    sounds = {}
    for name, entry in raw.items():
        name = str(name)
        if not NAME_RE.fullmatch(name):
            raise ConfigError(f"{path}: Name '{name}' ungültig (nur a–z, 0–9, _)")
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ConfigError(f"{path}: Ton '{name}' braucht 'file'")
        extra = sorted(set(entry) - {"file", "volume"})
        if extra:
            raise ConfigError(f"{path}: Ton '{name}': unbekannte Schlüssel {', '.join(extra)}")
        vol = _volume(entry["volume"], f"Ton '{name}'") if entry.get("volume") is not None else None
        sounds[name] = SoundEntry(name, Path(entry["file"]), vol)
    return SoundConfig(mqtt=MqttSettings.from_dict(data.get("mqtt")), sounds=sounds, **kw)


def available(cfg: SoundConfig) -> list[str]:
    """Namen, deren Datei vorhanden ist (fehlende Dateien sind kein Startfehler)."""
    return sorted(n for n, e in cfg.sounds.items() if e.file.is_file())
