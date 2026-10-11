from doorstation_common.config import MqttSettings
from doorstation_sip.config import SipConfig
from doorstation_sip.machine import CallMachine, CallState, Dial, Hangup, peer_from_uri

CFG = SipConfig(MqttSettings(), "192.168.178.1", "Tuerstation")
URI = "sip:**610@192.168.178.1"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(registered=True):
    c = Clock()
    m = CallMachine(CFG, c)
    if registered:
        m.baresip_event({"type": "REGISTER_OK"})
    return m, c


def calling(m):
    return m.ring("**610")


def established(m):
    calling(m)
    return m.baresip_event({"type": "CALL_ESTABLISHED", "direction": "outgoing", "peeruri": URI})


def test_ring_dials_target():
    m, c = make()
    assert m.ring("**610") == [Dial(URI), CallState("calling", "outgoing", "**610")]
    assert m.state == "calling"


def test_ring_when_muted_does_nothing():
    m, c = make()
    assert m.ring(None) == []
    assert m.state == "idle"


def test_ring_not_registered():
    m, c = make(registered=False)
    assert m.ring("**610") == [CallState("ended", "outgoing", "**610", "not_registered")]


def test_second_ring_while_calling_ignored():
    m, c = make()
    calling(m)
    assert m.ring("**610") == []


def test_established_then_remote_hangup():
    m, c = make()
    assert established(m) == [CallState("active", "outgoing", "**610")]
    assert m.baresip_event({"type": "CALL_CLOSED", "param": "Connection reset by peer"}) == [
        CallState("ended", "outgoing", "**610", "hangup")]


def test_ring_timeout_hangs_up():
    m, c = make()
    calling(m)
    c.t += 29.9
    assert m.tick() == []
    c.t += 0.1
    assert m.tick() == [Hangup(), CallState("ended", "outgoing", "**610", "timeout")]


def test_late_call_closed_after_timeout_ignored():
    m, c = make()
    calling(m)
    c.t += 30
    m.tick()
    assert m.baresip_event({"type": "CALL_CLOSED", "param": "terminated"}) == []
    assert m.state == "ended"


def test_max_duration():
    m, c = make()
    established(m)
    c.t += 120
    assert m.tick() == [Hangup(), CallState("ended", "outgoing", "**610", "max_duration")]


def test_busy_and_rejected():
    m, c = make()
    calling(m)
    assert m.baresip_event({"type": "CALL_CLOSED", "param": "486 Busy Here"})[-1].reason == "busy"
    m2, c2 = make()
    calling(m2)
    assert m2.baresip_event({"type": "CALL_CLOSED", "param": "603 Decline"})[-1].reason == "rejected"


def test_cooldown_blocks_then_idle():
    m, c = make()
    established(m)
    m.baresip_event({"type": "CALL_CLOSED", "param": "x"})
    c.t += 4
    assert m.ring("**610") == []
    assert m.tick() == []
    c.t += 1
    assert m.tick() == [CallState("idle")]
    assert m.ring("**610")[0] == Dial(URI)


def test_incoming_auto_answer():
    m, c = make()
    ev = {"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:**610@fritz.box"}
    assert m.baresip_event(ev) == [CallState("active", "incoming", "**610")]


def test_incoming_max_duration_applies():
    m, c = make()
    m.baresip_event({"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:**610@fritz.box"})
    c.t += 120
    assert m.tick()[0] == Hangup()


def test_register_ok_during_call_keeps_call():
    m, c = make()
    established(m)
    assert m.baresip_event({"type": "REGISTER_OK"}) == []
    assert m.state == "active"


def test_register_fail_sets_unregistered():
    m, c = make()
    m.baresip_event({"type": "REGISTER_FAIL"})
    assert m.registered is False


def test_local_hangup_command():
    m, c = make()
    established(m)
    assert m.hangup() == [Hangup(), CallState("ended", "outgoing", "**610", "hangup")]


def test_hangup_in_idle_does_nothing():
    m, c = make()
    assert m.hangup() == []


def test_reset_from_active():
    m, c = make()
    established(m)
    assert m.reset()[-1] == CallState("idle")
    assert m.state == "idle"


def test_call_closed_in_idle_ignored():
    m, c = make()
    assert m.baresip_event({"type": "CALL_CLOSED"}) == []


def test_peer_from_uri():
    assert peer_from_uri("sip:**610@fritz.box") == "**610"
    assert peer_from_uri("sip:x") == "sip:x"


def test_incoming_during_cooldown_is_tracked():
    m, c = make()
    established(m)
    m.baresip_event({"type": "CALL_CLOSED", "param": "x"})
    ev = {"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:**610@fritz.box"}
    assert m.baresip_event(ev) == [CallState("active", "incoming", "**610")]
    c.t += 120
    assert m.tick()[0] == Hangup()


def test_untracked_established_call_is_hung_up():
    m, c = make()
    established(m)
    ev = {"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:**611@fritz.box"}
    assert m.baresip_event(ev) == [Hangup()]


def test_incoming_not_via_fritzbox_is_hung_up():
    m, c = make()
    ev = {"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:evil@192.168.178.99"}
    assert m.baresip_event(ev) == [Hangup()]
    assert m.state == "idle"


def test_incoming_via_fritzbox_ip_accepted():
    m, c = make()
    ev = {"type": "CALL_ESTABLISHED", "direction": "incoming", "peeruri": "sip:**610@192.168.178.1"}
    assert m.baresip_event(ev)[0].state == "active"


def test_reset_hangs_up_running_call():
    m, c = make()
    established(m)
    assert m.reset() == [Hangup(), CallState("idle")]
