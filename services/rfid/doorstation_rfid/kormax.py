"""Integration of kormax/apple-home-key-reader (unchanged in vendor/, see vendor/README.md).

kormax uses top-level imports (``from service import Service``), so the vendor
directory goes first in sys.path.
"""

import sys
from pathlib import Path

_VENDOR = Path(__file__).parent / "vendor" / "apple_home_key_reader"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from pyhap.accessory_driver import AccessoryDriver  # noqa: E402

from accessory import Lock  # noqa: E402
from homekey import ProtocolError, read_homekey  # noqa: E402
from repository import Repository  # noqa: E402
from service import Service  # noqa: E402
from util.bfclf import BroadcastFrameContactlessFrontend, ISODEPTag, RemoteTarget, activate  # noqa: E402
from util.digital_key import DigitalKeyFlow, DigitalKeyTransactionType  # noqa: E402
from util.ecp import ECP  # noqa: E402
from util.iso7816 import ISO7816Tag  # noqa: E402

__all__ = [
    "AccessoryDriver", "Lock", "ProtocolError", "read_homekey", "Repository", "Service",
    "BroadcastFrameContactlessFrontend", "ISODEPTag", "RemoteTarget", "activate",
    "DigitalKeyFlow", "DigitalKeyTransactionType", "ECP", "ISO7816Tag",
]
