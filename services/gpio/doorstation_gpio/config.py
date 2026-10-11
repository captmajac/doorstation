"""Konfiguration des GPIO-Dienstes (/etc/doorstation/gpio.yaml)."""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal

from doorstation_common.config import ConfigError, MqttSettings, load_yaml

KINDS = ("button", "state")
TRIGGERS = ("press", "release")
ACTIVES = ("high", "low")
PULLS = ("off", "up", "down")


@dataclass(frozen=True)
class InputConfig:
    name: str
    pin: int
    kind: Literal["button", "state"]
    trigger: Literal["press", "release"] = "press"
    active: Literal["high", "low"] = "high"
    pull: Literal["off", "up", "down"] = "off"
    debounce_ms: int = 0
    min_interval_s: float = 0.0
    ring: bool = False
    states: tuple[str, str] | None = None
    report_release: bool = False


@dataclass(frozen=True)
class GpioConfig:
    mqtt: MqttSettings
    chip: str
    inputs: tuple[InputConfig, ...]


_INPUT_KEYS = {f.name for f in fields(InputConfig)} - {"name"}


def _parse_input(name: str, raw) -> InputConfig:
    def fail(msg: str) -> ConfigError:
        return ConfigError(f"Eingang '{name}': {msg}")

    if not isinstance(raw, dict):
        raise fail("muss ein Mapping sein")
    unknown = sorted(set(raw) - _INPUT_KEYS)
    if unknown:
        raise fail(f"unbekannte Schlüssel {', '.join(unknown)}")
    raw = dict(raw)
    if raw.get("pull") is False:  # YAML 1.1 liest "off" als false
        raw["pull"] = "off"
    for key in ("pin", "kind"):
        if key not in raw:
            raise fail(f"'{key}' fehlt")
    kind = raw["kind"]
    if kind not in KINDS:
        raise fail(f"kind muss {' oder '.join(KINDS)} sein, nicht '{kind}'")
    if not isinstance(raw["pin"], int) or isinstance(raw["pin"], bool) or raw["pin"] < 0:
        raise fail("pin muss eine BCM-Nummer sein")
    for key, allowed in (("trigger", TRIGGERS), ("active", ACTIVES), ("pull", PULLS)):
        if key in raw and raw[key] not in allowed:
            raise fail(f"{key} muss {', '.join(allowed)} sein, nicht '{raw[key]}'")
    debounce = raw.get("debounce_ms", 0)
    if not isinstance(debounce, int) or isinstance(debounce, bool) or debounce < 0:
        raise fail("debounce_ms muss eine ganze Zahl ≥ 0 sein")
    interval = raw.get("min_interval_s", 0)
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval < 0:
        raise fail("min_interval_s muss eine Zahl ≥ 0 sein")
    states = raw.get("states")
    if kind == "state":
        if (not isinstance(states, list) or len(states) != 2
                or not all(isinstance(s, str) and s for s in states) or states[0] == states[1]):
            raise fail("states muss zwei verschiedene Namen enthalten, z. B. [closed, open]")
        states = (states[0], states[1])
        for key in ("ring", "trigger", "report_release"):
            if key in raw:
                raise fail(f"'{key}' gibt es nur bei kind: button")
    else:
        if states is not None:
            raise fail("'states' gibt es nur bei kind: state")
        for key in ("ring", "report_release"):
            if key in raw and not isinstance(raw[key], bool):
                raise fail(f"{key} muss true oder false sein")
    return InputConfig(
        name=name,
        pin=raw["pin"],
        kind=kind,
        trigger=raw.get("trigger", "press"),
        active=raw.get("active", "high"),
        pull=raw.get("pull", "off"),
        debounce_ms=debounce,
        min_interval_s=float(interval),
        ring=raw.get("ring", False),
        states=states,
        report_release=raw.get("report_release", False),
    )


def load_config(path: Path) -> GpioConfig:
    data = load_yaml(path)
    unknown = sorted(set(data) - {"mqtt", "chip", "inputs"})
    if unknown:
        raise ConfigError(f"{path}: unbekannte Schlüssel {', '.join(unknown)}")
    raw_inputs = data.get("inputs")
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise ConfigError(f"{path}: 'inputs' fehlt oder ist leer")
    inputs = tuple(_parse_input(str(name), raw) for name, raw in raw_inputs.items())
    seen: dict[int, str] = {}
    for inp in inputs:
        if inp.pin in seen:
            raise ConfigError(f"Pin {inp.pin} doppelt belegt: '{seen[inp.pin]}' und '{inp.name}'")
        seen[inp.pin] = inp.name
    return GpioConfig(
        mqtt=MqttSettings.from_dict(data.get("mqtt")),
        chip=str(data.get("chip", "/dev/gpiochip0")),
        inputs=inputs,
    )
