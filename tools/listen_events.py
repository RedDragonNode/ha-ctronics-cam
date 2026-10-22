"""Diagnose: nimmt ONVIF-Ereignisse der Kamera entgegen und zeigt, was sie genau schickt.

Startet einen kleinen HTTP-Server auf diesem Rechner, abonniert die Kamera darauf und gibt jede
eingehende Anfrage mit Kopfzeilen und Text aus. Mit --reply lässt sich ändern, wie geantwortet wird,
um herauszufinden, worauf die Kamera wartet. Zugangsdaten stammen aus `.env.local`.

    python tools/listen_events.py --seconds 60 --reply 200
    python tools/listen_events.py --seconds 60 --reply 202
    python tools/listen_events.py --seconds 60 --reply soap

Windows fragt beim ersten Start, ob Python eingehende Verbindungen zulassen darf (privates Netz).
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import aiohttp  # noqa: E402
import probe  # noqa: E402

from custom_components.ctronics_cam.api import CtronicsError  # noqa: E402
from custom_components.ctronics_cam.onvif import OnvifEventClient  # noqa: E402

SOAP_REPLY = (
    '<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
    "<s:Body/></s:Envelope>"
)


def make_handler(reply: str, started: float, log: list[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            t = time.time() - started
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            log.append(f"+{t:5.1f}s POST {self.path}  Content-Length={length}")
            for key, value in self.headers.items():
                log.append(f"        {key}: {value}")
            log.append(f"        --- Text ({len(body)} Byte) ---")
            for line in body.decode("utf-8", "replace").replace("><", ">\n<").splitlines()[:40]:
                log.append(f"        {line}")
            if reply == "soap":
                payload = SOAP_REPLY.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
            elif reply == "202":
                payload = b""
                self.send_response(202)
            else:
                payload = b""
                self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            return

    return Handler


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--reply", choices=["200", "202", "soap"], default="200")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--nudge", action="store_true", help="Kamera kurz schwenken, um Ereignisse auszulösen")
    args = parser.parse_args()

    env = probe.load_env()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((env["CTRONICS_HOST"], 80))
    my_ip = sock.getsockname()[0]
    sock.close()

    log: list[str] = []
    started = time.time()
    server = HTTPServer(("0.0.0.0", args.port), make_handler(args.reply, started, log))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    async with aiohttp.ClientSession() as session:
        client = OnvifEventClient(
            session,
            f"{env['CTRONICS_HOST']}:{env.get('CTRONICS_ONVIF_PORT', 8080)}",
            env["CTRONICS_USER"],
            env["CTRONICS_PASS"],
        )
        url = f"http://{my_ip}:{args.port}/api/webhook/test"
        t = time.time()
        try:
            await client.subscribe(url, args.seconds + 30)
            print(
                f"Abo angelegt nach {time.time() - t:.1f} s, antworte mit '{args.reply}', höre {args.seconds} s zu ...",
                flush=True,
            )
        except CtronicsError as err:
            print(f"Abo fehlgeschlagen nach {time.time() - t:.1f} s: {err}")
            server.shutdown()
            return
        if args.nudge:
            # Kurz schwenken, damit die Bildänderung eine Bewegungsmeldung auslöst (Kamera danach wieder zurück).
            await asyncio.sleep(5)
            cam = probe.Cam(env)
            for action in ("left", "stop", "right", "stop"):
                await asyncio.to_thread(cam.get, f"/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={action}&-speed=4")
                await asyncio.sleep(0.8 if action != "stop" else 0.4)
            print("Kamera kurz geschwenkt und zurück", flush=True)
        await asyncio.sleep(args.seconds)
        # Kein Unsubscribe: Das Abo läuft nach seiner Laufzeit von selbst ab (Abmelden kann die Kamera blockieren).
    server.shutdown()
    print("\n".join(log) if log else "Keine Anfrage der Kamera angekommen.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
