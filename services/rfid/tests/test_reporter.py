import json

from doorstation_common.config import MqttSettings
from doorstation_common.mqtt import ServiceMqtt
from doorstation_common.testing import FakeMqttClient
from doorstation_rfid.config import RfidConfig
from doorstation_rfid.reporter import Reporter


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(**kw):
    c = FakeMqttClient()
    m = ServiceMqtt("rfid", MqttSettings(), client=c, state_settle_s=0)
    m.start()
    c.simulate_connect()
    clock = Clock()
    return c, Reporter(m, RfidConfig(MqttSettings(), **kw), clock), clock


def reads(c):
    return [(json.loads(p), q, r) for t, p, q, r in c.published if t == "doorstation/rfid/read"]


def sounds(c):
    return [json.loads(p) for t, p, *_ in c.published if t == "doorstation/sound/cmd"]


def test_report_publishes_read_and_beep():
    c, r, clock = make()
    assert r.report("card", "B3C06FA5") is True
    payload, qos, retain = reads(c)[-1]
    assert (payload["type"], payload["id"], qos, retain) == ("card", "B3C06FA5", 0, False)
    assert sounds(c)[-1]["action"] == "play" and sounds(c)[-1]["name"] == "beep"


def test_repeat_block_same_id():
    c, r, clock = make()
    r.report("card", "B3C06FA5")
    clock.t += 1
    assert r.report("card", "B3C06FA5") is False


def test_held_in_field_extends_block():
    c, r, clock = make()
    results = []
    for _ in range(10):
        results.append(r.report("homekey", "6850185941E3332E"))
        clock.t += 1
    assert results == [True] + [False] * 9


def test_other_id_not_blocked():
    c, r, clock = make()
    r.report("card", "B3C06FA5")
    assert r.report("card", "5F69D395551BAF") is True


def test_after_block_reported_again():
    c, r, clock = make()
    r.report("card", "B3C06FA5")
    clock.t += 3
    assert r.report("card", "B3C06FA5") is True


def test_no_sound_when_disabled():
    c, r, clock = make(feedback_sound="")
    r.report("card", "B3C06FA5")
    assert sounds(c) == []


def test_not_connected_drops():
    c, r, clock = make()
    c.connected = False
    n = len(c.published)
    assert r.report("card", "B3C06FA5") is False
    assert len(c.published) == n
