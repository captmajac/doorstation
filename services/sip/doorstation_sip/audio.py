"""doorstation-audio-init: find the USB sound card, set switches and levels, make echo cancel the default.

Runs as ExecStartPre of doorstation-baresip as user doorstation.
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
        raise ConfigError(f"{path}: unknown keys {', '.join(unknown)}")
    for key in ("card_match", "playback_control", "capture_control"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ConfigError(f"{path}: '{key}' missing")
    for key in ("playback_percent", "capture_percent"):
        v = data.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100:
            raise ConfigError(f"{path}: {key} must be an integer 0-100")
    agc = data.get("auto_gain_control")
    if agc is not None and not isinstance(agc, bool):
        raise ConfigError(f"{path}: auto_gain_control must be true, false or empty")
    mic_playback = data.get("mic_playback", False)
    if not isinstance(mic_playback, bool):  # bool("false") would be true: microphone to the speaker
        raise ConfigError(f"{path}: mic_playback must be true or false")
    ec = data.get("echo_cancel", {"enabled": True})
    ec_enabled = ec.get("enabled", True) if isinstance(ec, dict) else ec
    if not isinstance(ec_enabled, bool):
        raise ConfigError(f"{path}: echo_cancel.enabled must be true or false")
    return AudioConfig(data["card_match"], data["playback_control"], data["playback_percent"],
                       data["capture_control"], data["capture_percent"], agc, mic_playback, ec_enabled)


def find_card(proc_cards_text: str, match: str) -> int | None:
    """First card whose short or long name contains 'match' (case-insensitive)."""
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
    """Waits up to 'timeout' seconds for a matching card (USB may appear late at boot)."""
    deadline = clock() + timeout
    while True:
        card = find_card(read_cards(), match)
        if card is not None or clock() >= deadline:
            return card
        sleep(0.5)


def plan_commands(cfg: AudioConfig, card: int, controls: set[str]) -> list[list[str]]:
    """amixer commands for the switches; only for controls the stick has."""
    c = str(card)
    cmds: list[list[str]] = []
    if cfg.auto_gain_control is not None and "Auto Gain Control" in controls:
        cmds.append(["amixer", "-c", c, "sset", "Auto Gain Control", "on" if cfg.auto_gain_control else "off"])
    if cfg.capture_control in controls:
        cmds.append(["amixer", "-c", c, "sset", cfg.capture_control, "playback",
                     "unmute" if cfg.mic_playback else "mute"])
    return cmds


def nodes_for_card(dump: list, card: int) -> tuple[int | None, int | None]:
    """IDs of the card's Audio/Sink and Audio/Source nodes from pw-dump."""
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
    parser.add_argument("--wait", type=float, default=15.0, help="seconds to wait for PipeWire")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_audio_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    card = wait_for_card(lambda: Path("/proc/asound/cards").read_text(), cfg.card_match, args.wait)
    if card is None:
        log.error("no sound card matches card_match '%s'", cfg.card_match)
        return 1
    out = _run(["amixer", "-c", str(card), "scontrols"]).stdout
    controls = set(re.findall(r"'([^']+)'", out))
    for name in (cfg.playback_control, cfg.capture_control):
        if name not in controls:
            log.warning("control '%s' does not exist on card %d (available: %s)", name, card, ", ".join(sorted(controls)))
    for cmd in plan_commands(cfg, card, controls):
        if _run(cmd).returncode != 0:
            log.warning("failed: %s", " ".join(cmd))

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
        log.error("PipeWire does not show card %d - is PipeWire running for this user?", card)
        return 1
    _run(["wpctl", "set-volume", str(sink), f"{cfg.playback_percent / 100:.2f}"])
    _run(["wpctl", "set-volume", str(source), f"{cfg.capture_percent / 100:.2f}"])
    if cfg.echo_cancel and ec_sink and ec_source:
        _run(["wpctl", "set-default", str(ec_sink)])
        _run(["wpctl", "set-default", str(ec_source)])
    else:
        if cfg.echo_cancel:
            log.warning("echo cancel nodes missing - using the card directly")
        _run(["wpctl", "set-default", str(sink)])
        _run(["wpctl", "set-default", str(source)])
    log.info("audio ready: card %d, levels %d %%/%d %%, echo cancel %s",
             card, cfg.playback_percent, cfg.capture_percent, "on" if cfg.echo_cancel and ec_sink else "off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
