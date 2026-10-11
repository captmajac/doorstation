"""Konfiguration des SIP-Adapters (/etc/doorstation/sip.yaml)."""

import re
from dataclasses import dataclass
from pathlib import Path

from doorstation_common.config import ConfigError, MqttSettings, load_yaml

TARGET_RE = re.compile(r"^[0-9*#]{1,20}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def valid_target(t: object) -> bool:
    return isinstance(t, str) and TARGET_RE.fullmatch(t) is not None


@dataclass(frozen=True)
class SipConfig:
    mqtt: MqttSettings
    fritzbox: str
    username: str
    default_target: str | None = "**701"
    ring_timeout_s: float = 30
    max_call_s: float = 120
    cooldown_s: float = 5
    healthcheck_s: float = 30
    command_max_age_s: float = 30
    state_dir: Path = Path("/var/lib/doorstation/sip")


_NUMBERS = ("ring_timeout_s", "max_call_s", "cooldown_s", "healthcheck_s", "command_max_age_s")
_KEYS = {"mqtt", "fritzbox", "username", "default_target", "state_dir", *_NUMBERS}


def load_config(path: Path) -> SipConfig:
    data = load_yaml(path)
    unknown = sorted(set(data) - _KEYS)
    if unknown:
        raise ConfigError(f"{path}: unbekannte Schlüssel {', '.join(unknown)}")
    for key in ("fritzbox", "username"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ConfigError(f"{path}: '{key}' fehlt")
    if not USERNAME_RE.fullmatch(data["username"]):
        raise ConfigError(f"{path}: username darf nur A–Z, a–z, 0–9, . _ - enthalten (keine Umlaute)")
    kwargs: dict = {}
    if "default_target" in data:
        t = data["default_target"]
        if t is not None and not valid_target(t):
            raise ConfigError(f"{path}: default_target '{t}' ungültig (nur Ziffern, * und #, oder null)")
        kwargs["default_target"] = t
    for key in _NUMBERS:
        if key in data:
            v = data[key]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                raise ConfigError(f"{path}: {key} muss eine Zahl > 0 sein")
            kwargs[key] = float(v)
    if "state_dir" in data:
        kwargs["state_dir"] = Path(str(data["state_dir"]))
    return SipConfig(
        mqtt=MqttSettings.from_dict(data.get("mqtt")),
        fritzbox=data["fritzbox"],
        username=data["username"],
        **kwargs,
    )
