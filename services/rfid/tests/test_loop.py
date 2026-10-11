from types import SimpleNamespace

from doorstation_rfid.ids import homekey_id
from doorstation_rfid.kormax import ProtocolError
from doorstation_rfid.loop import ReaderLoop


class FakeTarget:
    def __init__(self, uid_hex, isodep):
        self.identifier = bytes.fromhex(uid_hex)
        self.isodep = isodep


class FakeClf:
    def __init__(self, results):
        self.results = list(results)
        self.path = "tty:AMA0:pn532"
        self.device = object()
        self.opened = 0
        self.closed = 0
        self.open_fails = 0
        self.sense_kwargs = []

    def sense(self, *targets, **kw):
        self.sense_kwargs.append(kw)
        r = self.results.pop(0) if self.results else None
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        self.closed += 1

    def open(self, path):
        if self.open_fails:
            self.open_fails -= 1
            raise OSError("kein Leser")
        self.opened += 1
        self.device = object()  # wie nfcpy nach erfolgreichem Öffnen


class FakeRepo:
    def __init__(self, paired=True):
        self.paired = paired
        self.upserted = []

    def get_reader_private_key(self):
        return b"\x01" * 32 if self.paired else b"\x00" * 32  # wie kormax ohne Paarung

    def get_reader_group_identifier(self):
        return b"\x02" * 8

    def get_reader_identifier(self):
        return b"\x03" * 8

    def get_all_issuers(self):
        return []

    def upsert_issuers(self, issuers):
        self.upserted.append(issuers)


class FakeReporter:
    def __init__(self):
        self.reports = []

    def report(self, kind, id_):
        self.reports.append((kind, id_))
        return True


PK = bytes.fromhex("04" + "ab" * 64)


def make(results, paired=True, homekey=None):
    clf = FakeClf(results)
    service = SimpleNamespace(repository=FakeRepo(paired), express=True, flow="FAST", throttle_polling=0.1)
    rep = FakeReporter()
    health = []
    sleeps = []

    def homekey_reader(tag, **kw):
        if homekey is None:
            raise ProtocolError("Could not select ISO7816Application.HOME_KEY 0x6a 0x82")
        return homekey

    loop = ReaderLoop(clf, service, rep, on_health=health.append, sleep=sleeps.append,
                      homekey_reader=homekey_reader, activate=lambda clf, r: r,
                      is_isodep=lambda t: t.isodep, wrap_iso7816=lambda t: t,
                      ecp_frame=lambda repo, express: b"ECP")
    return loop, clf, rep, health, sleeps


def test_card_reported():
    loop, clf, rep, health, sleeps = make([FakeTarget("b3c06fa5", False)])
    loop.step()
    assert rep.reports == [("card", "B3C06FA5")]


def test_random_isodep_dropped():
    loop, clf, rep, health, sleeps = make([FakeTarget("08993a17", True)])
    loop.step()
    assert rep.reports == []


def test_airtag_reported_as_card():
    loop, clf, rep, health, sleeps = make([FakeTarget("5f69d395551baf", True)])
    loop.step()
    assert rep.reports == [("card", "5F69D395551BAF")]


def test_homekey_reported():
    endpoint = SimpleNamespace(public_key=PK)
    loop, clf, rep, health, sleeps = make([FakeTarget("08993a17", True)], homekey=("FAST", ["iss"], endpoint))
    loop.step()
    assert rep.reports == [("homekey", homekey_id(PK))]
    assert clf.sense_kwargs[-1] == {"broadcast": b"ECP"}


def test_exception_reopens_reader():
    loop, clf, rep, health, sleeps = make([OSError(5, "Input/output error"), FakeTarget("b3c06fa5", False)])
    loop.step()
    assert (clf.closed, clf.opened, health) == (1, 1, [])  # ein Einzelfehler meldet kein degraded
    loop.step()
    assert rep.reports == [("card", "B3C06FA5")] and health[-1] is True


def test_reopen_failure_sleeps():
    loop, clf, rep, health, sleeps = make([OSError("x")])
    clf.open_fails = 1
    loop.step()
    assert 1 in sleeps


def test_unpaired_reads_cards_without_broadcast():
    loop, clf, rep, health, sleeps = make([FakeTarget("b3c06fa5", False)], paired=False)
    loop.step()
    assert clf.sense_kwargs[-1] == {}
    assert rep.reports == [("card", "B3C06FA5")]


def test_unpaired_isodep_treated_as_card():
    loop, clf, rep, health, sleeps = make([FakeTarget("5f69d395551baf", True)], paired=False)
    loop.step()
    assert rep.reports == [("card", "5F69D395551BAF")]


def test_nothing_in_field_throttles():
    loop, clf, rep, health, sleeps = make([None])
    loop.step()
    assert sleeps == [0.1] and health[-1] is True


def test_open_without_device_counts_as_failure():
    loop, clf, rep, health, sleeps = make([OSError("weg")])

    def open_no_device(path):
        clf.opened += 1
        clf.device = None  # so meldet nfcpy einen nicht gefundenen Leser

    clf.open = open_no_device
    loop.step()
    assert 1 in sleeps and health[-1] is False


def test_zero_key_means_unpaired():
    loop, clf, rep, health, sleeps = make([FakeTarget("b3c06fa5", False)], paired=False)
    loop.service.repository.get_reader_private_key = lambda: b"\x00" * 32  # kormax-Vorgabe ohne Paarung
    assert loop.paired is False
    loop.step()
    assert clf.sense_kwargs[-1] == {}


def test_single_transient_error_does_not_degrade():
    loop, clf, rep, health, sleeps = make([OSError("x"), None])
    loop.step()
    loop.step()
    assert False not in health


def test_three_consecutive_errors_degrade():
    loop, clf, rep, health, sleeps = make([OSError("a"), OSError("b"), OSError("c"), None])
    for _ in range(3):
        loop.step()
    assert health[-1] is False
    loop.step()
    assert health[-1] is True


def test_no_broadcast_right_after_homekey():
    endpoint = SimpleNamespace(public_key=PK)
    loop, clf, rep, health, sleeps = make([FakeTarget("08993a17", True), None, None],
                                          homekey=("FAST", [], endpoint))
    t = [1000.0]
    loop._clock = lambda: t[0]
    loop.step()                      # Home Key gelesen
    t[0] += 1
    loop.step()                      # innerhalb der Sperre: ohne Express-Broadcast
    assert clf.sense_kwargs[-1] == {}
    t[0] += 3
    loop.step()                      # danach wieder mit Broadcast
    assert clf.sense_kwargs[-1] == {"broadcast": b"ECP"}


def test_step_calls_on_tick():
    loop, clf, rep, health, sleeps = make([None])
    ticks = []
    loop._on_tick = lambda: ticks.append(1)
    loop.step()
    assert ticks == [1]
