"""ALPR land ownership data for /surveillance/.

/surveillance/ is the only ALPR page on this site. The land ownership explorer lives inside it: the
camera, owner and parcel lists are rendered into the page's own HTML (so a crawler and a reader
without JavaScript get every record), and assets/js/alpr-explorer.js opens the full records from a
data file served at /assets/alpr/ownership.json. That file is an asset, not a page: no HTML, no
canonical, nothing in the sitemap.

The data is researched on the local box (work/alpr_ownership/, gitignored) and committed as
data/alpr/explorer_data.json by work/alpr_ownership/rebuild_all.py, already through publish_filter.
This module reads it, applies the private-owner rule below, and writes the asset on every CI build.
"""
from __future__ import annotations

import hashlib
import json

from build import common

SRC = common.ROOT / "data" / "alpr" / "explorer_data.json"
STATS_SRC = common.ROOT / "data" / "alpr" / "explorer_stats.json"
ASSET_REL = "assets/alpr/ownership.json"

# Private owners: the tax roll names private individuals and family trusts, and most of them are not
# the camera's operator (202 of 268 cameras stand beside the joined parcel, in a street or setback,
# not on it). The explorer's own notes left "name private individuals next to exact camera
# locations?" as an open decision, so the page defaults to NOT printing those names. Companies and
# public agencies are always named. Set this to True to publish private names exactly as the roll
# states them; every surface (lists, records, FAQ, search) follows this one switch.
PUBLISH_PRIVATE_NAMES = False
PRIVATE_TYPES = {"individual", "person", "trust"}

# Fields that identify or reach a private owner. Dropped from private records when names are withheld.
_PRIVATE_FIELDS = ("phone", "email", "mail", "agent", "officers", "principal", "sos", "sos_status",
                   "status", "sos_note", "csource", "ent_src", "listed", "plabel", "court",
                   "court_url", "taxnum", "url", "conf")

_cache: dict | None = None


def is_private(t) -> bool:
    return str(t or "").lower() in PRIVATE_TYPES


def private_label(t) -> str:
    return "Private trust (name not published)" if str(t or "").lower() == "trust" \
        else "Private owner (name not published)"


def _apply_privacy(d: dict) -> dict:
    owners = d.get("owners", [])
    cams = d.get("cams", [])
    parcels = d.get("parcels", [])
    name_to_oid = {o.get("name"): o.get("oid") for o in owners}
    # Parcels list owners by name; give them the owner index too, so a record can link an owner
    # whose name is not printed.
    for p in parcels:
        p["oids"] = [name_to_oid.get(n) for n in p.get("owners", [])]
    if PUBLISH_PRIVATE_NAMES:
        return d
    priv = {o.get("oid"): o.get("type") for o in owners if is_private(o.get("type"))}
    for o in owners:
        if o.get("oid") in priv:
            o["_orig"] = o.get("name") or ""
            o["name"] = private_label(o.get("type"))
            o["withheld"] = True
            for k in _PRIVATE_FIELDS:
                o.pop(k, None)
            o["has_contact"] = False
    for c in cams:
        if c.get("oid") in priv:
            c["owner"] = private_label(c.get("otype"))
            c["withheld"] = True
            for k in _PRIVATE_FIELDS:
                c.pop(k, None)
    for p in parcels:
        p["owners"] = [private_label(priv[oid]) if oid in priv else n
                       for n, oid in zip(p.get("owners", []), p["oids"])]
    # A name can also ride inside free text (the city GIS note says "the tax-roll owner is ..."),
    # so scrub every string field, not only the fields known to hold a name.
    names = sorted({o["_orig"] for o in owners if o.get("_orig")}, key=len, reverse=True)
    for rec in cams + owners + parcels:
        for k, v in list(rec.items()):
            if isinstance(v, str):
                for n in names:
                    if n in v:
                        v = v.replace(n, "a private owner")
                rec[k] = v
    for o in owners:
        o.pop("_orig", None)
    return d


def load() -> dict | None:
    """The published ownership data, or None when the file is missing or unreadable."""
    global _cache
    if _cache is not None:
        return _cache or None
    try:
        d = json.loads(SRC.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not d.get("cams"):
            raise ValueError("empty ownership data")
        _cache = _apply_privacy(d)
    except Exception as e:  # noqa: BLE001 - a missing data file must not stop the site build
        common.log(f"alpr_explorer: ownership data unavailable ({type(e).__name__}: {e})")
        _cache = {}
    return _cache or None


def stats() -> dict:
    """Counts the pipeline printed (data/alpr/explorer_stats.json). 'n/a' when missing, never a guess."""
    try:
        s = json.loads(STATS_SRC.read_text(encoding="utf-8"))
        if not isinstance(s, dict) or not s.get("cameras"):
            raise ValueError("empty stats")
        return s
    except Exception:  # noqa: BLE001
        return {k: "n/a" for k in ("cameras", "owners", "parcels", "in_city", "contact_owners",
                                   "multi_owner", "private_parcel", "street_row", "city_owned", "built")}


def _payload() -> str:
    d = load()
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")) if d else ""


def asset_url(rel: str) -> str:
    """URL of the data file with a content hash, so a new build is never served from a stale cache."""
    blob = _payload()
    v = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10] if blob else "0"
    return f"{rel}{ASSET_REL}?v={v}"


def build(ctx, sources):
    blob = _payload()
    if not blob:
        common.log("builder alpr_explorer: no ownership data, asset not written")
        return []
    common.write(common.SITE / ASSET_REL, blob)
    common.log(f"builder alpr_explorer: {len(blob)} bytes to /{ASSET_REL}")
    # No HTML page: /surveillance/ is the only ALPR url.
    return []
