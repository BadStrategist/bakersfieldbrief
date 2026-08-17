"""
backgrounds.py — small library of procedurally drawn 1080x1920 night scenes for reel cards.
No photos, no downloads: everything is generated, so you own it and it renders the same every time.

Scenes:  highway | fire | police | water | city | medical | weather
Usage:   from backgrounds import make, pick_scene, treat
         bg = treat(make("highway"))          # ready to draw text on
         make("highway", seed=3)              # different streak layout, same look
         pick_scene("Structure fire on Union Ave")  -> "fire"
CLI:     python backgrounds.py            # writes previews to out/bg_<scene>.png + out/bg_sheet.png
"""
import numpy as np, re, os, sys
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920

SCENES = ["highway", "fire", "police", "water", "city", "medical", "weather"]

KEYWORDS = {
    "highway": r"\b(crash|collision|wrong[- ]way|highway|hwy|freeway|99|58|178|i-5|interstate|rollover|dui|hit[- ]and[- ]run|pedestrian struck|vehicle|motorcycl|traffic)\b",
    "fire":    r"\b(fire|blaze|flames|burn|smoke|structure|arson|brush|wildfire|explosion)\b",
    "police":  r"\b(shoot|shot|stab|homicide|murder|robber|burglar|arrest|suspect|police|bpd|kcso|deput|officer|pursuit|standoff|gunfire|assault|swat)\b",
    "water":   r"\b(river|kern river|canal|lake|drown|water rescue|swift[- ]water|rescue|missing hiker|search and rescue|search & rescue|isabella)\b",
    "medical": r"\b(hospital|overdose|medical|paramedic|ambulance|cpr|injur|hazmat|gas leak|carbon monoxide)\b",
    "weather": r"\b(storm|wind|rain|flood|fog|heat|lightning|weather|power outage|outage|pg&e|dust)\b",
}

def pick_scene(text: str) -> str:
    """Keyword-based scene selection. First match in priority order wins; default city."""
    t = text.lower()
    for scene in ["fire", "highway", "police", "water", "medical", "weather"]:
        if re.search(KEYWORDS[scene], t):
            return scene
    return "city"


# ---------------- drawing helpers ----------------
def _gradient(top, mid, bot, split=0.42):
    y = np.linspace(0, 1, H)[:, None]
    top, mid, bot = map(np.array, (top, mid, bot))
    img = np.where(y < split, top + (mid - top) * (y / split), mid + (bot - mid) * ((y - split) / (1 - split)))
    img = np.repeat(img[:, None, :], W, axis=1).astype(np.float32)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")

def _glow(im, box, color, blur):
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(g).ellipse(box, fill=color)
    g = g.filter(ImageFilter.GaussianBlur(blur)); im.alpha_composite(g)

def _grain(im, rng, amt=3.5):
    arr = np.asarray(im.convert("RGB")).astype(np.float32); arr += rng.normal(0, amt, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")

def _road(im, rng, vx=W * 0.5, vy=800, taillights=14, headlights=10):
    d = ImageDraw.Draw(im, "RGBA")
    d.polygon([(vx - 30, vy), (vx + 30, vy), (W + 500, H), (-500, H)], fill=(24, 24, 28, 255))
    for i in range(60):
        f = (i / 60) ** 2.2; f2 = ((i + 0.45) / 60) ** 2.2
        y0 = vy + f * (H - vy); y1 = vy + f2 * (H - vy)
        for lane in (-0.5, 0.5):
            d.line([(vx + lane * 60 * (1 + f * 12), y0), (vx + lane * 60 * (1 + f2 * 12), y1)],
                   fill=(230, 220, 190, int(200 * f + 30)), width=int(2 + f * 10))
    st = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(st)
    for lane, n, col in ((1, taillights, (255, 40, 30, 200)), (-1, headlights, (255, 245, 210, 190))):
        for _ in range(n):
            s = rng.uniform(0.15, 1.0)
            pts = [(vx + lane * 60 * (1 + t * 12) + rng.uniform(-8, 8), vy + t ** 2.2 * (H - vy)) for t in np.linspace(0.05, s, 12)]
            sd.line(pts, fill=col, width=int(4 + s * 26))
    st = st.filter(ImageFilter.GaussianBlur(14)); im.alpha_composite(st)
    d = ImageDraw.Draw(im, "RGBA")
    for i in range(6):
        f = (i / 6) ** 1.6
        for side in (-1, 1):
            x = vx + side * (120 + f * 700); y = vy + 20 - f * 300; r = 4 + f * 10
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 200, 120, 230))

def _skyline(im, rng, base_y=1180, color=(14, 16, 22), window=(255, 205, 120), density=0.25):
    d = ImageDraw.Draw(im, "RGBA")
    x = -40
    while x < W + 40:
        w = int(rng.uniform(50, 140)); h = int(rng.uniform(120, 520))
        d.rectangle([x, base_y - h, x + w, base_y + 40], fill=color + (255,))
        for wy in range(base_y - h + 18, base_y - 10, 26):
            for wx in range(x + 10, x + w - 12, 22):
                if rng.random() < density:
                    d.rectangle([wx, wy, wx + 9, wy + 12], fill=window + (int(rng.uniform(120, 230)),))
        x += w + int(rng.uniform(6, 30))
    d.rectangle([0, base_y + 40, W, H], fill=(8, 8, 11, 255))

def _stars(im, rng, n=120, ymax=700):
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, ymax); r = rng.uniform(0.6, 2.0)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, int(rng.uniform(60, 200))))


# ---------------- scenes ----------------
def scene_highway(rng):
    im = _gradient((12, 18, 34), (28, 32, 52), (10, 10, 14))
    _stars(im, rng, 60, 600)
    _glow(im, [-200, 720, W + 200, 1000], (255, 170, 80, 90), 120)
    _road(im, rng)
    _glow(im, [-100, 500, 500, 1000], (200, 40, 40, 70), 160)
    _glow(im, [600, 520, 1200, 1020], (40, 90, 220, 70), 160)
    return im

def scene_fire(rng):
    im = _gradient((10, 8, 10), (48, 22, 12), (8, 6, 6), 0.5)
    _skyline(im, rng, base_y=1250, color=(10, 8, 9), window=(255, 150, 60), density=0.06)
    # fire glow behind rooftops
    _glow(im, [150, 900, 930, 1300], (255, 120, 20, 170), 130)
    _glow(im, [300, 1000, 780, 1260], (255, 200, 60, 140), 60)
    # smoke plume
    sm = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sm)
    for i in range(18):
        t = i / 18; cx = 540 + rng.uniform(-60, 60) + t * 120; cy = 1100 - t * 900; r = 60 + t * 260
        sd.ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6], fill=(70, 55, 50, int(90 * (1 - t) + 20)))
    sm = sm.filter(ImageFilter.GaussianBlur(70)); im.alpha_composite(sm)
    # embers
    d = ImageDraw.Draw(im, "RGBA")
    for _ in range(90):
        x, y = rng.uniform(300, 800), rng.uniform(600, 1200); r = rng.uniform(1, 3.5)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, int(rng.uniform(120, 220)), 40, int(rng.uniform(120, 255))))
    _glow(im, [-100, 700, 300, 1150], (255, 60, 40, 60), 150)
    return im

def scene_police(rng):
    im = _gradient((6, 8, 18), (16, 20, 38), (8, 8, 12), 0.45)
    _stars(im, rng, 40, 500)
    _skyline(im, rng, base_y=1150, color=(12, 14, 20), window=(200, 210, 255), density=0.12)
    # wet street with reflections
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([0, 1190, W, H], fill=(14, 15, 20, 255))
    for i in range(0, 5):
        _glow(im, [60 + i * 220, 1240, 200 + i * 220, 1900], (60, 110, 255, 60) if i % 2 else (255, 60, 60, 60), 60)
    # alternating red/blue wash (frozen light bar)
    _glow(im, [-200, 300, 500, 1100], (255, 40, 40, 110), 170)
    _glow(im, [580, 300, 1280, 1100], (40, 90, 255, 130), 170)
    # street lamps
    for x in (140, 540, 940):
        d.ellipse([x - 8, 980, x + 8, 996], fill=(255, 220, 160, 240))
        _glow(im, [x - 90, 900, x + 90, 1080], (255, 220, 160, 60), 60)
    return im

def scene_water(rng):
    im = _gradient((6, 10, 22), (14, 26, 44), (4, 8, 16), 0.5)
    _stars(im, rng, 140, 800)
    # moon
    _glow(im, [760, 200, 900, 340], (230, 235, 255, 200), 30)
    d = ImageDraw.Draw(im, "RGBA"); d.ellipse([790, 230, 870, 310], fill=(240, 242, 250, 255))
    # canyon silhouettes
    for k, (yy, col) in enumerate(((880, (10, 14, 22)), (960, (7, 10, 16)), (1040, (5, 7, 12)))):
        pts = [(0, H)]
        x = 0
        while x <= W:
            pts.append((x, yy + rng.uniform(-90, 60) - k * 20)); x += 90
        pts += [(W, H)]
        d.polygon(pts, fill=col + (255,))
    # water with moon streak and ripples
    d.rectangle([0, 1120, W, H], fill=(6, 12, 22, 255))
    wv = Image.new("RGBA", (W, H), (0, 0, 0, 0)); wd = ImageDraw.Draw(wv)
    for y in range(1130, H, 9):
        t = (y - 1130) / (H - 1130); w = 40 + t * 380; x0 = 830 - w / 2 + rng.uniform(-30, 30)
        wd.line([(x0, y), (x0 + w, y)], fill=(200, 215, 240, int(120 * (1 - t) + 20)), width=2)
        for _ in range(3):
            xx = rng.uniform(0, W); ll = rng.uniform(20, 120)
            wd.line([(xx, y), (xx + ll, y)], fill=(90, 130, 180, int(rng.uniform(20, 70))), width=1)
    wv = wv.filter(ImageFilter.GaussianBlur(1.5)); im.alpha_composite(wv)
    _glow(im, [-100, 1000, 400, 1500], (255, 80, 60, 40), 150)  # faint rescue light on the bank
    return im

def scene_city(rng):
    im = _gradient((10, 12, 26), (24, 24, 44), (8, 8, 12), 0.5)
    _stars(im, rng, 100, 700)
    _glow(im, [-100, 700, W + 100, 1100], (255, 160, 90, 80), 140)
    _skyline(im, rng, base_y=1180, density=0.3)
    # a couple of oil derrick silhouettes on the horizon (Kern flavor)
    d = ImageDraw.Draw(im, "RGBA")
    for x in (180, 900):
        d.line([(x - 40, 1160), (x, 940), (x + 40, 1160)], fill=(6, 6, 9, 255), width=6)
        for yy in (1010, 1080): d.line([(x - 22 + (yy - 1010) * 0.15, yy), (x + 22 - (yy - 1010) * 0.15, yy)], fill=(6, 6, 9, 255), width=4)
    _road(im, rng, vy=1220, taillights=6, headlights=5)
    return im

def scene_medical(rng):
    im = _gradient((8, 10, 16), (18, 22, 30), (6, 8, 10), 0.5)
    _skyline(im, rng, base_y=1150, color=(12, 14, 18), window=(220, 240, 255), density=0.2)
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle([0, 1190, W, H], fill=(12, 13, 16, 255))
    # hospital / bay lighting: cool white + one amber, faint red cross glow (no logo)
    _glow(im, [200, 700, 880, 1150], (200, 230, 255, 120), 140)
    _glow(im, [-100, 900, 400, 1300], (255, 180, 80, 70), 130)
    _glow(im, [700, 500, 1200, 900], (255, 60, 60, 60), 160)
    for i in range(4):
        _glow(im, [120 + i * 260, 1230, 220 + i * 260, 1900], (200, 230, 255, 40), 60)
    return im

def scene_weather(rng):
    im = _gradient((10, 12, 20), (34, 38, 52), (12, 12, 16), 0.55)
    # cloud bank
    cl = Image.new("RGBA", (W, H), (0, 0, 0, 0)); cd = ImageDraw.Draw(cl)
    for _ in range(40):
        cx, cy = rng.uniform(-100, W + 100), rng.uniform(150, 700); r = rng.uniform(120, 320)
        cd.ellipse([cx - r, cy - r * 0.5, cx + r, cy + r * 0.5], fill=(60, 64, 80, 120))
    cl = cl.filter(ImageFilter.GaussianBlur(60)); im.alpha_composite(cl)
    # lightning glow
    _glow(im, [300, 200, 800, 700], (210, 220, 255, 90), 150)
    _skyline(im, rng, base_y=1200, color=(10, 11, 16), window=(240, 230, 200), density=0.15)
    # rain streaks
    rn = Image.new("RGBA", (W, H), (0, 0, 0, 0)); rd = ImageDraw.Draw(rn)
    for _ in range(500):
        x, y = rng.uniform(0, W), rng.uniform(0, H); ln = rng.uniform(25, 70)
        rd.line([(x, y), (x - 8, y + ln)], fill=(200, 210, 230, int(rng.uniform(25, 90))), width=1)
    rn = rn.filter(ImageFilter.GaussianBlur(0.8)); im.alpha_composite(rn)
    _road(im, rng, vy=1240, taillights=8, headlights=6)
    return im

_SCENE_FN = dict(highway=scene_highway, fire=scene_fire, police=scene_police, water=scene_water,
                 city=scene_city, medical=scene_medical, weather=scene_weather)


def make(scene: str = "city", seed: int = 0) -> Image.Image:
    """Return an untreated 1080x1920 RGB background for the scene."""
    scene = scene if scene in _SCENE_FN else "city"
    rng = np.random.default_rng(seed + hash(scene) % 1000)
    im = _SCENE_FN[scene](rng)
    return _grain(im, rng).convert("RGB")


def treat(bg: Image.Image, blur=3, darken=0.35, focus_y=0.32) -> Image.Image:
    """Make a background text-safe: soft blur, overall darken, vertical vignette (darkest at focus_y)."""
    b = bg.convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(blur))
    b = Image.blend(b, Image.new("RGB", (W, H), (0, 0, 0)), darken)
    m = np.linspace(0, 1, H); v = 0.18 + 0.50 * np.exp(-((m - focus_y) / 0.28) ** 2)
    arr = np.asarray(b).astype(np.float32) * (1 - v[:, None, None])
    return Image.fromarray(arr.astype(np.uint8))


def load_or_make(scene=None, image_path=None, seed=0):
    """image_path (a real photo) wins if it exists; otherwise the pre-treated
    background library (backgrounds/<scene>_treated.png — the exact images the
    reel shows); else render the scene procedurally as a fallback."""
    if image_path and os.path.exists(image_path):
        im = Image.open(image_path).convert("RGB")
        # cover-crop to 9:16
        r = max(W / im.width, H / im.height); im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1))
        x0 = (im.width - W) // 2; y0 = (im.height - H) // 2
        return treat(im.crop((x0, y0, x0 + W, y0 + H)))
    lib = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "backgrounds", f"{scene or 'city'}_treated.png")
    if os.path.exists(lib):
        return Image.open(lib).convert("RGB")
    return treat(make(scene or "city", seed))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__)); out = os.path.join(here, "out"); os.makedirs(out, exist_ok=True)
    tiles = []
    for s in SCENES:
        raw = make(s); raw.save(os.path.join(out, f"bg_{s}.png"))
        tiles.append(raw.resize((360, 640)))
        print("wrote", f"out/bg_{s}.png")
    sheet = Image.new("RGB", (len(tiles) * 372, 640), (255, 255, 255))
    for i, t in enumerate(tiles): sheet.paste(t, (i * 372, 0))
    sheet.save(os.path.join(out, "bg_sheet.png")); print("wrote out/bg_sheet.png")
