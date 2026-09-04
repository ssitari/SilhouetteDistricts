#!/usr/bin/env python3
"""
Build the 1200x630 link-preview card from the national five-colour figure.

Social cards are cropped hard by every platform, so this does not reuse a
figure directly: it lifts just the map out of docs/national_outward_5c.png
(dropping matplotlib's title and subtitle), fits it to the card, and sets the
page's own title over it.

    python scripts/make_social_card.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "national_outward_5c.png"
OUT = ROOT / "docs" / "social-card.png"

W, H = 1200, 630
TITLE = "Congressional districts as nested silhouettes"
SUB = "435 districts, each the shape of its own state, each an equal share of the 2020 population"

FONTS = Path("C:/Windows/Fonts")


def font(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:
        return ImageFont.load_default()


def main():
    src = Image.open(SRC).convert("RGB")

    # Drop the figure's own title and caption, then trim to the ink.
    body = src.crop((0, 60, src.width, src.height - 70))
    mask = Image.eval(body.convert("L"), lambda v: 255 - v)
    box = mask.getbbox()
    if box:
        body = body.crop(box)

    card = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(card)

    top = 120
    avail_w, avail_h = W - 96, H - top - 28
    k = min(avail_w / body.width, avail_h / body.height)
    body = body.resize((int(body.width * k), int(body.height * k)), Image.LANCZOS)
    card.paste(body, ((W - body.width) // 2, top + (avail_h - body.height) // 2))

    d.text((48, 40), TITLE, font=font("segoeuib.ttf", 40), fill="#1a1a1a")
    d.text((48, 90), SUB, font=font("segoeui.ttf", 20), fill="#6b7280")

    card.save(OUT, optimize=True)
    print(f"  wrote {OUT.relative_to(ROOT)} {card.size} {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
