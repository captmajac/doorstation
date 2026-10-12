from pathlib import Path

import pytest

from doorstation_common.config import ConfigError
from doorstation_rfid.config import load_config

ROOT = Path(__file__).parents[3]


def test_example_loads():
    cfg = load_config(ROOT / "config-examples/rfid.yaml")
    assert (cfg.nfc_path, cfg.express, cfg.repeat_block_s, cfg.feedback_sound, cfg.hap_port) == (
        "tty:AMA0:pn532", True, 3, "beep", 51926)


@pytest.mark.parametrize("body,needle", [
    ("finish: pink\n", "finish"),
    ("flow: slow\n", "flow"),
    ("repeat_block_s: 0\n", "repeat_block_s"),
    ("colour: red\n", "colour"),
])
def test_invalid(tmp_path, body, needle):
    p = tmp_path / "rfid.yaml"
    p.write_text(body)
    with pytest.raises(ConfigError, match=needle):
        load_config(p)


def test_empty_feedback_sound_disables(tmp_path):
    p = tmp_path / "rfid.yaml"
    p.write_text("feedback_sound:\n")
    assert load_config(p).feedback_sound == ""


def test_default_accessory_name(tmp_path):
    p = tmp_path / "rfid.yaml"
    p.write_text("mqtt: {}\n")
    assert load_config(p).accessory_name == "Mailbox NFC Reader"
