"""Draw the IPTV Player icon and logo for HACS and the integrations page (Home Assistant 2026.3+ serves
custom_components/<domain>/brand/). PNG only, drawn with Pillow: no fonts, so it renders the same on any machine.

A dark rounded square with a TV: a screen in Home Assistant blue with a white play triangle, a stand under it, and two
short "signal" arcs over the top corner. Reads at 24 px as "a TV that plays".

    python brand/make_brand.py   -> custom_components/iptv_player/brand/{icon,icon@2x,logo,logo@2x,dark_logo,dark_logo@2x}.png
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "custom_components", "iptv_player", "brand")

DARK = (28, 32, 38, 255)
BLUE = (3, 169, 244, 255)
BLUE_DEEP = (2, 119, 189, 255)
WHITE = (255, 255, 255, 255)
GREY = (150, 160, 172, 255)


def icon(size: int, background: bool = True) -> Image.Image:
    big = size * 4                                     # draw large, then shrink: smooth edges without anti-aliasing
    s = big / 256
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(56 * s), fill=DARK)
    # signal arcs over the top right of the screen
    for r, w in ((24, 9), (44, 9)):
        box = [int((184 - r) * s), int((66 - r) * s), int((184 + r) * s), int((66 + r) * s)]
        d.arc(box, start=270, end=360, fill=GREY, width=int(w * s))
    # the screen: a bezel and a blue picture
    d.rounded_rectangle([int(28 * s), int(70 * s), int(228 * s), int(192 * s)], radius=int(16 * s), fill=WHITE)
    d.rounded_rectangle([int(40 * s), int(82 * s), int(216 * s), int(180 * s)], radius=int(9 * s), fill=BLUE)
    d.polygon([(int(40 * s), int(160 * s)), (int(216 * s), int(118 * s)), (int(216 * s), int(180 * s)), (int(40 * s), int(180 * s))], fill=BLUE_DEEP)
    # play triangle
    d.polygon([(int(110 * s), int(103 * s)), (int(110 * s), int(159 * s)), (int(156 * s), int(131 * s))], fill=WHITE)
    # stand
    d.rectangle([int(118 * s), int(192 * s), int(138 * s), int(212 * s)], fill=WHITE)
    d.rounded_rectangle([int(82 * s), int(208 * s), int(174 * s), int(222 * s)], radius=int(7 * s), fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    icon(256).save(os.path.join(OUT, "icon.png"))
    icon(512).save(os.path.join(OUT, "icon@2x.png"))
    # the logo is the icon on its own (the brands guidelines allow a logo without a word mark), for light and dark
    for name, size in (("logo.png", 256), ("logo@2x.png", 512), ("dark_logo.png", 256), ("dark_logo@2x.png", 512)):
        icon(size).save(os.path.join(OUT, name))
    print("written:", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
