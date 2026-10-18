import json

from doorstation_common.config import MqttSettings
from doorstation_common.mqtt import ServiceMqtt
from doorstation_common.testing import FakeMqttClient
from doorstation_gpio.backend import FakeBackend
from doorstation_gpio.config import GpioConfig, InputConfig
from doorstation_gpio.service import GpioService

CFG = GpioConfig(MqttSettings(), "/dev/null", (
    InputConfig("bell", 9, "button", ring=True, min_interval_s=2),
    InputConfig("mail_flap", 19, "state", states=("closed", "open")),
))


def setup():
    c = FakeMqttClient()
    m = ServiceMqtt("gpio", MqttSettings(), client=c, state_settle_s=0)
    m.start()
    c.simulate_connect()
    b = FakeBackend({"bell": False, "mail_flap": True})
    s = GpioService(CFG, b, m)
    s.start()
    return c, b, s


def msgs(c, topic):
    return [(json.loads(p), r) for t, p, q, r in c.published if t == topic]


def test_start_publishes_initial_state_retained():
    c, b, s = setup()
    assert msgs(c, "doorstation/gpio/input/mail_flap")[-1][0]["state"] == "open"
    assert msgs(c, "doorstation/gpio/input/mail_flap")[-1][1] is True


def test_bell_press_emits_input_and_ring():
    c, b, s = setup()
    b.set_level("bell", True)
    s.step(0)
    payload, retained = msgs(c, "doorstation/gpio/input/bell")[-1]
    assert payload["event"] == "pressed" and retained is False
    assert msgs(c, "doorstation/event/ring")[-1][0]["source"] == "bell"


def test_state_change_published_retained():
    c, b, s = setup()
    b.set_level("mail_flap", False)
    s.step(0)
    payload, retained = msgs(c, "doorstation/gpio/input/mail_flap")[-1]
    assert payload["state"] == "closed" and retained is True


def test_reconnect_republishes_states():
    c, b, s = setup()
    n = len(msgs(c, "doorstation/gpio/input/mail_flap"))
    c.simulate_connect()
    s.step(0)
    assert len(msgs(c, "doorstation/gpio/input/mail_flap")) == n + 1
    assert ("doorstation/gpio/status", "online", 1, True) in c.published


def test_bell_press_while_disconnected_is_dropped_not_queued():
    c, b, s = setup()
    c.connected = False
    b.set_level("bell", True)
    s.step(0)
    c.connected = True
    c.simulate_connect()
    s.step(0)
    assert msgs(c, "doorstation/gpio/input/bell") == []
    assert msgs(c, "doorstation/event/ring") == []


def test_republish_after_reconnect_runs_in_main_loop_not_network_thread():
    c, b, s = setup()
    n = len(msgs(c, "doorstation/gpio/input/mail_flap"))
    c.simulate_connect()
    assert len(msgs(c, "doorstation/gpio/input/mail_flap")) == n
    s.step(0)
    assert len(msgs(c, "doorstation/gpio/input/mail_flap")) == n + 1


def test_bell_release_published_but_no_ring():
    cfg = GpioConfig(MqttSettings(), "/dev/null", (InputConfig("bell", 9, "button", ring=True, report_release=True),))
    c = FakeMqttClient()
    m = ServiceMqtt("gpio", MqttSettings(), client=c, state_settle_s=0)
    m.start(); c.simulate_connect()
    b = FakeBackend({"bell": False})
    s = GpioService(cfg, b, m)
    s.start()
    b.set_level("bell", True); s.step(0)
    b.set_level("bell", False); s.step(0)
    events = [p["event"] for p, r in msgs(c, "doorstation/gpio/input/bell")]
    assert events == ["pressed", "released"]
    assert len(msgs(c, "doorstation/event/ring")) == 1


def test_step_sends_heartbeat():
    t = [1000.0]
    c = FakeMqttClient()
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=300), client=c, clock=lambda: t[0], state_settle_s=0)
    m.start(); c.simulate_connect()
    s = GpioService(CFG, FakeBackend({"bell": False, "mail_flap": True}), m)
    s.start(); c.published.clear()
    t[0] += 300
    s.step(0)
    assert ("doorstation/gpio/status", "online", 1, True) in c.published


def test_restart_with_unchanged_state_sends_nothing():
    # The broker still holds the state: sending it again with a new ts would trigger the
    # home automation's "on change" events although nothing happened.
    t = [1000.0]
    c = FakeMqttClient()
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=0), client=c, clock=lambda: t[0])
    m.start()
    s = GpioService(CFG, FakeBackend({"bell": False, "mail_flap": True}), m)
    s.start()
    c.simulate_connect()
    c.simulate_message("doorstation/gpio/input/mail_flap",
                       b'{"ts": "2026-01-01T00:00:00.000+01:00", "state": "open"}', retain=True)
    t[0] += 1
    s.step(0)
    assert msgs(c, "doorstation/gpio/input/mail_flap") == []
