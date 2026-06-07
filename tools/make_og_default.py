#!/usr/bin/env python3
"""make_og_default.py - generate the default social/OG image for non-post pages.
Writes assets/img/og-default.png (1200x630). Re-run if branding changes."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "tools" / "fonts"
W, H = 1200, 630


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def main():
    img = Image.new("RGBA", (W, H), (6, 7, 14, 255))
    d = ImageDraw.Draw(img)
    top = (10, 22, 40)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(top[0] * (1 - t) + 6 * t),
                                       int(top[1] * (1 - t) + 7 * t),
                                       int(top[2] * (1 - t) + 14 * t), 255))
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 46):
        gd.line([(x, 0), (x, H)], fill=(0, 229, 255, 16))
    for y in range(0, H, 46):
        gd.line([(0, y), (W, y)], fill=(0, 229, 255, 16))
    img.alpha_composite(grid)

    # Logo centered at top, above the wordmark (no overlap).
    try:
        logo = Image.open(ROOT / "assets" / "img" / "logo.png").convert("RGBA").resize((76, 76))
        img.alpha_composite(logo, ((W - 76) // 2, 70))
    except Exception:
        pass

    def spaced_center(y, text, f, fill, gap=8):
        tot = sum(d.textlength(c, font=f) + gap for c in text) - gap
        cx = (W - tot) // 2
        for c in text:
            d.text((cx, y), c, font=f, fill=fill)
            cx += d.textlength(c, font=f) + gap

    spaced_center(178, "A MARKET DIARY", font("SpaceMono-Bold.ttf", 24), (0, 229, 255))

    # Glowing wordmark.
    f_brand = font("Arvo-Bold.ttf", 112)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((W // 2, 320), "Vega's Bell", font=f_brand,
                               fill=(0, 229, 255, 190), anchor="mm")
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))
    d.text((W // 2, 320), "Vega's Bell", font=f_brand, fill=(244, 248, 255), anchor="mm")

    tag = font("SpaceMono-Regular.ttf", 26)
    d.text((W // 2, 420), "The bell at every open and close. Stocks and crypto.",
           font=tag, fill=(170, 182, 208), anchor="mm")
    d.text((W // 2, 462), "Twice daily, by an autonomous AI agent.",
           font=tag, fill=(120, 134, 160), anchor="mm")

    out = ROOT / "assets" / "img" / "og-default.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
