import wave
from pathlib import Path

import pytest

from doorstation_common.config import ConfigError
from doorstation_sound.config import available, load_config

ROOT = Path(__file__).parents[3]


def test_example_loads():
    cfg = load_config(ROOT / "config-examples/sound.yaml")
    assert cfg.sounds["beep"].volume == 0.6 and cfg.sounds["post"].volume is None
    assert (cfg.target, cfg.queue_size, cfg.default_volume) == ("ec_sink", 3, 0.8)
    assert set(cfg.sounds) == {"beep", "post", "post_kurz", "tuer_oeffnet", "paket_ablage", "schrei"}


def write(tmp_path, body):
    p = tmp_path / "sound.yaml"
    p.write_text(body)
    return p


def test_invalid_name(tmp_path):
    with pytest.raises(ConfigError, match="Post!"):
        load_config(write(tmp_path, "sounds:\n  'Post!': {file: /x.wav}\n"))


def test_volume_out_of_range(tmp_path):
    with pytest.raises(ConfigError, match="volume"):
        load_config(write(tmp_path, "sounds:\n  a: {file: /x.wav, volume: 1.5}\n"))


def test_unknown_key(tmp_path):
    with pytest.raises(ConfigError, match="lautstaerke"):
        load_config(write(tmp_path, "lautstaerke: 1\nsounds: {}\n"))


def test_missing_file_not_available(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    cfg = load_config(write(tmp_path, f"sounds:\n  a: {{file: {tmp_path}/a.wav}}\n  b: {{file: {tmp_path}/b.wav}}\n"))
    assert available(cfg) == ["a"]


def test_beep_shipped():
    w = wave.open(str(ROOT / "services/sound/sounds/beep.wav"))
    assert 0.1 <= w.getnframes() / w.getframerate() <= 0.3
