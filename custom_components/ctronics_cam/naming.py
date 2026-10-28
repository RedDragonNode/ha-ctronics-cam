"""Gerätename mit Präfix und das Umbenennen der Entity-IDs dazu."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import CONF_PREFIX, DOMAIN, LOGGER


def device_name(title: str, prefix: str | None) -> str:
    """Name des Geräts: Präfix und Name der Kamera, getrennt durch ein Leerzeichen."""
    return f"{(prefix or '').strip()} {title}".strip()


def entry_device_name(entry: ConfigEntry) -> str:
    """Gerätename eines Eintrags, wie er in Home Assistant erscheint."""
    return device_name(entry.title, entry.options.get(CONF_PREFIX))


def rename_entity_ids(hass: HomeAssistant, entry: ConfigEntry, new_name: str) -> int:
    """Benennt die Entity-IDs des Eintrags von `<bisheriger_name>_…` in `<neuer_name>_…` um.

    Home Assistant legt die ID nur beim ersten Anlegen aus dem Gerätenamen an. Der bisherige Name ist
    die ID der Haupt-Kamera ohne Domain. Es werden nur IDs angefasst, die damit beginnen, und keine,
    deren neue ID schon vergeben ist. Automationen und Dashboards, die eine alte ID nennen, werden
    nicht angepasst.
    """
    registry = er.async_get(hass)
    main_id = registry.async_get_entity_id("camera", DOMAIN, f"{entry.unique_id}_camera")
    old_slug, new_slug = (main_id or "").partition(".")[2], slugify(new_name)
    if not old_slug or not new_slug or old_slug == new_slug:
        return 0

    renamed = 0
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        domain, _, object_id = entity.entity_id.partition(".")
        if object_id != old_slug and not object_id.startswith(f"{old_slug}_"):
            continue
        new_entity_id = f"{domain}.{new_slug}{object_id[len(old_slug) :]}"
        if registry.async_is_registered(new_entity_id) or hass.states.get(new_entity_id):
            LOGGER.warning("%s bleibt unverändert, %s ist schon vergeben", entity.entity_id, new_entity_id)
            continue
        registry.async_update_entity(entity.entity_id, new_entity_id=new_entity_id)
        renamed += 1
    return renamed
