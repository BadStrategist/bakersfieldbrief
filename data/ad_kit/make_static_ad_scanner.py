#!/usr/bin/env python3
"""Static ad for BakersfieldBrief.com, night desk scanner hero.

The structure follows the reference poster the owner sent: two tiers of centred
type high in the frame over clean darkness, the subject photograph filling the
rest, then the brand and the offer at the foot. The words are Claude's idea,
kept: you slept, we listened.

The hero is a generated night photograph of two digital scanners on a desk.
It is an illustration of a device, not a claim about a real place, and it
carries no brand marks. Do not put a real photograph of Bakersfield in here,
and do not use this hero on an ad that says the photo is Bakersfield.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw  # noqa: E402

import make_static_ad_hermes as M  # noqa: E402

AD_DIR = Path(__file__).resolve().parent
HERO = "scanner_hero_night.png"
INK = (7, 9, 14)

KICKER = "THE KERN OVERNIGHT"
TIER1 = "YOU SLEPT."
TIER2 = ["WE", "LISTENED."]
SUPPORT = "Overnight scanner calls, roads and weather, every morning."

FEED = {
    "w": 1080, "h": 1350,
    "hero_scale": None,          # fill the width
    "hero_top": 250,             # crop the hero's empty black, lift the desk in
    "band": 0.440, "kicker_y": 0.058, "kicker_size": 0.026,
    "t1_y": 0.108, "t1_cap": 0.086,
    "t2_y": 0.180, "t2_step": 0.168, "t2_cap": 0.218,
    "footer_y": 0.800, "brand_size": 46, "support_size": 25,
    "offer_size": 32, "fade": 0.680, "margin": 0.070,
}
FULL = {
    "w": 1080, "h": 1920,
    "hero_scale": None,
    "hero_top": 120,
    "band": 0.420, "kicker_y": 0.054, "kicker_size": 0.027,
    "t1_y": 0.104, "t1_cap": 0.092,
    "t2_y": 0.174, "t2_step": 0.166, "t2_cap": 0.238,
    "footer_y": 0.800, "brand_size": 58, "support_size": 28,
    "offer_size": 38, "fade": 0.655, "margin": 0.070,
}


def hero(base: Image.Image, cfg: dict) -> None:
    """The night desk photograph, filling the frame under the type."""
    w, h = base.width, base.height
    src = Image.open(AD_DIR / HERO).convert("RGB")
    s = cfg["hero_scale"] or (w / src.width)
    src = src.resize((round(src.width * s), round(src.height * s)), Image.LANCZOS)
    if src.height < h:
        s2 = h / src.height
        src = src.resize((round(src.width * s2), h), Image.LANCZOS)
    left = max(0, (src.width - w) // 2)
    top = cfg["hero_top"]
    top = max(0, min(top, src.height - h))
    base.paste(src.crop((left, top, left + w, top + h)), (0, 0))


def band(base: Image.Image, bottom: int) -> None:
    """Feathered ink over the top of the frame so the type never fights the photo."""
    w = base.width
    grad = Image.new("L", (1, bottom), 0)
    gd = ImageDraw.Draw(grad)
    feather = max(40, bottom // 4)
    for y in range(bottom):
        if y < bottom - feather:
            grad.putpixel((0, y), 255)
        else:
            t = (bottom - y) / feather
            grad.putpixel((0, y), int(255 * (t ** 0.8)))
    base.paste(Image.new("RGB", (w, bottom), INK), (0, 0), grad.resize((w, bottom)))


def fade(base: Image.Image, top: int) -> None:
    """The photograph dissolving into ink at the foot, so the footer always reads."""
    w, h = base.width, base.height
    span = h - top
    grad = Image.new("L", (1, span), 0)
    for y in range(span):
        t = y / max(1, span - 1)
        grad.putpixel((0, y), int(255 * min(1.0, (t / 0.62) ** 0.85)))
    base.paste(Image.new("RGB", (w, span), INK), (0, top), grad.resize((w, span)))


def compose(cfg: dict) -> Image.Image:
    w, h = cfg["w"], cfg["h"]
    im = Image.new("RGB", (w, h), INK)
    hero(im, cfg)
    band(im, round(h * cfg["band"]))
    d = ImageDraw.Draw(im)
    margin = round(w * cfg["margin"])
    max_w = w - 2 * margin

    def centred(text: str, f, y: int, fill, **kw) -> None:
        tw = d.textlength(text, font=f)
        M.gradient_text(im, text, (round((w - tw) / 2), y), f, fill, fill, **kw)

    kf = M.font(M.FONT_SANS, round(w * cfg["kicker_size"]))
    ky = round(h * cfg["kicker_y"])
    tr = kf.size * 0.16
    kw = M.tracked_width(KICKER, kf, tr)
    r = round(kf.size * 0.22)
    kx = round((w - kw) / 2)
    d.ellipse([kx - r * 3, ky + kf.size * 0.30, kx - r, ky + kf.size * 0.30 + 2 * r],
              fill=(226, 54, 46))
    M.draw_tracked(d, (kx, ky), KICKER, kf, M.GOLD, tracking=tr)

    f1 = M.fit(TIER1, M.FONT_SANS, max_w, round(w * cfg["t1_cap"]))
    t1w = d.textlength(TIER1, font=f1)
    centred(TIER1, f1, round(h * cfg["t1_y"]), M.CREAM, glow=(120, 120, 130), glow_alpha=30)

    y2 = round(h * cfg["t2_y"])
    step = round(h * cfg["t2_step"])
    f2 = [M.fit(line, M.FONT_SANS, max_w, round(w * cfg["t2_cap"])) for line in TIER2]
    for i, (line, f) in enumerate(zip(TIER2, f2)):
        centred(line, f, y2 + i * step, M.GOLD, glow=M.GOLD, glow_alpha=64)

    fade(im, round(h * cfg["fade"]))
    d = ImageDraw.Draw(im)
    ff = M.font(M.FONT_SERIF, cfg["brand_size"])
    by = round(h * cfg["footer_y"])
    d.text((margin, by), M.BRAND, font=ff, fill=M.CREAM)
    sf = M.font(M.FONT_SANS, cfg["support_size"])
    d.text((margin, by + round(ff.size * 1.42)), SUPPORT, font=sf, fill=(198, 194, 186))
    of = M.font(M.FONT_SANS, cfg["offer_size"])
    otr = of.size * 0.10
    ow = M.tracked_width(M.OFFER_FREE, of, otr)
    oy = by + round(ff.size * 1.42) + round(sf.size * 2.05)
    M.draw_tracked(d, (margin, oy), M.OFFER_FREE, of, M.GOLD, tracking=otr)
    ot = M.font(M.FONT_SANS, round(cfg["offer_size"] * 0.80))
    M.draw_tracked(d, (margin + ow + round(of.size * 0.55), oy + round(of.size * 0.24)),
                   M.OFFER_TAIL, ot, (232, 228, 218), tracking=ot.size * 0.06)
    return im


def main() -> int:
    for name, cfg in (("1350", FEED), ("1920", FULL)):
        p = AD_DIR / f"ad_static_scanner_{cfg['w']}x{cfg['h']}.png"
        compose(cfg).save(p)
        print(p, f"{cfg['w']}x{cfg['h']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
