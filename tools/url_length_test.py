"""Diagnose: prüft, ob die Länge der Empfängeradresse den ONVIF-Dienst der Kamera blockiert.

Abonniert die Kamera mit einer Adresse, deren Webhook-Name die gewünschte Länge hat, schwenkt sie kurz
(das löst Bewegungsmeldungen aus, die die Kamera an die Adresse schickt) und prüft danach, ob der
ONVIF-Dienst der Kamera noch antwortet. Hängt er, braucht er rund 8 Minuten, bis er sich erholt.

    python tools/url_length_test.py --host-url http://192.168.178.53:8123 --id-length 16
    python tools/url_length_test.py --host-url http://192.168.178.53:8123 --id-length 64
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import aiohttp  # noqa: E402
import probe  # noqa: E402

from custom_components.ctronics_cam.api import CtronicsError  # noqa: E402
from custom_components.ctronics_cam.onvif import OnvifEventClient  # noqa: E402


def onvif_answers(cam: probe.Cam) -> str:
    started = time.time()
    try:
        probe.soap(cam, cam.onvif_port, "/onvif/device_service", "<tds:GetDeviceInformation/>", probe.now_stamp())
    except Exception:
        return f"HÄNGT (nach {time.time() - started:.0f} s)"
    return f"ok ({time.time() - started:.1f} s)"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--host-url", required=True, help="Adresse von Home Assistant, z. B. http://192.168.178.53:8123"
    )
    parser.add_argument("--id-length", type=int, required=True, help="Länge des (nicht vorhandenen) Webhook-Namens")
    args = parser.parse_args()

    env = probe.load_env()
    cam = probe.Cam(env)
    url = f"{args.host_url}/api/webhook/{secrets.token_hex(args.id_length)[: args.id_length]}"
    print(f"Empfängeradresse mit {len(url)} Zeichen: {url[:50]}...", flush=True)

    async with aiohttp.ClientSession() as session:
        client = OnvifEventClient(
            session,
            f"{env['CTRONICS_HOST']}:{env.get('CTRONICS_ONVIF_PORT', 8080)}",
            env["CTRONICS_USER"],
            env["CTRONICS_PASS"],
        )
        try:
            await client.subscribe(url, 60)
        except CtronicsError as err:
            print(f"Abo fehlgeschlagen: {err}")
            return
        print("Abo angelegt, schwenke die Kamera kurz ...", flush=True)
        await asyncio.sleep(2)
        for action in ("left", "stop", "right", "stop"):
            await asyncio.to_thread(cam.get, f"/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={action}&-speed=4")
            await asyncio.sleep(0.8 if action != "stop" else 0.4)
        for i in range(5):
            print(f"  +{i * 4} s nach dem Schwenk: ONVIF {await asyncio.to_thread(onvif_answers, cam)}", flush=True)
            await asyncio.sleep(4)


if __name__ == "__main__":
    asyncio.run(main())
