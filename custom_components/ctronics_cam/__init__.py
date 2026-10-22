"""Ctronics 4K Cam: lokale Integration für Ctronics-Schwenk-/Neigekameras."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CtronicsApi
from .const import LOGGER, PLATFORMS
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .events import CtronicsEvents


async def async_setup_entry(hass: HomeAssistant, entry: CtronicsConfigEntry) -> bool:
    """Richtet eine Kamera ein."""
    api = CtronicsApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = CtronicsCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    runtime = CtronicsRuntimeData(api=api, coordinator=coordinator)
    if coordinator.data.onvif_enabled:
        runtime.events = CtronicsEvents(hass, entry, api, coordinator.data.onvif_port)
    else:
        LOGGER.warning("ONVIF ist an der Kamera %s ausgeschaltet, Bewegungsmeldungen sind nicht verfügbar", entry.title)
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if runtime.events:
        await runtime.events.async_start()
        entry.async_on_unload(runtime.events.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CtronicsConfigEntry) -> bool:
    """Entlädt eine Kamera."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
