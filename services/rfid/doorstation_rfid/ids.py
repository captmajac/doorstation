"""IDs, die an IP-Symcon gemeldet werden."""

import hashlib


def card_id(uid: bytes) -> str | None:
    """UID als Hex (groß). None bei Zufalls-UID nach ISO/IEC 14443-3 (4 Byte, erstes Byte 0x08)."""
    if len(uid) == 4 and uid[0] == 0x08:
        return None
    return uid.hex().upper()


def homekey_id(public_key: bytes) -> str:
    """Stabile, nicht geheime Kennung eines Home Keys: erste 8 Byte SHA-256 über den Public Key."""
    return hashlib.sha256(public_key).digest()[:8].hex().upper()
