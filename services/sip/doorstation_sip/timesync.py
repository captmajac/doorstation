"""doorstation-wait-timesync: wait (bounded) until the system clock is synchronized.

Runs as the first ExecStartPre of doorstation-baresip. The Pi has no real-time clock: after a
power failure it boots with the last saved time and jumps forward once NTP answers. baresip's
MQTT connection breaks on such a jump and never reconnects - so start it after the jump. Without
internet there is no sync: give up after the timeout and start anyway (the bell must work).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

log = logging.getLogger("doorstation_timesync")

MARKER = Path("/run/systemd/timesync/synchronized")  # created by systemd-timesyncd after a sync


def wait_for_time_sync(marker: Path, timeout: float, clock=time.monotonic, sleep=time.sleep) -> bool:
    """True as soon as the marker exists, False after 'timeout' seconds."""
    deadline = clock() + timeout
    while not Path(marker).exists():
        if clock() >= deadline:
            return False
        sleep(1)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-wait-timesync")
    parser.add_argument("--marker", type=Path, default=MARKER)
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait at most")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if wait_for_time_sync(args.marker, args.timeout):
        log.info("clock synchronized")
    else:
        log.warning("clock not synchronized after %.0f s - starting anyway", args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
