"""Ctronics 4K Cam: lokale Integration für Ctronics-Schwenk-/Neigekameras."""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .api import CtronicsApi
from .const import DISCOVERY_INTERVAL, DOMAIN, LOGGER, PLATFORMS
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .discovery import async_discover_cameras
from .events import CtronicsEvents

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Sucht nach dem Start und danach regelmäßig nach Kameras im Heimnetz."""

    async def discover(*_: object) -> None:
        await async_discover_cameras(hass)

    @callback
    def stop_discovery(_event: Event) -> None:
        cancel_timer()

    async_at_started(hass, discover)
    cancel_timer = async_track_time_interval(hass, discover, DISCOVERY_INTERVAL, name="Ctronics 4K Cam: Kameras suchen")
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_discovery)
    return True


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
