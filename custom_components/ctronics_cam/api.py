"""Client für die Hi3510-CGI der Ctronics-Kameras (HTTP, lokal)."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import aiohttp

from .const import DEFAULT_PTZ_SPEED

REQUEST_TIMEOUT = 10

_VAR_RE = re.compile(r'var\s+(\w+)\s*=\s*"([^"]*)";')


class CtronicsError(Exception):
    """Allgemeiner Fehler bei der Kommunikation mit der Kamera."""


class CtronicsAuthError(CtronicsError):
    """Benutzername oder Passwort wurden abgelehnt."""


class CtronicsConnectionError(CtronicsError):
    """Die Kamera ist nicht erreichbar oder antwortet nicht."""


def parse_vars(text: str) -> dict[str, str]:
    """Liest die Zeilen `var name="wert";` einer CGI-Antwort."""
    return dict(_VAR_RE.findall(text))


class CtronicsApi:
    """Spricht mit der CGI der Kamera."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._headers = {"Authorization": aiohttp.encode_basic_auth(username, password)}
        self.ptz_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        return self._host

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password

    @property
    def netloc(self) -> str:
        """Host mit Port, bei IPv6 in eckigen Klammern."""
        host = f"[{self._host}]" if ":" in self._host else self._host
        return f"{host}:{self._port}"

    @property
    def base_url(self) -> str:
        return f"http://{self.netloc}"

    async def _request(self, path: str) -> bytes:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(f"{self.base_url}{path}", headers=self._headers) as response:
                    if response.status in (401, 403):
                        raise CtronicsAuthError("Zugangsdaten abgelehnt")
                    if response.status != 200:
                        raise CtronicsConnectionError(f"HTTP {response.status}")
                    return await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CtronicsConnectionError(str(err) or type(err).__name__) from err

    @staticmethod
    def _check_ok(text: str) -> None:
        if "[Error]" in text or "[Failed]" in text:
            raise CtronicsError(text.strip())

    async def get_params(self, *commands: str) -> dict[str, str]:
        """Fragt einen oder mehrere `get*`-Befehle in einer Anfrage ab."""
        query = "&".join(f"cmd={command}" for command in commands)
        body = await self._request(f"/cgi-bin/hi3510/param.cgi?{query}")
        text = body.decode("utf-8", "replace")
        self._check_ok(text)
        return parse_vars(text)

    async def set_params(self, command: str, **params: str | int) -> None:
        """Sendet einen `set*`-Befehl, die Felder bekommen das Präfix `-`."""
        query = f"cmd={command}" + "".join(f"&-{key}={quote(str(value), safe='')}" for key, value in params.items())
        body = await self._request(f"/cgi-bin/hi3510/param.cgi?{query}")
        self._check_ok(body.decode("utf-8", "replace"))

    async def ptz(self, action: str, speed: int = DEFAULT_PTZ_SPEED, step: int = 0) -> None:
        """PTZ-Aktion: up, down, left, right, home, stop, hscan, vscan.

        `step=0` bewegt dauerhaft bis `stop`, `step=1` macht einen Einzelschritt.
        """
        body = await self._request(f"/cgi-bin/hi3510/ptzctrl.cgi?-step={step}&-act={action}&-speed={speed}")
        self._check_ok(body.decode("utf-8", "replace"))

    async def ptz_move(self, action: str, speed: int, duration: float) -> None:
        """Bewegt die Kamera `duration` Sekunden in eine Richtung und hält sie dann an."""
        async with self.ptz_lock:
            await self.ptz(action, speed)
            try:
                await asyncio.sleep(duration)
            finally:
                await self.ptz("stop", speed)

    async def goto_preset(self, number: int) -> None:
        """Fährt eine Preset-Position an. `number` zählt ab 1."""
        body = await self._request(f"/cgi-bin/hi3510/preset.cgi?-act=goto&-number={number - 1}")
        self._check_ok(body.decode("utf-8", "replace"))

    async def save_preset(self, number: int) -> None:
        """Speichert die aktuelle Position unter `number` (ab 1)."""
        body = await self._request(f"/cgi-bin/hi3510/preset.cgi?-act=set&-status=1&-number={number - 1}")
        self._check_ok(body.decode("utf-8", "replace"))

    async def delete_preset(self, number: int) -> None:
        """Löscht die Preset-Position `number` (ab 1)."""
        await self.set_params_raw(f"cmd=preset&-act=set&-status=0&-number={number - 1}")

    async def set_params_raw(self, query: str) -> None:
        body = await self._request(f"/cgi-bin/hi3510/param.cgi?{query}")
        self._check_ok(body.decode("utf-8", "replace"))

    async def snapshot(self) -> bytes:
        """Aktuelles Standbild als JPEG in voller Auflösung."""
        return await self._request("/tmpfs/auto.jpg")

    def rtsp_url(self, port: int, path: str) -> str:
        """RTSP-Adresse mit Zugangsdaten, wie sie ffmpeg und `stream` erwarten."""
        user = quote(self._username, safe="")
        password = quote(self._password, safe="")
        host = f"[{self._host}]" if ":" in self._host else self._host
        return f"rtsp://{user}:{password}@{host}:{port}/{path}"
