"""Test helpers: fake paho client."""

from types import SimpleNamespace


class FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscriptions: list[str] = []
        self.will: tuple | None = None
        self.on_connect = None
        self.on_message = None
        self.connected_to: tuple | None = None
        self.connected = True

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay, max_delay):
        pass

    def connect_async(self, host, port, keepalive):
        self.connected_to = (host, port)

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def is_connected(self) -> bool:
        return self.connected

    def subscribe(self, topic, qos):
        self.subscriptions.append(topic)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))

    def simulate_connect(self) -> None:
        self.on_connect(self, None, None, 0, None)

    def simulate_message(self, topic: str, payload: bytes, retain: bool = False) -> None:
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload, retain=retain))
