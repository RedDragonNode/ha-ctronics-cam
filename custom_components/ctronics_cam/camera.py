"""Kamera-Entities: Live-Stream (RTSP) und Schnappschuss, dazu die PTZ-Dienste."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback, async_get_current_platform

from .api import CtronicsError
from .const import (
    CONF_PTZ_STEP_MS,
    DEFAULT_PTZ_STEP_MS,
    LOGGER,
    MAX_PRESET,
    MAX_PTZ_SPEED,
    MIN_PTZ_SPEED,
    RTSP_MAIN_PATH,
    RTSP_SUB_PATH,
    SIGNAL_PTZ_MOVED,
)
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .entity import CtronicsEntity, command_error

PARALLEL_UPDATES = 1

PTZ_DIRECTIONS = ("up", "down", "left", "right")


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        [
            CtronicsCamera(runtime.coordinator, runtime, key="camera", path=RTSP_MAIN_PATH),
            CtronicsCamera(runtime.coordinator, runtime, key="sub_stream", path=RTSP_SUB_PATH),
        ]
    )

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "ptz_move",
        {
            vol.Required("direction"): vol.In(PTZ_DIRECTIONS),
            vol.Optional("speed"): vol.All(vol.Coerce(int), vol.Range(min=MIN_PTZ_SPEED, max=MAX_PTZ_SPEED)),
            vol.Optional("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=5)),
        },
        "async_ptz_move",
    )
    preset_schema = {vol.Required("preset"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_PRESET))}
    platform.async_register_entity_service("ptz_goto_preset", preset_schema, "async_goto_preset")
    platform.async_register_entity_service("ptz_save_preset", preset_schema, "async_save_preset")
    platform.async_register_entity_service("ptz_delete_preset", preset_schema, "async_delete_preset")


class CtronicsCamera(CtronicsEntity, Camera):
    """Live-Stream der Kamera. Der Hauptstream trägt den Gerätenamen, der Substream ist optional."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: CtronicsCoordinator,
        runtime: CtronicsRuntimeData,
        *,
        key: str,
        path: str,
    ) -> None:
        CtronicsEntity.__init__(self, coordinator, key)
        Camera.__init__(self)
        self._runtime = runtime
        self._path = path
        if key == "camera":
            self._attr_name = None
        else:
            self._attr_translation_key = key
            self._attr_entity_registry_enabled_default = False

    async def stream_source(self) -> str:
        return self.api.rtsp_url(self.coordinator.data.rtsp_port, self._path)

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        try:
            return await self.api.snapshot()
        except CtronicsError as err:
            LOGGER.debug("Schnappschuss nicht verfügbar: %s", err)
            return None

    def _moved(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_PTZ_MOVED.format(self.coordinator.config_entry.entry_id))

    async def async_ptz_move(self, direction: str, speed: int | None = None, duration: float | None = None) -> None:
        """Bewegt die Kamera kurz in eine Richtung."""
        if duration is None:
            duration = self.coordinator.config_entry.options.get(CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS) / 1000
        try:
            await self.api.ptz_move(direction, speed or self._runtime.ptz_speed, duration)
        except CtronicsError as err:
            raise command_error(err) from err
        self._moved()

    async def async_goto_preset(self, preset: int) -> None:
        """Fährt die Preset-Position `preset` an (1 bis 64)."""
        try:
            await self.api.goto_preset(preset)
        except CtronicsError as err:
            raise command_error(err) from err
        self._moved()

    async def async_save_preset(self, preset: int) -> None:
        """Speichert die aktuelle Position als `preset` (1 bis 64) und überschreibt eine vorhandene."""
        try:
            await self.api.save_preset(preset)
        except CtronicsError as err:
            raise command_error(err) from err

    async def async_delete_preset(self, preset: int) -> None:
        """Löscht die Preset-Position `preset` (1 bis 64)."""
        try:
            await self.api.delete_preset(preset)
        except CtronicsError as err:
            raise command_error(err) from err
