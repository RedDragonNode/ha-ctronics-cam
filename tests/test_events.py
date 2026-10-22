"""Tests der ONVIF-Ereignisse: Auswertung, Webhook, Abo und Erneuerung."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.ctronics_cam.api import CtronicsError
from custom_components.ctronics_cam.const import (
    EVENT_MOTION_TIMEOUT,
    EVENT_RENEW_INTERVAL,
    EVENT_SUBSCRIPTION_SECONDS,
    EVENT_TYPE,
)
from custom_components.ctronics_cam.onvif import OnvifEvent, motion_state, parse_notifications

from .conftest import WEBHOOK_ID


def notify(topic: str, item: str, value: str, operation: str = "Changed") -> bytes:
    """Baut eine Benachrichtigung in der Form, wie die Kamera sie per POST schickt."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tt="http://www.onvif.org/ver10/schema"
  xmlns:tns1="http://www.onvif.org/ver10/topics">
 <s:Body><wsnt:Notify><wsnt:NotificationMessage>
  <wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">tns1:{topic}</wsnt:Topic>
  <wsnt:Message><tt:Message UtcTime="2026-10-22T19:00:00Z" PropertyOperation="{operation}">
   <tt:Source><tt:SimpleItem Name="VideoSourceConfigurationToken" Value="VideoSourceToken"/></tt:Source>
   <tt:Data><tt:SimpleItem Name="{item}" Value="{value}"/></tt:Data>
  </tt:Message></wsnt:Message>
 </wsnt:NotificationMessage></wsnt:Notify></s:Body></s:Envelope>""".encode()


def test_parse_notification() -> None:
    events = parse_notifications(notify("RuleEngine/CellMotionDetector/Motion", "IsMotion", "true"))
    assert events == [
        OnvifEvent(
            topic="RuleEngine/CellMotionDetector/Motion",
            operation="Changed",
            utc_time="2026-10-22T19:00:00Z",
            source={"VideoSourceConfigurationToken": "VideoSourceToken"},
            data={"IsMotion": "true"},
        )
    ]


@pytest.mark.parametrize(
    ("topic", "item", "value", "expected"),
    [
        ("RuleEngine/CellMotionDetector/Motion", "IsMotion", "true", True),
        ("RuleEngine/CellMotionDetector/Motion", "IsMotion", "false", False),
        ("VideoSource/MotionAlarm", "State", "1", True),
        ("VideoSource/MotionAlarm", "State", "0", False),
        ("VideoSource/SignalLoss", "State", "true", None),
    ],
)
def test_motion_state(topic: str, item: str, value: str, expected: bool | None) -> None:
    assert motion_state(parse_notifications(notify(topic, item, value))[0]) is expected


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"kein xml", id="kein-xml"),
        pytest.param(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>', id="dtd"),
        pytest.param(b"<a>" + b"x" * (300 * 1024) + b"</a>", id="zu-gross"),
    ],
)
def test_parse_rejects_bad_bodies(body: bytes) -> None:
    with pytest.raises(ValueError):
        parse_notifications(body)


def test_parse_ignores_messages_without_notifications() -> None:
    assert parse_notifications(b"<s:Envelope xmlns:s='http://www.w3.org/2003/05/soap-envelope'/>") == []


async def test_subscribes_with_webhook_url(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_onvif: MagicMock
) -> None:
    mock_onvif.subscribe.assert_awaited_once_with(
        f"http://192.168.1.2:8123/api/webhook/{WEBHOOK_ID}", EVENT_SUBSCRIPTION_SECONDS
    )


async def test_webhook_updates_motion_and_fires_event(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client_no_auth: ClientSessionGenerator
) -> None:
    client = await hass_client_no_auth()
    events = async_capture_events(hass, EVENT_TYPE)

    response = await client.post(
        f"/api/webhook/{WEBHOOK_ID}", data=notify("RuleEngine/CellMotionDetector/Motion", "IsMotion", "true")
    )
    assert response.status == 200
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_ON
    assert events[0].data["topic"] == "RuleEngine/CellMotionDetector/Motion"
    assert events[0].data["data"] == {"IsMotion": "true"}
    assert events[0].data["device_id"]

    await client.post(f"/api/webhook/{WEBHOOK_ID}", data=notify("VideoSource/MotionAlarm", "State", "0"))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF


async def test_webhook_rejects_garbage(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client_no_auth: ClientSessionGenerator
) -> None:
    client = await hass_client_no_auth()
    response = await client.post(f"/api/webhook/{WEBHOOK_ID}", data=b"das ist kein xml")
    assert response.status == 400
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF


async def test_subscription_is_renewed(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_onvif: MagicMock
) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + EVENT_RENEW_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    mock_onvif.renew.assert_awaited_once_with("/onvif/Subscription?Idx=1", EVENT_SUBSCRIPTION_SECONDS)
    mock_onvif.subscribe.assert_awaited_once()


async def test_failed_renewal_subscribes_again(
    hass: HomeAssistant, setup_integration: MockConfigEntry, mock_onvif: MagicMock
) -> None:
    mock_onvif.renew.side_effect = CtronicsError("Action Not Implemented")
    async_fire_time_changed(hass, dt_util.utcnow() + EVENT_RENEW_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert mock_onvif.subscribe.await_count == 2
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF


async def test_stale_motion_is_cleared(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = await hass_client_no_auth()
    await client.post(
        f"/api/webhook/{WEBHOOK_ID}", data=notify("RuleEngine/CellMotionDetector/Motion", "IsMotion", "true")
    )
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_ON

    freezer.tick(EVENT_MOTION_TIMEOUT + EVENT_RENEW_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF


async def test_motion_unavailable_when_subscription_fails(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
) -> None:
    mock_onvif.subscribe.side_effect = CtronicsError("nein")
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_UNAVAILABLE

    # Beim nächsten Durchlauf klappt es, der Sensor wird wieder verfügbar.
    mock_onvif.subscribe.side_effect = None
    mock_onvif.subscribe.return_value = "/onvif/Subscription?Idx=2"
    async_fire_time_changed(hass, dt_util.utcnow() + EVENT_RENEW_INTERVAL + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_OFF


async def test_no_internal_url_leaves_events_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: MagicMock,
    mock_onvif: MagicMock,
) -> None:
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.ctronics_cam.events.webhook.async_generate_url", side_effect=NoURLAvailableError):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    mock_onvif.subscribe.assert_not_awaited()
    assert hass.states.get("binary_sensor.flur_motion").state == STATE_UNAVAILABLE
