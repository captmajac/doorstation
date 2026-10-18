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
    logging.getLogger().info("shared_key=0011 kenc=22")       # this is how kormax logs
    logging.getLogger("doorstation_rfid.loop").info("card reported")
    out = buf.getvalue()
    assert "kenc" not in out and "shared_key" not in out
    assert "card reported" in out


def _watch(tmp_path, paired):
    from doorstation_common.config import MqttSettings
    from doorstation_common.mqtt import ServiceMqtt
    from doorstation_common.testing import FakeMqttClient
    from doorstation_rfid.__main__ import PairingWatch
    c = FakeMqttClient()
    m = ServiceMqtt("rfid", MqttSettings(), client=c, state_settle_s=0)
    m.start()
    c.simulate_connect()
    return c, PairingWatch(m, paired, lambda: "123-45-678", tmp_path)


def _pairing(c):
    import json
    return [json.loads(p)["paired"] for t, p, *_ in c.published if t == "doorstation/rfid/pairing"]


def test_pairing_watch_survives_errors(tmp_path):
    # An exception must not end the watch thread (otherwise no more pairing reports).
    def boom():
        raise RuntimeError("repository broken")
    c, w = _watch(tmp_path, boom)
    w.check()
    w.check()


def test_pairing_reported_on_change_only(tmp_path):
    state = {"paired": True}
    c, w = _watch(tmp_path, lambda: state["paired"])
    w.check()
    w.check()
    assert _pairing(c) == [True]
    state["paired"] = False
    w.check()
    assert _pairing(c) == [True, False]


def test_pairing_unchanged_against_broker_not_sent_after_restart(tmp_path):
    from doorstation_common.config import MqttSettings
    from doorstation_common.mqtt import ServiceMqtt
    from doorstation_common.testing import FakeMqttClient
    from doorstation_rfid.__main__ import PairingWatch
    t = [1000.0]
    c = FakeMqttClient()
    m = ServiceMqtt("rfid", MqttSettings(heartbeat_s=0), client=c, clock=lambda: t[0])
    m.start()
    w = PairingWatch(m, lambda: True, lambda: "123-45-678", tmp_path)
    w.check()
    c.simulate_connect()
    c.simulate_message("doorstation/rfid/pairing", b'{"ts": "2026-01-01T00:00:00.000+01:00", "paired": true}', retain=True)
    t[0] += 1
    w.check()
    assert _pairing(c) == []
