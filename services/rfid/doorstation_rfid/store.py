"""HomeKit-Paarung (homekey.json) atomar speichern.

kormax' Repository schreibt bei jedem neuen Lesen eines Home Keys mit open(path, "w") – ein
Stromausfall in diesem Moment hinterlässt eine leere oder halbe Datei. Beim nächsten Start
gälte der Leser dann als ungepaart: neu koppeln, alle Home-Key-IDs ändern sich. Hier wird
in eine Temp-Datei im selben Ordner geschrieben, synchronisiert und erst dann ersetzt.
Format wie kormax (vendor/…/repository.py, unverändert).
"""

import json
import os
import tempfile

from .kormax import Repository


class AtomicRepository(Repository):
    def _save_state_to_file(self):
        with self._state_lock:
            data = {
                "reader_private_key": self._reader_private_key.hex(),
                "reader_identifier": self._reader_identifier.hex(),
                "issuers": {issuer.id.hex(): issuer.to_dict() for issuer in self._issuers},
            }
            _write_atomic(self.storage_file_path, json.dumps(data, indent=2))


def _write_atomic(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".homekey-", suffix=".tmp")  # Rechte 600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)  # Umbenennen dauerhaft machen
    finally:
        os.close(dir_fd)
