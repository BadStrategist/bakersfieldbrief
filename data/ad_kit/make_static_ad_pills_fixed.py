"""Minimum-change legibility fix of the BB static ad bottom panel.

Replaces the glitchy translucent pill cards with a flat opaque panel
carving five plain, high-contrast rows. Two canvases: 1080x1350 and 1080x1920.
"""
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageFilter

W1, H1 = 1080, 1350
W2, H2 = 1080, 1920
PHOTO = "data/ad_kit/uniden_desk_night.jpg"
LORA = "scripts/brief_reel/fonts/Lora-Variable.ttf"
BC700 = "data/ad_kit/fonts/barlow-condensed-700.ttf"
BC600 = "data/ad_kit/fonts/barlow-condensed-600.ttf"

CREAM = (250, 246, 236)
GREY = (160, 162, 168)
PANEL = (12, 15, 21)
AMBER = (232, 176, 46)
HAIRLINE = (35, 42, 52)

ROWS = [
    ("OVERNIGHT SCANNER LOG", "What was called in while the city slept"),
    ("WEATHER AND FOG DELAYS", "Tehachapi pass and school delay alerts"),
    ("ROADS AND TRAFFIC", "Grapevine, SR-58 and county road conditions"),
    ("9 LIVE TRACKERS", "Fire, water, cameras and ALPR, all on one page"),
    ("ALPR CAMERAS AND OWNERS", "Map with the land owner on each camera"),
]


def contrast(a, b):
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    l1 = sum(lin(v) * f for v, f in zip(a, (0.2126, 0.7152, 0.0722)))
    l2 = sum(lin(v) * f for v, f in zip(b, (0.2126, 0.7152, 0.0722)))
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def font(path, size, bold=False):
    f = ImageFont.truetype(path, size)
    if bold:
        f.set_variation_by_name("Bold")
    return f


def feather_band(img, x0, y0, x1, y1, max_alpha=190, feather=70):
    """Soft vertical gradient scrim behind headline type."""
    h = y1 - y0
    band = Image.new("L", (1, h), 0)
    for y in range(h):
        # ramp in, plateau, ramp out
        t = min(y / feather, 1.0) * min((h - 1 - y) / feather, 1.0)
        band.putpixel((0, y), int(max_alpha * min(1.0, t * 1.6)))
    band = band.resize((x1 - x0, h))
    black = Image.new("RGB", band.size, (5, 8, 14))
    img.paste(black, (x0, y0), band)


def draw_center(d, cx, y, text, f, fill):
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)
    return d.textbbox((cx - w / 2, y), text, font=f)


def compose(W, H):
    img = Image.new("RGB", (W, H), PANEL)
    hero = Image.open(PHOTO).convert("RGB")
    hero = hero.resize((1080, round(hero.height * 1080 / hero.width)), Image.LANCZOS)
    # The radio's display and the tablet's map hold invented readouts, and the display even
    # spells "SCAN: 1-12 ACTIVE" while the site runs nine. Boxes measured off the source
    # (they sit right of x 344, clear of the radio's own brand lettering) and scaled by the
    # resize factor. Soften and dim, or a bigger canvas leaves the text readable again.
    sc = hero.width / 928.0
    smask = Image.new("L", hero.size, 0)
    sd = ImageDraw.Draw(smask)
    for x0, y0, x1, y1 in ((340, 292, 556, 418), (714, 248, 888, 390)):
        sd.rounded_rectangle((round(x0 * sc), round(y0 * sc), round(x1 * sc), round(y1 * sc)),
                             radius=18, fill=255)
    smask = smask.filter(ImageFilter.GaussianBlur(12))
    softened = ImageEnhance.Brightness(hero.filter(ImageFilter.GaussianBlur(2.6))).enhance(0.55)
    hero = Image.composite(softened, hero, smask)
    img.paste(hero, (0, 0))
    photo_h = hero.height

    d = ImageDraw.Draw(img)
    # Headline over the photo's upper area, on a feathered band
    f_head = font(LORA, 84, bold=True)
    feather_band(img, 0, 60, W, 60 + 300)
    d = ImageDraw.Draw(img)
    draw_center(d, W / 2, 120, "Bakersfield Slept.", f_head, CREAM)
    draw_center(d, W / 2, 230, "We Listened.", f_head, CREAM)

    # Flat opaque panel below the photo
    d.rectangle([0, photo_h, W, H], fill=PANEL)

    panel_top = photo_h
    foot_clear = 250 if H == 1920 else 60
    d.rectangle([64, panel_top + 34, 64 + 160, panel_top + 36], fill=AMBER)

    # rows
    bottom_url = H - foot_clear - 20  # baseline area for URL
    url_h = 60
    rows_top = panel_top + 90
    rows_bottom = bottom_url - url_h - 30
    n = len(ROWS)
    row_h = (rows_bottom - rows_top) / n
    f_label = font(BC700, 46)
    f_detail = font(BC600, 26)
    f_url = font(LORA, 40, bold=True)

    for i, (label, detail) in enumerate(ROWS):
        ry = rows_top + i * row_h
        d.text((64, ry), label, font=f_label, fill=CREAM)
        d.text((64, ry + 58), detail, font=f_detail, fill=GREY)
        if i < n - 1:
            ly = round(ry + row_h - 6)
            d.rectangle([64, ly, W - 64, ly + 1], fill=HAIRLINE)

    # URL at very bottom of the panel
    uw = d.textlength("BakersfieldBrief.com", font=f_url)
    d.text(((W - uw) / 2, H - foot_clear - 40), "BakersfieldBrief.com",
           font=f_url, fill=CREAM)
    return img


if __name__ == "__main__":
    cr_cream = contrast(CREAM, PANEL)
    cr_grey = contrast(GREY, PANEL)
    print(f"contrast CREAM on PANEL: {cr_cream:.2f}")
    print(f"contrast GREY  on PANEL: {cr_grey:.2f}")
    compose(W1, H1).save("data/ad_kit/ad_static_pills_1080x1350.png")
    compose(W2, H2).save("data/ad_kit/ad_static_pills_1080x1920.png")
    print("rendered both")
