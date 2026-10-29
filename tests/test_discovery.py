"""Tests der Netzsuche nach Kameras."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ctronics_cam.const import DOMAIN
from custom_components.ctronics_cam.discovery import (
    _candidate_hosts,
    async_discover_cameras,
    async_find_cameras,
    async_start_discovery_flows,
    parse_arp_table,
)

CAMERA_HEADERS = {"WWW-Authenticate": 'Basic realm="index.html"'}


def _adapter(address: str, prefix: int, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "name": "eth0",
        "enabled": enabled,
        "auto": True,
        "default": enabled,
        "ipv4": [{"address": address, "network_prefix": prefix}],
        "ipv6": [],
    }


def _patch_adapters(*adapters: dict[str, Any]):
    return patch("custom_components.ctronics_cam.discovery.network.async_get_adapters", return_value=list(adapters))


async def test_find_cameras_returns_only_hosts_that_ask_for_the_camera_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get("http://192.168.1.1/", status=401, headers=CAMERA_HEADERS)
    aioclient_mock.get("http://192.168.1.3/", status=401, headers={"WWW-Authenticate": 'Basic realm="router"'})
    aioclient_mock.get("http://192.168.1.4/", status=200, text="<html></html>")
    aioclient_mock.get("http://192.168.1.5/", exc=aiohttp.ClientError)
    aioclient_mock.get("http://192.168.1.6/", exc=TimeoutError)

    with _patch_adapters(_adapter("192.168.1.2", 29)):
        assert await async_find_cameras(hass) == ["192.168.1.1"]


async def test_find_cameras_uses_the_given_port(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get("http://192.168.1.1:8000/", status=401, headers=CAMERA_HEADERS)

    with (
        _patch_adapters(_adapter("192.168.1.2", 30)),
        patch("custom_components.ctronics_cam.discovery._candidate_hosts", return_value=["192.168.1.1"]),
    ):
        assert await async_find_cameras(hass, port=8000) == ["192.168.1.1"]


async def test_find_cameras_without_network_adapters_finds_nothing(hass: HomeAssistant) -> None:
    with _patch_adapters():
        assert await async_find_cameras(hass) == []


async def test_candidates_skip_own_address_and_inactive_adapters(hass: HomeAssistant) -> None:
    with _patch_adapters(
        _adapter("192.168.1.2", 29),
        _adapter("10.0.0.5", 24, enabled=False),
        _adapter("127.0.0.1", 8),
        _adapter("169.254.3.4", 16),
    ):
        assert await _candidate_hosts(hass) == [
            "192.168.1.1",
            "192.168.1.3",
            "192.168.1.4",
            "192.168.1.5",
            "192.168.1.6",
        ]


async def test_candidates_never_exceed_one_class_c_network(hass: HomeAssistant) -> None:
    with _patch_adapters(_adapter("10.1.2.3", 16)):
        hosts = await _candidate_hosts(hass)

    assert len(hosts) == 253
    assert all(host.startswith("10.1.2.") for host in hosts)
    assert "10.1.2.3" not in hosts


async def test_candidates_list_a_shared_network_once(hass: HomeAssistant) -> None:
    with _patch_adapters(_adapter("192.168.1.2", 29), _adapter("192.168.1.3", 29)):
        hosts = await _candidate_hosts(hass)

    assert hosts == ["192.168.1.1", "192.168.1.4", "192.168.1.5", "192.168.1.6"]


ARP_TABLE = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.1      0x1         0x2         d4:5d:64:d8:00:f0     *        end0
192.168.1.30     0x1         0x2         00:0F:97:D5:67:3A     *        end0
192.168.1.77     0x1         0x0         00:00:00:00:00:00     *        end0
192.168.1.78     0x1         0x2         00:00:00:00:00:00     *        end0
"""

MACS = {"192.168.1.30": "00:0f:97:d5:67:3a", "192.168.1.35": "00:9a:7f:a1:f0:36"}


def test_parse_arp_table_keeps_complete_entries_in_lower_case() -> None:
    assert parse_arp_table(ARP_TABLE) == {"192.168.1.1": "d4:5d:64:d8:00:f0", "192.168.1.30": "00:0f:97:d5:67:3a"}


def test_parse_arp_table_of_an_empty_file_is_empty() -> None:
    assert parse_arp_table("") == {}


async def _discovery_flows(hass: HomeAssistant) -> dict[str, str]:
    """Adresse je MAC-Adresse der laufenden Entdeckungen."""
    await hass.async_block_till_done(wait_background_tasks=True)
    return {
        flow["context"]["unique_id"]: flow["context"]["title_placeholders"]["host"]
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"]["source"] == SOURCE_INTEGRATION_DISCOVERY
    }


async def test_start_discovery_flows_creates_one_flow_per_camera_with_a_known_mac(hass: HomeAssistant) -> None:
    with patch("custom_components.ctronics_cam.discovery._read_arp_table", return_value=MACS):
        await async_start_discovery_flows(hass, ["192.168.1.30", "192.168.1.35", "192.168.1.99"])

    assert await _discovery_flows(hass) == {
        "00:0f:97:d5:67:3a": "192.168.1.30",
        "00:9a:7f:a1:f0:36": "192.168.1.35",
    }


async def test_start_discovery_flows_twice_does_not_double_the_cards(hass: HomeAssistant) -> None:
    with patch("custom_components.ctronics_cam.discovery._read_arp_table", return_value=MACS):
        await async_start_discovery_flows(hass, ["192.168.1.30"])
        await _discovery_flows(hass)
        await async_start_discovery_flows(hass, ["192.168.1.30"])

    await _discovery_flows(hass)
    assert len(hass.config_entries.flow.async_progress_by_handler(DOMAIN)) == 1


async def test_start_discovery_flows_skips_cameras_that_are_set_up(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    macs = {"192.168.1.50": "00:0f:97:aa:bb:cc", "192.168.1.35": "00:9a:7f:a1:f0:36"}
    with patch("custom_components.ctronics_cam.discovery._read_arp_table", return_value=macs):
        await async_start_discovery_flows(hass, ["192.168.1.50", "192.168.1.35"])

    assert await _discovery_flows(hass) == {"00:9a:7f:a1:f0:36": "192.168.1.35"}


async def test_start_discovery_flows_without_cameras_does_not_read_the_arp_table(hass: HomeAssistant) -> None:
    with patch("custom_components.ctronics_cam.discovery._read_arp_table") as read:
        await async_start_discovery_flows(hass, [])

    read.assert_not_called()


async def test_discover_cameras_starts_a_flow_for_every_camera_found(hass: HomeAssistant) -> None:
    with (
        patch("custom_components.ctronics_cam.discovery.async_find_cameras", return_value=["192.168.1.30"]) as find,
        patch("custom_components.ctronics_cam.discovery.async_start_discovery_flows") as start,
    ):
        await async_discover_cameras(hass)

    find.assert_awaited_once_with(hass)
    start.assert_awaited_once_with(hass, ["192.168.1.30"])
