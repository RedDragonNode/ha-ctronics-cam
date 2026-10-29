"""Suche nach Ctronics-Kameras im Heimnetz.

Die DHCP-Erkennung von Home Assistant kennt die Kameras nur an der MAC-Adresse, und die hat nicht jede
Kamera mit demselben Anfang. Deshalb fragt die Einrichtung selbst jede Adresse im Netz ab. Die Weboberfläche
der Kameras verlangt ohne Zugangsdaten Anmeldung mit dem Bereich "index.html", daran sind sie erkennbar.
"""

from __future__ import annotations

import asyncio
import ipaddress

import aiohttp
from homeassistant.components import network
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_PORT, LOGGER

PROBE_TIMEOUT = 2
PROBE_CONCURRENCY = 64
# Größer als ein /24-Netz wird nicht abgesucht, sonst dauert die Suche zu lange
MIN_PREFIX_LENGTH = 24
CAMERA_REALM = 'realm="index.html"'


async def _candidate_hosts(hass: HomeAssistant) -> list[str]:
    """Alle Adressen in den Netzen der aktiven Netzwerkkarten, ohne die von Home Assistant selbst."""
    own: set[ipaddress.IPv4Address] = set()
    networks: dict[ipaddress.IPv4Network, None] = {}
    for adapter in await network.async_get_adapters(hass):
        if not adapter["enabled"]:
            continue
        for ipv4 in adapter["ipv4"]:
            address = ipaddress.IPv4Address(ipv4["address"])
            if address.is_loopback or address.is_link_local:
                continue
            own.add(address)
            prefix = max(ipv4["network_prefix"], MIN_PREFIX_LENGTH)
            networks[ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)] = None
    return [str(host) for net in networks for host in net.hosts() if host not in own]


async def _is_camera(session: aiohttp.ClientSession, host: str, port: int) -> bool:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT):
            async with session.get(f"http://{host}:{port}/", allow_redirects=False) as response:
                return response.status == 401 and CAMERA_REALM in response.headers.get("WWW-Authenticate", "")
    except (aiohttp.ClientError, TimeoutError, OSError):
        return False


async def async_find_cameras(hass: HomeAssistant, port: int = DEFAULT_PORT) -> list[str]:
    """Adressen aller Kameras im Heimnetz, die auf der Weboberfläche antworten."""
    hosts = await _candidate_hosts(hass)
    session = async_get_clientsession(hass)
    limit = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def probe(host: str) -> str | None:
        async with limit:
            return host if await _is_camera(session, host, port) else None

    found = [host for host in await asyncio.gather(*(probe(host) for host in hosts)) if host]
    LOGGER.debug("%d von %d Adressen im Heimnetz sind Kameras: %s", len(found), len(hosts), found)
    return found
