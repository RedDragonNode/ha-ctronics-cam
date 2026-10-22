"""Tests der Entities: Zustände, Befehle an die Kamera und Dienste."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ctronics_cam.api import CtronicsError
from custom_components.ctronics_cam.const import CONF_PRESETS, CONF_PTZ_STEP_MS, DOMAIN


async def test_switch_state_follows_camera(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
    camera_vars: dict[str, str],
) -> None:
    camera_vars.update(smd_enable="1", smartrack_enable="1", flip="on")
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.flur_ai_detection").state == STATE_ON
    assert hass.states.get("switch.flur_auto_tracking").state == STATE_ON
    assert hass.states.get("switch.flur_flip_image").state == STATE_ON
    assert hass.states.get("switch.flur_mirror_image").state == "off"


@pytest.mark.parametrize(
    ("entity_id", "service", "command", "params"),
    [
        ("switch.flur_auto_tracking", "turn_on", "setsmartrackattr", {"smartrack_enable": "1"}),
        ("switch.flur_auto_tracking", "turn_off", "setsmartrackattr", {"smartrack_enable": "0"}),
        ("switch.flur_ai_detection", "turn_on", "setsmdattr", {"smd_enable": "1"}),
        ("switch.flur_detection_frame_in_video", "turn_off", "setsmdex", {"smd_rect": "0"}),
        ("switch.flur_flip_image", "turn_on", "setimageattr", {"flip": "on"}),
        ("switch.flur_mirror_image", "turn_off", "setimageattr", {"mirror": "off"}),
    ],
)
async def test_switches_send_commands(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: MagicMock,
    entity_id: str,
    service: str,
    command: str,
    params: dict[str, str],
) -> None:
    await hass.services.async_call("switch", service, {ATTR_ENTITY_ID: entity_id}, blocking=True)
    mock_api.set_params.assert_awaited_once_with(command, **params)


async def test_number_sets_threshold(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    assert hass.states.get("number.flur_detection_threshold").state == "50"
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: "number.flur_detection_threshold", "value": 70}, blocking=True
    )
    mock_api.set_params.assert_awaited_once_with("setsmdex", smd_gthresh=70)


async def test_ptz_speed_is_kept_in_home_assistant(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    assert hass.states.get("number.flur_ptz_speed").state == "4"
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: "number.flur_ptz_speed", "value": 7}, blocking=True
    )
    assert hass.states.get("number.flur_ptz_speed").state == "7"
    mock_api.set_params.assert_not_awaited()

    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.flur_move_up"}, blocking=True)
    mock_api.ptz_move.assert_awaited_once_with("up", 7, 0.4)


@pytest.mark.parametrize(
    ("entity_id", "option", "command", "params"),
    [
        ("select.flur_detection_type", "human_pet", "setsmdex", {"smd_type": 2}),
        ("select.flur_night_vision_leds", "on", "setinfrared", {"infraredstat": "open"}),
        ("select.flur_night_vision_leds", "auto", "setinfrared", {"infraredstat": "auto"}),
        ("select.flur_night_vision_leds", "off", "setinfrared", {"infraredstat": "close"}),
    ],
)
async def test_selects_send_commands(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: MagicMock,
    entity_id: str,
    option: str,
    command: str,
    params: dict[str, int | str],
) -> None:
    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: entity_id, "option": option}, blocking=True
    )
    mock_api.set_params.assert_awaited_once_with(command, **params)


async def test_select_states(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert hass.states.get("select.flur_detection_type").state == "human"
    assert hass.states.get("select.flur_night_vision_leds").state == "off"


@pytest.mark.parametrize(
    ("entity_id", "expected_call"),
    [
        ("button.flur_move_left", ("ptz_move", ("left", 4, 0.4))),
        ("button.flur_move_right", ("ptz_move", ("right", 4, 0.4))),
        ("button.flur_move_to_center", ("ptz", ("home", 4))),
        ("button.flur_stop", ("ptz", ("stop", 4))),
    ],
)
async def test_buttons(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: MagicMock,
    entity_id: str,
    expected_call: tuple[str, tuple],
) -> None:
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: entity_id}, blocking=True)
    method, args = expected_call
    getattr(mock_api, method).assert_awaited_once_with(*args)


async def test_button_uses_step_duration_from_options(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    hass.config_entries.async_update_entry(setup_integration, options={CONF_PTZ_STEP_MS: 1000})
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.flur_move_down"}, blocking=True)
    mock_api.ptz_move.assert_awaited_once_with("down", 4, 1.0)


async def test_failed_command_raises_translated_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    mock_api.set_params.side_effect = CtronicsError("[Error]Param error.")
    with pytest.raises(HomeAssistantError, match="Param error"):
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: "switch.flur_auto_tracking"}, blocking=True
        )


async def test_camera_snapshot_and_stream_source(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_api: MagicMock
) -> None:
    image = await async_get_image(hass, "camera.flur")
    assert image.content == b"\xff\xd8\xff jpeg"
    mock_api.rtsp_url.assert_not_called()

    from homeassistant.components import camera

    entity = hass.data[camera.DATA_COMPONENT].get_entity("camera.flur")
    assert await entity.stream_source() == "rtsp://admin:geheim@192.168.1.50:554/11"


@pytest.mark.parametrize(
    ("service", "data", "method", "args"),
    [
        ("ptz_move", {"direction": "left"}, "ptz_move", ("left", 4, 0.4)),
        ("ptz_move", {"direction": "up", "speed": 2, "duration": 1.5}, "ptz_move", ("up", 2, 1.5)),
        ("ptz_goto_preset", {"preset": 3}, "goto_preset", (3,)),
        ("ptz_save_preset", {"preset": 5}, "save_preset", (5,)),
        ("ptz_delete_preset", {"preset": 64}, "delete_preset", (64,)),
    ],
)
async def test_ptz_services(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: MagicMock,
    service: str,
    data: dict,
    method: str,
    args: tuple,
) -> None:
    await hass.services.async_call(DOMAIN, service, {ATTR_ENTITY_ID: "camera.flur", **data}, blocking=True)
    getattr(mock_api, method).assert_awaited_once_with(*args)


async def test_preset_select_from_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
) -> None:
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_PRESETS: "10: Bett\n1: Schaukel\n2: Bett"})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("select.flur_preset_position")
    assert state.state == "unknown"
    assert state.attributes["options"] == ["Schaukel", "Bett (2)", "Bett (10)"]

    await hass.services.async_call(
        "select", "select_option", {ATTR_ENTITY_ID: "select.flur_preset_position", "option": "Bett (10)"}, blocking=True
    )
    mock_api.goto_preset.assert_awaited_once_with(10)
    assert hass.states.get("select.flur_preset_position").state == "Bett (10)"

    # Wird die Kamera anders bewegt, vergisst die Auswahl die Position.
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.flur_move_left"}, blocking=True)
    assert hass.states.get("select.flur_preset_position").state == "unknown"


async def test_no_preset_select_without_presets(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    assert hass.states.get("select.flur_preset_position") is None
