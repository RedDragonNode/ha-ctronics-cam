"""Bewegungsmeldung der Kamera über ONVIF-Ereignisse."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CtronicsConfigEntry, CtronicsCoordinator
from .entity import CtronicsEntity
from .events import CtronicsEvents

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.events:
        async_add_entities([CtronicsMotionSensor(runtime.coordinator, runtime.events)])


class CtronicsMotionSensor(CtronicsEntity, BinarySensorEntity):
    """Bewegung oder erkannte Person, je nach Einstellung der KI-Erkennung an der Kamera."""

    _attr_translation_key = "motion"
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, coordinator: CtronicsCoordinator, events: CtronicsEvents) -> None:
        super().__init__(coordinator, "motion")
        self._events = events

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._events.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return super().available and self._events.subscribed

    @property
    def is_on(self) -> bool | None:
        return self._events.motion
