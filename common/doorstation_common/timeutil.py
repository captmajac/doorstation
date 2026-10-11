"""Zeitstempel für MQTT-Nutzdaten."""

from datetime import datetime


def now_iso(now: datetime | None = None) -> str:
    """ISO-8601 mit Zeitzone und Millisekunden, z. B. 2026-10-07T18:03:12.481+02:00."""
    if now is None:
        now = datetime.now().astimezone()
    return now.isoformat(timespec="milliseconds")
