"""Gerätename aus Präfix und Name der Kamera."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .const import CONF_PREFIX


def device_name(title: str, prefix: str | None) -> str:
    """Name des Geräts: Präfix und Name der Kamera, getrennt durch ein Leerzeichen."""
    return f"{(prefix or '').strip()} {title}".strip()


def entry_device_name(entry: ConfigEntry) -> str:
    """Gerätename eines Eintrags, wie er in Home Assistant erscheint."""
    return device_name(entry.title, entry.options.get(CONF_PREFIX))
