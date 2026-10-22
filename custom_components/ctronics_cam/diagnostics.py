"""Diagnose-Download mit geschwärzten persönlichen Daten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant

from .coordinator import CtronicsConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
    "macaddress",
    "ip",
    "netmask",
    "gateway",
    "fdnsip",
    "sdnsip",
    "unique_id",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: CtronicsConfigEntry) -> dict[str, Any]:
    runtime = entry.runtime_data
    state = runtime.coordinator.data
    events = runtime.events
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "unique_id": "**REDACTED**",
        },
        "camera": async_redact_data(dict(state.raw), TO_REDACT),
        "events": {
            "enabled": events is not None,
            "subscribed": events.subscribed if events else None,
            "motion": events.motion if events else None,
        },
        "ptz_speed": runtime.ptz_speed,
    }
