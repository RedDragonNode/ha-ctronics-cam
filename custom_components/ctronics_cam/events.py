"""ONVIF-Ereignisse der Kamera über einen Webhook in Home Assistant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util import dt as dt_util

from .api import CtronicsApi, CtronicsError
from .const import (
    DOMAIN,
    EVENT_MOTION_TIMEOUT,
    EVENT_RENEW_INTERVAL,
    EVENT_SUBSCRIPTION_SECONDS,
    EVENT_TYPE,
    LOGGER,
)
from .onvif import OnvifEvent, OnvifEventClient, motion_state, parse_notifications

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


class CtronicsEvents:
    """Hält das Ereignis-Abo der Kamera am Leben und verteilt die Meldungen."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: CtronicsApi, onvif_port: int) -> None:
        self._hass = hass
        self._entry = entry
        host = f"[{api.host}]" if ":" in api.host else api.host
        self._client = OnvifEventClient(
            async_get_clientsession(hass), f"{host}:{onvif_port}", api.username, api.password
        )
        self._webhook_id: str = entry.data[CONF_WEBHOOK_ID]
        self._subscription_path: str | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []
        self._warned = False
        self._last_motion: datetime | None = None

        self.motion: bool | None = None
        self.subscribed = False

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Meldet einen Empfänger für Änderungen an Bewegung und Abo-Status an."""
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    async def async_start(self) -> None:
        """Registriert den Webhook und abonniert die Kamera."""
        webhook.async_register(
            self._hass,
            DOMAIN,
            self._entry.title,
            self._webhook_id,
            self._handle_webhook,
            local_only=True,
            allowed_methods=["POST"],
        )
        await self._async_subscribe()
        self._unsub_timer = async_track_time_interval(self._hass, self._async_tick, EVENT_RENEW_INTERVAL)

    async def async_stop(self) -> None:
        """Beendet Abo und Webhook."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        webhook.async_unregister(self._hass, self._webhook_id)
        if self._subscription_path:
            try:
                await self._client.unsubscribe(self._subscription_path)
            except CtronicsError as err:
                LOGGER.debug("Abo konnte nicht beendet werden: %s", err)
            self._subscription_path = None
        self.subscribed = False

    def _consumer_url(self) -> str | None:
        try:
            return webhook.async_generate_url(self._hass, self._webhook_id, allow_external=False, allow_ip=True)
        except NoURLAvailableError:
            return None

    def _warn_once(self, message: str, *args: object) -> None:
        if not self._warned:
            self._warned = True
            LOGGER.warning(message, *args)
        else:
            LOGGER.debug(message, *args)

    async def _async_subscribe(self) -> None:
        url = self._consumer_url()
        if url is None:
            self._warn_once(
                "Keine interne Adresse von Home Assistant bekannt, Bewegungsmeldungen der Kamera %s sind aus. "
                "Bitte unter Einstellungen > System > Netzwerk eine interne URL eintragen",
                self._entry.title,
            )
            self._set_subscribed(False)
            return
        if urlparse(url).scheme != "http":
            self._warn_once(
                "Die interne Adresse %s nutzt HTTPS, die Kamera %s kann Ereignisse nur per HTTP zustellen",
                url,
                self._entry.title,
            )
        try:
            self._subscription_path = await self._client.subscribe(url, EVENT_SUBSCRIPTION_SECONDS)
        except CtronicsError as err:
            self._subscription_path = None
            self._warn_once("ONVIF-Abo der Kamera %s fehlgeschlagen: %s", self._entry.title, err)
            self._set_subscribed(False)
            return
        self._warned = False
        self._set_subscribed(True)

    async def _async_tick(self, _now: datetime) -> None:
        """Erneuert das Abo und setzt eine hängende Bewegungsmeldung zurück."""
        if self._subscription_path:
            try:
                await self._client.renew(self._subscription_path, EVENT_SUBSCRIPTION_SECONDS)
            except CtronicsError as err:
                LOGGER.debug("Abo-Erneuerung fehlgeschlagen, abonniere neu: %s", err)
                self._subscription_path = None
        if not self._subscription_path:
            await self._async_subscribe()
        if self.motion and self._last_motion and dt_util.utcnow() - self._last_motion > EVENT_MOTION_TIMEOUT:
            self._set_motion(False)

    @callback
    def _set_subscribed(self, subscribed: bool) -> None:
        if subscribed and self.motion is None:
            self.motion = False
        if self.subscribed != subscribed:
            self.subscribed = subscribed
            self._notify()

    @callback
    def _set_motion(self, motion: bool) -> None:
        self._last_motion = dt_util.utcnow()
        if self.motion != motion:
            self.motion = motion
            self._notify()

    async def _handle_webhook(self, hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        try:
            events = parse_notifications(await request.read())
        except ValueError as err:
            LOGGER.debug("Ungültige Ereignis-Nachricht: %s", err)
            return web.Response(status=HTTPStatus.BAD_REQUEST)
        for event in events:
            self._process(event)
        return web.Response(status=HTTPStatus.OK)

    @callback
    def _process(self, event: OnvifEvent) -> None:
        LOGGER.debug(
            "ONVIF-Ereignis %s (%s) quelle=%s daten=%s", event.topic, event.operation, event.source, event.data
        )
        device = dr.async_get(self._hass).async_get_device_by_identifier(
            (DOMAIN, self._entry.unique_id or ""), self._entry.entry_id
        )
        self._hass.bus.async_fire(
            EVENT_TYPE,
            {
                "device_id": device.id if device else None,
                "topic": event.topic,
                "operation": event.operation,
                "source": event.source,
                "data": event.data,
            },
        )
        if (motion := motion_state(event)) is not None:
            self._set_motion(motion)
