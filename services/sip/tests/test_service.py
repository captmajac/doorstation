import json
from datetime import datetime, timedelta, timezone

from doorstation_common.config import MqttSettings
from doorstation_common.mqtt import ServiceMqtt
from doorstation_common.testing import FakeMqttClient
from doorstation_sip.config import SipConfig
from doorstation_sip.service import SipService
from doorstation_sip.target_store import TargetStore

CFG = SipConfig(MqttSettings(), "192.168.178.1", "Tuerstation")
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

REGINFO_OK = (b'{"response":true,"ok":true,"data":"\\n--- User Agents (1) ---\\n0 - sip:Tuerstation@192.168.178.1'
              b'                \\u001B[32mOK \\u001B[;m  Expires 300s\\n\\n","token":"%s"}')


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def setup(tmp_path, target="**610", registered=True, restarts=None):
    c = FakeMqttClient()
    m = ServiceMqtt("sip", MqttSettings(), client=c, state_settle_s=0)
    m.start()
    c.simulate_connect()
    store = TargetStore(tmp_path / "target.json", "**701")
    store.save(target)
    clock = Clock()
    request = (lambda: restarts.append(clock.t)) if restarts is not None else (lambda: None)
    s = SipService(CFG, m, store, clock=clock, wall=lambda: NOW.timestamp(), request_baresip_restart=request)
    s.start()
    if registered:
        ev(c, "REGISTER_OK")
    s.step(0)
    return c, s, clock


def ev(c, typ, **kw):
    c.simulate_message("/baresip/event", json.dumps({"type": typ, **kw}).encode())


def cmd(c, **kw):
    c.simulate_message("doorstation/sip/cmd", json.dumps(kw).encode())


def cmds(c, skip_start=True):
    out = []
    for t, p, *_ in c.published:
        if t.startswith("/baresip/command/"):
            d = json.loads(p)
            if skip_start and d["token"] == "1":  # hangup at start, separate test
                continue
            if d["command"] != "reginfo":  # health check, separate tests
                out.append((d["command"], d.get("params", "")))
    return out


def msgs(c, topic):
    return [json.loads(p) if p.startswith("{") else p for t, p, *_ in c.published if t == topic]


def test_ring_event_triggers_dial_to_stored_target(tmp_path):
    c, s, clock = setup(tmp_path)
    c.simulate_message("doorstation/event/ring", b'{"source":"bell"}')
    s.step(0)
    assert cmds(c) == [("dial", "sip:**610@192.168.178.1")]
    assert msgs(c, "doorstation/sip/call")[-1]["state"] == "calling"


def test_set_target_null_mutes_and_persists(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="set_target", target=None)
    s.step(0)
    assert msgs(c, "doorstation/sip/target")[-1]["target"] is None
    assert TargetStore(tmp_path / "target.json", "**701").load() is None
    c.simulate_message("doorstation/event/ring", b"{}")
    s.step(0)
    assert cmds(c) == []


def test_invalid_target_rejected(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="set_target", target="12a")
    s.step(0)
    assert msgs(c, "doorstation/sip/error")
    assert TargetStore(tmp_path / "target.json", "**701").load() == "**610"


def test_stale_call_command_dropped(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="call", ts=(NOW - timedelta(seconds=60)).isoformat())
    s.step(0)
    assert msgs(c, "doorstation/sip/error") and cmds(c) == []


def test_fresh_call_command_with_target(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="call", target="**621", ts=NOW.isoformat())
    s.step(0)
    assert cmds(c) == [("dial", "sip:**621@192.168.178.1")]


def test_call_while_muted_without_target_is_error(tmp_path):
    c, s, clock = setup(tmp_path, target=None)
    cmd(c, action="call")
    s.step(0)
    assert msgs(c, "doorstation/sip/error") and cmds(c) == []


def test_unknown_action_is_error(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="test")
    s.step(0)
    assert msgs(c, "doorstation/sip/error")


def test_timeout_sends_hangup(tmp_path):
    c, s, clock = setup(tmp_path)
    c.simulate_message("doorstation/event/ring", b"{}")
    s.step(0)
    clock.t += 30
    s.step(0)
    assert ("hangup", "") in cmds(c)  # after 30 s the health check (reginfo) runs too
    assert msgs(c, "doorstation/sip/call")[-1]["reason"] == "timeout"


def test_dtmf_published_during_active_call(tmp_path):
    c, s, clock = setup(tmp_path)
    ev(c, "CALL_ESTABLISHED", direction="incoming", peeruri="sip:**610@fritz.box")
    ev(c, "CALL_DTMF_START", param="#")
    s.step(0)
    assert msgs(c, "doorstation/sip/dtmf")[-1]["key"] == "#"


def test_dtmf_without_active_call_not_published(tmp_path):
    # Without an active call no key (e.g. "#" = door opener) may be reported.
    c, s, clock = setup(tmp_path)
    ev(c, "CALL_DTMF_START", param="#")
    s.step(0)
    assert msgs(c, "doorstation/sip/dtmf") == []


def test_dtmf_from_rejected_direct_call_not_published(tmp_path):
    # Direct call from the LAN: hung up, a key sent right after is not reported.
    c, s, clock = setup(tmp_path)
    ev(c, "CALL_ESTABLISHED", direction="incoming", peeruri="sip:evil@192.168.178.99")
    ev(c, "CALL_DTMF_START", param="#")
    s.step(0)
    assert ("hangup", "") in cmds(c)
    assert msgs(c, "doorstation/sip/dtmf") == []


def test_registration_published(tmp_path):
    c, s, clock = setup(tmp_path)
    assert msgs(c, "doorstation/sip/registration")[-1]["state"] == "registered"


def test_healthcheck_two_misses_degraded_and_reset(tmp_path):
    c, s, clock = setup(tmp_path)
    ev(c, "CALL_ESTABLISHED", direction="incoming", peeruri="sip:**610@fritz.box")
    s.step(0)
    for _ in range(3):
        clock.t += 30
        s.step(0)
    assert ("doorstation/sip/status", "degraded", 1, True) in c.published
    assert msgs(c, "doorstation/sip/call")[-1]["state"] == "idle"


def test_healthcheck_response_online(tmp_path):
    c, s, clock = setup(tmp_path)
    clock.t += 30
    s.step(0)
    token = json.loads([p for t, p, *_ in c.published if t.startswith("/baresip/command/")][-1])["token"]
    c.published.clear()
    c.simulate_message(f"/baresip/command_resp/{token}", REGINFO_OK % token.encode())
    s.step(0)
    clock.t += 30
    s.step(0)
    assert ("doorstation/sip/status", "degraded", 1, True) not in c.published



def first_reginfo_token(c):
    for t, p, *_ in c.published:
        if t.startswith("/baresip/command/") and json.loads(p)["command"] == "reginfo":
            return json.loads(p)["token"]
    return None


def test_adapter_restart_learns_registration_from_reginfo(tmp_path):
    c, s, clock = setup(tmp_path, registered=False)
    token = first_reginfo_token(c)
    assert token is not None  # queried right at start, not only after healthcheck_s
    c.simulate_message(f"/baresip/command_resp/{token}", REGINFO_OK % token.encode())
    s.step(0)
    assert msgs(c, "doorstation/sip/registration")[-1]["state"] == "registered"
    c.simulate_message("doorstation/event/ring", b"{}")
    s.step(0)
    assert ("dial", "sip:**610@192.168.178.1") in cmds(c)


def test_status_published_only_on_change(tmp_path):
    c, s, clock = setup(tmp_path)
    for _ in range(3):
        clock.t += 30
        s.step(0)
        last = [json.loads(p)["token"] for t, p, *_ in c.published
                if t.startswith("/baresip/command/") and json.loads(p)["command"] == "reginfo"][-1]
        c.simulate_message(f"/baresip/command_resp/{last}", REGINFO_OK % last.encode())
        s.step(0)
    statuses = [p for t, p, *_ in c.published if t == "doorstation/sip/status"]
    assert statuses.count("online") <= 2  # start + at most one confirmation, not on every check


def test_startup_hangs_up_leftover_call(tmp_path):
    c, s, clock = setup(tmp_path)
    assert cmds(c, skip_start=False)[:1] == [("hangup", "")]  # before anything else: end a leftover baresip call


def test_step_sends_heartbeat(tmp_path):
    t = [1000.0]
    c = FakeMqttClient()
    m = ServiceMqtt("sip", MqttSettings(heartbeat_s=300), client=c, clock=lambda: t[0])
    m.start(); c.simulate_connect()
    s = SipService(CFG, m, TargetStore(tmp_path / "t.json", "**701"), clock=Clock(), wall=lambda: NOW.timestamp())
    s.start(); c.published.clear()
    t[0] += 300
    s.step(0)
    assert ("doorstation/sip/status", "online", 1, True) in c.published


def test_naive_timestamp_rejected(tmp_path):
    # Without a time zone the age is undefined (local time or UTC?) - drop it.
    c, s, clock = setup(tmp_path)
    cmd(c, action="call", ts=NOW.replace(tzinfo=None).isoformat())
    s.step(0)
    assert cmds(c) == []
    assert "time zone" in msgs(c, "doorstation/sip/error")[-1]["message"]


def test_far_future_timestamp_rejected(tmp_path):
    # Home automation clock running fast: a command "from the future" would stay valid indefinitely.
    c, s, clock = setup(tmp_path)
    cmd(c, action="call", ts=(NOW + timedelta(seconds=120)).isoformat())
    s.step(0)
    assert cmds(c) == []
    assert msgs(c, "doorstation/sip/error")


def test_slightly_future_timestamp_accepted(tmp_path):
    c, s, clock = setup(tmp_path)
    cmd(c, action="call", ts=(NOW + timedelta(seconds=5)).isoformat())
    s.step(0)
    assert cmds(c) == [("dial", "sip:**610@192.168.178.1")]


def test_failing_item_does_not_stop_queue(tmp_path):
    # An error in one item (e.g. target file not writable) must neither lose the others
    # nor end the service.
    c, s, clock = setup(tmp_path)

    def broken_save(target):
        raise OSError("read-only file system")

    s.store.save = broken_save
    cmd(c, action="set_target", target="**621")
    c.simulate_message("doorstation/event/ring", b"{}")
    s.step(0)
    assert "read-only file system" in msgs(c, "doorstation/sip/error")[-1]["message"]
    assert cmds(c) == [("dial", "sip:**610@192.168.178.1")]


def test_registration_unknown_when_baresip_silent(tmp_path):
    # If baresip does not respond, the registration is unknown - not the last value.
    c, s, clock = setup(tmp_path)
    for _ in range(3):
        clock.t += 30
        s.step(0)
    assert msgs(c, "doorstation/sip/registration")[-1]["state"] == "unknown"


def test_silent_baresip_gets_restarted(tmp_path):
    # baresip loses its MQTT connection after a clock jump and never reconnects: restart it.
    restarts = []
    c, s, clock = setup(tmp_path, restarts=restarts)
    for _ in range(3):
        clock.t += 30
        s.step(0)
    assert len(restarts) == 1


def test_baresip_restart_rate_limited(tmp_path):
    restarts = []
    c, s, clock = setup(tmp_path, restarts=restarts)
    for _ in range(9):          # silent for 4.5 min: one restart request only
        clock.t += 30
        s.step(0)
    assert len(restarts) == 1
    for _ in range(6):          # still silent after 5 min: ask again
        clock.t += 30
        s.step(0)
    assert len(restarts) == 2


def test_responding_baresip_is_not_restarted(tmp_path):
    restarts = []
    c, s, clock = setup(tmp_path, restarts=restarts)
    for _ in range(4):
        token = first_reginfo_token_after(c, s)
        c.simulate_message(f"/baresip/command_resp/{token}", REGINFO_OK % token.encode())
        clock.t += 30
        s.step(0)
    assert restarts == []


def first_reginfo_token_after(c, s):
    for t, p, *_ in reversed(c.published):
        if t.startswith("/baresip/command/") and json.loads(p)["command"] == "reginfo":
            return json.loads(p)["token"]
    return None


def test_restart_with_unchanged_states_sends_nothing(tmp_path):
    clock = Clock()
    c = FakeMqttClient()
    m = ServiceMqtt("sip", MqttSettings(heartbeat_s=0), client=c, clock=clock)
    store = TargetStore(tmp_path / "target.json", "**701")
    store.save("**610")
    s = SipService(CFG, m, store, clock=clock, wall=lambda: NOW.timestamp())
    m.start()
    s.start()
    c.simulate_connect()
    old = "2026-01-01T00:00:00.000+01:00"
    for sub, data in (("target", {"target": "**610"}), ("call", {"state": "idle"})):
        c.simulate_message(f"doorstation/sip/{sub}", json.dumps({"ts": old, **data}).encode(), retain=True)
    clock.t += 1
    s.step(0)
    for sub in ("target", "call", "registration"):
        assert msgs(c, f"doorstation/sip/{sub}") == [], sub
