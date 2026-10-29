"""Tests der Netzsuche nach Kameras."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ctronics_cam.discovery import _candidate_hosts, async_find_cameras

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
