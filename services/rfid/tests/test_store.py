import json
import os

import pytest

from doorstation_rfid.kormax import Repository
from doorstation_rfid.store import AtomicRepository

KEY = bytes(range(32))
ISSUER = {
    "public_key": "11" * 32,
    "endpoints": {"aa": {"last_used_at": 5, "counter": 2, "key_type": 2,
                         "public_key": "04" + "22" * 64, "persistent_key": "33" * 16,
                         "enrollments": {"hap": None, "attestation": None}}},
}


def _issuer():
    from entity import Issuer  # kormax, on the path via doorstation_rfid.kormax

    return Issuer.from_dict(ISSUER)


def test_written_file_is_read_by_unchanged_kormax(tmp_path):
    path = tmp_path / "homekey.json"
    repo = AtomicRepository(str(path))
    repo.set_reader_private_key(KEY)
    repo.set_reader_identifier(b"\x01" * 8)
    repo.upsert_issuers([_issuer()])

    loaded = Repository(str(path))
    assert loaded.get_reader_private_key() == KEY
    assert loaded.get_reader_identifier() == b"\x01" * 8
    assert loaded.get_all_issuers() == [_issuer()]


def test_old_file_survives_interrupted_write(tmp_path, monkeypatch):
    # Power failure/crash before the rename: the previous pairing must stay readable.
    path = tmp_path / "homekey.json"
    repo = AtomicRepository(str(path))
    repo.set_reader_private_key(KEY)
    before = path.read_text()

    def crash(*_):
        raise OSError("power failure")

    monkeypatch.setattr("doorstation_rfid.store.os.replace", crash)
    with pytest.raises(OSError):
        repo.upsert_issuers([_issuer()])

    assert path.read_text() == before
    assert Repository(str(path)).get_reader_private_key() == KEY
    assert [p.name for p in tmp_path.iterdir()] == ["homekey.json"]  # no temp leftovers


def test_file_is_private_from_the_start(tmp_path):
    path = tmp_path / "homekey.json"
    AtomicRepository(str(path)).set_reader_private_key(KEY)
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_content_is_synced_before_rename(tmp_path, monkeypatch):
    calls = []
    real_fsync = os.fsync
    monkeypatch.setattr("doorstation_rfid.store.os.fsync", lambda fd: (calls.append(fd), real_fsync(fd)))
    AtomicRepository(str(tmp_path / "homekey.json")).set_reader_private_key(KEY)
    assert len(calls) >= 2  # file and directory


def test_written_json_matches_kormax_format(tmp_path):
    path = tmp_path / "homekey.json"
    repo = AtomicRepository(str(path))
    repo.set_reader_private_key(KEY)
    data = json.loads(path.read_text())
    assert set(data) == {"reader_private_key", "reader_identifier", "issuers"}
    assert data["reader_private_key"] == KEY.hex()
