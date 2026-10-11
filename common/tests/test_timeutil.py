from datetime import datetime, timezone, timedelta

from doorstation_common.timeutil import now_iso


def test_now_iso_format_with_offset_and_millis():
    t = datetime(2026, 10, 7, 18, 3, 12, 481000, tzinfo=timezone(timedelta(hours=2)))
    assert now_iso(t) == "2026-10-07T18:03:12.481+02:00"


def test_now_iso_default_is_local_aware():
    s = now_iso()
    assert len(s) == 29 and s[19] == "." and s[23] in "+-"
