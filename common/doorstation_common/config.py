"""Gemeinsame Konfigurationsbausteine."""

import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Ungültige oder fehlende Konfiguration."""


PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # ein Topic-Abschnitt: ohne / + #


@dataclass(frozen=True)
class MqttSettings:
    host: str = "localhost"
    port: int = 1883
    prefix: str = "doorstation"
    heartbeat_s: float = 300  # Status regelmäßig wiederholen (Lebenszeichen); 0 = aus

    @classmethod
    def from_dict(cls, d: dict | None) -> "MqttSettings":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise ConfigError("mqtt: muss ein Mapping sein")
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise ConfigError(f"mqtt: unbekannte Schlüssel {', '.join(unknown)}")
        hb = d.get("heartbeat_s", 300)
        if not isinstance(hb, (int, float)) or isinstance(hb, bool) or hb < 0:
            raise ConfigError("mqtt: heartbeat_s muss eine Zahl ≥ 0 sein")
        host = d.get("host", "localhost")
        if not isinstance(host, str) or not host:
            raise ConfigError("mqtt: host muss ein Rechnername oder eine Adresse sein")
        port = d.get("port", 1883)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ConfigError("mqtt: port muss eine Zahl 1–65535 sein")
        prefix = d.get("prefix", "doorstation")
        if not isinstance(prefix, str) or not PREFIX_RE.fullmatch(prefix):
            raise ConfigError("mqtt: prefix darf nur A–Z, a–z, 0–9, _ und - enthalten (ohne / + #)")
        return cls(**d)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader, der doppelte Schlüssel ablehnt (sonst überschreibt der zweite still den ersten)."""


def _construct_unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _value in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConfigError(f"Schlüssel '{key}' doppelt (Zeile {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506 (SafeLoader)
    except FileNotFoundError:
        raise ConfigError(f"Konfiguration nicht gefunden: {path}") from None
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: kein gültiges YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: oberste Ebene muss ein Mapping sein")
    return data
