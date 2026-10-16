from doorstation_sip.timesync import main, wait_for_time_sync


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_returns_immediately_when_synchronized(tmp_path):
    marker = tmp_path / "synchronized"
    marker.touch()
    clock = Clock()
    assert wait_for_time_sync(marker, 90, clock=clock, sleep=clock.sleep) is True
    assert clock.t == 0


def test_waits_until_marker_appears(tmp_path):
    marker = tmp_path / "synchronized"
    clock = Clock()

    def sleep(s):
        clock.sleep(s)
        if clock.t >= 5:
            marker.touch()

    assert wait_for_time_sync(marker, 90, clock=clock, sleep=sleep) is True
    assert 5 <= clock.t < 7


def test_gives_up_after_timeout(tmp_path):
    clock = Clock()
    assert wait_for_time_sync(tmp_path / "synchronized", 90, clock=clock, sleep=clock.sleep) is False
    assert 90 <= clock.t < 92


def test_main_never_blocks_the_start(tmp_path):
    # Without internet there is no time sync: baresip must start anyway (the bell must work).
    assert main(["--marker", str(tmp_path / "missing"), "--timeout", "0"]) == 0
