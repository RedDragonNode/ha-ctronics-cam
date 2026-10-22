"""Namen der Preset-Positionen, die der User in den Optionen einträgt."""

from __future__ import annotations

import re

from .const import MAX_PRESET

_PRESET_LINE = re.compile(r"^\s*(\d+)\s*[:=]\s*(.+?)\s*$")


def parse_presets(text: str) -> dict[int, str]:
    """Liest Zeilen wie `1: Schaukel` in eine Zuordnung Nummer zu Name.

    Wirft ValueError bei Zeilen im falschen Format oder Nummern außerhalb von 1 bis MAX_PRESET.
    """
    presets: dict[int, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _PRESET_LINE.match(line)
        if not match or not 1 <= int(match.group(1)) <= MAX_PRESET:
            raise ValueError(line)
        presets[int(match.group(1))] = match.group(2)
    return presets
