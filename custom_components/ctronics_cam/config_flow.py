"""Einrichtung der Ctronics-Kamera über die Oberfläche."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import (
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_WEBHOOK_ID,
)
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
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_USERNAME,
    DOMAIN,
    EVENT_WEBHOOK_ID_LENGTH,
)
from .coordinator import CtronicsConfigEntry
from .discovery import async_find_cameras, async_start_discovery_flows
from .presets import parse_presets


def _credentials_schema(defaults: Mapping[str, Any] | None = None, *, with_name: bool = False) -> vol.Schema:
    defaults = defaults or {}
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = selector.TextSelector()
        fields[vol.Required(CONF_PREFIX, default=defaults.get(CONF_PREFIX, vol.UNDEFINED))] = selector.TextSelector()
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
        """Kamera im Heimnetz auswählen oder ihre Adresse von Hand eintragen."""
        if user_input is not None:
            self._discovered_host = user_input[CONF_HOST].strip()
            return await self.async_step_credentials()

        found = await async_find_cameras(self.hass)
        # Die gefundenen Kameras erscheinen auch einzeln unter "Entdeckt"
        await async_start_discovery_flows(self.hass, found)
        configured = {entry.data.get(CONF_HOST) for entry in self._async_current_entries()}
        found = [host for host in found if host not in configured]
        host_selector = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=found, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
            if found
            else selector.TextSelector()
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): host_selector}),
            description_placeholders={"count": str(len(found))},
        )

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Name, Präfix und Zugangsdaten der Kamera."""
        errors: dict[str, str] = {}
        mac: str | None = None
        if user_input is not None:
            prefix = user_input[CONF_PREFIX].strip()
            if not prefix:
                errors[CONF_PREFIX] = "prefix_required"
            else:
                errors, mac = await self._async_validate(user_input)
            if not errors and mac:
                # Wer die Kamera selbst wählt, darf weitermachen, auch wenn dazu schon eine Entdeckung läuft
                await self.async_set_unique_id(mac, raise_on_progress=self.source != SOURCE_USER)
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
                    options={CONF_PREFIX: prefix},
                )

        defaults: dict[str, Any] = dict(user_input or {})
        if self._discovered_host and CONF_HOST not in defaults:
            defaults[CONF_HOST] = self._discovered_host
        return self.async_show_form(
            step_id="credentials",
            data_schema=_credentials_schema(defaults, with_name=True),
            errors=errors,
        )

    async def _async_step_discovered(self, mac: str, host: str) -> ConfigFlowResult:
        """Eine Kamera wurde entdeckt: bekannte Kameras bekommen nur die neue Adresse, neue die Zugangsdaten."""
        await self.async_set_unique_id(format_mac(mac))
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered_host = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_credentials()

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Eine Kamera dieser Bauart ist im Netz aufgetaucht."""
        return await self._async_step_discovered(discovery_info.macaddress, discovery_info.ip)

    async def async_step_integration_discovery(self, discovery_info: dict[str, Any]) -> ConfigFlowResult:
        """Die Netzsuche der Integration hat eine Kamera gefunden."""
        return await self._async_step_discovered(discovery_info[CONF_MAC], discovery_info[CONF_HOST])

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
    """Präfix des Gerätenamens, Schrittdauer der PTZ-Tasten und Namen der Preset-Positionen.

    Ein geändertes Präfix wirkt auf den Gerätenamen, die Entity-IDs bleiben, wie sie sind.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prefix = user_input[CONF_PREFIX].strip()
            if not prefix:
                errors[CONF_PREFIX] = "prefix_required"
            try:
                parse_presets(user_input.get(CONF_PRESETS, ""))
            except ValueError:
                errors[CONF_PRESETS] = "invalid_presets"
            if not errors:
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_PREFIX: prefix,
                        CONF_PTZ_STEP_MS: int(user_input[CONF_PTZ_STEP_MS]),
                        CONF_PRESETS: user_input.get(CONF_PRESETS, ""),
                    }
                )

        current = user_input or self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_PREFIX, default=current.get(CONF_PREFIX, vol.UNDEFINED)): selector.TextSelector(),
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
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
