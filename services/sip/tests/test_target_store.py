from doorstation_sip.target_store import TargetStore


def test_missing_file_returns_default(tmp_path):
    assert TargetStore(tmp_path / "t.json", "**701").load() == "**701"


def test_save_and_load_roundtrip(tmp_path):
    TargetStore(tmp_path / "t.json", "**701").save("**610")
    assert TargetStore(tmp_path / "t.json", "**701").load() == "**610"


def test_save_none_persists_mute(tmp_path):
    TargetStore(tmp_path / "t.json", "**701").save(None)
    assert TargetStore(tmp_path / "t.json", "**701").load() is None


def test_corrupt_file_returns_default(tmp_path):
    (tmp_path / "t.json").write_text("{broken")
    assert TargetStore(tmp_path / "t.json", "**701").load() == "**701"


def test_invalid_target_in_file_returns_default(tmp_path):
    (tmp_path / "t.json").write_text('{"target":"abc"}')
    assert TargetStore(tmp_path / "t.json", "**701").load() == "**701"


def test_save_creates_directory(tmp_path):
    TargetStore(tmp_path / "sub" / "t.json", None).save("**610")
    assert (tmp_path / "sub" / "t.json").exists()
