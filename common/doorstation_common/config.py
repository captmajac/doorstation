"""Shared configuration building blocks."""

import re
from dataclasses import dataclass, fields
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Invalid or missing configuration."""


PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # a single topic level: no / + #


@dataclass(frozen=True)
class MqttSettings:
    host: str = "localhost"
    port: int = 1883
    prefix: str = "doorstation"
    heartbeat_s: float = 300  # repeat status periodically (heartbeat); 0 = off

    @classmethod
    def from_dict(cls, d: dict | None) -> "MqttSettings":
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise ConfigError("mqtt: must be a mapping")
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise ConfigError(f"mqtt: unknown keys {', '.join(unknown)}")
        hb = d.get("heartbeat_s", 300)
        if not isinstance(hb, (int, float)) or isinstance(hb, bool) or hb < 0:
            raise ConfigError("mqtt: heartbeat_s must be a number >= 0")
        host = d.get("host", "localhost")
        if not isinstance(host, str) or not host:
            raise ConfigError("mqtt: host must be a host name or address")
        port = d.get("port", 1883)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ConfigError("mqtt: port must be a number 1-65535")
        prefix = d.get("prefix", "doorstation")
        if not isinstance(prefix, str) or not PREFIX_RE.fullmatch(prefix):
            raise ConfigError("mqtt: prefix may only contain A-Z, a-z, 0-9, _ and - (no / + #)")
        return cls(**d)


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys (otherwise the second silently overrides the first)."""


def _construct_unique_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _value in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ConfigError(f"duplicate key '{key}' (line {key_node.start_mark.line + 1})")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506 (SafeLoader)
    except FileNotFoundError:
        raise ConfigError(f"configuration not found: {path}") from None
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data
