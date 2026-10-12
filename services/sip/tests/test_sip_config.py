from pathlib import Path

import pytest

from doorstation_common.config import ConfigError
from doorstation_sip.config import load_config, valid_target

ROOT = Path(__file__).parents[3]


def test_example_loads():
    cfg = load_config(ROOT / "config-examples/sip.yaml")
    assert (cfg.fritzbox, cfg.username, cfg.default_target, cfg.ring_timeout_s) == ("192.168.178.1", "Tuerstation", "**701", 30)
    assert cfg.command_max_age_s == 30


@pytest.mark.parametrize("body,needle", [
    ("fritzbox: 1.2.3.4\nusername: T\u00fcrstation\n", "username"),
    ("fritzbox: 1.2.3.4\nusername: A\ndefault_target: '12a'\n", "default_target"),
    ("fritzbox: 1.2.3.4\nusername: A\nring_timeout_s: 0\n", "ring_timeout_s"),
    ("fritzbox: 1.2.3.4\nusername: A\nfoo: 1\n", "foo"),
    ("username: A\n", "fritzbox"),
])
def test_invalid(tmp_path, body, needle):
    p = tmp_path / "sip.yaml"
    p.write_text(body)
    with pytest.raises(ConfigError, match=needle):
        load_config(p)


def test_default_target_null_means_mute(tmp_path):
    p = tmp_path / "sip.yaml"
    p.write_text("fritzbox: 1.2.3.4\nusername: A\ndefault_target: null\n")
    assert load_config(p).default_target is None


def test_valid_target():
    assert valid_target("**701") and valid_target("0301234#")
    assert not valid_target("12a") and not valid_target("") and not valid_target(None) and not valid_target("1" * 21)
