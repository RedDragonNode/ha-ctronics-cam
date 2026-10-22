"""Tests des CGI-Clients gegen gespielte HTTP-Antworten."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ctronics_cam.api import (
    CtronicsApi,
    CtronicsAuthError,
    CtronicsConnectionError,
    CtronicsError,
    parse_vars,
)
from custom_components.ctronics_cam.presets import parse_presets

HOST = "192.168.1.50"
CGI = f"http://{HOST}:80/cgi-bin/hi3510"


@pytest.fixture
async def api(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> CtronicsApi:
    return CtronicsApi(async_get_clientsession(hass), HOST, 80, "admin", "p@ss wort")


def test_parse_vars() -> None:
    text = 'var model="C6F0";\r\nvar smd_enable="1";\n\nvar leer="";\nkein treffer'
    assert parse_vars(text) == {"model": "C6F0", "smd_enable": "1", "leer": ""}


async def test_get_params_joins_commands(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=getsmdattr&cmd=getsmdex", text='var smd_enable="1";\nvar smd_type="2";\n')
    assert await api.get_params("getsmdattr", "getsmdex") == {"smd_enable": "1", "smd_type": "2"}
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Basic YWRtaW46cEBzcyB3b3J0"


async def test_set_params_prefixes_fields(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=setsmdex&-smd_gthresh=70&-smd_type=2", text="[Succeed]set ok.")
    await api.set_params("setsmdex", smd_gthresh=70, smd_type=2)
    assert aioclient_mock.call_count == 1


async def test_error_text_raises(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=setsmdattr&-smd_enable=9", text="[Error]Param error.")
    with pytest.raises(CtronicsError, match="Param error"):
        await api.set_params("setsmdattr", smd_enable=9)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, CtronicsAuthError),
        (403, CtronicsAuthError),
        (404, CtronicsConnectionError),
        (500, CtronicsConnectionError),
    ],
)
async def test_http_errors(
    api: CtronicsApi, aioclient_mock: AiohttpClientMocker, status: int, error: type[Exception]
) -> None:
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=getserverinfo", status=status)
    with pytest.raises(error):
        await api.get_params("getserverinfo")


@pytest.mark.parametrize("exc", [TimeoutError, aiohttp.ClientError])
async def test_network_errors(api: CtronicsApi, aioclient_mock: AiohttpClientMocker, exc: type[Exception]) -> None:
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=getserverinfo", exc=exc)
    with pytest.raises(CtronicsConnectionError):
        await api.get_params("getserverinfo")


async def test_ptz_and_presets(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{CGI}/ptzctrl.cgi?-step=0&-act=left&-speed=4", text="[Succeed]set ok.")
    aioclient_mock.get(f"{CGI}/ptzctrl.cgi?-step=0&-act=stop&-speed=4", text="[Succeed]set ok.")
    aioclient_mock.get(f"{CGI}/preset.cgi?-act=goto&-number=0", text="[Succeed]set ok.")
    aioclient_mock.get(f"{CGI}/preset.cgi?-act=set&-status=1&-number=9", text="[Succeed]set ok.")
    aioclient_mock.get(f"{CGI}/param.cgi?cmd=preset&-act=set&-status=0&-number=63", text="[Succeed]set ok.")

    await api.ptz_move("left", 4, 0)
    await api.goto_preset(1)
    await api.save_preset(10)
    await api.delete_preset(64)
    assert aioclient_mock.call_count == 5


async def test_ptz_move_always_stops(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{CGI}/ptzctrl.cgi?-step=0&-act=up&-speed=4", text="[Succeed]set ok.")
    aioclient_mock.get(f"{CGI}/ptzctrl.cgi?-step=0&-act=stop&-speed=4", text="[Succeed]set ok.")

    class Cancelled(Exception):
        pass

    from unittest.mock import patch

    with patch("custom_components.ctronics_cam.api.asyncio.sleep", side_effect=Cancelled), pytest.raises(Cancelled):
        await api.ptz_move("up", 4, 5)
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("-act=stop&-speed=4")


async def test_snapshot(api: CtronicsApi, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"http://{HOST}:80/tmpfs/auto.jpg", content=b"\xff\xd8\xff data")
    assert await api.snapshot() == b"\xff\xd8\xff data"


async def test_rtsp_url_quotes_credentials(api: CtronicsApi) -> None:
    assert api.rtsp_url(554, "11") == f"rtsp://admin:p%40ss%20wort@{HOST}:554/11"


async def test_ipv6_host_gets_brackets(hass: HomeAssistant) -> None:
    api = CtronicsApi(async_get_clientsession(hass), "fe80::1", 8080, "a", "b")
    assert api.base_url == "http://[fe80::1]:8080"
    assert api.rtsp_url(554, "12") == "rtsp://a:b@[fe80::1]:554/12"


def test_parse_presets() -> None:
    assert parse_presets("1: Schaukel\n\n 10 = Bett  \n") == {1: "Schaukel", 10: "Bett"}
    assert parse_presets("") == {}
    for bad in ("Schaukel", "0: zu klein", "65: zu groß", "1:"):
        with pytest.raises(ValueError):
            parse_presets(bad)
