"""Tests des Config-Flows: Einrichtung, DHCP, Reauth, Reconfigure und Optionen."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import TextSelector
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ctronics_cam.api import CtronicsAuthError, CtronicsConnectionError
from custom_components.ctronics_cam.const import (
    CONF_PREFIX,
    CONF_PRESETS,
    CONF_PTZ_STEP_MS,
    DOMAIN,
)

from .conftest import HOST, MAC


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Verhindert, dass ein im Flow angelegter Eintrag wirklich eingerichtet wird."""
    with patch("custom_components.ctronics_cam.async_setup_entry", return_value=True) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_scan() -> Generator[AsyncMock]:
    """Die Netzsuche der Einrichtung findet eine Kamera, ohne das Netz wirklich abzusuchen."""
    with patch("custom_components.ctronics_cam.config_flow.async_find_cameras", return_value=[HOST]) as mock:
        yield mock


async def _pick_camera(hass: HomeAssistant, host: str = HOST) -> ConfigFlowResult:
    """Wählt im ersten Schritt die Kamera und liefert das Formular mit den Zugangsdaten."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: host})


USER_INPUT = {
    CONF_NAME: "Flur",
    CONF_PREFIX: "Haus",
    CONF_HOST: HOST,
    CONF_PORT: 80,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "geheim",
}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_creates_entry(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await _pick_camera(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flur"
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_PORT] == 80
    assert result["data"][CONF_PASSWORD] == "geheim"
    assert len(result["data"][CONF_WEBHOOK_ID]) == 12
    assert result["result"].unique_id == MAC
    assert result["options"] == {CONF_PREFIX: "Haus"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_strips_prefix(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await _pick_camera(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PREFIX: " Spielzimmer "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flur"
    assert result["options"] == {CONF_PREFIX: "Spielzimmer"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_requires_prefix(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await _pick_camera(hass)
    prefix_field = next(key for key in result["data_schema"].schema if key == CONF_PREFIX)
    assert isinstance(prefix_field, vol.Required)

    for empty in ("", "   "):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**USER_INPUT, CONF_PREFIX: empty})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {CONF_PREFIX: "prefix_required"}
    mock_api.get_params.assert_not_called()

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_offers_found_cameras_that_are_not_set_up_yet(
    hass: HomeAssistant, mock_scan: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_scan.return_value = [HOST, "192.168.1.51", "192.168.1.52"]

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {"count": "2"}
    host_selector = result["data_schema"].schema[CONF_HOST]
    assert host_selector.config["options"] == ["192.168.1.51", "192.168.1.52"]
    assert host_selector.config["custom_value"] is True


async def test_user_step_without_found_cameras_asks_for_the_address(hass: HomeAssistant, mock_scan: AsyncMock) -> None:
    mock_scan.return_value = []

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    assert result["step_id"] == "user"
    assert result["description_placeholders"] == {"count": "0"}
    assert isinstance(result["data_schema"].schema[CONF_HOST], TextSelector)


async def test_user_step_passes_the_typed_address_on(hass: HomeAssistant) -> None:
    result = await _pick_camera(hass, " 192.168.1.9 ")

    assert result["step_id"] == "credentials"
    host_field = next(key for key in result["data_schema"].schema if key == CONF_HOST)
    assert host_field.default() == "192.168.1.9"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_cannot_connect_then_recovers(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = CtronicsConnectionError("down")
    result = await _pick_camera(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_api.get_params.side_effect = None
    mock_api.get_params.return_value = {"macaddress": "00:0F:97:AA:BB:CC"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_auth(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = CtronicsAuthError("nein")
    result = await _pick_camera(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unknown_device(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = None
    mock_api.get_params.return_value = {"model": "irgendwas"}
    result = await _pick_camera(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "unknown_device"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_already_configured_updates_host(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _pick_camera(hass, "192.168.1.77")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.77"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.77"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_dhcp_discovery_prefills_host(hass: HomeAssistant, mock_api: MagicMock, mock_scan: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.168.1.60", hostname="ipcam", macaddress="000f97aabbcc"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "credentials"
    mock_scan.assert_not_awaited()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.60"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MAC


@pytest.mark.usefixtures("mock_setup_entry")
async def test_dhcp_known_camera_updates_host(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.168.1.99", hostname="ipcam", macaddress="000f97aabbcc"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.99"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_updates_password(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "neu"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "neu"


async def test_reauth_wrong_device(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_api.get_params.side_effect = None
    mock_api.get_params.return_value = {"macaddress": "00:0F:97:11:22:33"}
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "admin", CONF_PASSWORD: "neu"}
    )
    assert result["errors"] == {"base": "wrong_device"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reconfigure_changes_address(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.168.1.80", CONF_PORT: 8000, CONF_USERNAME: "admin", CONF_PASSWORD: "geheim"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.80"
    assert mock_config_entry.data[CONF_PORT] == 8000


async def test_options_flow_rejects_bad_presets_then_saves(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PTZ_STEP_MS: 500, CONF_PRESETS: "kaputt"}
    )
    assert result["errors"] == {CONF_PRESETS: "invalid_presets"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PTZ_STEP_MS: 500, CONF_PRESETS: "1: Schaukel\n10: Bett"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options == {
        CONF_PTZ_STEP_MS: 500,
        CONF_PRESETS: "1: Schaukel\n10: Bett",
    }


async def test_options_flow_has_no_prefix_field_and_keeps_the_prefix(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock, mock_onvif: MagicMock
) -> None:
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_PREFIX: "Spielzimmer"})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert set(result["data_schema"].schema) == {CONF_PTZ_STEP_MS, CONF_PRESETS}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PTZ_STEP_MS: 400, CONF_PRESETS: "1: Schaukel"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_config_entry.options == {
        CONF_PREFIX: "Spielzimmer",
        CONF_PTZ_STEP_MS: 400,
        CONF_PRESETS: "1: Schaukel",
    }
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), mock_config_entry.entry_id)
    assert device is not None
    assert device.name == "Spielzimmer Flur"


async def test_reconfigure_has_no_prefix_field(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert CONF_PREFIX not in {str(key) for key in result["data_schema"].schema}
