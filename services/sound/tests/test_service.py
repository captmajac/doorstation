import json
from pathlib import Path

from doorstation_common.config import MqttSettings
from doorstation_common.mqtt import ServiceMqtt
from doorstation_common.testing import FakeMqttClient
from doorstation_sound.config import SoundConfig, SoundEntry
from doorstation_sound.player import FakePlayer
from doorstation_sound.queue import PlayQueue
from doorstation_sound.service import SoundService


def setup(tmp_path):
    (tmp_path / "beep.wav").write_bytes(b"RIFF")
    (tmp_path / "post.wav").write_bytes(b"RIFF")
    cfg = SoundConfig(MqttSettings(), default_volume=0.8, sounds={
        "beep": SoundEntry("beep", tmp_path / "beep.wav", 0.6),
        "post": SoundEntry("post", tmp_path / "post.wav", None),
        "fehlt": SoundEntry("fehlt", tmp_path / "fehlt.wav", None),
    })
    c = FakeMqttClient()
    m = ServiceMqtt("sound", MqttSettings(), client=c)
    m.start()
    c.simulate_connect()
    p = FakePlayer()
    s = SoundService(cfg, m, PlayQueue(p, 3, 120))
    s.start()
    return c, s, p


def cmd(c, s, **kw):
    c.simulate_message("doorstation/sound/cmd", json.dumps(kw).encode())
    s.step(0)


def last(c, topic):
    vals = [json.loads(p) for t, p, *_ in c.published if t == topic]
    return vals[-1] if vals else None


def test_start_publishes_available_and_idle(tmp_path):
    c, s, p = setup(tmp_path)
    assert last(c, "doorstation/sound/available")["names"] == ["beep", "post"]
    assert last(c, "doorstation/sound/state")["state"] == "idle"


def test_play_known_name(tmp_path):
    c, s, p = setup(tmp_path)
    cmd(c, s, action="play", name="beep")
    assert last(c, "doorstation/sound/state") | {"ts": 0} == {"ts": 0, "state": "playing", "name": "beep"}


def test_play_unknown_name_error(tmp_path):
    c, s, p = setup(tmp_path)
    cmd(c, s, action="play", name="fehlt")
    assert last(c, "doorstation/sound/error") and p.started == []


def test_volume_precedence(tmp_path):
    c, s, p = setup(tmp_path)
    cmd(c, s, action="play", name="beep", volume=0.3)
    p.finish(); s.step(0)
    cmd(c, s, action="play", name="beep")
    p.finish(); s.step(0)
    cmd(c, s, action="play", name="post")
    assert p.volumes == [0.3, 0.6, 0.8]


def test_invalid_volume_error(tmp_path):
    c, s, p = setup(tmp_path)
    c.published.clear()  # Startmeldung "Tondatei fehlt" nicht mitzählen
    cmd(c, s, action="play", name="beep", volume="laut")
    cmd(c, s, action="play", name="beep", volume=1.5)
    errors = [t for t, *_ in c.published if t == "doorstation/sound/error"]
    assert len(errors) == 2 and p.started == []


def test_stop_command(tmp_path):
    c, s, p = setup(tmp_path)
    cmd(c, s, action="play", name="post")
    cmd(c, s, action="stop")
    assert last(c, "doorstation/sound/state")["state"] == "idle"


def test_unknown_action_error(tmp_path):
    c, s, p = setup(tmp_path)
    cmd(c, s, action="lauter")
    assert last(c, "doorstation/sound/error")


def statuses(c):
    return [p for t, p, *_ in c.published if t == "doorstation/sound/status"]


def test_three_failures_degrade_then_success_online(tmp_path):
    c, s, p = setup(tmp_path)
    for _ in range(3):
        cmd(c, s, action="play", name="beep")
        p.finish(ok=False)
        s.step(0)
    assert statuses(c)[-1] == "degraded"
    cmd(c, s, action="play", name="beep")
    p.finish(ok=True)
    s.step(0)
    assert statuses(c)[-1] == "online"


def test_step_sends_heartbeat(tmp_path):
    t = [1000.0]
    c = FakeMqttClient()
    m = ServiceMqtt("sound", MqttSettings(heartbeat_s=300), client=c, clock=lambda: t[0])
    m.start(); c.simulate_connect()
    cfg = SoundConfig(MqttSettings(), sounds={})
    s = SoundService(cfg, m, PlayQueue(FakePlayer(), 3, 120))
    s.start(); c.published.clear()
    t[0] += 300
    s.step(0)
    assert ("doorstation/sound/status", "online", 1, True) in c.published


def test_missing_sound_files_reported_as_error(tmp_path):
    # Nicht nur im Journal: die Hausautomation soll sehen, dass ein konfigurierter Ton fehlt.
    c, s, p = setup(tmp_path)
    errors = [json.loads(p_)["message"] for t, p_, *_ in c.published if t == "doorstation/sound/error"]
    assert any("fehlt" in e for e in errors)
