from doorstation_gpio.config import InputConfig
from doorstation_gpio.inputs import ButtonInput, StateInput


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def btn(**kw):
    return InputConfig(name="bell", pin=9, kind="button", **kw)


def st(**kw):
    return InputConfig(name="flap", pin=19, kind="state", states=("closed", "open"), **kw)


def test_press_fires_once_hold_does_not_repeat():
    b = ButtonInput(btn(), Clock())
    assert b.on_level(True) is True
    assert b.on_level(True) is False
    assert b.on_level(False) is False


def test_release_trigger():
    b = ButtonInput(btn(trigger="release"), Clock())
    assert b.on_level(True) is False and b.on_level(False) is True


def test_active_low_button():
    b = ButtonInput(btn(active="low"), Clock())
    assert b.on_level(False) is True


def test_button_min_interval():
    c = Clock()
    b = ButtonInput(btn(min_interval_s=2), c)
    assert b.on_level(True)
    b.on_level(False)
    c.t += 1
    assert not b.on_level(True)
    b.on_level(False)
    c.t += 1.5
    assert b.on_level(True)


def test_state_initial_and_immediate_change():
    s = StateInput(st(), Clock())
    assert s.initial(False) == "closed"
    assert s.on_level(True) == "open" and s.current == "open"


def test_state_trailing_reports_final_state():
    c = Clock()
    s = StateInput(st(min_interval_s=10), c)
    s.initial(False)
    assert s.on_level(True) == "open"
    c.t += 1; assert s.on_level(False) is None
    c.t += 1; assert s.on_level(True) is None
    c.t += 1; assert s.on_level(False) is None
    c.t += 1; assert s.on_level(True) is None
    c.t += 7; assert s.poll() is None  # Endzustand open == gemeldet
    c.t += 1; assert s.on_level(False) == "closed"  # Sperrfenster abgelaufen: sofort


def test_state_no_duplicate_report():
    s = StateInput(st(), Clock())
    s.initial(True)
    assert s.on_level(True) is None


def test_throttle_uses_only_injected_clock():
    c = Clock()
    s = StateInput(st(min_interval_s=10), c)
    s.initial(False)
    s.on_level(True)
    c.t += 3; assert s.on_level(False) is None
    c.t += 7; assert s.poll() == "closed"


def test_initial_pressed_button_does_not_fire_until_released_and_pressed():
    b = ButtonInput(btn(), Clock())
    b.initial(True)
    assert b.on_level(True) is False
    assert b.on_level(False) is False
    assert b.on_level(True) is True


def test_release_reported_after_reported_press():
    c = Clock()
    b = ButtonInput(btn(report_release=True), c)
    assert b.on_level(True) is True and b.pop_release() is False
    assert b.on_level(False) is False and b.pop_release() is True
    assert b.pop_release() is False


def test_no_release_for_throttled_press():
    c = Clock()
    b = ButtonInput(btn(report_release=True, min_interval_s=2), c)
    b.on_level(True); b.on_level(False); b.pop_release()
    c.t += 1
    assert b.on_level(True) is False          # gedrosselt
    b.on_level(False)
    assert b.pop_release() is False


def test_no_release_without_option():
    b = ButtonInput(btn(), Clock())
    b.on_level(True); b.on_level(False)
    assert b.pop_release() is False
