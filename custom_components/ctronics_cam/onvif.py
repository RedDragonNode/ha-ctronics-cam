"""ONVIF-Ereignisse der Kamera: Abo per Push (Webhook), Erneuerung und Auswertung.

Die Kamera kennt kein PullPoint (`CreatePullPointSubscription` wird mit "Action Not
Implemented" abgelehnt), nimmt aber ein einfaches `wsnt:Subscribe` mit Empfängeradresse an
und schickt die Ereignisse dann per HTTP-POST dorthin.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import aiohttp

from .api import CtronicsAuthError, CtronicsConnectionError, CtronicsError

REQUEST_TIMEOUT = 10
MAX_BODY_BYTES = 256 * 1024

ACTION_SUBSCRIBE = "http://docs.oasis-open.org/wsn/bw-2/NotificationProducer/SubscribeRequest"
ACTION_RENEW = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/RenewRequest"
ACTION_UNSUBSCRIBE = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager/UnsubscribeRequest"

_URL_PATH_RE = re.compile(r"^https?://[^/]+(?P<path>/.*)$")


@dataclass(slots=True)
class OnvifEvent:
    """Eine einzelne Benachrichtigung der Kamera."""

    topic: str
    operation: str | None = None
    utc_time: str | None = None
    source: dict[str, str] = field(default_factory=dict)
    data: dict[str, str] = field(default_factory=dict)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_notifications(body: bytes) -> list[OnvifEvent]:
    """Liest die Benachrichtigungen aus einer SOAP-Nachricht.

    Der Webhook ist von jedem Gerät im LAN erreichbar, deshalb werden Größe und
    DTD/Entities abgewiesen, bevor geparst wird.
    """
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("Nachricht zu groß")
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("DTD nicht erlaubt")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as err:
        raise ValueError("Kein gültiges XML") from err

    events: list[OnvifEvent] = []
    for message in root.iter():
        if _local(message.tag) != "NotificationMessage":
            continue
        topic = ""
        inner: ET.Element | None = None
        for child in message:
            name = _local(child.tag)
            if name == "Topic":
                topic = (child.text or "").strip()
            elif name == "Message":
                inner = next((c for c in child if _local(c.tag) == "Message"), child)
        if not topic or inner is None:
            continue
        event = OnvifEvent(
            topic=topic.split(":", 1)[-1],
            operation=inner.get("PropertyOperation"),
            utc_time=inner.get("UtcTime"),
        )
        for section in inner:
            target = (
                event.source
                if _local(section.tag) == "Source"
                else event.data
                if _local(section.tag) == "Data"
                else None
            )
            if target is None:
                continue
            for item in section:
                if _local(item.tag) == "SimpleItem" and (name := item.get("Name")):
                    target[name] = item.get("Value", "")
        events.append(event)
    return events


def motion_state(event: OnvifEvent) -> bool | None:
    """Wahrheitswert, wenn die Benachrichtigung eine Bewegung meldet, sonst None."""
    if not event.topic.endswith(("CellMotionDetector/Motion", "VideoSource/MotionAlarm")):
        return None
    for value in event.data.values():
        lowered = value.strip().lower()
        if lowered in ("true", "1", "on"):
            return True
        if lowered in ("false", "0", "off"):
            return False
    return None


def _security_header(username: str, password: str) -> str:
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = os.urandom(16)
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    return (
        '<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        f"<UsernameToken><Username>{_xml_escape(username)}</Username>"
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
        f"{digest}</Password>"
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
        f"{base64.b64encode(nonce).decode()}</Nonce>"
        f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>'
        "</UsernameToken></Security>"
    )


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _envelope(username: str, password: str, body: str, action: str | None) -> str:
    addressing = f'<wsa:Action xmlns:wsa="http://www.w3.org/2005/08/addressing">{action}</wsa:Action>' if action else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f"<s:Header>{addressing}{_security_header(username, password)}</s:Header>"
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )


class OnvifEventClient:
    """Abonniert, erneuert und beendet Ereignis-Abos an der Kamera."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        netloc: str,
        username: str,
        password: str,
    ) -> None:
        """`netloc` ist Host und ONVIF-Port der Kamera, z. B. `192.168.178.30:8080`."""
        self._session = session
        self._netloc = netloc
        self._username = username
        self._password = password

    async def _post(self, path: str, body: str, action: str | None) -> ET.Element:
        envelope = _envelope(self._username, self._password, body, action)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    f"http://{self._netloc}{path}",
                    data=envelope.encode(),
                    headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                ) as response:
                    payload = await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CtronicsConnectionError(str(err) or type(err).__name__) from err
        if len(payload) > MAX_BODY_BYTES or b"<!DOCTYPE" in payload.upper():
            raise CtronicsError("Unerwartete ONVIF-Antwort")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as err:
            raise CtronicsError("ONVIF-Antwort ist kein XML") from err
        for element in root.iter():
            if _local(element.tag) == "Fault":
                reason = next((e.text for e in element.iter() if _local(e.tag) == "Text"), "ONVIF-Fehler")
                if reason and "authorized" in reason.lower():
                    raise CtronicsAuthError(reason)
                raise CtronicsError(reason or "ONVIF-Fehler")
        return root

    @staticmethod
    def _path(address: str) -> str:
        match = _URL_PATH_RE.match(address)
        if not match:
            raise CtronicsError("Ungültige Abo-Adresse")
        return match.group("path")

    async def subscribe(self, consumer_url: str, seconds: int) -> str:
        """Legt ein Push-Abo an und liefert den Pfad zum Verwalten (Erneuern, Beenden)."""
        body = (
            '<wsnt:Subscribe xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            f"<wsnt:ConsumerReference><wsa:Address>{_xml_escape(consumer_url)}</wsa:Address></wsnt:ConsumerReference>"
            f"<wsnt:InitialTerminationTime>PT{seconds}S</wsnt:InitialTerminationTime></wsnt:Subscribe>"
        )
        root = await self._post("/onvif/event_service", body, ACTION_SUBSCRIBE)
        for element in root.iter():
            if _local(element.tag) == "Address" and element.text and "Subscription" in element.text:
                return self._path(element.text.strip())
        raise CtronicsError("Die Kamera hat keine Abo-Adresse geliefert")

    async def renew(self, path: str, seconds: int) -> None:
        body = (
            '<wsnt:Renew xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2">'
            f"<wsnt:TerminationTime>PT{seconds}S</wsnt:TerminationTime></wsnt:Renew>"
        )
        await self._post(path, body, ACTION_RENEW)

    async def unsubscribe(self, path: str) -> None:
        await self._post(
            path, '<wsnt:Unsubscribe xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2"/>', ACTION_UNSUBSCRIBE
        )
