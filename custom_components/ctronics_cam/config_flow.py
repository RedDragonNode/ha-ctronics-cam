"""Einrichtung der Ctronics-Kamera über die Oberfläche."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_WEBHOOK_ID
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import CtronicsApi, CtronicsAuthError, CtronicsError
from .const import (
    CONF_PREFIX,
    CONF_PRESETS,
    CONF_PTZ_STEP_MS,
    CONF_RENAME_ENTITY_IDS,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_USERNAME,
    DOMAIN,
    EVENT_WEBHOOK_ID_LENGTH,
)
from .coordinator import CtronicsConfigEntry
from .naming import device_name, rename_entity_ids
from .presets import parse_presets


def _credentials_schema(defaults: Mapping[str, Any] | None = None, *, with_name: bool = False) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = selector.TextSelector()
        fields[vol.Optional(CONF_PREFIX, default=defaults.get(CONF_PREFIX, ""))] = selector.TextSelector()
    fields[vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED))] = selector.TextSelector()
    fields[vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=1, max=65535, mode=selector.NumberSelectorMode.BOX)
    )
    fields[vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME))] = selector.TextSelector()
    fields[vol.Required(CONF_PASSWORD)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    return vol.Schema(fields)


class CtronicsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config-Flow mit manueller Eingabe, DHCP-Erkennung, Reauth und Reconfigure."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None

    async def _async_validate(self, user_input: Mapping[str, Any]) -> tuple[dict[str, str], str | None]:
        """Prüft die Zugangsdaten und liefert Fehler sowie die MAC-Adresse der Kamera."""
        api = CtronicsApi(
            async_get_clientsession(self.hass),
            user_input[CONF_HOST],
            int(user_input[CONF_PORT]),
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
        )
        try:
            values = await api.get_params("getserverinfo", "getnetattr")
        except CtronicsAuthError:
            return {"base": "invalid_auth"}, None
        except CtronicsError:
            return {"base": "cannot_connect"}, None
        mac = format_mac(values.get("macaddress", ""))
        if not mac:
            return {"base": "unknown_device"}, None
        return {}, mac

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, mac = await self._async_validate(user_input)
            if not errors and mac:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST], CONF_PORT: int(user_input[CONF_PORT])}
                )
                data = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_PORT: int(user_input[CONF_PORT]),
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_WEBHOOK_ID: secrets.token_hex(EVENT_WEBHOOK_ID_LENGTH // 2),
                }
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=data,
                    options={CONF_PREFIX: user_input.get(CONF_PREFIX, "").strip()},
                )

        defaults: dict[str, Any] = dict(user_input or {})
        if self._discovered_host and CONF_HOST not in defaults:
            defaults[CONF_HOST] = self._discovered_host
        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(defaults, with_name=True),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Eine Kamera dieser Bauart ist im Netz aufgetaucht."""
        await self.async_set_unique_id(format_mac(discovery_info.macaddress))
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._discovered_host = discovery_info.ip
        self.context["title_placeholders"] = {"host": discovery_info.ip}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**entry.data, **user_input}
            errors, mac = await self._async_validate(candidate)
            if not errors:
                if mac != entry.unique_id:
                    errors["base"] = "wrong_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): selector.TextSelector(),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, mac = await self._async_validate(user_input)
            if not errors:
                if mac != entry.unique_id:
                    errors["base"] = "wrong_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_HOST: user_input[CONF_HOST],
                            CONF_PORT: int(user_input[CONF_PORT]),
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(user_input or entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: CtronicsConfigEntry) -> CtronicsOptionsFlow:
        return CtronicsOptionsFlow()


class CtronicsOptionsFlow(OptionsFlowWithReload):
    """Präfix des Gerätenamens, Schrittdauer der PTZ-Tasten und Namen der Preset-Positionen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parse_presets(user_input.get(CONF_PRESETS, ""))
            except ValueError:
                errors[CONF_PRESETS] = "invalid_presets"
            else:
                prefix = user_input.get(CONF_PREFIX, "").strip()
                if user_input.get(CONF_RENAME_ENTITY_IDS):
                    rename_entity_ids(self.hass, self.config_entry, device_name(self.config_entry.title, prefix))
                return self.async_create_entry(
                    data={
                        CONF_PREFIX: prefix,
                        CONF_PTZ_STEP_MS: int(user_input[CONF_PTZ_STEP_MS]),
                        CONF_PRESETS: user_input.get(CONF_PRESETS, ""),
                    }
                )

        current = user_input or self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_PREFIX, default=current.get(CONF_PREFIX, "")): selector.TextSelector(),
                vol.Required(
                    CONF_PTZ_STEP_MS, default=current.get(CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=3000, step=50, unit_of_measurement="ms", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_PRESETS, default=current.get(CONF_PRESETS, "")): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
                vol.Optional(CONF_RENAME_ENTITY_IDS, default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
