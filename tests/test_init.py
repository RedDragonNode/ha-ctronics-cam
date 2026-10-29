"""Tests für Einrichten, Entladen und Fehlerfälle."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ctronics_cam.api import CtronicsAuthError, CtronicsConnectionError
from custom_components.ctronics_cam.const import CONF_PREFIX, DISCOVERY_INTERVAL, DOMAIN
from custom_components.ctronics_cam.naming import device_name

from .conftest import MAC


async def test_setup_and_unload(hass: HomeAssistant, setup_integration: MockConfigEntry, mock_onvif: MagicMock) -> None:
    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get("camera.flur") is not None
    assert hass.states.get("switch.flur_auto_tracking").state == STATE_OFF
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), setup_integration.entry_id)
    assert device is not None
    assert device.manufacturer == "Ctronics"
    assert device.model_id == "C6F0SpZ0N0PpL2"
    assert device.sw_version == "V30.1.60.11.88-20260204"
    assert (dr.CONNECTION_NETWORK_MAC, MAC) in device.connections

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    mock_onvif.subscribe.assert_awaited_once()


async def test_setup_looks_for_cameras_at_start_and_every_hour(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_discover_cameras: AsyncMock
) -> None:
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_discover_cameras.await_count == 1

    async_fire_time_changed(hass, dt_util.utcnow() + DISCOVERY_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_discover_cameras.await_count == 2


async def test_prefix_is_part_of_device_name_and_entity_ids(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock, mock_onvif: MagicMock
) -> None:
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_PREFIX: "Spielzimmer"})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, MAC), mock_config_entry.entry_id)
    assert device is not None
    assert device.name == "Spielzimmer Flur"
    assert hass.states.get("camera.spielzimmer_flur") is not None
    assert hass.states.get("switch.spielzimmer_flur_auto_tracking") is not None


def test_device_name_joins_prefix_and_title() -> None:
    assert device_name("Flur", None) == "Flur"
    assert device_name("Flur", "") == "Flur"
    assert device_name("Flur", "  Spielzimmer ") == "Spielzimmer Flur"


async def test_substream_is_disabled_by_default(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    entry = er.async_get(hass).async_get("camera.flur_sub_stream")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("camera.flur_sub_stream") is None


async def test_setup_without_onvif_has_no_motion_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
    camera_vars: dict[str, str],
) -> None:
    camera_vars["ov_enable"] = "0"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("binary_sensor.flur_motion") is None
    mock_onvif.subscribe.assert_not_awaited()


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock, mock_onvif: MagicMock
) -> None:
    mock_api.get_params.side_effect = CtronicsAuthError("nein")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_connection_failure_retries(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock, mock_onvif: MagicMock
) -> None:
    mock_api.get_params.side_effect = CtronicsConnectionError("down")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_sd_sensors_only_with_card(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
    camera_vars: dict[str, str],
) -> None:
    assert hass.states.get("sensor.flur_sd_card_status") is None
    camera_vars.update(sdstatus="Ready", sdfreespace="124807616", sdtotalspace="124807648")
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("sensor.flur_sd_card_status").state == "ready"
    assert round(float(hass.states.get("sensor.flur_sd_card_free_space").state), 1) == 119.0
