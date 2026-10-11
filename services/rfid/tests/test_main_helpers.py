import logging
import os

from doorstation_rfid.__main__ import QUIET_LOGGERS, quiet_loggers, secure_state_files


def test_secure_state_files(tmp_path):
    d = tmp_path / "rfid"
    d.mkdir(mode=0o755)
    f = d / "homekey.json"
    f.write_text("{}")
    os.chmod(f, 0o664)
    secure_state_files(d)
    assert oct(d.stat().st_mode & 0o777) == "0o700"
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_quiet_loggers():
    quiet_loggers()
    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_root_logger_info_is_not_written():
    import io
    from doorstation_rfid.__main__ import configure_logging
    buf = io.StringIO()
    configure_logging(buf)
    logging.getLogger().info("shared_key=0011 kenc=22")       # so loggt kormax
    logging.getLogger("doorstation_rfid.loop").info("Karte gemeldet")
    out = buf.getvalue()
    assert "kenc" not in out and "shared_key" not in out
    assert "Karte gemeldet" in out


def _watch(tmp_path, paired):
    from doorstation_common.config import MqttSettings
    from doorstation_common.mqtt import ServiceMqtt
    from doorstation_common.testing import FakeMqttClient
    from doorstation_rfid.__main__ import PairingWatch
    c = FakeMqttClient()
    m = ServiceMqtt("rfid", MqttSettings(), client=c)
    m.start()
    c.simulate_connect()
    return c, PairingWatch(m, paired, lambda: "123-45-678", tmp_path)


def _pairing(c):
    import json
    return [json.loads(p)["paired"] for t, p, *_ in c.published if t == "doorstation/rfid/pairing"]


def test_pairing_watch_survives_errors(tmp_path):
    # Eine Ausnahme darf den Überwachungs-Thread nicht beenden (sonst keine Paarungsmeldung mehr).
    def boom():
        raise RuntimeError("Repository kaputt")
    c, w = _watch(tmp_path, boom)
    w.check()
    w.check()


def test_pairing_reported_on_change_and_after_reconnect(tmp_path):
    state = {"paired": True}
    c, w = _watch(tmp_path, lambda: state["paired"])
    w.check()
    w.check()
    assert _pairing(c) == [True]
    w.republish()          # z. B. nach Wiederverbindung zum Broker
    w.check()
    assert _pairing(c) == [True, True]
    state["paired"] = False
    w.check()
    assert _pairing(c) == [True, True, False]
