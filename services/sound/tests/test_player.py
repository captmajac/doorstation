from pathlib import Path

from doorstation_sound import player as player_mod
from doorstation_sound.player import PwPlayPlayer


def test_pw_play_command(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            calls.append(cmd)

        def poll(self):
            return None

    monkeypatch.setattr(player_mod.subprocess, "Popen", FakePopen)
    PwPlayPlayer("ec_sink").start(Path("/s/you_have_mail.wav"), 0.8)
    assert calls == [["pw-play", "--target", "ec_sink", "--volume", "0.80", "/s/you_have_mail.wav"]]
