"""Schalter: Auto-Tracking, KI-Erkennung, Erkennungsrahmen, Bild spiegeln und drehen."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CtronicsError
from .coordinator import CameraState, CtronicsConfigEntry, CtronicsCoordinator
from .entity import CtronicsEntity, command_error

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class CtronicsSwitchDescription(SwitchEntityDescription):
    """Beschreibt einen Schalter und den CGI-Befehl dahinter."""

    is_on_fn: Callable[[CameraState], bool]
    command: str
    field: str
    on_value: str = "1"
    off_value: str = "0"


SWITCHES: tuple[CtronicsSwitchDescription, ...] = (
    CtronicsSwitchDescription(
        key="auto_tracking",
        translation_key="auto_tracking",
        is_on_fn=lambda state: state.auto_tracking,
        command="setsmartrackattr",
        field="smartrack_enable",
    ),
    CtronicsSwitchDescription(
        key="ai_detection",
        translation_key="ai_detection",
        is_on_fn=lambda state: state.smd_enable,
        command="setsmdattr",
        field="smd_enable",
    ),
    CtronicsSwitchDescription(
        key="detection_frame",
        translation_key="detection_frame",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.smd_frame,
        command="setsmdex",
        field="smd_rect",
    ),
    CtronicsSwitchDescription(
        key="image_flip",
        translation_key="image_flip",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.flip,
        command="setimageattr",
        field="flip",
        on_value="on",
        off_value="off",
    ),
    CtronicsSwitchDescription(
        key="image_mirror",
        translation_key="image_mirror",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.mirror,
        command="setimageattr",
        field="mirror",
        on_value="on",
        off_value="off",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(CtronicsSwitch(coordinator, description) for description in SWITCHES)


class CtronicsSwitch(CtronicsEntity, SwitchEntity):
    """Schalter, der ein Feld der Kamera setzt."""

    entity_description: CtronicsSwitchDescription

    def __init__(self, coordinator: CtronicsCoordinator, description: CtronicsSwitchDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def _async_set(self, value: str) -> None:
        description = self.entity_description
        try:
            await self.api.set_params(description.command, **{description.field: value})
        except CtronicsError as err:
            raise command_error(err) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(self.entity_description.on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(self.entity_description.off_value)
