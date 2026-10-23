"""Koordinator, der den Zustand der Kamera regelmäßig abfragt."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CtronicsApi, CtronicsAuthError, CtronicsError
from .const import DEFAULT_PTZ_SPEED, DOMAIN, LOGGER, REFRESH_COOLDOWN, UPDATE_INTERVAL

if TYPE_CHECKING:
    from .events import CtronicsEvents

POLL_COMMANDS = (
    "getserverinfo",
    "getnetattr",
    "getimageattr",
    "getinfrared",
    "getsmdattr",
    "getsmdex",
    "getsmartrackattr",
    "getrtspport",
    "getonvifattr",
)


def _int(values: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(values.get(key, default))
    except ValueError:
        return default


@dataclass(slots=True, frozen=True)
class CameraState:
    """Zustand der Kamera, aus den `var`-Zeilen der CGI gelesen."""

    mac: str
    model: str
    firmware: str
    hardware: str
    rtsp_port: int
    onvif_enabled: bool
    onvif_port: int
    smd_enable: bool
    smd_type: int
    smd_threshold: int
    smd_frame: bool
    auto_tracking: bool
    flip: bool
    mirror: bool
    infrared: str
    sd_status: str
    sd_free_kib: int
    sd_total_kib: int
    raw: dict[str, str] = field(repr=False)

    @classmethod
    def from_vars(cls, values: dict[str, str]) -> CameraState:
        return cls(
            mac=format_mac(values.get("macaddress", "")),
            model=values.get("model", ""),
            firmware=values.get("softVersion", ""),
            hardware=values.get("hardVersion", ""),
            rtsp_port=_int(values, "rtspport", 554),
            onvif_enabled=values.get("ov_enable") == "1",
            onvif_port=_int(values, "ov_port", 8080),
            smd_enable=values.get("smd_enable") == "1",
            smd_type=_int(values, "smd_type"),
            smd_threshold=_int(values, "smd_gthresh", 50),
            smd_frame=values.get("smd_rect") == "1",
            auto_tracking=values.get("smartrack_enable") == "1",
            flip=values.get("flip") == "on",
            mirror=values.get("mirror") == "on",
            infrared=values.get("infraredstat", ""),
            sd_status=values.get("sdstatus", ""),
            sd_free_kib=_int(values, "sdfreespace"),
            sd_total_kib=_int(values, "sdtotalspace"),
            raw=values,
        )


@dataclass(slots=True)
class CtronicsRuntimeData:
    """Alles, was ein Eintrag zur Laufzeit braucht."""

    api: CtronicsApi
    coordinator: CtronicsCoordinator
    events: CtronicsEvents | None = None
    ptz_speed: int = DEFAULT_PTZ_SPEED


type CtronicsConfigEntry = ConfigEntry[CtronicsRuntimeData]


class CtronicsCoordinator(DataUpdateCoordinator[CameraState]):
    """Fragt die Kamera alle 30 Sekunden mit einer einzigen Anfrage ab."""

    config_entry: CtronicsConfigEntry

    def __init__(self, hass: HomeAssistant, entry: CtronicsConfigEntry, api: CtronicsApi) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
            # Nach einem Schaltvorgang wenig warten, damit die Anzeige schnell nachzieht (Standard wären 10 s).
            request_refresh_debouncer=Debouncer(hass, LOGGER, cooldown=REFRESH_COOLDOWN, immediate=False),
        )
        self.api = api

    async def _async_update_data(self) -> CameraState:
        try:
            values = await self.api.get_params(*POLL_COMMANDS)
        except CtronicsAuthError as err:
            raise ConfigEntryAuthFailed from err
        except CtronicsError as err:
            raise UpdateFailed(f"Kamera nicht erreichbar: {err}") from err
        return CameraState.from_vars(values)

    @property
    def device_info(self) -> DeviceInfo:
        entry = self.config_entry
        state = self.data
        info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or state.mac)},
            manufacturer="Ctronics",
            model="4K Pan/Tilt Camera",
            model_id=state.model or None,
            name=entry.title,
            sw_version=state.firmware or None,
            hw_version=state.hardware or None,
            configuration_url=self.api.base_url,
        )
        if state.mac:
            info["connections"] = {(CONNECTION_NETWORK_MAC, state.mac)}
        return info

    @property
    def host(self) -> str:
        return self.config_entry.data[CONF_HOST]

    @property
    def port(self) -> int:
        return self.config_entry.data[CONF_PORT]
