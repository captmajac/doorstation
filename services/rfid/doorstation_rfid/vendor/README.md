# Vendor: kormax/apple-home-key-reader

- Quelle: https://github.com/kormax/apple-home-key-reader
- Commit: `9675407` („fix(tlv): incorrect unpacking offset in constructed tags“), übernommen am 2026-10-11
- Lizenz: Apache-2.0 (siehe `apple_home_key_reader/LICENSE`)
- Übernommen: `accessory.py entity.py homekey.py repository.py service.py util/ LICENSE README.md` – **unverändert**. Nicht übernommen: `main.py`, `tests/`, `assets/`, `configuration.json`.
- Anpassungen erfolgen ausschließlich im Dienst `doorstation_rfid` (Unterklassen, eigene Leseschleife), nicht in diesen Dateien.
- Geprüft im Spike `docs/spikes/2026-10-11-rfid-homekey-spike.md`.
