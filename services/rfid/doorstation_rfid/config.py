"""Konfiguration des RFID-Dienstes (/etc/doorstation/rfid.yaml)."""

from dataclasses import dataclass
from pathlib import Path

from doorstation_common.config import ConfigError, MqttSettings, load_yaml

FINISHES = ("silver", "black", "gold", "tan")
FLOWS = ("fast", "standard", "attestation")


@dataclass(frozen=True)
class RfidConfig:
    mqtt: MqttSettings
    nfc_path: str = "tty:AMA0:pn532"
    express: bool = True
    finish: str = "silver"
    flow: str = "fast"
    repeat_block_s: float = 3
    feedback_sound: str = "beep"
    state_dir: Path = Path("/var/lib/doorstation/rfid")
    hap_port: int = 51926
    accessory_name: str = "NFC-Leser Briefkasten"


_KEYS = {"mqtt", "nfc_path", "express", "finish", "flow", "repeat_block_s", "feedback_sound",
         "state_dir", "hap_port", "accessory_name"}


def load_config(path: Path) -> RfidConfig:
    data = load_yaml(path)
    unknown = sorted(set(data) - _KEYS)
    if unknown:
        raise ConfigError(f"{path}: unbekannte Schlüssel {', '.join(unknown)}")
    kw: dict = {}
    for key in ("nfc_path", "accessory_name"):
        if key in data:
            if not isinstance(data[key], str) or not data[key]:
                raise ConfigError(f"{path}: {key} muss ein Text sein")
            kw[key] = data[key]
    if "express" in data:
        if not isinstance(data["express"], bool):
            raise ConfigError(f"{path}: express muss true oder false sein")
        kw["express"] = data["express"]
    if "finish" in data:
        if data["finish"] not in FINISHES:
            raise ConfigError(f"{path}: finish muss {', '.join(FINISHES)} sein")
        kw["finish"] = data["finish"]
    if "flow" in data:
        if data["flow"] not in FLOWS:
            raise ConfigError(f"{path}: flow muss {', '.join(FLOWS)} sein")
        kw["flow"] = data["flow"]
    if "repeat_block_s" in data:
        v = data["repeat_block_s"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ConfigError(f"{path}: repeat_block_s muss eine Zahl > 0 sein")
        kw["repeat_block_s"] = float(v)
    if "feedback_sound" in data:
        v = data["feedback_sound"]
        if v is not None and not isinstance(v, str):
            raise ConfigError(f"{path}: feedback_sound muss ein Name oder leer sein")
        kw["feedback_sound"] = v or ""
    if "hap_port" in data:
        v = data["hap_port"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 65535:
            raise ConfigError(f"{path}: hap_port muss ein Port sein")
        kw["hap_port"] = v
    if "state_dir" in data:
        kw["state_dir"] = Path(str(data["state_dir"]))
    return RfidConfig(mqtt=MqttSettings.from_dict(data.get("mqtt")), **kw)
