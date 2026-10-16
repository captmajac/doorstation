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


HELPERS = {"doorstation-firewall.service", "doorstation-baresip-restart.path", "doorstation-baresip-restart.service"}


def test_all_service_units_covered():
    found = {p.name for p in UNITS.iterdir()} - HELPERS
    assert found == set(SERVICES)


def test_baresip_waits_for_time_sync_before_audio_init():
    # After a clock jump baresip loses MQTT for good; start it only after the clock is set.
    pre = (UNITS / "doorstation-baresip.service.template").read_text(encoding="utf-8")
    lines = [line for line in pre.splitlines() if line.startswith("ExecStartPre=")]
    assert "doorstation-wait-timesync" in lines[0]
    assert "doorstation-audio-init" in lines[1]


def test_silent_baresip_restart_is_wired():
    path = _unit("doorstation-baresip-restart.path")
    assert path["Path"].get("PathExists") == "/var/lib/doorstation/sip/restart-baresip"
    assert path["Path"].get("Unit") == "doorstation-baresip-restart.service"
    svc = (UNITS / "doorstation-baresip-restart.service").read_text(encoding="utf-8")
    assert "ExecStart=/bin/rm -f /var/lib/doorstation/sip/restart-baresip" in svc
    assert "ExecStart=/bin/systemctl restart --no-block doorstation-baresip.service" in svc


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


def test_baresip_start_timeout_covers_all_waits():
    # systemd's default start timeout (90 s) covers all ExecStartPre steps. Waiting for the time
    # sync (no internet) plus audio-init (card and PipeWire, 15 s each) must fit with margin -
    # otherwise baresip is killed during start and never comes up.
    import re
    text = (UNITS / "doorstation-baresip.service.template").read_text(encoding="utf-8")
    wait = re.search(r"doorstation-wait-timesync --timeout (\d+)", text)
    assert wait, "wait-timesync needs an explicit --timeout"
    start_timeout = int(_unit("doorstation-baresip.service.template")["Service"].get("TimeoutStartSec", "90"))
    assert int(wait.group(1)) + 2 * 15 + 30 <= start_timeout
