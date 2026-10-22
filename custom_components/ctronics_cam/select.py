"""Auswahlfelder: Erkennungsart, Nachtsicht-LEDs und Preset-Positionen."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CtronicsError
from .const import CONF_PRESETS, INFRARED_MODES, SIGNAL_PTZ_MOVED, SMD_TYPES
from .coordinator import CtronicsConfigEntry, CtronicsCoordinator, CtronicsRuntimeData
from .entity import CtronicsEntity, command_error
from .presets import parse_presets

PARALLEL_UPDATES = 1

_INFRARED_BY_CAMERA = {value: key for key, value in INFRARED_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: CtronicsConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    entities: list[SelectEntity] = [
        CtronicsDetectionType(runtime.coordinator),
        CtronicsInfrared(runtime.coordinator),
    ]
    try:
        presets = parse_presets(entry.options.get(CONF_PRESETS, ""))
    except ValueError:
        presets = {}
    if presets:
        entities.append(CtronicsPreset(runtime.coordinator, runtime, presets, entry.entry_id))
    async_add_entities(entities)


class CtronicsDetectionType(CtronicsEntity, SelectEntity):
    """Was die KI-Erkennung melden soll."""

    _attr_translation_key = "detection_type"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CtronicsCoordinator) -> None:
        super().__init__(coordinator, "detection_type")
        self._attr_options = list(SMD_TYPES)

    @property
    def current_option(self) -> str | None:
        index = self.coordinator.data.smd_type
        return SMD_TYPES[index] if 0 <= index < len(SMD_TYPES) else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.api.set_params("setsmdex", smd_type=SMD_TYPES.index(option))
        except CtronicsError as err:
            raise command_error(err) from err
        await self.coordinator.async_request_refresh()


class CtronicsInfrared(CtronicsEntity, SelectEntity):
    """Nachtsicht-LEDs: automatisch, immer an oder aus."""

    _attr_translation_key = "infrared"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CtronicsCoordinator) -> None:
        super().__init__(coordinator, "infrared")
        self._attr_options = list(INFRARED_MODES)

    @property
    def current_option(self) -> str | None:
        return _INFRARED_BY_CAMERA.get(self.coordinator.data.infrared)

    async def async_select_option(self, option: str) -> None:
        try:
            await self.api.set_params("setinfrared", infraredstat=INFRARED_MODES[option])
        except CtronicsError as err:
            raise command_error(err) from err
        await self.coordinator.async_request_refresh()


class CtronicsPreset(CtronicsEntity, SelectEntity):
    """Fährt eine benannte Preset-Position an. Die Namen stammen aus den Optionen."""

    _attr_translation_key = "preset"

    def __init__(
        self,
        coordinator: CtronicsCoordinator,
        runtime: CtronicsRuntimeData,
        presets: dict[int, str],
        entry_id: str,
    ) -> None:
        super().__init__(coordinator, "preset")
        self._entry_id = entry_id
        names = list(presets.values())
        self._number_by_option = {
            (name if names.count(name) == 1 else f"{name} ({number})"): number
            for number, name in sorted(presets.items())
        }
        self._attr_options = list(self._number_by_option)
        self._current: str | None = None

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PTZ_MOVED.format(self._entry_id), self._async_moved)
        )

    @callback
    def _async_moved(self) -> None:
        """Die Kamera wurde anders bewegt, die gemerkte Position stimmt nicht mehr."""
        if self._current is not None:
            self._current = None
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        try:
            await self.api.goto_preset(self._number_by_option[option])
        except CtronicsError as err:
            raise command_error(err) from err
        self._current = option
        self.async_write_ha_state()
