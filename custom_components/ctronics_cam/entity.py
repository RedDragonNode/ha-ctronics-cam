"""Gemeinsame Basis aller Entities."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CtronicsApi, CtronicsError
from .const import DOMAIN
from .coordinator import CtronicsCoordinator


class CtronicsEntity(CoordinatorEntity[CtronicsCoordinator]):
    """Entity, die zu genau einer Kamera gehört."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CtronicsCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info

    @property
    def api(self) -> CtronicsApi:
        return self.coordinator.api


def command_error(err: CtronicsError) -> HomeAssistantError:
    """Übersetzbarer Fehler für fehlgeschlagene Befehle an die Kamera."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"error": str(err)},
    )
