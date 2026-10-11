"""doorstation-audio-init: USB-Soundkarte finden, Schalter und Pegel setzen, Echo-Cancel als Standard.

Läuft als ExecStartPre von doorstation-baresip unter dem Benutzer doorstation.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from doorstation_common.config import ConfigError, load_yaml

log = logging.getLogger("doorstation_audio")

_CARD_LINE = re.compile(r"^\s*(\d+)\s+\[([^\]]*)\]:\s*(.*)$")


@dataclass(frozen=True)
class AudioConfig:
    card_match: str
    playback_control: str
    playback_percent: int
    capture_control: str
    capture_percent: int
    auto_gain_control: bool | None
    mic_playback: bool
    echo_cancel: bool = True


def load_audio_config(path: Path) -> AudioConfig:
    data = load_yaml(path)
    allowed = {"card_match", "playback_control", "playback_percent", "capture_control",
               "capture_percent", "auto_gain_control", "mic_playback", "echo_cancel"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{path}: unbekannte Schlüssel {', '.join(unknown)}")
    for key in ("card_match", "playback_control", "capture_control"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ConfigError(f"{path}: '{key}' fehlt")
    for key in ("playback_percent", "capture_percent"):
        v = data.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
            raise ConfigError(f"{path}: {key} muss eine ganze Zahl 0–100 sein")
    agc = data.get("auto_gain_control")
    if agc is not None and not isinstance(agc, bool):
        raise ConfigError(f"{path}: auto_gain_control muss true, false oder leer sein")
    mic_playback = data.get("mic_playback", False)
    if not isinstance(mic_playback, bool):  # bool("false") wäre wahr: Mikrofon auf den Lautsprecher
        raise ConfigError(f"{path}: mic_playback muss true oder false sein")
    ec = data.get("echo_cancel", {"enabled": True})
    ec_enabled = ec.get("enabled", True) if isinstance(ec, dict) else ec
    if not isinstance(ec_enabled, bool):
        raise ConfigError(f"{path}: echo_cancel.enabled muss true oder false sein")
    return AudioConfig(data["card_match"], data["playback_control"], data["playback_percent"],
                       data["capture_control"], data["capture_percent"], agc, mic_playback, ec_enabled)


def find_card(proc_cards_text: str, match: str) -> int | None:
    """Erste Karte, deren Kurz- oder Langname 'match' enthält (ohne Groß/Klein)."""
    lines = proc_cards_text.splitlines()
    needle = match.lower()
    for i, line in enumerate(lines):
        m = _CARD_LINE.match(line)
        if not m:
            continue
        long_name = lines[i + 1].strip() if i + 1 < len(lines) else ""
        text = f"{m.group(2)} {m.group(3)} {long_name}".lower()
        if needle in text:
            return int(m.group(1))
    return None


def wait_for_card(read_cards, match: str, timeout: float,
                  clock=time.monotonic, sleep=time.sleep) -> int | None:
    """Wartet bis 'timeout' Sekunden, bis eine passende Karte erscheint (USB beim Booten spät)."""
    deadline = clock() + timeout
    while True:
        card = find_card(read_cards(), match)
        if card is not None or clock() >= deadline:
            return card
        sleep(0.5)


def plan_commands(cfg: AudioConfig, card: int, controls: set[str]) -> list[list[str]]:
    """amixer-Befehle für die Schalter; nur für Regler, die der Stick hat."""
    c = str(card)
    cmds: list[list[str]] = []
    if cfg.auto_gain_control is not None and "Auto Gain Control" in controls:
        cmds.append(["amixer", "-c", c, "sset", "Auto Gain Control", "on" if cfg.auto_gain_control else "off"])
    if cfg.capture_control in controls:
        cmds.append(["amixer", "-c", c, "sset", cfg.capture_control, "playback",
                     "unmute" if cfg.mic_playback else "mute"])
    return cmds


def nodes_for_card(dump: list, card: int) -> tuple[int | None, int | None]:
    """IDs des Audio/Sink- und Audio/Source-Knotens der ALSA-Karte aus pw-dump."""
    sink = source = None
    for obj in dump:
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("alsa.card") != card:
            continue
        if props.get("media.class") == "Audio/Sink" and sink is None:
            sink = obj["id"]
        elif props.get("media.class") == "Audio/Source" and source is None:
            source = obj["id"]
    return sink, source


def _node_by_name(dump: list, name: str) -> int | None:
    for obj in dump:
        if ((obj.get("info") or {}).get("props") or {}).get("node.name") == name:
            return obj["id"]
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    log.info("%s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _pw_dump() -> list:
    res = subprocess.run(["pw-dump"], capture_output=True, text=True, check=False)
    try:
        return json.loads(res.stdout) if res.returncode == 0 else []
    except ValueError:
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doorstation-audio-init")
    parser.add_argument("--config", type=Path, default=Path("/etc/doorstation/audio.yaml"))
    parser.add_argument("--wait", type=float, default=15.0, help="Sekunden auf PipeWire warten")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_audio_config(args.config)
    except ConfigError as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2

    card = wait_for_card(lambda: Path("/proc/asound/cards").read_text(), cfg.card_match, args.wait)
    if card is None:
        log.error("keine Soundkarte passt zu card_match '%s'", cfg.card_match)
        return 1
    out = _run(["amixer", "-c", str(card), "scontrols"]).stdout
    controls = set(re.findall(r"'([^']+)'", out))
    for name in (cfg.playback_control, cfg.capture_control):
        if name not in controls:
            log.warning("Regler '%s' gibt es auf Karte %d nicht (vorhanden: %s)", name, card, ", ".join(sorted(controls)))
    for cmd in plan_commands(cfg, card, controls):
        if _run(cmd).returncode != 0:
            log.warning("fehlgeschlagen: %s", " ".join(cmd))

    deadline = time.monotonic() + args.wait
    while True:
        dump = _pw_dump()
        sink, source = nodes_for_card(dump, card)
        ec_sink, ec_source = _node_by_name(dump, "ec_sink"), _node_by_name(dump, "ec_source")
        ready = sink is not None and source is not None and (not cfg.echo_cancel or (ec_sink and ec_source))
        if ready or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    if sink is None or source is None:
        log.error("PipeWire zeigt die Karte %d nicht – läuft PipeWire für diesen Benutzer?", card)
        return 1
    _run(["wpctl", "set-volume", str(sink), f"{cfg.playback_percent / 100:.2f}"])
    _run(["wpctl", "set-volume", str(source), f"{cfg.capture_percent / 100:.2f}"])
    if cfg.echo_cancel and ec_sink and ec_source:
        _run(["wpctl", "set-default", str(ec_sink)])
        _run(["wpctl", "set-default", str(ec_source)])
    else:
        if cfg.echo_cancel:
            log.warning("Echo-Cancel-Knoten fehlen – nutze die Karte direkt")
        _run(["wpctl", "set-default", str(sink)])
        _run(["wpctl", "set-default", str(source)])
    log.info("Audio bereit: Karte %d, Pegel %d %%/%d %%, Echounterdrückung %s",
             card, cfg.playback_percent, cfg.capture_percent, "an" if cfg.echo_cancel and ec_sink else "aus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
