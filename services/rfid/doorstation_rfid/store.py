"""Save the HomeKit pairing (homekey.json) atomically.

kormax' Repository writes with open(path, "w") on every new Home Key read - a power
failure at that moment leaves an empty or partial file. On the next start the reader
would count as unpaired: pair again, all Home Key IDs change. Here we write to a temp
file in the same directory, sync it and only then replace the original.
Same format as kormax (vendor/.../repository.py, unchanged).
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
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".homekey-", suffix=".tmp")  # mode 600
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
        os.fsync(dir_fd)  # make the rename durable
    finally:
        os.close(dir_fd)
