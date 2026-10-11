"""Eigene, fehlertolerante Leseschleife (statt kormax Service.run/_read_homekey).

In kormax' Schleife beendet jede Ausnahme den Lesevorgang mit 5 s Pause. Hier wird jede
Ausnahme abgefangen und der Leser sofort neu geöffnet; Doppelmeldungen verhindert der
Reporter über seine Wiederholsperre statt „warten, bis die Karte weg ist“.
"""

import logging
import threading
import time
from collections.abc import Callable

from .ids import card_id, homekey_id
from .kormax import (ECP, ISO7816Tag, ISODEPTag, DigitalKeyTransactionType, ProtocolError, RemoteTarget,
                     activate, read_homekey)

log = logging.getLogger(__name__)

AFTER_READ_S = 0.5
REOPEN_FAIL_S = 1.0
DEGRADED_AFTER = 3        # aufeinanderfolgende Fehler, bevor degraded gemeldet wird


def _ecp_frame(repository, express: bool) -> bytes:
    return ECP.home(identifier=repository.get_reader_group_identifier(), flag_2=express).pack()


class ReaderLoop:
    def __init__(self, clf, service, reporter, *, on_health: Callable[[bool], None],
                 sleep: Callable[[float], None] = time.sleep,
                 homekey_reader=read_homekey, activate=activate,
                 is_isodep: Callable[[object], bool] = lambda t: isinstance(t, ISODEPTag),
                 wrap_iso7816=ISO7816Tag, ecp_frame=_ecp_frame,
                 clock: Callable[[], float] = time.monotonic, quiet_after_homekey_s: float = 3.0,
                 on_tick: Callable[[], None] = lambda: None) -> None:
        self.clf = clf
        self.service = service
        self.reporter = reporter
        self._on_health = on_health
        self._sleep = sleep
        self._homekey_reader = homekey_reader
        self._activate = activate
        self._is_isodep = is_isodep
        self._wrap = wrap_iso7816
        self._ecp_frame = ecp_frame
        self._clock = clock
        self._quiet_s = quiet_after_homekey_s
        self._quiet_until = 0.0
        self._failures = 0
        self._on_tick = on_tick

    @property
    def paired(self) -> bool:
        key = self.service.repository.get_reader_private_key()
        # kormax nutzt ohne Paarung (und nach dem Entfernen aus Apple Home) 32 Null-Bytes.
        return bool(key) and any(key)

    def step(self) -> None:
        self._on_tick()  # Lebenszeichen aus der Leseschleife (hängt sie, bleibt es aus)
        try:
            self._read_once()
        except Exception as exc:  # Leser- oder Funkfehler: nie die Schleife beenden
            self._failures += 1
            log.warning("Lesefehler %r – Leser wird neu geöffnet", exc)
            reopened = self._reopen()
            # Einzelne Funkfehler des PN532 nach dem Lesen sind normal – erst Dauerfehler melden.
            if not reopened or self._failures >= DEGRADED_AFTER:
                self._on_health(False)
            return
        self._failures = 0
        self._on_health(True)

    def _read_once(self) -> None:
        repo = self.service.repository
        paired = self.paired
        if paired and self._clock() >= self._quiet_until:
            remote = self.clf.sense(RemoteTarget("106A"), broadcast=self._ecp_frame(repo, self.service.express))
        else:
            remote = self.clf.sense(RemoteTarget("106A"))
        if remote is None:
            self._sleep(self.service.throttle_polling)
            return
        target = self._activate(self.clf, remote)
        if target is None:
            return
        if not self._is_isodep(target):
            self._report_card(target)
        elif paired:
            self._read_isodep(target)
        else:
            self._report_card(target)
        self._sleep(AFTER_READ_S)

    def _read_isodep(self, target) -> None:
        repo = self.service.repository
        try:
            _flow, new_issuers, endpoint = self._homekey_reader(
                self._wrap(target),
                issuers=repo.get_all_issuers(),
                preferred_versions=[b"\x02\x00"],
                flow=self.service.flow,
                transaction_code=DigitalKeyTransactionType.UNLOCK,
                reader_identifier=repo.get_reader_group_identifier() + repo.get_reader_identifier(),
                reader_private_key=repo.get_reader_private_key(),
                key_size=16,
            )
        except ProtocolError as exc:
            # Kein Home Key: AirTag (feste UID) melden, Apple Pay/Bankkarte (Zufalls-UID) verwerfen.
            log.info("ISO-DEP ohne Home Key (%s)", exc)
            self._report_card(target)
            return
        if new_issuers:
            repo.upsert_issuers(new_issuers)
        if endpoint is not None:
            self.reporter.report("homekey", homekey_id(endpoint.public_key))
            # Liegt das iPhone weiter am Leser, nicht jede Sekunde neu per Express wecken.
            self._quiet_until = self._clock() + self._quiet_s

    def _report_card(self, target) -> None:
        cid = card_id(bytes(target.identifier))
        if cid is None:
            log.info("Zufalls-UID verworfen")
            return
        self.reporter.report("card", cid)

    def _reopen(self) -> bool:
        try:
            self.clf.close()
        except Exception:
            pass
        self.clf.device = None
        try:
            self._open()
            return True
        except Exception as exc:
            log.warning("Leser kann nicht geöffnet werden: %r", exc)
            self._sleep(REOPEN_FAIL_S)
            return False

    def _open(self) -> None:
        self.clf.open(self.clf.path)
        if getattr(self.clf, "device", None) is None:  # nfcpy: Leser nicht gefunden
            raise OSError(f"kein Leser an {self.clf.path}")

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self._open()
                break
            except Exception as exc:
                log.warning("Leser nicht gefunden (%r) – neuer Versuch", exc)
                self._on_health(False)
                self._sleep(REOPEN_FAIL_S)
        while not stop.is_set():
            self.step()
