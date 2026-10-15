#!/usr/bin/env python3
"""Static ad for BakersfieldBrief.com, photo strip layout, Hermes version.

Same words as the poster version, different structure: the headline sits on clean
ink at the top, the real photograph of downtown runs as a full width strip under
it, and the brand line closes the frame. The strip shows the Fox Theater properly
instead of cropping the tower behind the type.

The photograph is real (CC0, see PHOTO_CREDITS.md). Never swap in a generated
image here: the whole point of this layout is that the place is the real one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import make_static_ad_hermes as M  # noqa: E402

AD_DIR = Path(__file__).resolve().parent
INK = (11, 14, 21)
NAVY = (16, 22, 38)
CREAM = M.CREAM
GOLD = M.GOLD

KICKER = "BAKERSFIELD \u00b7 OVERNIGHT"
TIER1 = "SIRENS AT 3 AM."
TIER2 = ["THE STORY", "BY 6 AM."]

FEED = {
    "w": 1080, "h": 1350,
    "kicker_y": 0.062, "t1_y": 0.130, "t2_y": 0.192, "t2_size": 262,
    "strip": (0.560, 0.855), "strip_center_y": 0.58, "strip_center_x": 0.40,
    "footer_y": 0.882, "brand_size": 52, "offer_size": 27,
}
FULL = {
    "w": 1080, "h": 1920,
    "kicker_y": 0.070, "t1_y": 0.142, "t2_y": 0.206, "t2_size": 272,
    "strip": (0.556, 0.775), "strip_center_y": 0.58, "strip_center_x": 0.40,
    "footer_y": 0.800, "brand_size": 62, "offer_size": 30,
}


def ground(w: int, h: int) -> Image.Image:
    """Ink to navy, top to bottom: a dark page for the type to sit on."""
    im = Image.new("RGB", (w, h), INK)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = (y / h) ** 1.5
        d.line([(0, y), (w, y)],
               fill=tuple(round(INK[i] + (NAVY[i] - INK[i]) * t) for i in range(3)))
    return im


def strip(base: Image.Image, y0: int, y1: int, cy: float, cx: float) -> None:
    """The photograph, cropped to the strip and graded to night, feathered edges."""
    w = base.width
    win = y1 - y0
    src = Image.open(AD_DIR / M.PLATE_FILE).convert("RGB")
    s = max(w / src.width, win / src.height)
    src = src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS)
    left = int((src.width - w) * cx)
    top = int((src.height - win) * cy)
    band = M.night_grade(src.crop((left, top, left + w, top + win)))

    mask = Image.new("L", (w, win), 255)
    md = ImageDraw.Draw(mask)
    f = max(6, win // 12)
    for i in range(f):
        a = int(255 * (i / f) ** 0.7)
        md.line([(0, i), (w, i)], fill=a)
        md.line([(0, win - 1 - i), (w, win - 1 - i)], fill=a)
    base.paste(band, (0, y0), mask)
    d = ImageDraw.Draw(base)
    for y in (y0, y1 - 1):
        d.line([(0, y), (w, y)], fill=(70, 60, 40), width=2)


def compose(cfg: dict) -> Image.Image:
    w, h = cfg["w"], cfg["h"]
    im = ground(w, h)
    d = ImageDraw.Draw(im)
    margin = round(w * 0.078)
    max_w = w - 2 * margin

    kf = M.font(M.FONT_SANS, round(w * 0.028))
    ky = round(h * cfg["kicker_y"])
    r = round(kf.size * 0.20)
    d.ellipse([margin, ky + kf.size * 0.34, margin + 2 * r, ky + kf.size * 0.34 + 2 * r],
              fill=(226, 54, 46))
    kx = margin + 2 * r + round(kf.size * 0.55)
    M.draw_tracked(d, (kx, ky), KICKER, kf, M.GOLD, tracking=kf.size * 0.16)
    d.line([(margin, ky + kf.size * 1.62), (margin + max_w, ky + kf.size * 1.62)],
           fill=M.GOLD_DIM, width=max(2, w // 400))

    f1 = M.fit(TIER1, M.FONT_SANS, max_w, round(w * 0.082))
    M.gradient_text(im, TIER1, (margin, round(h * cfg["t1_y"])), f1, CREAM, (206, 200, 190))
    f2 = [M.fit(line, M.FONT_SANS, max_w, cfg["t2_size"]) for line in TIER2]
    step = round(max(f.size for f in f2) * 1.02)
    y2 = round(h * cfg["t2_y"])
    for i, (line, f) in enumerate(zip(TIER2, f2)):
        M.gradient_text(im, line, (margin, y2 + i * step), f, GOLD, CREAM,
                        glow=GOLD, glow_alpha=58)

    strip(im, round(h * cfg["strip"][0]), round(h * cfg["strip"][1]),
          cfg["strip_center_y"], cfg["strip_center_x"])

    ff = M.font(M.FONT_SERIF, cfg["brand_size"])
    by = round(h * cfg["footer_y"])
    d.text((margin, by), M.BRAND, font=ff, fill=CREAM)
    of = M.font(M.FONT_SANS, round(cfg["offer_size"] * 1.34))
    oy = round(by + ff.size * 1.70)
    M.draw_tracked(d, (margin, oy), M.OFFER_FREE, of, GOLD, tracking=of.size * 0.10)
    fx = margin + M.tracked_width(M.OFFER_FREE, of, of.size * 0.10) + round(of.size * 0.55)
    ot = M.font(M.FONT_SANS, cfg["offer_size"])
    M.draw_tracked(d, (fx, oy + round(of.size * 0.24)), M.OFFER_TAIL, ot, (232, 228, 218),
                   tracking=ot.size * 0.06)
    return im


def main() -> int:
    for name, cfg in (("1350", FEED), ("1920", FULL)):
        p = AD_DIR / f"ad_static_strip_{cfg['w']}x{cfg['h']}.png"
        compose(cfg).save(p)
        print(p, f"{cfg['w']}x{cfg['h']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
