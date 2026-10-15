#!/usr/bin/env python3
"""Static ad for BakersfieldBrief.com, Hermes version.

One idea: the night is loud and unexplained, the brief explains it by 6am.
Hard cut type over a dark street plate, gradient fill on the big tier, small
gold kicker above and a serif brand line below.

Renders the Meta feed crop (1080x1350) and the full-screen crop (1080x1920) as
two separate compositions of the same design.

    .venv\\Scripts\\python.exe data\\ad_kit\\make_static_ad_hermes.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

AD_DIR = Path(__file__).resolve().parent
# A real photograph of downtown Bakersfield (the Fox Theater on Chester Avenue).
# CC0, so it may be cropped and graded for paid ads. See PHOTO_CREDITS.md.
PLATE_FILE = "downtown_bakersfield_fox.jpg"
FONT_SANS = r"C:\Windows\Fonts\bahnschrift.ttf"
FONT_SERIF = r"C:\Users\tscac\Projects\BakersfieldBrief.com\scripts\brief_reel\fonts\Lora-Variable.ttf"

CREAM = (250, 246, 236)
INK = (8, 10, 16)
GOLD = (232, 176, 46)
GOLD_DIM = (196, 142, 30)

KICKER = "BAKERSFIELD \u00b7 OVERNIGHT"
TIER1 = "SIRENS AT 3 AM."
TIER2 = ["THE STORY", "BY 6 AM."]
BRAND = "BakersfieldBrief.com"
OFFER_FREE = "FREE"
OFFER_TAIL = "DAILY BRIEF \u00b7 IN YOUR INBOX EVERY MORNING"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def fit(text: str, path: str, max_w: float, start: int, floor: int = 40) -> ImageFont.FreeTypeFont:
    """Largest size at or below start whose text fits max_w."""
    size = start
    while size > floor:
        f = font(path, size)
        if f.getlength(text) <= max_w:
            return f
        size -= 2
    return font(path, floor)


def tracked_width(text: str, f: ImageFont.FreeTypeFont, tracking: float) -> float:
    return sum(f.getlength(c) for c in text) + tracking * max(0, len(text) - 1)


def draw_tracked(draw: ImageDraw.ImageDraw, xy, text, f, fill, tracking=0.0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking


def gradient_text(base: Image.Image, text: str, xy, f, c_top, c_bot, tracking=0.0,
                  glow=None, glow_alpha=70) -> None:
    """Paint text with a vertical gradient, optionally behind a soft glow."""
    W, H = base.size
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    draw_tracked(md, xy, text, f, 255, tracking)

    bbox = mask.getbbox()
    if bbox is None:
        return

    if glow:
        g = Image.new("L", (W, H), 0)
        gd = ImageDraw.Draw(g)
        draw_tracked(gd, (xy[0], xy[1] + 4), text, f, 255, tracking)
        g = g.filter(ImageFilter.GaussianBlur(18))
        g = g.point(lambda v: int(v * glow_alpha / 255))
        base.paste(Image.new("RGB", (W, H), glow), (0, 0), g)

    x0, y0, x1, y1 = bbox
    grad = Image.new("RGB", (W, H), c_top)
    gd = ImageDraw.Draw(grad)
    span = max(1, y1 - y0)
    for y in range(y0, y1):
        t = (y - y0) / span
        col = tuple(int(c_top[i] + (c_bot[i] - c_top[i]) * t) for i in range(3))
        gd.line([(0, y), (W, y)], fill=col)
    base.paste(grad, (0, 0), mask)


def scrim(base: Image.Image, top_h: float, bot_h: float) -> None:
    """Darken the top and the bottom so type stays legible on any plate."""
    W, H = base.size
    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)
    for y in range(int(H * top_h)):
        t = max(0.0, 1 - y / max(1.0, H * top_h))
        d.line([(0, y), (W, y)], fill=int(215 * t ** 1.4))
    for y in range(int(H * (1 - bot_h)), H):
        t = max(0.0, (y - H * (1 - bot_h)) / max(1.0, H * bot_h))
        d.line([(0, y), (W, y)], fill=int(225 * t ** 1.3))
    base.paste(Image.new("RGB", (W, H), INK), (0, 0), ov)


def band(base: Image.Image, y0: int, y1: int, alpha: int = 130) -> None:
    """Feathered dark band, so a headline over a photo is never a gamble."""
    W, H = base.size
    y0, y1 = max(0, y0), min(H, y1)
    hgt = y1 - y0
    if hgt <= 1:
        return
    ov = Image.new("L", (W, hgt), alpha)
    d = ImageDraw.Draw(ov)
    f = max(8, int(hgt * 0.30))
    for i in range(f):
        a = int(alpha * (i / f) ** 0.8)
        d.line([(0, i), (W, i)], fill=a)
        d.line([(0, hgt - 1 - i), (W, hgt - 1 - i)], fill=a)
    base.paste(Image.new("RGB", (W, hgt), INK), (0, y0), ov)


def scanlines(base: Image.Image, gap: int = 4, alpha: int = 12) -> None:
    """Faint broadcast scanlines. Modern, not 80s: two pixels of dark every few rows."""
    W, H = base.size
    ov = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ov)
    for y in range(0, H, gap):
        d.line([(0, y), (W, y)], fill=alpha)
    base.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), ov)


def night_grade(im: Image.Image) -> Image.Image:
    """Dusk grade for a daylight frame: deep sky, crushed blacks, warm street glow.

    The photograph is real, the time of day is not. Keep the buildings readable:
    the grade must never turn the subject into a silhouette.
    """
    im = ImageEnhance.Brightness(im).enhance(0.36)
    im = ImageEnhance.Contrast(im).enhance(1.20)
    im = ImageEnhance.Color(im).enhance(0.68)
    im = Image.blend(im, Image.new("RGB", im.size, (22, 32, 60)), 0.36)

    # warm sodium glow from the street up, the way a lit block reads at night
    W, H = im.size
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    for y in range(int(H * 0.55), H):
        t = max(0.0, (y - H * 0.55) / (H * 0.45))
        gd.line([(0, y), (W, y)], fill=int(120 * t ** 1.7))
    im = Image.composite(Image.new("RGB", (W, H), (96, 62, 20)), im, glow)
    return im


def plate(w: int, h: int, anchor: float, x_anchor: float = 0.5,
          zoom: float = 1.0) -> Image.Image:
    """The downtown frame, cropped to the canvas, then graded to dusk."""
    im = Image.open(AD_DIR / PLATE_FILE).convert("RGB")
    s = max(w / im.width, h / im.height) * zoom
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    left = int((im.width - w) * x_anchor)
    top = int((im.height - h) * anchor)
    im = im.crop((left, top, left + w, top + h))
    im = night_grade(im)
    return im


def compose(w: int, h: int, build: dict) -> Image.Image:
    im = plate(w, h, build["anchor"], build.get("x_anchor", 0.5), build.get("zoom", 1.0))
    scrim(im, build["scrim_top"], build["scrim_bottom"])
    scanlines(im)
    d = ImageDraw.Draw(im)

    margin = round(w * 0.078)
    max_w = w - 2 * margin

    # geometry first: the headline block is placed, then the plate is darkened
    # behind it, then the type goes on. Type legibility is not left to the photo.
    kf = font(FONT_SANS, build["kicker_size"])
    f1 = fit(TIER1, FONT_SANS, max_w, build["t1_size"])
    f2 = [fit(line, FONT_SANS, max_w, build["t2_size"]) for line in TIER2]
    ky, y1, y2 = round(h * build["kicker_y"]), round(h * build["t1_y"]), round(h * build["t2_y"])
    step = round(max(f.size for f in f2) * 1.01)
    block_bot = y2 + step * (len(TIER2) - 1) + max(f.size for f in f2) + round(h * 0.012)
    band(im, max(0, ky - round(h * 0.016)), block_bot, alpha=132)

    # kicker row: live dot + city label
    cx = margin
    r = round(kf.size * 0.20)
    d.ellipse([cx, ky + kf.size * 0.34, cx + 2 * r, ky + kf.size * 0.34 + 2 * r], fill=(226, 54, 46))
    cx += 2 * r + round(kf.size * 0.42)
    draw_tracked(d, (cx, ky), KICKER, kf, GOLD, tracking=kf.size * 0.16)
    kw = tracked_width(KICKER, kf, kf.size * 0.16)
    d.line([(cx, ky + kf.size * 1.62), (cx + kw, ky + kf.size * 1.62)], fill=GOLD_DIM, width=max(2, w // 400))

    # tier 1: the tension, small on purpose, so tier 2 lands harder
    gradient_text(im, TIER1, (margin, y1), f1, CREAM, (206, 200, 190))

    # tier 2: the promise, the focal point
    for i, (line, f) in enumerate(zip(TIER2, f2)):
        gradient_text(im, line, (margin, y2 + i * step), f, GOLD, CREAM,
                      glow=GOLD, glow_alpha=58)

    # footer: serif brand, gold rule, offer line
    ff = font(FONT_SERIF, build["brand_size"])
    by = round(h * build["brand_y"])
    d.text((margin, by), BRAND, font=ff, fill=CREAM)
    d.line([(margin, by + ff.size * 1.72), (margin + max_w, by + ff.size * 1.72)],
           fill=GOLD, width=max(2, w // 420))
    oy = round(by + ff.size * 1.72 + build["offer_gap"])
    of = font(FONT_SANS, round(build["offer_size"] * 1.34))
    draw_tracked(d, (margin, oy), OFFER_FREE, of, GOLD, tracking=of.size * 0.10)
    fx = margin + tracked_width(OFFER_FREE, of, of.size * 0.10) + round(of.size * 0.55)
    ot = font(FONT_SANS, build["offer_size"])
    draw_tracked(d, (fx, oy + round(of.size * 0.24)), OFFER_TAIL, ot, (232, 228, 218),
                 tracking=ot.size * 0.06)
    return im


FEED = {  # 1080x1350, Meta/IG feed: keep the street lights and the streetlamp
    "anchor": 0.30, "zoom": 1.35, "x_anchor": 0.42,
    "scrim_top": 0.34, "scrim_bottom": 0.38,
    "kicker_size": 30, "kicker_y": 0.070,
    "t1_size": 86, "t1_y": 0.140,
    "t2_size": 258, "t2_y": 0.208,
    "brand_size": 52, "brand_y": 0.800, "offer_size": 27, "offer_gap": 30,
}

FULL = {  # 1080x1920, stories/reels: same design, more air, bigger type
    "anchor": 0.30, "zoom": 1.35, "x_anchor": 0.42,
    "scrim_top": 0.30, "scrim_bottom": 0.24,
    "kicker_size": 32, "kicker_y": 0.098,
    "t1_size": 96, "t1_y": 0.168,
    "t2_size": 272, "t2_y": 0.238,
    "brand_size": 60, "brand_y": 0.792, "offer_size": 29, "offer_gap": 34,
}


def main() -> int:
    out = []
    for build, (w, h), name in ((FEED, (1080, 1350), "ad_static_hermes_1080x1350.png"),
                                (FULL, (1080, 1920), "ad_static_hermes_1080x1920.png")):
        im = compose(w, h, build)
        dest = AD_DIR / name
        im.save(dest, "PNG")
        out.append(f"{dest} {im.size[0]}x{im.size[1]} {dest.stat().st_size} bytes")

    for line in out:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
