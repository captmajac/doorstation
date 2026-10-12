"""Published code, scripts and examples are written in English.

German belongs only in README.de.md and docs/de/ (and internal documents that are not published).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

AREAS = {
    "common": ["common"],
    "services/gpio": ["services/gpio"],
    "services/sip": ["services/sip"],
    "services/sound": ["services/sound"],
    "services/rfid": ["services/rfid"],
    "tests": ["tests"],
    "install.sh": ["install.sh", "pytest.ini", ".gitignore"],
    "scripts": ["scripts"],
    "deploy": ["deploy"],
    "config-examples": ["config-examples"],
}

SKIP_PARTS = {"vendor", "__pycache__", "build", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".sh", ".toml", ".ini", ".yaml", ".service", ".template", ".conf", ".txt", ""}
GERMAN = re.compile(
    r"[äöüÄÖÜß]|\b(nicht|und|oder|wird|werden|ungültig|fehlt|muss|keine?|bei|für|über|beim|nach|fehler|konfiguration|das|ist|auf|wenn|dann|nur|auch|siehe|laut|kaputt)\b|\bz\.\s?B\.",
    re.IGNORECASE,
)


def _files(paths: list[str]):
    for rel in paths:
        p = ROOT / rel
        candidates = [p] if p.is_file() else sorted(p.rglob("*"))
        for f in candidates:
            if (f.is_file() and f.suffix in TEXT_SUFFIXES and not SKIP_PARTS & set(f.parts)
                    and not f.name.endswith(".egg-info") and f != Path(__file__).resolve()):
                yield f


def _german_lines(area: str) -> list[str]:
    hits = []
    for f in _files(AREAS[area]):
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if GERMAN.search(line):
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    return hits


@pytest.mark.parametrize("area", list(AREAS))
def test_no_german_in_published_code(area):
    hits = _german_lines(area)
    assert not hits, f"{len(hits)} German lines in {area}:\n" + "\n".join(hits)
