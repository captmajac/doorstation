import pytest

from doorstation_rfid.kormax import AccessoryDriver
from doorstation_rfid.lock import QuietLock


class FakeService:
    """Die Methoden, die kormax' Lock beim Aufbau als Callbacks einträgt."""

    def __init__(self):
        self.on_endpoint_authenticated = None

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def lock(tmp_path):
    driver = AccessoryDriver(port=51999, persist_file=str(tmp_path / "hap.state"))
    seen = []
    service = FakeService()
    lk = QuietLock(driver, "NFC-Leser Test", service=service, on_homekey=seen.append)
    yield lk, service, seen
    driver.loop.close()


def test_lock_starts_secured(lock):
    lk, service, seen = lock
    assert lk.get_lock_current_state() == 1 and lk.get_lock_target_state() == 1


def test_unlock_request_snaps_back(lock):
    lk, service, seen = lock
    assert lk.set_lock_target_state(0) == 1
    assert lk.get_lock_current_state() == 1 and lk.get_lock_target_state() == 1


def test_homekey_does_not_toggle(lock):
    lk, service, seen = lock
    ep = object()
    service.on_endpoint_authenticated(ep)
    assert lk.get_lock_current_state() == 1 and lk.get_lock_target_state() == 1
    assert seen == [ep]
