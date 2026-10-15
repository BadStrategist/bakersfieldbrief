"""Static ad for BakersfieldBrief.com, the "cream paper foot" angle.

The desk-at-night photograph holds the top, full bleed, with the headline over
the dark window behind a feathered ink scrim. The foot is the site's own paper
(#FAF6EC), squared off and flush to the bottom edge, set in ink like the top of
a newspaper front page: a double rule, one deck, a ledger of the nine trackers,
and the masthead (Lora 700, as on the site). Amber only marks: the numeral,
the separators, one hairline.

Renders a 4:5 feed and a 9:16 story, each composed on its own.

Run: .venv\\Scripts\\python.exe data\\ad_kit\\make_static_ad_claude.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONTS = HERE / "fonts"
LORA = REPO / "scripts" / "brief_reel" / "fonts" / "Lora-Variable.ttf"
HERO = HERE / "uniden_desk_night.jpg"

CREAM = (0xFA, 0xF6, 0xEC)
INK = (0x1A, 0x21, 0x26)
INK_SOFT = (0x57, 0x50, 0x4A)
AMBER = (0xDC, 0x9A, 0x1F)

W = 1080
HEADLINE = ("Bakersfield Slept.", "We Listened.")
DECK = ("Overnight scanner news, roads, fog and weather.",
        "One free email, every morning.")
TRACKERS = ("Grapevine", "SR-58", "Kern roads", "Traffic cameras", "Fog delays",
            "Kern fires", "Lake Isabella", "Flock & ALPR", "Tehachapi weather")
assert len(TRACKERS) == 9, "the site runs nine trackers; the copy says nine"
URL = "BakersfieldBrief.com"
TAG = "FREE DAILY EMAIL"


def barlow(size, weight=600):
    return ImageFont.truetype(str(FONTS / f"barlow-condensed-{weight}.ttf"), size)


def lora(size, weight=700):
    f = ImageFont.truetype(str(LORA), size)
    f.set_variation_by_axes([weight])
    return f


def luminance(rgb):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def tracked(d, xy, text, font, fill, tracking, anchor="l"):
    """Letter-spaced uppercase label; anchor 'l' or 'r' on x, top on y."""
    widths = [d.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if anchor == "r":
        x -= total
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += w + tracking
    return total


def hero(h, focus_x):
    """The photograph scaled to fill W x h, cropped around source x `focus_x`."""
    src = Image.open(HERO).convert("RGB")
    # The radio's display and the tablet's map hold invented readouts. Legible, they are a
    # false claim (the display even reads "1-12 ACTIVE", and the site runs nine), so soften
    # them at every ratio.
    s = h / src.height
    img = src.resize((round(src.width * s), h), Image.LANCZOS)
    left = max(0, min(img.width - W, round(focus_x * s - W / 2)))
    img = img.crop((left, 0, left + W, h))
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=2))

    # Soften the invented readouts LAST, through a feathered mask. Softening before the
    # sharpen puts the text straight back, and a hard-edged box reads as a smear. The
    # boxes hug the lit screens only: the radio's own brand lettering sits left of them
    # and must stay crisp, because that is a real product name.
    mask = Image.new("L", (W, h), 0)
    md = ImageDraw.Draw(mask)
    # Boxes measured off the source, not guessed: the readout's text occupies x 350 to 502,
    # rows 304 to 407, and the brand lettering sits left of x 344, so it stays crisp.
    for x0, y0, x1, y1 in ((340, 292, 556, 418), (714, 248, 888, 390)):
        box = (max(0, round(x0 * s - left)), max(0, round(y0 * s)),
               min(W, round(x1 * s - left)), min(h, round(y1 * s)))
        if box[2] > box[0] and box[3] > box[1]:
            md.rounded_rectangle(box, radius=18, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(12))
    # The blur has to track the zoom, and a blur alone leaves big text readable: measured on
    # both ratios, the feed was illegible at 3.4 px while the story crop still spelled
    # "SCAN: 1-12 ACTIVE" at the same radius. Dim the masked area as well, which holds at
    # any zoom and reads as a display seen out of focus rather than a smear.
    radius = round(2.2 * s, 1)
    dim = ImageEnhance.Brightness(img.filter(ImageFilter.GaussianBlur(radius))).enhance(0.55)
    return Image.composite(dim, img, mask)


def fit(text, width, make, lo=40, hi=220):
    while hi - lo > 1:
        mid = (lo + hi) // 2
        l, _, r, _ = make(mid).getbbox(text)
        lo, hi = (mid, hi) if r - l <= width else (lo, mid)
    return lo


def headline(img, top, pad):
    """Two centred lines of Lora Bold in cream over a feathered ink band."""
    # 92% of the edge-to-edge fit: the full fit read as crammed against the frame.
    size = round(0.92 * min(fit(t, W - 2 * pad, lora) for t in HEADLINE))
    font = lora(size)
    lead = round(size * 1.08)
    ys = [top + i * lead for i in range(len(HEADLINE))]
    d = ImageDraw.Draw(img)
    boxes = [d.textbbox((W // 2, y), t, font=font, anchor="mt") for t, y in zip(HEADLINE, ys)]
    x0 = min(b[0] for b in boxes); x1 = max(b[2] for b in boxes)
    y0 = boxes[0][1]; y1 = boxes[-1][3]

    # Feathered scrim: a soft top wash plus a blurred band behind the type.
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    fade_end = y1 + 160
    for y in range(fade_end):
        md.line((0, y, W, y), fill=round(160 * (1 - y / fade_end) ** 1.2))
    band = Image.new("L", img.size, 0)
    ImageDraw.Draw(band).rectangle((x0 - 60, y0 - 50, x1 + 60, y1 + 50), fill=175)
    band = band.filter(ImageFilter.GaussianBlur(55))
    mask = ImageChops.lighter(mask, band)
    img.paste(Image.new("RGB", img.size, INK), (0, 0), mask)

    d = ImageDraw.Draw(img)
    for t, y in zip(HEADLINE, ys):
        d.text((W // 2, y), t, font=font, fill=CREAM, anchor="mt")
    return size, y1


def wrap_ledger(d, items, font, sep_w, width):
    lines, cur, cur_w = [], [], 0
    for it in items:
        w = d.textlength(it, font=font)
        add = w if not cur else sep_w + w
        if cur and cur_w + add > width:
            lines.append(cur); cur, cur_w = [it], w
        else:
            cur.append(it); cur_w += add
    lines.append(cur)
    return lines


def render(h, path, spec):
    pad = spec["pad"]
    img = Image.new("RGB", (W, h), CREAM)
    photo = hero(spec["photo_h"], spec["focus_x"])
    img.paste(photo, (0, 0))
    hl_size, _ = headline(img, spec["hl_top"], pad)
    d = ImageDraw.Draw(img)
    sizes = {"headline": hl_size}

    # --- paper foot ---------------------------------------------------------
    y = spec["photo_h"]
    d.rectangle((0, y, W, y + 5), fill=INK)              # edge rule, full bleed
    y += spec["rule_gap"]
    d.rectangle((pad, y, W - pad, y + 3), fill=INK)      # newspaper double rule
    d.rectangle((pad, y + 9, W - pad, y + 9), fill=INK)
    y += 9

    # tier 1: the deck
    deck = barlow(spec["deck"], 600)
    sizes["deck"] = spec["deck"]
    y += spec["deck_gap"]
    for line in DECK:
        y += round(spec["deck"] * 0.98)
        d.text((pad, y), line, font=deck, fill=INK, anchor="ls")
        y += round(spec["deck"] * 0.22)

    # tier 2: the nine trackers
    y += spec["ledger_gap"]
    num = barlow(spec["num"], 700)
    sizes["numeral"] = spec["num"]
    nb = d.textbbox((pad, y), "9", font=num, anchor="lt")
    at = (2 * pad - nb[0], 2 * y - nb[1])            # ink box starts at (pad, y)
    d.text(at, "9", font=num, fill=AMBER, anchor="lt")
    nb = d.textbbox(at, "9", font=num, anchor="lt")
    col = nb[2] + spec["num_gap"]
    lab = barlow(spec["label"], 700)
    sizes["label"] = spec["label"]
    tracked(d, (col, nb[1] + round(spec["label"] * 0.72)), "LIVE TRACKERS ON THE SITE",
            lab, INK, round(spec["label"] * 0.16))
    item = barlow(spec["item"], 600)
    sizes["ledger"] = spec["item"]
    sep = "  ·  "
    sep_w = d.textlength(sep, font=item)
    lines = wrap_ledger(d, TRACKERS, item, sep_w, W - pad - col)
    ly = nb[1] + round(spec["label"] * 0.72) + round(spec["item"] * 1.25)
    for ln in lines:
        x = col
        for i, it in enumerate(ln):
            if i:
                d.text((x, ly), sep, font=item, fill=AMBER, anchor="ls")
                x += sep_w
            d.text((x, ly), it, font=item, fill=INK_SOFT, anchor="ls")
            x += d.textlength(it, font=item)
        ly += round(spec["item"] * 1.22)
    y = max(nb[3], ly - round(spec["item"] * 1.22) + 8)

    # amber hairline, then tier 3: the masthead
    y += spec["sig_gap"]
    d.rectangle((pad, y, W - pad, y + 1), fill=AMBER)
    mast = lora(spec["mast"], 700)
    sizes["masthead"] = spec["mast"]
    my = y + spec["sig_gap"] + round(spec["mast"] * 0.78)
    d.text((pad, my), URL, font=mast, fill=INK, anchor="ls")
    tag = barlow(spec["tag"], 600)
    sizes["tag"] = spec["tag"]
    tag_w = tracked(d, (W - pad, my), TAG, tag, INK, round(spec["tag"] * 0.2), anchor="r")
    gap = (W - pad - tag_w) - d.textbbox((pad, my), URL, font=mast, anchor="ls")[2]
    assert gap >= 60, f"masthead and tag {gap}px apart"
    sizes["last_baseline"] = my

    img.save(path, optimize=True)
    print(path, sizes)
    return sizes


FEED = dict(pad=64, photo_h=860, focus_x=470, hl_top=78, rule_gap=44, deck=44,
            deck_gap=12, ledger_gap=40, num=120, num_gap=26, label=26, item=29,
            sig_gap=32, mast=56, tag=26)
STORY = dict(pad=64, photo_h=1150, focus_x=470, hl_top=170, rule_gap=52, deck=54,
             deck_gap=14, ledger_gap=50, num=165, num_gap=32, label=31, item=36,
             sig_gap=40, mast=58, tag=27)

if __name__ == "__main__":
    print("ink on cream %.2f:1, ink-soft on cream %.2f:1, cream on ink %.2f:1" % (
        contrast(INK, CREAM), contrast(INK_SOFT, CREAM), contrast(CREAM, INK)))
    render(1350, HERE / "ad_static_claude_1080x1350.png", FEED)
    s = render(1920, HERE / "ad_static_claude_1080x1920.png", STORY)
    assert s["last_baseline"] <= 1920 - 250, "story foot runs into the platform UI"
