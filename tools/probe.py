"""Nur lesende Abfragen an eine Ctronics-Kamera, um Protokoll und Befehle zu erkunden.

Zugangsdaten stehen in `.env.local` (siehe `.env.local.example`), nie auf der Kommandozeile.
Es werden ausschließlich GET-Abfragen (`get*`), ONVIF-Lesebefehle und RTSP-DESCRIBE gesendet.
Passwort-ähnliche Werte werden in der Ausgabe maskiert. Rohdaten landen in `tools/out/` (von Git ignoriert).

    python tools/probe.py cgi      # Hi3510-CGI: bekannte get*-Befehle
    python tools/probe.py web      # Web-Oberfläche der Kamera nach Befehlsnamen durchsuchen
    python tools/probe.py onvif    # ONVIF: Geräteinfo, Profile, PTZ-Presets, Event-Themen
    python tools/probe.py rtsp     # RTSP-DESCRIBE für /11 und /12
    python tools/probe.py all
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "out"

GET_COMMANDS = [
    "getserverinfo", "getnetattr", "getwirelessattr", "getvideoattr", "getimageattr",
    "getircutattr", "getaudioattr", "getmdattr", "getmdalarm", "getrtspattr", "getosdattr",
    "getptzattr", "getalarmattr", "getalarmstatus", "gettimeattr", "getlanguage",
    "getsdcardinfo", "getrecattr", "getrecordattr", "getrecordscheduleattr", "getpushattr",
    "gettrackattr", "getaiattr", "getdetectattr", "getpersonattr", "gethumanattr",
    "getsmartattr", "getmotorattr", "getptzspeed", "getprivacyattr", "getcoverattr",
    "getsirenattr", "getlightattr", "getonvifattr", "getcloudattr", "getp2pattr",
    "getsetupflag", "getuserattr", "getrtmpattr", "getftpattr", "getemailattr",
]
SECRET_KEY = re.compile(r"pwd|pass|psk|secret|token|auth|key", re.I)


def load_env() -> dict[str, str]:
    path = ROOT / ".env.local"
    if not path.exists():
        sys.exit("`.env.local` fehlt. Vorlage: `.env.local.example`.")
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    for required in ("CTRONICS_HOST", "CTRONICS_USER", "CTRONICS_PASS"):
        if not env.get(required):
            sys.exit(f"`{required}` fehlt in `.env.local`.")
    return env


class Cam:
    def __init__(self, env: dict[str, str]) -> None:
        self.host = env["CTRONICS_HOST"]
        self.user = env["CTRONICS_USER"]
        self.password = env["CTRONICS_PASS"]
        self.http_port = int(env.get("CTRONICS_HTTP_PORT", 80))
        self.onvif_port = int(env.get("CTRONICS_ONVIF_PORT", 8080))
        self.rtsp_port = int(env.get("CTRONICS_RTSP_PORT", 554))
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        self.basic = f"Basic {token}"

    def get(self, path: str, port: int | None = None, timeout: float = 6) -> tuple[int, bytes]:
        url = f"http://{self.host}:{port or self.http_port}{path}"
        request = urllib.request.Request(url, headers={"Authorization": self.basic})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            return 0, str(err).encode()


def mask(text: str) -> str:
    """Maskiert Werte von `var name="wert";`-Zeilen mit passwortähnlichen Namen."""

    def repl(match: re.Match[str]) -> str:
        return match.group(0) if not SECRET_KEY.search(match.group(1)) else f'var {match.group(1)}="***";'

    return re.sub(r'var\s+(\w+)\s*=\s*"[^"]*";', repl, text)


def save(name: str, text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def probe_cgi(cam: Cam, extra: list[str] | None = None) -> None:
    report: list[str] = []
    for command in extra or GET_COMMANDS:
        if not command.startswith("get"):
            print(f"{command}: übersprungen, nur get*-Befehle sind erlaubt")
            continue
        status, body = cam.get(f"/cgi-bin/hi3510/param.cgi?cmd={command}")
        text = mask(body.decode("utf-8", "replace").strip())
        if status == 200 and text:
            block = f"== {command}\n{text}"
            print(block if len(text) < 1500 else block[:1500] + "\n[...]")
        else:
            block = f"== {command}: HTTP {status}, {'leer' if not text else text[:80]}"
        report.append(block)
    name = "cgi_extra.txt" if extra else "cgi.txt"
    save(name, "\n".join(report))
    print(f"\nRohdaten: {OUT / name}")


def probe_web(cam: Cam) -> None:
    seen: dict[str, str] = {}
    queue = ["/web/admin.html", "/web/index.html", "/index.html"]
    while queue and len(seen) < 60:
        path = queue.pop(0)
        if path in seen:
            continue
        status, body = cam.get(path)
        if status != 200:
            continue
        text = body.decode("utf-8", "replace")
        seen[path] = text
        for ref in re.findall(r"""(?:src|href)\s*=\s*["']([^"'#?]+\.(?:js|html|htm))""", text):
            full = ref if ref.startswith("/") else str(Path(path).parent.as_posix() + "/" + ref)
            queue.append(full.replace("//", "/"))
    if not seen:
        print("Keine Seiten der Web-Oberfläche erreichbar.")
        return
    commands: set[str] = set()
    scripts: set[str] = set()
    for path, text in seen.items():
        save("web_" + re.sub(r"\W+", "_", path.strip("/")) + ".txt", mask(text))
        commands.update(re.findall(r"cmd=([A-Za-z0-9_]+)", text))
        scripts.update(re.findall(r"/cgi-bin/[\w/]+\.cgi", text))
    print(f"{len(seen)} Dateien geladen:", *sorted(seen), sep="\n  ")
    print("\nBefehle (cmd=...):", *sorted(commands), sep="\n  ")
    print("\nCGI-Skripte:", *sorted(scripts), sep="\n  ")


def probe_rtsp(cam: Cam) -> None:
    for path in ("/11", "/12"):
        try:
            with socket.create_connection((cam.host, cam.rtsp_port), timeout=5) as sock:
                request = (
                    f"DESCRIBE rtsp://{cam.host}:{cam.rtsp_port}{path} RTSP/1.0\r\nCSeq: 2\r\n"
                    f"Accept: application/sdp\r\nAuthorization: {cam.basic}\r\n\r\n"
                )
                sock.sendall(request.encode())
                time.sleep(0.8)
                data = sock.recv(8192).decode("utf-8", "replace")
        except OSError as err:
            print(f"RTSP {path}: {err}")
            continue
        wanted = [ln for ln in data.splitlines() if ln.startswith(("RTSP/", "m=", "a=rtpmap", "a=framerate", "a=fmtp", "WWW-Auth"))]
        print(f"== RTSP {path}", *("  " + ln for ln in wanted), sep="\n")


NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}


def soap(cam: Cam, port: int, path: str, body: str, camera_time: str | None) -> ET.Element:
    header = ""
    if camera_time:
        nonce = os.urandom(16)
        digest = base64.b64encode(hashlib.sha1(nonce + camera_time.encode() + cam.password.encode()).digest()).decode()
        header = (
            '<s:Header><Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            f"<UsernameToken><Username>{cam.user}</Username>"
            '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
            f"{digest}</Password>"
            '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
            f"{base64.b64encode(nonce).decode()}</Nonce>"
            f'<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{camera_time}</Created>'
            "</UsernameToken></Security></s:Header>"
        )
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
        'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
        'xmlns:tt="http://www.onvif.org/ver10/schema">'
        f"{header}<s:Body>{body}</s:Body></s:Envelope>"
    )
    request = urllib.request.Request(
        f"http://{cam.host}:{port}{path}", data=envelope.encode(), headers={"Content-Type": "application/soap+xml; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return ET.fromstring(response.read())
    except urllib.error.HTTPError as err:
        return ET.fromstring(err.read() or b"<error/>")


def strip_ns(root: ET.Element) -> ET.Element:
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def probe_onvif(cam: Cam) -> None:
    now = soap(cam, cam.onvif_port, "/onvif/device_service", "<tds:GetSystemDateAndTime/>", None)
    flat = strip_ns(now)
    utc = flat.find(".//UTCDateTime")
    stamp = None
    if utc is not None:
        t = {tag: utc.findtext(f".//{tag}") for tag in ("Year", "Month", "Day", "Hour", "Minute", "Second")}
        stamp = "{Year}-{Month:0>2}-{Day:0>2}T{Hour:0>2}:{Minute:0>2}:{Second:0>2}Z".format(**t)
        print("Kamerazeit (UTC):", stamp, "| PC:", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if stamp is None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        print("Kamerazeit nicht abrufbar (Kamera verlangt schon dafür Anmeldung), verwende PC-Zeit:", stamp)
    device_path = "/onvif/device_service"

    info = strip_ns(soap(cam, cam.onvif_port, device_path, "<tds:GetDeviceInformation/>", stamp))
    print("\n== GetDeviceInformation")
    for tag in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId"):
        print(f"  {tag}: {info.findtext(f'.//{tag}')}")
    fault = info.findtext(".//Text")
    if fault:
        print("  Fehler:", fault)

    caps = strip_ns(soap(cam, cam.onvif_port, device_path, "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>", stamp))
    xaddrs = {el.tag: el.text for el in caps.iter("XAddr")}
    for parent in caps.iter():
        for child in list(parent):
            if child.tag == "XAddr":
                xaddrs[parent.tag] = child.text
    xaddrs.pop("XAddr", None)
    print("\n== Dienste (XAddr)", *(f"  {k}: {v}" for k, v in xaddrs.items()), sep="\n")

    def path_of(name: str) -> str | None:
        url = xaddrs.get(name)
        return re.sub(r"^https?://[^/]+", "", url) if url else None

    media = path_of("Media")
    token = None
    if media:
        profiles = strip_ns(soap(cam, cam.onvif_port, media, "<trt:GetProfiles/>", stamp))
        print("\n== Profile")
        for prof in profiles.iter("Profiles"):
            res = prof.find(".//VideoEncoderConfiguration/Resolution")
            enc = prof.findtext(".//VideoEncoderConfiguration/Encoding")
            size = f"{res.findtext('Width')}x{res.findtext('Height')}" if res is not None else "?"
            print(f"  {prof.get('token')}: {prof.findtext('Name')} {enc} {size}")
            token = token or prof.get("token")
    ptz = path_of("PTZ")
    if ptz and token:
        presets = strip_ns(soap(cam, cam.onvif_port, ptz, f"<tptz:GetPresets><tptz:ProfileToken>{token}</tptz:ProfileToken></tptz:GetPresets>", stamp))
        names = [(p.get("token"), p.findtext("Name")) for p in presets.iter("Preset")]
        print("\n== PTZ-Presets:", names or "keine")
    events = path_of("Events")
    if events:
        props = strip_ns(soap(cam, cam.onvif_port, events, "<tev:GetEventProperties/>", stamp))
        topics: list[str] = []

        def walk(node: ET.Element, prefix: str) -> None:
            for child in node:
                if child.tag in ("MessageDescription", "Source", "Data", "Key"):
                    continue
                path = f"{prefix}/{child.tag}" if prefix else child.tag
                if any(v == "true" for k, v in child.attrib.items() if k.endswith("topic")):
                    topics.append(path)
                walk(child, path)

        topic_set = props.find(".//TopicSet")
        if topic_set is not None:
            walk(topic_set, "")
        print("\n== Event-Themen", *(f"  {t}" for t in topics or ["keine gefunden"]), sep="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["cgi", "web", "onvif", "rtsp", "all"])
    parser.add_argument("--cmds", help="nur diese get*-Befehle abfragen (kommagetrennt), nur für `cgi`")
    args = parser.parse_args()
    cam = Cam(load_env())
    steps = {"cgi": probe_cgi, "web": probe_web, "onvif": probe_onvif, "rtsp": probe_rtsp}
    for name in steps if args.what == "all" else [args.what]:
        print(f"\n######## {name} ########")
        if name == "cgi" and args.cmds:
            probe_cgi(cam, [c.strip() for c in args.cmds.split(",") if c.strip()])
        else:
            steps[name](cam)


if __name__ == "__main__":
    main()
