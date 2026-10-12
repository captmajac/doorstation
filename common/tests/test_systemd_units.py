"""Basic rules for the systemd units in deploy/systemd/."""

import configparser
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
SERVICES = ["doorstation-gpio.service", "doorstation-sip.service", "doorstation-rfid.service",
            "doorstation-sound.service.template", "doorstation-baresip.service.template"]
PYTHON = ["doorstation-gpio.service", "doorstation-sip.service", "doorstation-rfid.service",
          "doorstation-sound.service.template"]


def _unit(name: str) -> configparser.ConfigParser:
    p = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    p.optionxform = str
    p.read_string((UNITS / name).read_text(encoding="utf-8"))
    return p


def test_all_service_units_covered():
    found = {p.name for p in UNITS.iterdir()} - {"doorstation-firewall.service"}
    assert found == set(SERVICES)


@pytest.mark.parametrize("name", SERVICES)
def test_never_gives_up(name):
    # Without StartLimitIntervalSec=0 systemd gives up after 5 starts in 10 s - then the bell stays silent.
    u = _unit(name)
    assert u["Unit"].get("StartLimitIntervalSec") == "0"
    assert u["Service"].get("Restart") == "always"


@pytest.mark.parametrize("name", PYTHON)
def test_config_error_does_not_loop(name):
    # Exit 2 = configuration error: do not restart every 2 s, stay stopped (status offline).
    assert _unit(name)["Service"].get("RestartPreventExitStatus") == "2"


@pytest.mark.parametrize("name", SERVICES)
def test_basic_hardening(name):
    s = _unit(name)["Service"]
    assert s.get("NoNewPrivileges") == "yes"
    assert s.get("ProtectSystem") == "strict"
    assert s.get("PrivateTmp") == "yes"
    assert s.get("UMask") == "0077"
    assert s.get("CapabilityBoundingSet") == ""
    assert s.get("DevicePolicy") == "closed"
    assert "AF_UNIX" in s.get("RestrictAddressFamilies", "")
