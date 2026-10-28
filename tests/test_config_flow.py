"""Tests des Config-Flows: Einrichtung, DHCP, Reauth, Reconfigure und Optionen."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ctronics_cam.api import CtronicsAuthError, CtronicsConnectionError
from custom_components.ctronics_cam.const import (
    CONF_PREFIX,
    CONF_PRESETS,
    CONF_PTZ_STEP_MS,
    CONF_RENAME_ENTITY_IDS,
    DOMAIN,
)

from .conftest import HOST, MAC


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Verhindert, dass ein im Flow angelegter Eintrag wirklich eingerichtet wird."""
    with patch("custom_components.ctronics_cam.async_setup_entry", return_value=True) as mock:
        yield mock


USER_INPUT = {
    CONF_NAME: "Flur",
    CONF_HOST: HOST,
    CONF_PORT: 80,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "geheim",
}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_creates_entry(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flur"
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_PORT] == 80
    assert result["data"][CONF_PASSWORD] == "geheim"
    assert len(result["data"][CONF_WEBHOOK_ID]) == 12
    assert result["result"].unique_id == MAC
    assert result["options"] == {CONF_PREFIX: ""}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_stores_prefix(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_PREFIX: " Spielzimmer "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Flur"
    assert result["options"] == {CONF_PREFIX: "Spielzimmer"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_cannot_connect_then_recovers(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = CtronicsConnectionError("down")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_api.get_params.side_effect = None
    mock_api.get_params.return_value = {"macaddress": "00:0F:97:AA:BB:CC"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_invalid_auth(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = CtronicsAuthError("nein")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unknown_device(hass: HomeAssistant, mock_api: MagicMock) -> None:
    mock_api.get_params.side_effect = None
    mock_api.get_params.return_value = {"model": "irgendwas"}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "unknown_device"}


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_already_configured_updates_host(
    hass: HomeAssistant, mock_api: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.77"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.77"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_dhcp_discovery_prefills_host(hass: HomeAssistant, mock_api: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.168.1.60", hostname="ipcam", macaddress="000f97aabbcc"),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

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
        CONF_PREFIX: "",
        CONF_PTZ_STEP_MS: 500,
        CONF_PRESETS: "1: Schaukel\n10: Bett",
    }


async def _set_prefix(hass: HomeAssistant, entry: MockConfigEntry, prefix: str, *, rename_ids: bool) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PREFIX: prefix, CONF_PTZ_STEP_MS: 400, CONF_PRESETS: "", CONF_RENAME_ENTITY_IDS: rename_ids},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_options_prefix_changes_names_but_keeps_entity_ids(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    await _set_prefix(hass, setup_integration, "Spielzimmer", rename_ids=False)

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), setup_integration.entry_id)
    assert device is not None
    assert device.name == "Spielzimmer Flur"
    assert hass.states.get("camera.flur").attributes["friendly_name"] == "Spielzimmer Flur"
    assert hass.states.get("camera.spielzimmer_flur") is None


async def test_options_prefix_can_rename_entity_ids(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    await _set_prefix(hass, setup_integration, "Spielzimmer", rename_ids=True)

    registry = er.async_get(hass)
    assert hass.states.get("camera.spielzimmer_flur") is not None
    assert hass.states.get("switch.spielzimmer_flur_auto_tracking") is not None
    assert hass.states.get("binary_sensor.spielzimmer_flur_motion") is not None
    assert not registry.async_is_registered("camera.flur")
    assert not registry.async_is_registered("switch.flur_auto_tracking")

    # Ein zweiter Wechsel baut auf den bereits umbenannten IDs auf
    await _set_prefix(hass, setup_integration, "Bad", rename_ids=True)
    assert hass.states.get("camera.bad_flur") is not None
    assert not registry.async_is_registered("camera.spielzimmer_flur")


async def test_options_rename_skips_taken_entity_ids(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    registry = er.async_get(hass)
    registry.async_get_or_create("camera", "other", "belegt", suggested_object_id="spielzimmer_flur")

    await _set_prefix(hass, setup_integration, "Spielzimmer", rename_ids=True)

    assert registry.async_is_registered("camera.flur")
    assert hass.states.get("switch.spielzimmer_flur_auto_tracking") is not None


async def test_options_rename_without_prefix_change_does_nothing(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    await _set_prefix(hass, setup_integration, "", rename_ids=True)

    assert hass.states.get("camera.flur") is not None
