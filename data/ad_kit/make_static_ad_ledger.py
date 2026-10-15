#!/usr/bin/env python3
"""Static ad, ledger angle: the night desk photograph, the type high on ink, and a
flat typographic ledger at the foot. No pills, no icons, no translucency, no small
serif on a busy photograph.

Type colour is cream. Amber is a mark only: the live dot, one hairline, and the
numeral nine. Nothing else on the plate is amber, and no line of type is set in it.

Every text colour is measured against its background before the plate is written.
Run:  .venv\\Scripts\\python.exe data/ad_kit/make_static_ad_ledger.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"C:\Users\tscac\Projects\BakersfieldBrief.com")
AD = ROOT / "data" / "ad_kit"
HERO = AD / "uniden_desk_night.jpg"
F_SERIF = ROOT / "scripts" / "brief_reel" / "fonts" / "Lora-Variable.ttf"
F_COND700 = AD / "fonts" / "barlow-condensed-700.ttf"
F_COND600 = AD / "fonts" / "barlow-condensed-600.ttf"

INK = (8, 10, 16)
CREAM = (250, 246, 236)
GREY = (172, 174, 180)
AMBER = (220, 154, 31)

KICKER = "OVERNIGHT IN KERN COUNTY  \u00b7  FREE EVERY MORNING"
HEAD1 = "Bakersfield Slept."
HEAD2 = "We Listened."
SUB = "What Kern County called in while you slept."
LEDGER1 = "SCANNER CALLS \u00b7 ROADS \u00b7 WEATHER"
LEDGER2_NUM = "9"
LEDGER2 = " LIVE TRACKERS. ONE EMAIL."
CTA = "BakersfieldBrief.com"

CFG = {
    "feed": dict(W=1080, H=1350, kicker_y=92, kicker=24, head1_y=148, head=88, head_step=106,
                 sub_y=400, sub=40, hero_y=375, fade=54, band=180, rule_y=1072, l1_y=1100, ledger=52,
                 l2_y=1166, cta_y=1232, cta=46, margin=72),
    "full": dict(W=1080, H=1920, kicker_y=118, kicker=28, head1_y=196, head=104, head_step=124,
                 sub_y=512, sub=46, hero_y=640, fade=90, band=260, rule_y=1330, l1_y=1364, ledger=58,
                 l2_y=1440, cta_y=1520, cta=52, margin=72),
}


def lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(rgb) -> float:
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg, bg) -> float:
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def cond(size: int, weight: int = 700) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(F_COND700 if weight == 700 else F_COND600), size)


def serif(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(F_SERIF), size)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        f.set_variation_by_axes([700])
    return f


def tw(draw, text, font, tracking=0.0) -> float:
    if not tracking:
        return draw.textlength(text, font=font)
    return draw.textlength(text, font=font) + tracking * font.size * (len(text) - 1)


def fit(draw, text, maker, size, max_w, **kw):
    while size > 12 and tw(draw, text, maker(size, **kw)) > max_w:
        size -= 2
    return maker(size, **kw)


def put(draw, xy, text, font, fill, tracking=0.0, anchor="la"):
    x, y = xy
    if tracking:
        for ch in text:
            draw.text((x, y), ch, font=font, fill=fill, anchor=anchor)
            x += draw.textlength(ch, font=font) + tracking * font.size
    else:
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def ramp(width: int, height: int, top_value: int, bottom_value: int, power: float = 0.85) -> Image.Image:
    """A vertical alpha ramp, one column, resized across the width."""
    col = Image.new("L", (1, height))
    cd = ImageDraw.Draw(col)
    for y in range(height):
        t = (y / max(1, height - 1)) ** power
        cd.point((0, y), fill=round(top_value + (bottom_value - top_value) * t))
    return col.resize((width, height))


def blend_row(base: Image.Image, row: Image.Image, y: int, height: int, flipped: bool) -> None:
    """Continue each column of the photograph into the ink from that column's own colour.

    The row is one pixel tall; stretched down it gives every column its own starting
    colour, so no column steps where the photograph ends. A one-colour average does
    step, which is why the desk edge showed as a line.
    """
    if height <= 0:
        return
    stretched = row.resize((base.width, height), Image.BILINEAR)
    if flipped:
        mask = ramp(base.width, height, 255, 0)  # ink at the far end, photo at the edge
    else:
        mask = ramp(base.width, height, 0, 255)
    band = Image.composite(Image.new("RGB", (base.width, height), INK), stretched, mask)
    base.paste(band, (0, y))


def top_band(base: Image.Image, hero_top: int, fade: int) -> None:
    """Ink above the photograph, fading out over the photograph's own top rows.

    A stretched gradient under real texture shows the join as a line, because no flat
    fill matches grain. Dimming the photograph's own pixels cannot show a join.
    """
    if fade <= 0:
        return
    height = hero_top + fade
    layer = Image.new("RGB", (base.width, height), INK)
    mask = Image.new("L", (base.width, height), 255)
    md = ImageDraw.Draw(mask)
    for i in range(fade):
        md.line([(0, hero_top + i), (base.width, hero_top + i)],
                fill=round(255 * (1 - (i / fade) ** 0.8)))
    base.paste(layer, (0, 0), mask)


def fade_below(base: Image.Image, photo_bottom: int, fade: int, photo: Image.Image) -> None:
    """Carry the photograph's own last row into the ink, so the panel edge never shows."""
    if fade <= 0:
        return
    blend_row(base, photo.crop((0, photo.height - 1, photo.width, photo.height)),
              photo_bottom, fade, flipped=False)


def compose(c) -> Image.Image:
    w, h, m = c["W"], c["H"], c["margin"]
    im = Image.new("RGB", (w, h), INK)
    d = ImageDraw.Draw(im)

    photo = Image.open(HERO).convert("RGB")
    scale = w / photo.width
    photo = photo.resize((w, round(photo.height * scale)), Image.LANCZOS)

    im.paste(photo, (0, c["hero_y"]))
    fade_below(im, c["hero_y"] + photo.height, c["fade"], photo)
    top_band(im, c["hero_y"], c["band"])
    d = ImageDraw.Draw(im)

    max_w = w - 2 * m

    # kicker, with the amber live dot as the only mark up here
    kf = cond(c["kicker"], 600)
    d.ellipse([m, c["kicker_y"] + 9, m + 9, c["kicker_y"] + 18], fill=AMBER)
    put(d, (m + 22, c["kicker_y"]), KICKER, kf, GREY, tracking=0.14)

    hf1 = fit(d, HEAD1, serif, c["head"], max_w)
    hf2 = fit(d, HEAD2, serif, c["head"], max_w)
    put(d, (w // 2, c["head1_y"]), HEAD1, hf1, CREAM, anchor="ma")
    put(d, (w // 2, c["head1_y"] + c["head_step"]), HEAD2, hf2, CREAM, anchor="ma")

    sf = cond(c["sub"], 600)
    put(d, (w // 2, c["sub_y"]), SUB, sf, CREAM, anchor="ma")

    # the ledger
    d.rectangle([m, c["rule_y"], w - m, c["rule_y"] + 2], fill=AMBER)
    l1 = fit(d, LEDGER1, cond, c["ledger"], max_w, weight=700)
    put(d, (m, c["l1_y"]), LEDGER1, l1, CREAM, tracking=0.02)

    l2f = cond(c["ledger"], 700)
    nw = d.textlength(LEDGER2_NUM, font=l2f)
    d.text((m, c["l2_y"]), LEDGER2_NUM, font=l2f, fill=AMBER)
    d.text((m + nw, c["l2_y"]), LEDGER2, font=l2f, fill=CREAM)

    cf = fit(d, CTA, serif, c["cta"], max_w)
    put(d, (m, c["cta_y"]), CTA, cf, CREAM)
    return im


def main() -> int:
    print("contrast on ink %s" % (INK,))
    for name, col in (("cream", CREAM), ("grey", GREY), ("amber", AMBER)):
        r = ratio(col, INK)
        print("  %-6s %-16s %.2f:1 %s" % (name, col, r, "OK" if r >= 7 else "LOW"))
        if r < 7:
            raise SystemExit("text colour %s is under 7:1 on ink" % name)
    for key, c in CFG.items():
        out = AD / ("ad_static_ledger_%dx%d.png" % (c["W"], c["H"]))
        im = compose(c)
        im.save(out)
        d = ImageDraw.Draw(im)
        print("%s  %dx%d  head %.0fpx ledger %.0fpx cta %.0fpx  head_w %.0f/%d"
              % (out.name, im.width, im.height,
                 c["head"], c["ledger"], c["cta"],
                 tw(d, HEAD1, serif(c["head"])) if False else 0, c["W"] - 2 * c["margin"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
