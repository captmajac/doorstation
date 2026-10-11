import textwrap
from pathlib import Path

import pytest

from doorstation_common.config import ConfigError
from doorstation_gpio.config import load_config


def write(tmp_path, body):
    p = tmp_path / "gpio.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_example_config_loads():
    cfg = load_config(Path(__file__).parents[3] / "config-examples/gpio.yaml")
    bell = next(i for i in cfg.inputs if i.name == "bell")
    assert (bell.pin, bell.kind, bell.trigger, bell.ring, bell.min_interval_s) == (9, "button", "press", True, 2)
    assert next(i for i in cfg.inputs if i.name == "mail_flap").states == ("closed", "open")


@pytest.mark.parametrize("body,needle", [
    ("inputs:\n  a: {pin: 9, kind: button, colour: red}\n", "a"),
    ("inputs:\n  a: {pin: 9, kind: button}\n  b: {pin: 9, kind: button}\n", "9"),
    ("inputs:\n  m: {pin: 7, kind: state}\n", "m"),
    ("inputs:\n  m: {pin: 7, kind: lever}\n", "m"),
    ("inputs:\n  m: {pin: 7, kind: button, active: mid}\n", "m"),
])
def test_invalid_configs_rejected(tmp_path, body, needle):
    with pytest.raises(ConfigError, match=needle):
        load_config(write(tmp_path, body))


def test_report_release_only_for_buttons(tmp_path):
    cfg = load_config(write(tmp_path, "inputs:\n  b: {pin: 9, kind: button, report_release: true}\n"))
    assert cfg.inputs[0].report_release is True
    with pytest.raises(ConfigError, match="report_release"):
        load_config(write(tmp_path, "inputs:\n  m: {pin: 7, kind: state, states: [a, b], report_release: true}\n"))
