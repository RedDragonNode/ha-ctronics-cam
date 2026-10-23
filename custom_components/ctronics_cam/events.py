"""ONVIF-Ereignisse der Kamera über einen Webhook in Home Assistant."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.util import dt as dt_util

from .api import CtronicsApi, CtronicsError
from .const import (
    DOMAIN,
    EVENT_ISSUE_AFTER_FAILURES,
    EVENT_MAX_URL_LENGTH,
    EVENT_MOTION_TIMEOUT,
    EVENT_RESUBSCRIBE_INTERVAL,
    EVENT_RETRY_DELAYS,
    EVENT_SUBSCRIPTION_SECONDS,
    EVENT_TICK_INTERVAL,
    EVENT_TYPE,
    EVENT_WEBHOOK_ID_LENGTH,
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
        # Einträge der ersten Version haben einen langen Namen, der gekürzt benutzt wird.
        self._webhook_id: str = entry.data[CONF_WEBHOOK_ID][:EVENT_WEBHOOK_ID_LENGTH]
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []
        self._warned = False
        self._last_motion: datetime | None = None
        self._failures = 0
        self._next_subscribe_at: datetime | None = None
        self._expires_at: datetime | None = None
        self._subscribing = False

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
        """Registriert den Webhook und abonniert die Kamera im Hintergrund.

        Das erste Abo läuft als Hintergrundaufgabe, damit eine träge Kamera die Einrichtung nicht aufhält.
        """
        webhook.async_register(
            self._hass,
            DOMAIN,
            self._entry.title,
            self._webhook_id,
            self._handle_webhook,
            local_only=True,
            allowed_methods=["POST"],
        )
        self._entry.async_create_background_task(
            self._hass, self._async_subscribe(), f"{DOMAIN} {self._entry.title} Ereignis-Abo"
        )
        self._unsub_timer = async_track_time_interval(self._hass, self._async_tick, EVENT_TICK_INTERVAL)

    async def async_stop(self) -> None:
        """Beendet Webhook und Zeitgeber. Das Abo an der Kamera läuft von selbst ab (siehe const.py)."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        webhook.async_unregister(self._hass, self._webhook_id)
        self._delete_issue()
        self.subscribed = False

    @property
    def _issue_id(self) -> str:
        return f"onvif_unreachable_{self._entry.entry_id}"

    @callback
    def _create_issue(self) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="onvif_unreachable",
            translation_placeholders={"name": self._entry.title},
        )

    @callback
    def _delete_issue(self) -> None:
        ir.async_delete_issue(self._hass, DOMAIN, self._issue_id)

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
        """Legt ein neues Abo an. Bei Fehlern wächst die Pause bis zum nächsten Versuch."""
        if self._subscribing:
            return
        self._subscribing = True
        try:
            await self._async_do_subscribe()
        finally:
            self._subscribing = False

    async def _async_do_subscribe(self) -> None:
        url = self._consumer_url()
        if url is None:
            self._warn_once(
                "Keine interne Adresse von Home Assistant bekannt, Bewegungsmeldungen der Kamera %s sind aus. "
                "Bitte unter Einstellungen > System > Netzwerk eine interne URL eintragen",
                self._entry.title,
            )
            self._set_subscribed(False)
            return
        if len(url) > EVENT_MAX_URL_LENGTH:
            # Eine zu lange Adresse legt den ONVIF-Dienst der Kamera für Minuten lahm, also gar nicht erst abonnieren.
            self._next_subscribe_at = dt_util.utcnow() + timedelta(seconds=EVENT_RETRY_DELAYS[-1])
            self._warn_once(
                "Die Adresse %s ist mit %s Zeichen zu lang für die Kamera %s (höchstens %s), "
                "Bewegungsmeldungen sind aus. Bitte unter Einstellungen > System > Netzwerk "
                "eine kürzere interne URL eintragen, am besten die IP-Adresse",
                url,
                len(url),
                self._entry.title,
                EVENT_MAX_URL_LENGTH,
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
            await self._client.subscribe(url, EVENT_SUBSCRIPTION_SECONDS)
        except CtronicsError as err:
            delay = EVENT_RETRY_DELAYS[min(self._failures, len(EVENT_RETRY_DELAYS) - 1)]
            self._failures += 1
            self._next_subscribe_at = dt_util.utcnow() + timedelta(seconds=delay)
            self._warn_once(
                "ONVIF-Abo der Kamera %s fehlgeschlagen, neuer Versuch in %s s: %s", self._entry.title, delay, err
            )
            if self._failures >= EVENT_ISSUE_AFTER_FAILURES:
                self._create_issue()
            # Das letzte erfolgreiche Abo gilt noch bis zu seinem Ablauf.
            self._set_subscribed(self._expires_at is not None and dt_util.utcnow() < self._expires_at)
            return
        now = dt_util.utcnow()
        self._warned = False
        self._failures = 0
        self._delete_issue()
        self._next_subscribe_at = now + EVENT_RESUBSCRIBE_INTERVAL
        self._expires_at = now + timedelta(seconds=EVENT_SUBSCRIPTION_SECONDS)
        self._set_subscribed(True)

    async def _async_tick(self, _now: datetime) -> None:
        """Abonniert rechtzeitig neu und setzt eine hängende Bewegungsmeldung zurück."""
        now = dt_util.utcnow()
        if self._next_subscribe_at is None or now >= self._next_subscribe_at:
            await self._async_subscribe()
        if self.subscribed and self._expires_at is not None and now >= self._expires_at:
            self._set_subscribed(False)
        if self.motion and self._last_motion and now - self._last_motion > EVENT_MOTION_TIMEOUT:
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
        # Die Kamera ist ein einfacher Client: Verbindung schließen, damit sie nicht auf uns wartet.
        return web.Response(status=HTTPStatus.OK, headers={"Connection": "close"})

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
