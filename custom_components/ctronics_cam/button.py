"""PTZ-Tasten: Richtung, Mitte, Stopp und Rundgänge."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CtronicsError
from .const import CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS, SIGNAL_PTZ_MOVED
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .entity import CtronicsEntity, command_error

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class CtronicsButtonDescription(ButtonEntityDescription):
    """PTZ-Aktion der Kamera; `timed` bewegt nur für die eingestellte Schrittdauer."""

    action: str
    timed: bool = False


BUTTONS: tuple[CtronicsButtonDescription, ...] = (
    CtronicsButtonDescription(key="ptz_up", translation_key="ptz_up", action="up", timed=True),
    CtronicsButtonDescription(key="ptz_down", translation_key="ptz_down", action="down", timed=True),
    CtronicsButtonDescription(key="ptz_left", translation_key="ptz_left", action="left", timed=True),
    CtronicsButtonDescription(key="ptz_right", translation_key="ptz_right", action="right", timed=True),
    CtronicsButtonDescription(key="ptz_center", translation_key="ptz_center", action="home"),
    CtronicsButtonDescription(key="ptz_stop", translation_key="ptz_stop", action="stop"),
    CtronicsButtonDescription(
        key="patrol_horizontal",
        translation_key="patrol_horizontal",
        action="hscan",
        entity_registry_enabled_default=False,
    ),
    CtronicsButtonDescription(
        key="patrol_vertical",
        translation_key="patrol_vertical",
        action="vscan",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    async_add_entities(CtronicsButton(runtime.coordinator, runtime, description) for description in BUTTONS)


class CtronicsButton(CtronicsEntity, ButtonEntity):
    """Löst eine PTZ-Aktion aus."""

    entity_description: CtronicsButtonDescription

    def __init__(
        self,
        coordinator: CtronicsCoordinator,
        runtime: CtronicsRuntimeData,
        description: CtronicsButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._runtime = runtime

    async def async_press(self) -> None:
        description = self.entity_description
        speed = self._runtime.ptz_speed
        try:
            if description.timed:
                step_ms = self.coordinator.config_entry.options.get(CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS)
                await self.api.ptz_move(description.action, speed, step_ms / 1000)
            else:
                await self.api.ptz(description.action, speed)
        except CtronicsError as err:
            raise command_error(err) from err
        async_dispatcher_send(self.hass, SIGNAL_PTZ_MOVED.format(self.coordinator.config_entry.entry_id))
