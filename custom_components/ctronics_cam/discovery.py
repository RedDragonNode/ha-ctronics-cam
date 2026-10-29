"""Suche nach Ctronics-Kameras im Heimnetz.

Die DHCP-Erkennung von Home Assistant kennt die Kameras nur an der MAC-Adresse, und die hat nicht jede
Kamera mit demselben Anfang. Deshalb fragt die Integration selbst jede Adresse im Netz ab. Die Weboberfläche
der Kameras verlangt ohne Zugangsdaten Anmeldung mit dem Bereich "index.html", daran sind sie erkennbar.
Jede gefundene Kamera erscheint in Home Assistant als Entdeckung, die MAC-Adresse dazu liefert die ARP-Tabelle.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Iterable
from pathlib import Path

import aiohttp
from homeassistant.components import network
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .const import DEFAULT_PORT, DOMAIN, LOGGER

PROBE_TIMEOUT = 2
PROBE_CONCURRENCY = 64
# Größer als ein /24-Netz wird nicht abgesucht, sonst dauert die Suche zu lange
MIN_PREFIX_LENGTH = 24
CAMERA_REALM = 'realm="index.html"'
ARP_TABLE = Path("/proc/net/arp")


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


def parse_arp_table(text: str) -> dict[str, str]:
    """Liest die ARP-Tabelle von Linux (`/proc/net/arp`) als Zuordnung Adresse -> MAC-Adresse."""
    macs: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        # IP address, HW type, Flags, HW address, Mask, Device. Flags 0x0 heißt: Eintrag unvollständig
        fields = line.split()
        if len(fields) >= 4 and fields[2] != "0x0" and fields[3] != "00:00:00:00:00:00":
            macs[fields[0]] = format_mac(fields[3])
    return macs


def _read_arp_table() -> dict[str, str]:
    try:
        return parse_arp_table(ARP_TABLE.read_text(encoding="ascii"))
    except OSError:
        return {}


async def async_start_discovery_flows(hass: HomeAssistant, hosts: Iterable[str]) -> None:
    """Legt für jede Kamera eine Entdeckung an, die Home Assistant unter "Entdeckt" zeigt.

    Eine Kamera ohne bekannte MAC-Adresse (die ARP-Tabelle fehlt, etwa im Docker-Netz) bekommt keine Entdeckung,
    sie bleibt in der Auswahlliste der Einrichtung. Bereits eingerichtete Kameras und schon laufende
    Entdeckungen erledigt Home Assistant über die MAC-Adresse selbst.
    """
    hosts = list(hosts)
    if not hosts:
        return
    macs = await hass.async_add_executor_job(_read_arp_table)
    for host in hosts:
        if not (mac := macs.get(host)):
            LOGGER.debug("Zu %s ist keine MAC-Adresse bekannt, die Kamera wird nicht als Entdeckung angelegt", host)
            continue
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            {"source": SOURCE_INTEGRATION_DISCOVERY},
            {CONF_HOST: host, CONF_MAC: mac},
            discovery_key=discovery_flow.DiscoveryKey(domain=DOMAIN, key=mac, version=1),
        )


async def async_discover_cameras(hass: HomeAssistant) -> None:
    """Sucht Kameras im Heimnetz und legt für jede eine Entdeckung an."""
    await async_start_discovery_flows(hass, await async_find_cameras(hass))
