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
