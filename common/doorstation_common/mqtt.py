"""MQTT wrapper for a service: topics, status with last will, errors, commands."""

import json
import logging
import time
from collections.abc import Callable

from paho.mqtt.client import topic_matches_sub

from .config import MqttSettings
from .timeutil import now_iso

log = logging.getLogger(__name__)

STATUS_VALUES = {"online", "offline", "degraded"}


class ServiceMqtt:
    def __init__(self, service: str, settings: MqttSettings, client=None, clock=time.monotonic,
                 client_id_suffix: str = "") -> None:
        self.service = service
        self.settings = settings
        if client is None:
            import paho.mqtt.client as paho

            # One client ID per instance: identical IDs disconnect each other at the broker.
            client = paho.Client(paho.CallbackAPIVersion.VERSION2,
                                 client_id=f"doorstation-{service}{client_id_suffix}")
        self._client = client
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self.status = "online"
        self._clock = clock
        self._next_heartbeat = clock() + settings.heartbeat_s
        self._command_handler: Callable[[dict], None] | None = None
        self._connected_callbacks: list[Callable[[], None]] = []
        self._subscriptions: list[tuple[str, Callable[[str, bytes], None], int]] = []

    @property
    def connected(self) -> bool:
        return bool(self._client.is_connected())

    def topic(self, *parts: str) -> str:
        return "/".join((self.settings.prefix, self.service, *parts))

    def _abs_topic(self, parts: tuple[str, ...]) -> str:
        return "/".join((self.settings.prefix, *parts))

    @staticmethod
    def _json(payload: dict) -> str:
        return json.dumps({"ts": now_iso(), **payload}, ensure_ascii=False)

    def publish_json(self, subtopic: str, payload: dict, *, retain: bool = False, qos: int = 1) -> None:
        self._client.publish(self.topic(subtopic), self._json(payload), qos, retain)

    def publish_json_abs(self, parts: tuple[str, ...], payload: dict, *, retain: bool = False, qos: int = 1) -> None:
        self._client.publish(self._abs_topic(parts), self._json(payload), qos, retain)

    def publish_text_abs(self, topic: str, text: str, *, qos: int = 1, retain: bool = False) -> None:
        """Publish text unchanged to an absolute topic (e.g. baresip commands)."""
        self._client.publish(topic, text, qos, retain)

    def subscribe(self, topic: str, handler: Callable[[str, bytes], None], qos: int = 1) -> None:
        """Subscribe to an absolute topic (wildcards allowed); kept across reconnects."""
        self._subscriptions.append((topic, handler, qos))
        if self.connected:
            self._client.subscribe(topic, qos)

    def publish_raw(self, subtopic: str, text: str, *, retain: bool, qos: int = 1) -> None:
        self._client.publish(self.topic(subtopic), text, qos, retain)

    def set_status(self, state: str) -> None:
        if state not in STATUS_VALUES:
            raise ValueError(f"invalid status: {state}")
        self.status = state
        self.publish_raw("status", state, retain=True)

    def heartbeat(self) -> None:
        """Call from the main loop: repeats the status every heartbeat_s seconds.

        If the main loop hangs, the repetition stops - visible in the home automation as
        the status variable's "last update" getting old.
        """
        if self.settings.heartbeat_s <= 0:
            return
        now = self._clock()
        if now < self._next_heartbeat:
            return
        self._next_heartbeat = now + self.settings.heartbeat_s
        if self.connected:
            self.publish_raw("status", self.status, retain=True)

    def publish_error(self, message: str) -> None:
        log.warning("%s", message)
        self.publish_json("error", {"message": message})

    def on_command(self, handler: Callable[[dict], None]) -> None:
        self._command_handler = handler

    def on_connected(self, callback: Callable[[], None]) -> None:
        self._connected_callbacks.append(callback)

    def start(self) -> None:
        self._client.will_set(self.topic("status"), "offline", 1, True)
        self._client.reconnect_delay_set(1, 30)
        self._client.connect_async(self.settings.host, self.settings.port, 30)
        self._client.loop_start()

    def stop(self) -> None:
        self.set_status("offline")
        self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        failed = getattr(reason_code, "is_failure", reason_code != 0)
        if failed:
            log.warning("MQTT connection refused: %s", reason_code)
            return
        if self._command_handler is not None:
            self._client.subscribe(self.topic("cmd"), 1)
        for topic, _handler, qos in self._subscriptions:
            self._client.subscribe(topic, qos)
        self.set_status(self.status)
        for cb in self._connected_callbacks:
            try:
                cb()
            except Exception:  # must not end paho's network thread
                log.exception("error in on_connected callback")

    def _on_message(self, client, userdata, msg) -> None:
        for topic, handler, _qos in self._subscriptions:
            if topic_matches_sub(topic, msg.topic):
                try:
                    handler(msg.topic, msg.payload)
                except Exception as exc:
                    self.publish_error(f"error handling {msg.topic}: {exc}")
        if msg.topic != self.topic("cmd") or self._command_handler is None:
            return
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.publish_error(f"invalid JSON on {msg.topic}: {exc}")
            return
        if not isinstance(data, dict):
            self.publish_error(f"command on {msg.topic} must be a JSON object")
            return
        try:
            self._command_handler(data)
        except Exception as exc:  # command errors must not end the service
            self.publish_error(str(exc))
