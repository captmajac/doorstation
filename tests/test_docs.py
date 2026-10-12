"""Documentation in English (main) and German: both complete, language switchers and links valid."""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# (English, German)
PAIRS = [
    ("README.md", "README.de.md"),
    ("docs/architecture.md", "docs/de/architektur.md"),
    ("docs/hardware.md", "docs/de/hardware.md"),
    ("docs/installation.md", "docs/de/installation.md"),
    ("docs/ip-symcon.md", "docs/de/ip-symcon.md"),
    ("docs/development.md", "docs/de/entwicklung.md"),
    ("docs/services/gpio.md", "docs/de/dienste/gpio.md"),
    ("docs/services/sip.md", "docs/de/dienste/sip.md"),
    ("docs/services/sound.md", "docs/de/dienste/sound.md"),
    ("docs/services/rfid.md", "docs/de/dienste/rfid.md"),
]
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def slug(heading: str) -> str:
    """GitHub anchor of a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _doc_files() -> list[Path]:
    """All published documents: README*.md, docs/*.md, docs/services/ and docs/de/."""
    files = sorted(ROOT.glob("README*.md")) + sorted((ROOT / "docs").glob("*.md"))
    for sub in ("services", "de"):
        files += sorted((ROOT / "docs" / sub).rglob("*.md"))
    return files


def _rel(src: str, dst: str) -> str:
    return os.path.relpath(ROOT / dst, (ROOT / src).parent)


def _anchors(md: Path) -> set[str]:
    text = FENCE.sub("", md.read_text(encoding="utf-8"))
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)}


def test_every_doc_has_its_counterpart():
    for en, de in PAIRS:
        assert (ROOT / en).is_file(), f"missing {en}"
        assert (ROOT / de).is_file(), f"missing {de}"
    listed = {p for pair in PAIRS for p in pair}
    extra = [str(p.relative_to(ROOT)) for p in _doc_files() if str(p.relative_to(ROOT)) not in listed]
    assert not extra, f"documents without a counterpart in PAIRS: {extra}"


@pytest.mark.parametrize("en, de", PAIRS)
def test_language_switcher_points_to_counterpart(en, de):
    en_first = (ROOT / en).read_text(encoding="utf-8").splitlines()[0]
    de_first = (ROOT / de).read_text(encoding="utf-8").splitlines()[0]
    assert en_first == f"**English** | [Deutsch]({_rel(en, de)})"
    assert de_first == f"[English]({_rel(de, en)}) | **Deutsch**"


@pytest.mark.parametrize("md", _doc_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_and_anchors_resolve(md):
    broken = []
    for link in LINK.findall(FENCE.sub("", md.read_text(encoding="utf-8"))):
        if re.match(r"[a-z]+:", link):
            continue
        path, _, anchor = link.partition("#")
        target = (md.parent / path).resolve() if path else md
        if not target.exists():
            broken.append(f"{link}: file missing")
        elif anchor and target.suffix == ".md" and anchor not in _anchors(target):
            broken.append(f"{link}: anchor missing")
    assert not broken, f"{md.relative_to(ROOT)}: {broken}"
