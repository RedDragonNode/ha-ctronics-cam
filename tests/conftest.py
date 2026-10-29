"""Gemeinsame Fixtures: eine gespielte Kamera ohne Netzwerkzugriff."""

from __future__ import annotations

import sys
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_socket
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ctronics_cam.const import DOMAIN

if sys.platform == "win32":
    # Nur für lokale Läufe unter Windows: Dessen Ereignisschleife legt ein lokales Socket-Paar an,
    # das die Socket-Sperre des Test-Plugins sonst blockiert. Unter Linux (CI) bleibt die Sperre aktiv.
    pytest_socket.disable_socket = lambda *args, **kwargs: None

MAC = "00:0f:97:aa:bb:cc"
HOST = "192.168.1.50"
WEBHOOK_ID = "testwebhook1"

CAMERA_VARS = {
    "model": "C6F0SpZ0N0PpL2",
    "hardVersion": "V1.0.0.1",
    "softVersion": "V30.1.60.11.88-20260204",
    "webVersion": "V3.0.7.6",
    "name": "IPCAM",
    "sdstatus": "out",
    "sdfreespace": "0",
    "sdtotalspace": "0",
    "ip": HOST,
    "macaddress": "00:0F:97:AA:BB:CC",
    "flip": "off",
    "mirror": "off",
    "night": "off",
    "infraredstat": "close",
    "smd_enable": "0",
    "smd_type": "0",
    "smd_gthresh": "50",
    "smd_rect": "1",
    "smartrack_enable": "0",
    "rtspport": "554",
    "ov_enable": "1",
    "ov_port": "8080",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lässt Home Assistant die Integration aus `custom_components` laden."""


@pytest.fixture(autouse=True)
def mock_discover_cameras() -> Generator[AsyncMock]:
    """Verhindert, dass der Start der Integration das Netz wirklich nach Kameras absucht."""
    with patch("custom_components.ctronics_cam.async_discover_cameras") as mock:
        yield mock


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Flur",
        unique_id=MAC,
        data={
            CONF_HOST: HOST,
            CONF_PORT: 80,
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "geheim",
            CONF_WEBHOOK_ID: WEBHOOK_ID,
        },
    )


@pytest.fixture
def camera_vars() -> dict[str, str]:
    """Kopie der Kameradaten, die ein Test vor dem Einrichten ändern darf."""
    return dict(CAMERA_VARS)


@pytest.fixture
def mock_api(camera_vars: dict[str, str]) -> Generator[MagicMock]:
    """Ersetzt den CGI-Client durch einen Mock, der die Kameradaten liefert."""
    with (
        patch("custom_components.ctronics_cam.CtronicsApi", autospec=True) as api_class,
        patch("custom_components.ctronics_cam.config_flow.CtronicsApi", new=api_class),
    ):
        api = api_class.return_value
        api.host = HOST
        api.username = "admin"
        api.password = "geheim"
        api.base_url = f"http://{HOST}:80"
        api.netloc = f"{HOST}:80"
        api.get_params = AsyncMock(side_effect=lambda *commands: dict(camera_vars))
        api.rtsp_url = MagicMock(side_effect=lambda port, path: f"rtsp://admin:geheim@{HOST}:{port}/{path}")
        api.snapshot = AsyncMock(return_value=b"\xff\xd8\xff jpeg")
        for method in (
            "set_params",
            "ptz",
            "ptz_move",
            "goto_preset",
            "save_preset",
            "delete_preset",
        ):
            setattr(api, method, AsyncMock())
        yield api


@pytest.fixture
def mock_onvif() -> Generator[MagicMock]:
    """Ersetzt den ONVIF-Client, die Kamera nimmt jedes Abo an."""
    with patch("custom_components.ctronics_cam.events.OnvifEventClient", autospec=True) as client_class:
        client = client_class.return_value
        client.subscribe = AsyncMock()
        yield client


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_api: MagicMock, mock_onvif: MagicMock
) -> MockConfigEntry:
    """Richtet die Integration mit der gespielten Kamera ein."""
    hass.config.internal_url = "http://192.168.1.2:8123"
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return mock_config_entry
