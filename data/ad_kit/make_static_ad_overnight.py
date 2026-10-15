#!/usr/bin/env python3
"""Static ad: the overnight brief, rebuilt on the brand palette.

The photograph is the desk at night with the scanners and the city behind it.
The type is the site's own: Lora for the headline, Barlow Condensed (converted
from assets/fonts in this repo) for the tech block. The palette is the brand's
ink, gold and cream. No neon, no third colour, nothing that reads as a voucher.

The tracker count in the copy is the count the site actually runs. It is nine.
Verify it against https://bakersfieldbrief.com/trackers/ before you change it:
the nine cards live in that page's HTML. Never write a bigger number.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

import make_static_ad_hermes as M  # noqa: E402

AD_DIR = Path(__file__).resolve().parent
HERO = "uniden_desk_night.jpg"
FONT_COND = str(AD_DIR / "fonts" / "barlow-condensed-700.ttf")
FONT_COND_600 = str(AD_DIR / "fonts" / "barlow-condensed-600.ttf")

INK = (8, 10, 16)
CREAM = M.CREAM
GOLD = M.GOLD
GREY = (168, 170, 176)

KICKER = "THE OVERNIGHT BRIEF"
T1 = "Bakersfield Slept."
T2 = "We Listened."
HEAD1 = "Scanner calls, roads, weather."
HEAD2_GOLD = "9 LIVE TRACKERS."
HEAD2_CREAM = " ONE EMAIL."
MICRO = "EVERY MORNING \u00b7 ALWAYS FREE"

FEED = {
    "w": 1080, "h": 1350, "margin": 0.072,
    "kicker_y": 0.052, "kick_size": 0.023,
    "t_y": 0.098, "t_cap": 0.086, "t_step": 0.0865,
    "hero_y": 0.281, "grade": True,
    "rule_y": 0.770,
    "head_size": 0.036, "head2_size": 0.038, "cta_size": 0.043, "micro_size": 0.019,
}
FULL = {
    "w": 1080, "h": 1920, "margin": 0.072,
    "kicker_y": 0.048, "kick_size": 0.024,
    "t_y": 0.088, "t_cap": 0.094, "t_step": 0.094,
    "hero_y": 0.333, "grade": True,
    "rule_y": 0.693,
    "head_size": 0.037, "head2_size": 0.039, "cta_size": 0.044, "micro_size": 0.020,
}


def serif(size: int) -> ImageFont.FreeTypeFont:
    """Lora at Bold: the variable file's default instance is Regular."""
    f = ImageFont.truetype(M.FONT_SERIF, size)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    return f


def cond(size: int, weight: str = "700") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_COND if weight == "700" else FONT_COND_600, size)


def grade(im: Image.Image) -> Image.Image:
    """Pull the device greens toward the brand's warm night, keep the city lights."""
    hsv = im.convert("HSV")
    h, s, v = hsv.split()
    mask = h.point(lambda x: 255 if 55 <= x <= 135 else 0).filter(
        ImageFilter.GaussianBlur(3))
    s = Image.composite(s.point(lambda x: int(x * 0.42)), s, mask)
    im = Image.merge("HSV", (h, s, v)).convert("RGB")
    r, g, b = im.split()
    r = r.point(lambda x: min(255, int(x * 1.05)))
    b = b.point(lambda x: int(x * 0.94))
    return Image.merge("RGB", (r, g, b))


SCREENS = ((340, 322, 478, 402), (712, 243, 884, 333))


def soften(photo: Image.Image) -> None:
    """Blur the two lit screens in place: at ad size a crisp fake readout is a lie."""
    k = photo.width / 928
    for x0, y0, x1, y1 in SCREENS:
        box = (round(x0 * k), round(y0 * k), round(x1 * k), round(y1 * k))
        patch = photo.crop(box).filter(ImageFilter.GaussianBlur(2.2))
        patch = Image.blend(patch, Image.new("RGB", patch.size, (0, 0, 0)), 0.10)
        photo.paste(patch, box[:2])


def extend(base: Image.Image, hero_top: int, photo: Image.Image) -> None:
    """Ink above the photograph, fading into the photograph's own top row colour.

    The photograph's first rows are the dark ceiling of the room, so a gradient
    that lands exactly on that row colour makes the frame read as one scene.
    """
    w = base.width
    top = tuple(photo.getpixel((x, 0)) for x in range(0, w, max(1, w // 24)))
    edge = tuple(sum(c[i] for c in top) // len(top) for i in range(3))
    grad = Image.new("RGB", (1, max(1, hero_top)))
    gd = ImageDraw.Draw(grad)
    for y in range(hero_top):
        t = (y / max(1, hero_top - 1)) ** 1.35
        gd.point((0, y), fill=tuple(round(INK[i] + (edge[i] - INK[i]) * t) for i in range(3)))
    base.paste(grad.resize((w, max(1, hero_top))), (0, 0))


def compose(cfg: dict) -> Image.Image:
    w, h = cfg["w"], cfg["h"]
    im = Image.new("RGB", (w, h), INK)
    margin = round(w * cfg["margin"])
    max_w = w - 2 * margin

    src = Image.open(AD_DIR / HERO).convert("RGB")
    if cfg["grade"]:
        src = grade(src)
    s = w / src.width
    photo = src.resize((w, round(src.height * s)), Image.LANCZOS)
    soften(photo)
    hero_y = round(h * cfg["hero_y"])
    extend(im, hero_y, photo)
    feather = max(24, round(photo.height * 0.14))
    mask = Image.new("L", (w, photo.height), 255)
    md = ImageDraw.Draw(mask)
    for i in range(feather):
        md.line([(0, i), (w, i)], fill=int(255 * (i / feather) ** 0.85))
    im.paste(photo, (0, hero_y), mask)
    fade = round(h * 0.055)
    bottom = hero_y + photo.height
    tail = Image.new("RGB", (1, fade + 1))
    td = ImageDraw.Draw(tail)
    cols = range(0, w, max(1, w // 24))
    rows = [photo.getpixel((x, photo.height - 1)) for x in cols]
    edge = tuple(sum(r[i] for r in rows) // len(rows) for i in range(3))
    for y in range(fade + 1):
        t = (y / fade) ** 0.8
        td.point((0, y), fill=tuple(round(edge[i] + (INK[i] - edge[i]) * t) for i in range(3)))
    im.paste(tail.resize((w, fade + 1)), (0, bottom))

    d = ImageDraw.Draw(im)

    kf = cond(round(w * cfg["kick_size"]), "600")
    ky = round(h * cfg["kicker_y"])
    tr = kf.size * 0.20
    kw = M.tracked_width(KICKER, kf, tr)
    r = round(kf.size * 0.24)
    kx = margin
    d.ellipse([kx, ky + kf.size * 0.28, kx + 2 * r, ky + kf.size * 0.28 + 2 * r],
              fill=(226, 54, 46))
    M.draw_tracked(d, (kx + 2 * r + round(kf.size * 0.7), ky), KICKER, kf, GOLD, tracking=tr)

    cap = round(w * cfg["t_cap"])
    step = round(h * cfg["t_step"])
    f1 = M.fit(T1, M.FONT_SERIF, max_w, cap)
    try:
        f1.set_variation_by_name("Bold")
    except Exception:
        pass
    f2 = M.fit(T2, M.FONT_SERIF, max_w, cap)
    try:
        f2.set_variation_by_name("Bold")
    except Exception:
        pass
    ty = round(h * cfg["t_y"])
    M.gradient_text(im, T1, (margin, ty), f1, CREAM, (226, 220, 208))
    M.gradient_text(im, T2, (margin, ty + step), f2, GOLD, (208, 158, 40),
                    glow=GOLD, glow_alpha=44)

    ry = round(h * cfg["rule_y"])
    d.line([(margin, ry), (w - margin, ry)], fill=M.GOLD_DIM, width=max(2, w // 380))

    y = ry + round(h * 0.024)
    fh = cond(round(w * cfg["head_size"]), "600")
    d.text((margin, y), HEAD1, font=fh, fill=CREAM)
    y += round(fh.size * 1.42)
    fh2 = cond(round(w * cfg["head2_size"]))
    wg = d.textlength(HEAD2_GOLD, font=fh2)
    d.text((margin, y), HEAD2_GOLD, font=fh2, fill=GOLD)
    d.text((margin + wg, y), HEAD2_CREAM, font=fh2, fill=CREAM)
    y += round(fh2.size * 1.52)
    fc = serif(round(w * cfg["cta_size"]))
    d.text((margin, y), M.BRAND, font=fc, fill=CREAM)
    y += round(fc.size * 1.66)
    fm = cond(round(w * cfg["micro_size"]), "600")
    M.draw_tracked(d, (margin, y), MICRO, fm, GREY, tracking=fm.size * 0.14)
    return im


def main() -> int:
    for name, cfg in (("1350", FEED), ("1920", FULL)):
        p = AD_DIR / f"ad_static_overnight_{cfg['w']}x{cfg['h']}.png"
        compose(cfg).save(p)
        print(p, f"{cfg['w']}x{cfg['h']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
