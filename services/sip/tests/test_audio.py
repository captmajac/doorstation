import pytest

from doorstation_common.config import ConfigError
from doorstation_sip.audio import AudioConfig, find_card, load_audio_config, nodes_for_card, plan_commands

CARDS = """ 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 3 [Device         ]: USB-Audio - USB Audio Device
                      C-Media Electronics Inc. USB Audio Device at usb-0000:01:00.0-1.1, full speed
"""

CFG = AudioConfig("USB", "Speaker", 80, "Mic", 50, False, False)

DUMP = [
    {"id": 38, "info": {"props": {"media.class": "Audio/Sink", "node.name": "ec_sink"}}},
    {"id": 61, "info": {"props": {"media.class": "Audio/Sink", "alsa.card": 3}}},
    {"id": 62, "info": {"props": {"media.class": "Audio/Source", "alsa.card": 3}}},
    {"id": 77, "info": {"props": {"media.class": "Audio/Sink", "alsa.card": 0}}},
    {"id": 5, "type": "PipeWire:Interface:Core"},
]


def test_find_card_by_usb():
    assert find_card(CARDS, "USB") == 3


def test_find_card_case_insensitive_long_name():
    assert find_card(CARDS, "c-media") == 3


def test_find_card_none():
    assert find_card(CARDS, "Jabra") is None


def test_plan_skips_missing_agc():
    cmds = plan_commands(CFG, 3, {"Speaker", "Mic"})
    assert not any("Auto Gain Control" in c for c in cmds)


def test_plan_agc_off_and_mic_playback_mute():
    cmds = plan_commands(CFG, 3, {"Speaker", "Mic", "Auto Gain Control"})
    assert ["amixer", "-c", "3", "sset", "Auto Gain Control", "off"] in cmds
    assert ["amixer", "-c", "3", "sset", "Mic", "playback", "mute"] in cmds


def test_plan_agc_none_skipped():
    cfg = AudioConfig("USB", "Speaker", 80, "Mic", 50, None, False)
    assert not any("Auto Gain Control" in c for c in plan_commands(cfg, 3, {"Auto Gain Control", "Mic"}))


def test_nodes_for_card():
    assert nodes_for_card(DUMP, 3) == (61, 62)
    assert nodes_for_card(DUMP, 9) == (None, None)


def test_load_example_and_percent_validation(tmp_path):
    from pathlib import Path
    cfg = load_audio_config(Path(__file__).parents[3] / "config-examples/audio.yaml")
    assert (cfg.card_match, cfg.playback_control, cfg.auto_gain_control) == ("USB", "Headphone", False)
    p = tmp_path / "a.yaml"
    p.write_text("card_match: USB\nplayback_control: X\nplayback_percent: 120\ncapture_control: Mic\ncapture_percent: 50\n")
    with pytest.raises(ConfigError, match="playback_percent"):
        load_audio_config(p)


def test_wait_for_card_retries_until_present():
    from doorstation_sip.audio import wait_for_card
    texts = iter(["", "", CARDS])
    t = [0.0]

    def clock():
        return t[0]

    def sleep(d):
        t[0] += d

    assert wait_for_card(lambda: next(texts), "USB", timeout=10, clock=clock, sleep=sleep) == 3
    assert wait_for_card(lambda: "", "USB", timeout=2, clock=clock, sleep=sleep) is None


@pytest.mark.parametrize("extra, field", [
    ('mic_playback: "false"\n', "mic_playback"),
    ("echo_cancel:\n  enabled: \"no\"\n", "echo_cancel"),
    ("echo_cancel: yes-please\n", "echo_cancel"),
])
def test_switches_must_be_real_booleans(tmp_path, extra, field):
    # bool("false") would be true: microphone straight to the speaker (feedback).
    p = tmp_path / "a.yaml"
    p.write_text("card_match: USB\nplayback_control: X\nplayback_percent: 50\ncapture_control: Mic\n"
                 "capture_percent: 50\n" + extra)
    with pytest.raises(ConfigError, match=field):
        load_audio_config(p)
