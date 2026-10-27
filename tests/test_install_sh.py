"""Tests for install.sh: single functions are sourced into bash and called without root."""

import os
import subprocess
from pathlib import Path

INSTALL = Path(__file__).resolve().parents[1] / "install.sh"
TEMPLATE_DIR = Path(__file__).resolve().parents[1]


def bash(script: str, tmp_path: Path, **env) -> subprocess.CompletedProcess:
    full_env = {**os.environ, "DOORSTATION_ETC": str(tmp_path / "etc"), "DOORSTATION_VAR": str(tmp_path / "var"),
                **env}
    return subprocess.run(
        ["bash", "-c", f'source "{INSTALL}"; set +e; SRC="{TEMPLATE_DIR}"; RUN_TMP="{tmp_path}"\n{script}'],
        capture_output=True, text=True, env=full_env,
    )


# --- config.txt ---------------------------------------------------------------

def test_config_line_appended_under_existing_all(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text("arm_64bit=1\n[cm4]\notg_mode=1\n[all]\n")
    r = bash(f'config_txt_add "{f}" enable_uart=1; echo "rc=$?"', tmp_path)
    assert "rc=0" in r.stdout
    assert f.read_text() == "arm_64bit=1\n[cm4]\notg_mode=1\n[all]\nenable_uart=1\n"


def test_config_line_gets_all_section_when_file_ends_in_model_section(tmp_path):
    # Otherwise the line would only apply to [pi5] - the UART would stay off on Pi 3/4.
    f = tmp_path / "config.txt"
    f.write_text("arm_64bit=1\n[pi5]\ndtoverlay=nospi10\n")
    bash(f'config_txt_add "{f}" enable_uart=1', tmp_path)
    assert f.read_text() == "arm_64bit=1\n[pi5]\ndtoverlay=nospi10\n[all]\nenable_uart=1\n"


def test_config_line_only_in_model_section_counts_as_missing(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text("[cm4]\nenable_uart=1\n")
    bash(f'config_txt_add "{f}" enable_uart=1', tmp_path)
    assert f.read_text() == "[cm4]\nenable_uart=1\n[all]\nenable_uart=1\n"


def test_config_line_already_present_unchanged(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text("arm_64bit=1\n[all]\nenable_uart=1\n")
    r = bash(f'config_txt_add "{f}" enable_uart=1; echo "rc=$?"', tmp_path)
    assert "rc=1" in r.stdout
    assert f.read_text() == "arm_64bit=1\n[all]\nenable_uart=1\n"


def test_config_line_without_any_section_is_global(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text("enable_uart=1\n")
    r = bash(f'config_txt_add "{f}" enable_uart=1; echo "rc=$?"', tmp_path)
    assert "rc=1" in r.stdout


# --- Bridge ---------------------------------------------------------------------

def _bridge(tmp_path, yaml: str, password: bytes):
    (tmp_path / "bridge.yaml").write_text(yaml)
    (tmp_path / "pw").write_bytes(password)
    out = tmp_path / "bridge.conf"
    r = bash(f'render_bridge "{tmp_path}/bridge.yaml" "{tmp_path}/pw" "{out}"; echo "rc=$?"', tmp_path)
    return r, out


def test_bridge_password_with_special_chars_and_crlf(tmp_path):
    r, out = _bridge(tmp_path, "host: 192.168.178.10\nport: 1026\nusername: doorstation\n", b"a&b|c\\d\r\n")
    assert "rc=0" in r.stdout
    assert "remote_password a&b|c\\d\n" in out.read_text()


def test_bridge_rejects_host_with_special_chars(tmp_path):
    r, out = _bridge(tmp_path, "host: evil|x&y\nport: 1026\nusername: doorstation\n", b"pw\n")
    assert "rc=0" not in r.stdout
    assert "host" in r.stderr


def test_bridge_rejects_prefix_with_wildcard(tmp_path):
    r, out = _bridge(tmp_path, "host: h\nport: 1026\nusername: u\nprefix: door/#\n", b"pw\n")
    assert "rc=0" not in r.stdout
    assert "prefix" in r.stderr


def test_broken_bridge_is_rolled_back_and_mosquitto_keeps_running(tmp_path):
    # If Mosquitto does not start with the new bridge, nothing would work - not even the bell.
    dst = tmp_path / "bridge.conf"
    dst.write_text("OLD\n")
    new = tmp_path / "new.conf"
    new.write_text("BROKEN\n")
    r = bash(f'''
chown() {{ :; }}
systemctl() {{ if [ "$1" = restart ] && grep -q BROKEN "{dst}" 2>/dev/null; then return 1; fi; return 0; }}
apply_mosquitto_conf "{new}" "{dst}"; echo "rc=$?"''', tmp_path)
    assert "rc=0" in r.stdout
    assert dst.read_text() == "OLD\n"
    assert "WARNING" in r.stderr


def test_broken_new_bridge_without_previous_is_removed(tmp_path):
    dst = tmp_path / "bridge.conf"
    new = tmp_path / "new.conf"
    new.write_text("BROKEN\n")
    r = bash(f'''
chown() {{ :; }}
systemctl() {{ if [ "$1" = restart ] && grep -q BROKEN "{dst}" 2>/dev/null; then return 1; fi; return 0; }}
apply_mosquitto_conf "{new}" "{dst}"; echo "rc=$?"''', tmp_path)
    assert "rc=0" in r.stdout
    assert not dst.exists()


# --- SIP without password -------------------------------------------------------

def test_sip_without_password_is_skipped_not_fatal(tmp_path):
    # Fresh installation: the password comes later - sound and rfid must be installed anyway.
    (tmp_path / "etc" / "secrets").mkdir(parents=True)
    r = bash('''
install_python_package() { echo CALLED-PIP; return 1; }
install_sip; echo "rc=$?"''', tmp_path)
    assert "rc=0" in r.stdout
    assert "CALLED-PIP" not in r.stdout
    assert "WARNING" in r.stderr and "sip_password" in r.stderr
    assert "docs/installation.md" in r.stderr


def test_sip_password_with_account_separators_is_rejected(tmp_path):
    # ";" or ">" break the baresip accounts line - registration would fail silently.
    (tmp_path / "etc" / "secrets").mkdir(parents=True)
    (tmp_path / "etc" / "secrets" / "sip_password").write_text("geheim;answermode=manual\n")
    r = bash('''
install_python_package() { echo CALLED-PIP; return 1; }
install_sip; echo "rc=$?"''', tmp_path)
    assert "rc=0" in r.stdout
    assert "CALLED-PIP" not in r.stdout
    assert "WARNING" in r.stderr and "character" in r.stderr


# --- time server ----------------------------------------------------------------

def _timesync(tmp_path, server):
    return bash(f'''
systemctl() {{ echo "systemctl $*"; }}
install_timesync "{server}"; echo "rc=$?"''', tmp_path, DOORSTATION_TIMESYNC_DIR=str(tmp_path / "timesyncd.conf.d"))


def test_timesync_uses_fritzbox_with_internet_fallback(tmp_path):
    # No real-time clock: after a power failure the FritzBox answers at once, the internet pool may take minutes.
    r = _timesync(tmp_path, "192.168.178.1")
    conf = (tmp_path / "timesyncd.conf.d" / "doorstation.conf").read_text()
    assert "rc=0" in r.stdout
    assert "[Time]\nNTP=192.168.178.1\n" in conf
    assert "FallbackNTP=0.debian.pool.ntp.org" in conf
    assert "systemctl restart systemd-timesyncd" in r.stdout


def test_timesync_unchanged_does_not_restart(tmp_path):
    _timesync(tmp_path, "192.168.178.1")
    r = _timesync(tmp_path, "192.168.178.1")
    assert "rc=0" in r.stdout and "systemctl restart" not in r.stdout


def test_timesync_rejects_invalid_server(tmp_path):
    r = _timesync(tmp_path, "evil\\nNTP=attacker")
    assert "rc=0" in r.stdout and "WARNING" in r.stderr
    assert not (tmp_path / "timesyncd.conf.d" / "doorstation.conf").exists()


def test_timesync_disabled_removes_our_config(tmp_path):
    _timesync(tmp_path, "192.168.178.1")
    r = _timesync(tmp_path, "")
    assert "rc=0" in r.stdout and "systemctl restart systemd-timesyncd" in r.stdout
    assert not (tmp_path / "timesyncd.conf.d" / "doorstation.conf").exists()


def _time_server(tmp_path, sip_yaml: str):
    (tmp_path / "sip.yaml").write_text(sip_yaml)
    r = bash(f'echo "server=[$(time_server_from_config "{tmp_path}/sip.yaml" 192.168.178.1)]"', tmp_path)
    return r.stdout.strip()


def test_time_server_defaults_to_fritzbox(tmp_path):
    assert _time_server(tmp_path, "fritzbox: 192.168.178.1\n") == "server=[192.168.178.1]"


def test_time_server_can_be_overridden(tmp_path):
    assert _time_server(tmp_path, "fritzbox: 192.168.178.1\ntime_server: ntp.example.org   # own\n") \
        == "server=[ntp.example.org]"


def test_time_server_null_keeps_system_default(tmp_path):
    assert _time_server(tmp_path, "fritzbox: 192.168.178.1\ntime_server: null\n") == "server=[]"


# --- PipeWire / WirePlumber configuration ----------------------------------------

def test_audio_conf_installed_once(tmp_path):
    src = tmp_path / "51-test.conf"
    src.write_text("x = 1\n")
    dest = tmp_path / "var" / ".config" / "wireplumber" / "wireplumber.conf.d"
    script = f'SVC_USER="$(id -un)"; install_audio_conf "{src}" "{dest}"; echo "rc=$?"'
    assert "rc=0" in bash(script, tmp_path).stdout
    assert (dest / "51-test.conf").read_text() == "x = 1\n"
    assert "rc=1" in bash(script, tmp_path).stdout   # unchanged: no restart needed


PIPEWIRE_UNITS = ("pipewire.service", "pipewire.socket", "pipewire-pulse.service", "pipewire-pulse.socket",
                  "wireplumber.service", "filter-chain.service")


def _pipewire_only(tmp_path):
    units = tmp_path / "user-units"
    r = bash('SVC_USER=doorstation; install_pipewire_service_user_only; echo "rc=$?"', tmp_path,
             DOORSTATION_USER_UNIT_DIR=str(units))
    return r, units


def test_pipewire_runs_only_for_the_service_user(tmp_path):
    # A login session (e.g. SSH) started its own PipeWire, took over the sound card and set
    # the speaker to WirePlumber's default of 40 %.
    r, units = _pipewire_only(tmp_path)
    assert "rc=0" in r.stdout
    for unit in PIPEWIRE_UNITS:
        conf = (units / f"{unit}.d" / "doorstation.conf").read_text()
        assert "[Unit]\nConditionUser=doorstation\n" in conf, unit


def test_pipewire_service_user_only_unchanged_second_time(tmp_path):
    _pipewire_only(tmp_path)
    r, _ = _pipewire_only(tmp_path)
    assert "rc=1" in r.stdout


def test_wireplumber_keeps_restoring_volumes(tmp_path):
    # "device.restore-routes = false" made WirePlumber set its defaults (40 % speaker) on every
    # restart - restoring keeps the levels doorstation-audio-init set last.
    assert not (TEMPLATE_DIR / "deploy" / "wireplumber" / "51-doorstation-volumes.conf").exists()
    old = tmp_path / "var" / ".config" / "wireplumber" / "wireplumber.conf.d" / "51-doorstation-volumes.conf"
    old.parent.mkdir(parents=True)
    old.write_text("wireplumber.settings = { device.restore-routes = false }\n")
    script = f'remove_audio_conf "{old}"; echo "rc=$?"; remove_audio_conf "{old}"; echo "rc=$?"'
    assert bash(script, tmp_path).stdout.split() == ["rc=0", "rc=1"]
    assert not old.exists()


def test_alsa_headroom_against_crackling():
    # Raspberry Pi 3: USB and Ethernet share one bus, small transfers arrive late now and
    # then - the speaker crackles. More buffer between PipeWire and the USB card.
    conf = (TEMPLATE_DIR / "deploy" / "wireplumber" / "50-doorstation-alsa.conf").read_text()
    assert "api.alsa.headroom = 1024" in conf
    assert 'deploy/wireplumber/50-doorstation-alsa.conf' in INSTALL.read_text()
