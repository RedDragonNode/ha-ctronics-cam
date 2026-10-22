"""Tests des Diagnose-Downloads: persönliche Daten müssen geschwärzt sein."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import HOST, MAC, WEBHOOK_ID


async def test_diagnostics_redacts_private_data(
    hass: HomeAssistant, setup_integration: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)

    dump = str(diagnostics)
    for secret in ("geheim", HOST, MAC, MAC.upper(), WEBHOOK_ID, "admin"):
        assert secret not in dump

    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["camera"]["model"] == "C6F0SpZ0N0PpL2"
    assert diagnostics["events"] == {"enabled": True, "subscribed": True, "motion": False}
    assert diagnostics["ptz_speed"] == 4
