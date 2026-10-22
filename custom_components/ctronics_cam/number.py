"""Zahlenwerte: Erkennungsschwelle der KI und PTZ-Geschwindigkeit."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CtronicsError
from .const import MAX_PTZ_SPEED, MIN_PTZ_SPEED
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .entity import CtronicsEntity, command_error

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        [CtronicsDetectionThreshold(runtime.coordinator), CtronicsPtzSpeed(runtime.coordinator, runtime)]
    )


class CtronicsDetectionThreshold(CtronicsEntity, NumberEntity):
    """Empfindlichkeit der KI-Erkennung (1 bis 100)."""

    _attr_translation_key = "detection_threshold"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: CtronicsCoordinator) -> None:
        super().__init__(coordinator, "detection_threshold")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.smd_threshold

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.api.set_params("setsmdex", smd_gthresh=int(value))
        except CtronicsError as err:
            raise command_error(err) from err
        await self.coordinator.async_request_refresh()


class CtronicsPtzSpeed(CtronicsEntity, RestoreNumber):
    """Geschwindigkeit der PTZ-Tasten. Die Kamera speichert sie nicht, Home Assistant merkt sie sich."""

    _attr_translation_key = "ptz_speed"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = MIN_PTZ_SPEED
    _attr_native_max_value = MAX_PTZ_SPEED
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: CtronicsCoordinator, runtime: CtronicsRuntimeData) -> None:
        super().__init__(coordinator, "ptz_speed")
        self._runtime = runtime

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self._runtime.ptz_speed = max(MIN_PTZ_SPEED, min(MAX_PTZ_SPEED, int(last.native_value)))

    @property
    def native_value(self) -> float:
        return self._runtime.ptz_speed

    async def async_set_native_value(self, value: float) -> None:
        self._runtime.ptz_speed = int(value)
        self.async_write_ha_state()
