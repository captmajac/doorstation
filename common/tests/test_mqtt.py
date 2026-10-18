import json

from doorstation_common.config import MqttSettings
from doorstation_common.mqtt import ServiceMqtt
from doorstation_common.testing import FakeMqttClient


def make():
    c = FakeMqttClient()
    m = ServiceMqtt("gpio", MqttSettings(), client=c)
    m.start()
    c.simulate_connect()
    return m, c


def test_last_will_and_online_on_connect():
    m, c = make()
    assert c.will == ("doorstation/gpio/status", "offline", 1, True)
    assert ("doorstation/gpio/status", "online", 1, True) in c.published


def test_publish_json_adds_ts_first():
    m, c = make()
    m.publish_json("input/bell", {"event": "pressed"})
    topic, payload, qos, retain = c.published[-1]
    data = json.loads(payload)
    assert topic == "doorstation/gpio/input/bell" and list(data)[0] == "ts" and data["event"] == "pressed"
    assert (qos, retain) == (1, False)


def test_invalid_command_json_reports_error_and_survives():
    m, c = make()
    calls = []
    m.on_command(calls.append)
    c.simulate_connect()
    c.simulate_message("doorstation/gpio/cmd", b"{broken")
    c.simulate_message("doorstation/gpio/cmd", b"[1,2]")
    c.simulate_message("doorstation/gpio/cmd", b'{"action":"x"}')
    errors = [p for t, p, *_ in c.published if t == "doorstation/gpio/error"]
    assert len(errors) == 2 and calls == [{"action": "x"}]


def test_handler_exception_becomes_error():
    m, c = make()

    def boom(_):
        raise ValueError("unbekannt")

    m.on_command(boom)
    c.simulate_connect()
    c.simulate_message("doorstation/gpio/cmd", b'{"action":"x"}')
    assert "unbekannt" in c.published[-1][1]


def test_reconnect_restores_status_and_calls_callback():
    m, c = make()
    called = []
    m.on_connected(lambda: called.append(1))
    m.set_status("degraded")
    c.published.clear()
    c.simulate_connect()
    assert ("doorstation/gpio/status", "degraded", 1, True) in c.published
    assert called == [1]


def test_publish_json_abs():
    m, c = make()
    m.publish_json_abs(("event", "ring"), {"source": "bell"})
    assert c.published[-1][0] == "doorstation/event/ring"


def test_connected_property_reflects_client():
    m, c = make()
    assert m.connected is True
    c.connected = False
    assert m.connected is False


def test_subscribe_receives_matching_messages_and_resubscribes():
    m, c = make()
    got = []
    m.subscribe("/baresip/event", lambda t, p: got.append((t, p)))
    assert "/baresip/event" in c.subscriptions
    c.subscriptions.clear()
    c.simulate_connect()
    assert "/baresip/event" in c.subscriptions
    c.simulate_message("/baresip/event", b'{"type":"REGISTER_OK"}')
    assert got == [("/baresip/event", b'{"type":"REGISTER_OK"}')]


def test_subscribe_wildcard():
    m, c = make()
    got = []
    m.subscribe("/baresip/command_resp/+", lambda t, p: got.append(t))
    c.simulate_message("/baresip/command_resp/7", b"{}")
    assert got == ["/baresip/command_resp/7"]


def test_subscribe_handler_exception_becomes_error():
    m, c = make()

    def boom(t, p):
        raise ValueError("broken")

    m.subscribe("/x", boom)
    c.simulate_message("/x", b"1")
    assert "broken" in c.published[-1][1]


def test_publish_text_abs_unchanged():
    m, c = make()
    m.publish_text_abs("/baresip/command/1", '{"command":"reginfo"}')
    assert c.published[-1] == ("/baresip/command/1", '{"command":"reginfo"}', 1, False)


def test_on_connected_exception_does_not_propagate():
    m, c = make()

    def boom():
        raise RuntimeError("x")

    m.on_connected(boom)
    c.simulate_connect()


def test_heartbeat_republishes_status_when_due():
    c = FakeMqttClient()
    t = [1000.0]
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=300), client=c, clock=lambda: t[0])
    m.start(); c.simulate_connect()
    c.published.clear()
    m.heartbeat()
    assert c.published == []                       # not due yet
    t[0] += 300
    m.heartbeat()
    assert c.published == [("doorstation/gpio/status", "online", 1, True)]
    m.set_status("degraded"); c.published.clear()
    t[0] += 300
    m.heartbeat()
    assert c.published == [("doorstation/gpio/status", "degraded", 1, True)]


def test_heartbeat_off_with_zero():
    c = FakeMqttClient()
    t = [1000.0]
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=0), client=c, clock=lambda: t[0])
    m.start(); c.simulate_connect(); c.published.clear()
    t[0] += 10000
    m.heartbeat()
    assert c.published == []


def test_heartbeat_skipped_when_disconnected():
    c = FakeMqttClient()
    t = [1000.0]
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=300), client=c, clock=lambda: t[0])
    m.start(); c.simulate_connect(); c.published.clear()
    c.connected = False
    t[0] += 300
    m.heartbeat()
    assert c.published == []


def test_client_id_suffix_for_parallel_instances():
    # --simulate next to the running service: identical client IDs would disconnect each other.
    from doorstation_common.config import MqttSettings
    from doorstation_common.mqtt import ServiceMqtt
    m = ServiceMqtt("gpio", MqttSettings(), client_id_suffix="-sim")
    assert m._client._client_id == b"doorstation-gpio-sim"


# --- retained states: only sent when the content changes (not on every restart) ---

FLAP = "doorstation/gpio/input/mail_flap"


def make_states(settle=1.0):
    c = FakeMqttClient()
    t = [1000.0]
    m = ServiceMqtt("gpio", MqttSettings(heartbeat_s=0), client=c, clock=lambda: t[0], state_settle_s=settle)
    m.start()
    return m, c, t


def states(c, topic=FLAP):
    return [(p, r) for tp, p, q, r in c.published if tp == topic]


def retained_msg(state, ts="2026-01-01T00:00:00.000+01:00"):
    return json.dumps({"ts": ts, "state": state}).encode()


def test_state_waits_for_retained_then_publishes_when_broker_has_none():
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "closed"})
    c.simulate_connect()
    assert FLAP in c.subscriptions          # learns what the broker holds
    m.heartbeat()
    assert states(c) == []                  # retained messages may still be arriving
    t[0] += 1.0
    m.heartbeat()
    (payload, retain), = states(c)
    assert json.loads(payload)["state"] == "closed" and retain is True


def test_state_unchanged_against_broker_is_not_sent_again():
    # Restart: the broker still holds "closed" - sending it again with a new ts would
    # make the home automation see a change.
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "closed"})
    c.simulate_connect()
    c.simulate_message(FLAP, retained_msg("closed"), retain=True)
    t[0] += 1.0
    m.heartbeat()
    assert states(c) == []


def test_state_differing_from_broker_is_sent_with_time_of_change():
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "open"})
    c.simulate_connect()
    c.simulate_message(FLAP, retained_msg("closed"), retain=True)
    t[0] += 1.0
    m.heartbeat()
    (payload, _), = states(c)
    assert json.loads(payload)["state"] == "open"


def test_state_after_sync_sent_immediately_only_on_change():
    m, c, t = make_states()
    c.simulate_connect()
    m.publish_state("input/mail_flap", {"state": "closed"})
    c.simulate_message(FLAP, retained_msg("closed"), retain=True)
    t[0] += 1.0
    m.heartbeat()
    assert states(c) == []
    m.publish_state("input/mail_flap", {"state": "open"})
    m.publish_state("input/mail_flap", {"state": "open"})
    assert [json.loads(p)["state"] for p, _ in states(c)] == ["open"]


def test_new_state_topic_after_connect_is_synced_too():
    m, c, t = make_states()
    c.simulate_connect()
    t[0] += 5
    m.publish_state("input/mail_flap", {"state": "closed"})
    assert FLAP in c.subscriptions and states(c) == []
    c.simulate_message(FLAP, retained_msg("closed"), retain=True)
    t[0] += 1.0
    m.heartbeat()
    assert states(c) == []


def test_reconnect_resends_only_what_the_broker_lost_unchanged():
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "open"})
    c.simulate_connect()
    t[0] += 1.0
    m.heartbeat()
    (first, _), = states(c)
    c.simulate_connect()                    # broker kept it
    c.simulate_message(FLAP, first.encode(), retain=True)
    t[0] += 1.0
    m.heartbeat()
    assert len(states(c)) == 1
    c.simulate_connect()                    # broker lost it (no retained message)
    t[0] += 1.0
    m.heartbeat()
    assert [p for p, _ in states(c)] == [first, first]   # same ts: no new change


def test_state_not_sent_while_disconnected():
    m, c, t = make_states()
    c.connected = False
    m.publish_state("input/mail_flap", {"state": "open"})
    t[0] += 5
    m.heartbeat()
    assert states(c) == []


def test_live_echo_of_state_does_not_count_as_broker_state():
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "open"})
    c.simulate_connect()
    c.simulate_message(FLAP, retained_msg("open"), retain=False)   # not retained
    t[0] += 1.0
    m.heartbeat()
    assert len(states(c)) == 1


def test_broker_state_that_is_no_json_object_counts_as_different():
    m, c, t = make_states()
    m.publish_state("input/mail_flap", {"state": "open"})
    c.simulate_connect()
    c.simulate_message(FLAP, b"open", retain=True)
    t[0] += 1.0
    m.heartbeat()
    assert len(states(c)) == 1
    assert not [p for tp, p, *_ in c.published if tp.endswith("/error")]
