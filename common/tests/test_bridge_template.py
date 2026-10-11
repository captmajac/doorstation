"""Regeln der Mosquitto-Bridge (deploy/mosquitto/bridge.conf.template).

Mosquitto verwendet bei überlappenden Regeln die höchste QoS. Ereignisse, die nach einem
Ausfall nicht verspätet ankommen dürfen, darf deshalb keine Regel mit QoS 1 erfassen.
"""

from pathlib import Path

import pytest
from paho.mqtt.client import topic_matches_sub

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "mosquitto" / "bridge.conf.template"


def _rules() -> list[tuple[str, str, int]]:
    rules = []
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and parts[0] == "topic":
            _, pattern, direction, qos = parts
            rules.append((pattern.replace("@PREFIX@", "doorstation"), direction, int(qos)))
    return rules


def _qos(topic: str, directions: tuple[str, ...]) -> int | None:
    """Höchste QoS aller passenden Regeln, None = Topic wird nicht übertragen."""
    matches = [q for p, d, q in _rules() if d in directions and topic_matches_sub(p, topic)]
    return max(matches) if matches else None


# Verspätet ausgeliefert könnten sie eine Tür öffnen: nur QoS 0, nie gepuffert.
@pytest.mark.parametrize("topic", ["doorstation/event/ring", "doorstation/rfid/read", "doorstation/sip/dtmf"])
def test_time_critical_events_go_out_with_qos0_only(topic):
    assert _qos(topic, ("out", "both")) == 0


@pytest.mark.parametrize("topic", [
    "doorstation/gpio/status", "doorstation/gpio/input/mail_flap",
    "doorstation/sip/status", "doorstation/sip/call", "doorstation/sip/target",
    "doorstation/sip/registration", "doorstation/sip/error",
    "doorstation/sound/status", "doorstation/sound/state", "doorstation/sound/available",
    "doorstation/rfid/status", "doorstation/rfid/pairing", "doorstation/rfid/error",
])
def test_states_go_out_with_qos1(topic):
    assert _qos(topic, ("out", "both")) == 1


@pytest.mark.parametrize("topic", ["doorstation/sip/cmd", "doorstation/sound/cmd"])
def test_commands_come_in_with_qos0_only(topic):
    # Mit QoS 1 puffert der Server der Hausautomation Befehle während eines Ausfalls und
    # liefert sie verspätet nach (z. B. eine Ansage Stunden später).
    assert _qos(topic, ("in", "both")) == 0


@pytest.mark.parametrize("topic", ["doorstation/event/ring", "doorstation/sip/dtmf", "baresip/command/1",
                                   "/baresip/command/1"])
def test_only_commands_come_in(topic):
    assert _qos(topic, ("in", "both")) is None
