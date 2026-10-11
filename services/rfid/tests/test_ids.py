import hashlib

from doorstation_rfid.ids import card_id, homekey_id


def test_card_id_hex_upper():
    assert card_id(bytes.fromhex("b3c06fa5")) == "B3C06FA5"


def test_card_id_7_byte_airtag():
    assert card_id(bytes.fromhex("5f69d395551baf")) == "5F69D395551BAF"


def test_random_uid_dropped():
    assert card_id(bytes.fromhex("08993a17")) is None


def test_7_byte_starting_08_is_not_random():
    assert card_id(bytes.fromhex("08aabbccddeeff")) == "08AABBCCDDEEFF"


def test_homekey_id_16_chars_stable():
    pk = bytes.fromhex("04" + "ab" * 64)
    assert homekey_id(pk) == homekey_id(pk) == hashlib.sha256(pk).digest()[:8].hex().upper()
    assert len(homekey_id(pk)) == 16
