"""IDs reported to the home automation."""

import hashlib


def card_id(uid: bytes) -> str | None:
    """UID as hex (upper case). None for a random UID per ISO/IEC 14443-3 (4 bytes, first byte 0x08)."""
    if len(uid) == 4 and uid[0] == 0x08:
        return None
    return uid.hex().upper()


def homekey_id(public_key: bytes) -> str:
    """Stable, non-secret identifier of a Home Key: first 8 bytes of SHA-256 over the public key."""
    return hashlib.sha256(public_key).digest()[:8].hex().upper()
