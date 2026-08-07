"""Fetch topic images from Wikimedia Commons into assets/img/ and write
data/images.json manifest. Run once; images are committed so CI builds never
hit the network. Credit metadata comes from the Commons API (license, artist)."""
import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "assets" / "img"
IMG_DIR.mkdir(exist_ok=True)

UA = {"User-Agent": "BakersfieldBrief/1.0 (site build; contact via site)"}

# slug -> (Commons file title, fallback alt)
WANT = {
    "skyline": ("File:BakersfieldSkyline.jpg", "Bakersfield skyline"),
    "river": ("File:Bakersfield aerial with Kern River.jpg", "Kern River through Bakersfield"),
    "isabella": ("File:01-2007-LakeIsabella-fromEast.jpg", "Isabella Lake, Kern County"),
    "oil": ("File:Bakersfield Field Office oil derrick (48080292657).jpg", "Oil derrick in the Kern County oil field"),
    "almonds": ("File:20250825-USDA-NRCS-DD-4 (54762040882).jpg", "Almond orchard in the San Joaquin Valley"),
    "wind": ("File:20211126 Nordtank Tehachapi Pass 0044.jpg", "Wind turbines at Tehachapi Pass"),
    "downtown": ("File:DowntownBakersfield.jpg", "Downtown Bakersfield"),
    "fair": ("File:Kern County Fair 009 (3988359129).jpg", "Kern County Fair"),
    "amtrak": ("File:Bakersfield Amtrak Station.jpg", "Bakersfield Amtrak station"),
    "chp": ("File:California Highway Patrol (48906661386).jpg", "California Highway Patrol vehicle"),
}


def api(params):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def strip_html(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    # collapse nested link text like "User:Foo" to a readable name
    return s


def clean_artist(raw):
    s = strip_html(raw)
    s = re.sub(r"^https?://\S+\s*", "", s)
    if s.lower().startswith("user:"):
        s = s[len("user:"):]
    return s or "Unknown"


manifest = {}
for slug, (title, alt) in WANT.items():
    out = IMG_DIR / f"{slug}.jpg"
    print(f"--- {slug}: {title}")
    try:
        data = api({
            "action": "query", "format": "json", "titles": title,
            "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1280",
        })
        pages = data.get("query", {}).get("pages", {})
        info = next(iter(pages.values()))
        ii = info.get("imageinfo", [{}])[0]
        thumb = ii.get("thumburl")
        if not thumb:
            print("  no thumburl, skipping"); continue
        req = urllib.request.Request(thumb, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        tmp = IMG_DIR / f"{slug}.orig"
        tmp.write_bytes(raw)
        im = Image.open(tmp).convert("RGB")
        im.thumbnail((1280, 1280))
        im.save(out, "JPEG", quality=82, optimize=True)
        tmp.unlink()
        meta = ii.get("extmetadata", {})
        manifest[slug] = {
            "file": f"assets/img/{slug}.jpg",
            "alt": alt,
            "credit": clean_artist((meta.get("Artist") or {}).get("value", "")),
            "license": (meta.get("LicenseShortName") or {}).get("value", ""),
            "source": info.get("title", ""),
            "width": im.width, "height": im.height,
        }
        print(f"  saved {out.name} {im.width}x{im.height} | {manifest[slug]['license']} | {manifest[slug]['credit'][:50]}")
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED: {e}")
    time.sleep(3)

(ROOT / "data" / "images.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print("\nManifest entries:", len(manifest))
