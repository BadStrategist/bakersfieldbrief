"""Static ad for BakersfieldBrief.com, round 2: "YOU SLEPT. / WE LISTENED."

A dark poster: two tiers of headline high in the frame, the scanner photograph
low in the frame, the offer at the foot. The photograph is scanner_hero_night.png,
a generated illustration of two scanners on a desk. It stands for "a scanner",
nothing more: no caption, no place, no product name.

Legibility does not depend on the photo. Every block of type sits on a feathered
ink scrim, and after rendering the script measures the contrast of each block
against the pixels actually behind it and refuses to save below 7:1.

Run: .venv\\Scripts\\python.exe data\\ad_kit\\make_static_ad_claude_v2.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BAHN = r"C:\Windows\Fonts\bahnschrift.ttf"
LORA = REPO / "scripts" / "brief_reel" / "fonts" / "Lora-Variable.ttf"
HERO = HERE / "scanner_hero_night.png"

INK = (0x0B, 0x0E, 0x15)
GOLD = (0xE8, 0xB2, 0x3A)
CREAM = (0xF2, 0xED, 0xE4)

W = 1080
PAD = 72
MIN_CONTRAST = 7.0

# Per format: photo scale, where the photo's top edge lands, kicker position.
# Source rows: antenna tip ~310, radio bodies 620 to 1120, reflections below.
# The scrims are fitted to the measured type, so they are not set here.
LAYOUTS = {
    1350: dict(scale=1.25, photo_y=-360, kicker_y=70, support=False),
    1920: dict(scale=1.45, photo_y=-250, kicker_y=176, support=True),
}
FADE = 150  # px over which a scrim goes from solid to clear
IG_REPLY_BAR = 250  # 9:16 only: bottom band Instagram covers with the reply bar


def bahn(size, weight="Bold Condensed"):
    # bahnschrift.ttf is a variable font; Pillow loads "Regular" unless told.
    f = ImageFont.truetype(BAHN, size)
    f.set_variation_by_name(weight)
    return f


def lora(size, weight=700):
    f = ImageFont.truetype(str(LORA), size)
    f.set_variation_by_axes([weight])
    return f


def fit(text, width, weight="Bold Condensed"):
    """Largest Bahnschrift size whose ink is at most `width` wide."""
    lo, hi = 20, 800
    while hi - lo > 1:
        mid = (lo + hi) // 2
        l, _, r, _ = bahn(mid, weight).getbbox(text)
        lo, hi = (mid, hi) if r - l <= width else (lo, mid)
    return lo


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def plate(h, lay):
    """Ink ground with the photograph graded into it, edges feathered away."""
    src = Image.open(HERO).convert("RGB")
    pw, ph = int(src.width * lay["scale"]), int(src.height * lay["scale"])
    photo = src.resize((pw, ph), Image.LANCZOS)
    # Lift the photo's pure black to brand ink (screen blend), so the photo
    # and the ground are one surface.
    photo = ImageChops.screen(photo, Image.new("RGB", photo.size, INK))

    # Feather all four edges of the photo into the ground.
    mask = Image.new("L", photo.size, 0)
    m = int(min(pw, ph) * 0.06)
    ImageDraw.Draw(mask).rectangle((m, m, pw - m, ph - m), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(m * 0.8))

    img = Image.new("RGB", (W, h), INK)
    img.paste(photo, ((W - pw) // 2, lay["photo_y"]), mask)

    # Grain, very light, so the flat ink reads as a photograph too.
    noise = Image.effect_noise((W, h), 18).point(lambda v: max(0, v - 128) // 10)
    img = ImageChops.add(img, noise.convert("RGB"))
    return img.convert("RGBA")


def scrim(img, y_full, y_clear, top=True, peak=245):
    """Feathered ink band: `peak` alpha up to y_full, fading out by y_clear."""
    h = img.height
    a = Image.new("L", (1, h), 0)
    for y in range(h):
        if top:
            t = 1.0 if y <= y_full else 1 - smooth((y - y_full) / (y_clear - y_full))
        else:
            t = 1.0 if y >= y_full else smooth((y - y_clear) / (y_full - y_clear))
        a.putpixel((0, y), int(peak * t))
    band = Image.new("RGBA", img.size, INK + (255,))
    band.putalpha(a.resize(img.size))
    img.alpha_composite(band)


def halo(img, boxes, blur=40, alpha=170):
    """A soft ink shadow behind each text block: local insurance on top of the band."""
    sh = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(sh)
    for l, t, r, b in boxes:
        d.rounded_rectangle((l - 30, t - 24, r + 30, b + 24), radius=40, fill=alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", img.size, INK + (255,))
    layer.putalpha(sh)
    img.alpha_composite(layer)


def spaced(d, xy, text, font, fill, tracking, measure=False):
    """Letter-spaced line, top-left anchored. Returns its box."""
    x, y = xy
    x0 = x
    for i, ch in enumerate(text):
        if not measure:
            d.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += d.textlength(ch, font=font) + (tracking if i < len(text) - 1 else 0)
    asc = font.getbbox("H", anchor="ls")[1]
    return (x0, y + asc, x, y)


def luminance(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(fg, bg):
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def worst_background(plate_img, box):
    """Brightest 2% of the ground behind a text block (the text is not drawn yet)."""
    l, t, r, b = (int(v) for v in box)
    crop = plate_img.convert("RGB").crop((max(0, l), max(0, t), min(W, r), min(plate_img.height, b)))
    px = sorted(crop.get_flattened_data(), key=luminance)
    return px[int(len(px) * 0.98) - 1]


def render(h, path):
    lay = LAYOUTS[h]
    tall = h == 1920
    img = plate(h, lay)
    d = ImageDraw.Draw(img)
    inner = W - 2 * PAD

    # ---- measure the headline stack first, so the scrims can be fitted to it
    kick_font = bahn(34 if tall else 30, "SemiBold")
    s2 = fit("WE LISTENED.", inner + 8)       # tier 2 runs the full measure
    t2 = bahn(s2)
    t1 = bahn(int(s2 * 0.52))                 # tier 1 is a clear step down
    cap2 = t2.getbbox("W", anchor="ls")
    cap1 = t1.getbbox("Y", anchor="ls")
    cap2_h, cap1_h = cap2[3] - cap2[1], cap1[3] - cap1[1]

    ky = lay["kicker_y"] + 30                  # kicker baseline
    y1 = ky + 30 + cap1_h                       # YOU SLEPT. baseline
    y2 = y1 + int(cap1_h * 0.30) + cap2_h       # WE LISTENED. baseline

    x2 = PAD - cap2[0]                          # optical left edge for tier 2
    boxes = {
        "kicker": spaced(d, (PAD, ky), "THE KERN OVERNIGHT", kick_font, None, 8, measure=True),
        "slept": d.textbbox((PAD - cap1[0], y1), "YOU SLEPT.", font=t1, anchor="ls"),
        "listened": d.textbbox((x2, y2), "WE LISTENED.", font=t2, anchor="ls"),
    }

    # ---- the foot: offer, brand, optional support line
    bottom = h - (IG_REPLY_BAR + 40 if tall else 72)
    brand_font = lora(46 if tall else 42, 700)
    offer_font = bahn(30 if tall else 27, "SemiBold")
    free_font = bahn(150 if tall else 124)
    sup_font = lora(34 if tall else 30, 500)
    offer = "DAILY BRIEF \u00b7 IN YOUR INBOX EVERY MORNING"

    by = bottom                                  # brand baseline
    rule_y = by - (brand_font.getbbox("B", anchor="ls")[3] - brand_font.getbbox("B", anchor="ls")[1]) - 34
    oy = rule_y - 30                             # offer line baseline
    free_cap = free_font.getbbox("F", anchor="ls")
    fy = oy - 22 - (offer_font.getbbox("D", anchor="ls")[3] - offer_font.getbbox("D", anchor="ls")[1])
    free_xy = (PAD - free_cap[0], fy)
    boxes["free"] = d.textbbox(free_xy, "FREE", font=free_font, anchor="ls")
    boxes["offer"] = spaced(d, (PAD, oy), offer, offer_font, None, 3, measure=True)
    boxes["brand"] = d.textbbox((PAD, by), "BakersfieldBrief.com", font=brand_font, anchor="ls")
    support = "Overnight scanner calls, roads and weather, every morning."
    if lay["support"]:
        sy = boxes["free"][1] - 52
        boxes["support"] = d.textbbox((PAD, sy), support, font=sup_font, anchor="ls")

    # ---- engineered legibility: a feathered band under the headline and one
    # under the foot, each solid across its type and fading out beyond it,
    # plus a soft halo for the support line, which sits closest to the photo.
    head_bottom = boxes["listened"][3]
    # Solid (255): at 245 the antenna tip ghosted through above the kicker.
    scrim(img, head_bottom + 24, head_bottom + 24 + FADE, peak=255)
    foot_top = min(b[1] for k, b in boxes.items() if k in ("free", "support", "offer", "brand"))
    scrim(img, foot_top - 24, foot_top - 24 - FADE, top=False, peak=235)
    if "support" in boxes:
        halo(img, [boxes["support"]], blur=30, alpha=140)

    # ---- check contrast on the ground the type will actually sit on
    colours = {"kicker": GOLD, "slept": CREAM, "listened": GOLD,
               "free": GOLD, "offer": CREAM, "brand": CREAM, "support": CREAM}
    report = []
    for k, box in boxes.items():
        bg = worst_background(img, box)
        c = contrast(colours[k], bg)
        report.append(f"{k}={c:.1f}")
        if c < MIN_CONTRAST:
            raise SystemExit(f"{path.name}: {k} contrast {c:.2f} < {MIN_CONTRAST} (bg {bg})")
    if tall:
        lowest = max(b[3] for b in boxes.values())
        if lowest > h - IG_REPLY_BAR:
            raise SystemExit(f"{path.name}: type reaches y={lowest}, inside the reply bar")

    # ---- type
    d = ImageDraw.Draw(img)
    spaced(d, (PAD, ky), "THE KERN OVERNIGHT", kick_font, GOLD, 8)
    d.text((PAD - cap1[0], y1), "YOU SLEPT.", font=t1, fill=CREAM, anchor="ls")
    d.text((x2, y2), "WE LISTENED.", font=t2, fill=GOLD, anchor="ls")

    if lay["support"]:
        d.text((PAD, sy), support, font=sup_font, fill=CREAM + (215,), anchor="ls")
    d.text(free_xy, "FREE", font=free_font, fill=GOLD, anchor="ls")
    spaced(d, (PAD, oy), offer, offer_font, CREAM, 3)
    d.line((PAD, rule_y, PAD + 120, rule_y), fill=GOLD, width=3)
    d.text((PAD, by), "BakersfieldBrief.com", font=brand_font, fill=CREAM, anchor="ls")

    img.convert("RGB").save(path, optimize=True)
    print(path.name, " ".join(report))


if __name__ == "__main__":
    render(1350, HERE / "ad_static_claude_v2_1080x1350.png")
    render(1920, HERE / "ad_static_claude_v2_1080x1920.png")
