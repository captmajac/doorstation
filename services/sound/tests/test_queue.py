from pathlib import Path

from doorstation_sound.player import FakePlayer
from doorstation_sound.queue import Job, PlayQueue


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def job(name):
    return Job(name, Path(f"/s/{name}.wav"), 0.8)


def make(size=3):
    p = FakePlayer()
    c = Clock()
    return PlayQueue(p, queue_size=size, max_play_s=120, clock=c), p, c


def test_play_starts_immediately():
    q, p, c = make()
    q.play(job("a"))
    assert q.tick() == [("playing", "a")]
    assert p.started == [Path("/s/a.wav")]


def test_queue_in_order():
    q, p, c = make()
    q.play(job("a")); q.play(job("b")); q.tick()
    assert p.started == [Path("/s/a.wav")]
    p.finish()
    assert q.tick() == [("done", "a"), ("playing", "b")]


def test_queue_overflow_drops_oldest():
    q, p, c = make(size=3)
    q.play(job("a")); q.tick()
    for n in "bcde":
        q.play(job(n))
    started = []
    for _ in range(4):
        p.finish()
        started += [e[1] for e in q.tick() if e[0] == "playing"]
    assert started == ["c", "d", "e"]


def test_interrupt_clears_queue():
    q, p, c = make()
    q.play(job("a")); q.tick(); q.play(job("b"))
    q.play(job("x"), interrupt=True)
    assert p.stopped == 1
    assert q.tick() == [("playing", "x")]
    p.finish()
    assert q.tick() == [("done", "x"), ("idle", None)]


def test_stop_idle_is_harmless():
    q, p, c = make()
    q.stop()
    assert q.tick() == []


def test_stop_running():
    q, p, c = make()
    q.play(job("a")); q.tick()
    q.stop()
    assert q.tick() == [("idle", None)]


def test_failed_reports_error_and_continues():
    q, p, c = make()
    q.play(job("a")); q.play(job("b")); q.tick()
    p.finish(ok=False)
    events = q.tick()
    assert events[0][0] == "error" and ("playing", "b") in events


def test_max_play_kills():
    q, p, c = make()
    q.play(job("a")); q.play(job("b")); q.tick()
    c.t += 120
    events = q.tick()
    assert p.stopped == 1 and ("playing", "b") in events


class BrokenPlayer(FakePlayer):
    def start(self, file, volume):
        raise FileNotFoundError("pw-play")


def test_start_failure_reports_error_and_continues():
    q = PlayQueue(BrokenPlayer(), queue_size=3, max_play_s=120, clock=Clock())
    q.play(job("a"))
    events = q.tick()
    assert events[0][0] == "error" and "pw-play" in events[0][1]
    assert q.current is None
