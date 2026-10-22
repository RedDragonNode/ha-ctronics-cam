"""Erzeugt Icon, Logo und Banner der Integration (Stil wie bei den anderen HA-Integrationen).

Aufruf aus dem Projektordner:  python tools/make_brand.py
Benötigt nur Pillow. Die Schrift ist Segoe UI Black (Windows); mit --font lässt sich eine andere angeben.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "custom_components" / "ctronics_cam" / "brand"
DOCS_DIR = ROOT / "docs"

BASE = 512  # Zeichenfläche des Icons
SS = 4  # Supersampling für glatte Kanten

BG_TOP = (47, 38, 112)  # #2F2670
BG_BOTTOM = (26, 16, 64)  # #1A1040
TEAL = (32, 201, 190)  # #20C9BE
NAVY = (39, 69, 127)  # #27457F
DARK = (18, 19, 56)  # #121338
CORE_DARK = (13, 14, 42)  # #0D0E2A
ORANGE = (255, 138, 31)  # #FF8A1F
LAVENDER = (143, 130, 240)  # #8F82F0
LAVENDER_LIGHT = (179, 169, 255)  # #B3A9FF
WORD_LAVENDER = (123, 108, 240)  # #7B6CF0
GREEN = (61, 220, 132)  # #3DDC84
WHITE = (255, 255, 255)


def diagonal_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Diagonaler Verlauf von oben links nach unten rechts, klein berechnet und hochskaliert."""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
    return img.resize((size, size), Image.BICUBIC)


def circle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)


def draw_icon() -> Image.Image:
    """Quadratisches Icon: Schwenk-/Neigekamera mit IR-LEDs und KI-Personen-Abzeichen."""
    s = BASE * SS

    def p(v: float) -> float:
        return v * SS

    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    bg = diagonal_gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=p(112), fill=255)
    canvas.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(canvas)
    cx, cy = 240, 250

    # Standfuß mit Schwenk-Pfeilen
    d.rounded_rectangle((p(128), p(350), p(352), p(440)), radius=p(30), fill=LAVENDER)
    d.rounded_rectangle((p(150), p(386), p(330), p(395)), radius=p(4.5), fill=LAVENDER_LIGHT)
    for sign in (-1, 1):
        x = 240 + sign * 78
        d.line(
            [(p(x - sign * 10), p(399)), (p(x + sign * 10), p(410)), (p(x - sign * 10), p(421))],
            fill=ORANGE,
            width=int(p(9)),
            joint="curve",
        )
        circle(d, p(x - sign * 10), p(399), p(4.5), ORANGE)
        circle(d, p(x - sign * 10), p(421), p(4.5), ORANGE)

    # Kopf: türkiser Ring, dunkle Scheibe, Objektiv
    circle(d, p(cx), p(cy), p(128), TEAL)
    circle(d, p(cx), p(cy), p(106), DARK)
    for angle in (45, 135, 225, 315):
        a = math.radians(angle)
        circle(d, p(cx + 92 * math.cos(a)), p(cy + 92 * math.sin(a)), p(9), ORANGE)
    circle(d, p(cx), p(cy), p(76), NAVY)
    circle(d, p(cx), p(cy), p(52), CORE_DARK)
    circle(d, p(cx), p(cy), p(26), TEAL)
    circle(d, p(cx - 9), p(cy - 9), p(8), (210, 255, 250))

    # Abzeichen oben rechts: Person erkannt
    bx, by = 408, 114
    circle(d, p(bx), p(by), p(56), (15, 16, 48))
    circle(d, p(bx), p(by), p(42), GREEN)
    person = Image.new("L", (s, s), 0)
    pd = ImageDraw.Draw(person)
    circle(pd, p(bx), p(by - 12), p(10), 255)
    pd.pieslice((p(bx - 23), p(by + 2), p(bx + 23), p(by + 48)), 180, 360, fill=255)
    clip = Image.new("L", (s, s), 0)
    circle(ImageDraw.Draw(clip), p(bx), p(by), p(42), 255)
    person = Image.composite(person, Image.new("L", (s, s), 0), clip)
    canvas.paste(Image.new("RGBA", (s, s), (15, 16, 48, 255)), (0, 0), person)

    return canvas.resize((BASE, BASE), Image.LANCZOS)


def draw_banner(icon: Image.Image, font_path: str) -> Image.Image:
    """Breiter Banner: Icon links, Name zweizeilig rechts, transparenter Hintergrund."""
    height = 440
    pad = 40
    icon_size = height - 2 * pad
    icon_small = icon.resize((icon_size, icon_size), Image.LANCZOS)

    font = ImageFont.truetype(font_path, 150)
    lines = [("Ctronics", WORD_LAVENDER), ("4K Cam", ORANGE)]
    boxes = [font.getbbox(text) for text, _ in lines]
    text_w = max(b[2] - b[0] for b in boxes)
    line_h = [b[3] - b[1] for b in boxes]
    gap = 26
    block_h = sum(line_h) + gap
    text_x = pad + icon_size + 56
    width = text_x + text_w + pad + 20

    banner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    banner.alpha_composite(icon_small, (pad, pad))
    d = ImageDraw.Draw(banner)
    y = (height - block_h) // 2
    for (text, color), box, h in zip(lines, boxes, line_h):
        d.text((text_x - box[0], y - box[1]), text, font=font, fill=color)
        y += h + gap
    return banner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default=r"C:\Windows\Fonts\seguibl.ttf")
    args = parser.parse_args()

    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    icon = draw_icon()  # 512 x 512
    icon.save(BRAND_DIR / "icon@2x.png", optimize=True)
    icon.resize((256, 256), Image.LANCZOS).save(BRAND_DIR / "icon.png", optimize=True)
    icon.save(DOCS_DIR / "icon.png", optimize=True)

    banner = draw_banner(icon, args.font)
    banner.save(DOCS_DIR / "banner.png", optimize=True)
    for name, h in (("logo.png", 256), ("logo@2x.png", 512)):
        w = round(banner.width * h / banner.height)
        banner.resize((w, h), Image.LANCZOS).save(BRAND_DIR / name, optimize=True)

    print("Fertig:", *sorted(p.relative_to(ROOT).as_posix() for p in (*BRAND_DIR.glob("*.png"), *DOCS_DIR.glob("*.png"))), sep="\n  ")


if __name__ == "__main__":
    main()
