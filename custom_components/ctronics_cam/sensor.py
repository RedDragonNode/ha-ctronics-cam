"""Diagnose-Sensoren: Zustand und Platz der SD-Karte (nur wenn eine Karte steckt)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CameraState, CtronicsConfigEntry, CtronicsCoordinator
from .entity import CtronicsEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CtronicsSensorDescription(SensorEntityDescription):
    """Beschreibt einen Sensor, dessen Wert aus dem Kamerazustand kommt."""

    value_fn: Callable[[CameraState], str | int]


SENSORS: tuple[CtronicsSensorDescription, ...] = (
    CtronicsSensorDescription(
        key="sd_status",
        translation_key="sd_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.sd_status.lower(),
    ),
    CtronicsSensorDescription(
        key="sd_free",
        translation_key="sd_free",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        value_fn=lambda state: state.sd_free_kib,
    ),
    CtronicsSensorDescription(
        key="sd_total",
        translation_key="sd_total",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.KIBIBYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        value_fn=lambda state: state.sd_total_kib,
    ),
)


def _has_sd_card(state: CameraState) -> bool:
    return state.sd_status.lower() not in ("", "out")


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    added = False

    def _add_sensors() -> None:
        nonlocal added
        if not added and _has_sd_card(coordinator.data):
            added = True
            async_add_entities(CtronicsSensor(coordinator, description) for description in SENSORS)

    _add_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_sensors))


class CtronicsSensor(CtronicsEntity, SensorEntity):
    """Wert aus dem Kamerazustand."""

    entity_description: CtronicsSensorDescription

    def __init__(self, coordinator: CtronicsCoordinator, description: CtronicsSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int:
        return self.entity_description.value_fn(self.coordinator.data)
