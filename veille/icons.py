"""Icônes de l'application (écran d'accueil du téléphone) : un écran radar."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BG, ACCENT, RED = (7, 12, 20), (47, 184, 255), (255, 59, 78)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#070c14"/>
<circle cx="32" cy="32" r="22" fill="#0b1a2c" stroke="#2fb8ff" stroke-width="3"/>
<circle cx="32" cy="32" r="13" fill="none" stroke="#2fb8ff" stroke-opacity=".4" stroke-width="1.5"/>
<path d="M32 32 L32 10 A22 22 0 0 1 51 21 Z" fill="#2fb8ff" fill-opacity=".55"/>
<circle cx="42" cy="22" r="3" fill="#ff3b4e"/>
</svg>
"""


def _png(size: int) -> Image.Image:
    scale = 4  # dessin en grand puis réduction, pour des bords lisses
    s = size * scale
    img = Image.new("RGB", (s, s), BG)
    d = ImageDraw.Draw(img)
    c, r = s / 2, s * 0.36  # marge suffisante pour les icônes « maskable »
    d.ellipse([c - r, c - r, c + r, c + r], fill=(11, 26, 44), outline=ACCENT, width=int(s * 0.03))
    r2 = r * 0.58
    d.ellipse([c - r2, c - r2, c + r2, c + r2], outline=(28, 92, 128), width=int(s * 0.012))
    d.pieslice([c - r, c - r, c + r, c + r], start=-90, end=-30, fill=(30, 120, 168))
    b = s * 0.035
    bx, by = c + r * 0.45, c - r * 0.5
    d.ellipse([bx - b, by - b, bx + b, by + b], fill=RED)
    return img.resize((size, size), Image.LANCZOS)


def write_icons(out: Path) -> None:
    (out / "icon.svg").write_text(SVG, encoding="utf-8")
    for size in (192, 512):
        _png(size).save(out / f"icon-{size}.png", optimize=True)
