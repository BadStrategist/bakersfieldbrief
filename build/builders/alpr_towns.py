"""Town pages for the Flock & ALPR map: /surveillance/<town>/, spokes off /surveillance/.

Each page is one town's share of the county camera list, with the same map and records as the
hub and a table that a list of dots cannot print: for every camera, the owner of record for the
land at or beside it, the use and assessed value the assessor lists, and the county supervisor
district.

Which town a camera is in is a looked-up fact (build/places_kern.py, Census boundaries). A
camera inside no city or Census place is on no town page: the hub lists it. A town may also
list the cameras just outside its limits, under their own heading, each with the measured
distance to the boundary; they are never counted as the town's.

A page is built only when it would not be thin and not be half empty:
  * the town is in TOWNS, which is the reviewed list (a place that reaches MIN_CAMERAS and is
    not listed is named in the build log, so adding it is a decision and not an accident);
  * it holds at least FLOOR cameras inside its places;
  * the ownership data comes from a join that covered the county (it carries "norecord"),
    and that join has looked up READY_SHARE of all mapped cameras and of this town's own.
Until the county join lands, the third test fails for every town and this builder writes
nothing: no page, no link on the hub, no sitemap entry.
"""
from __future__ import annotations

import collections
import html
import re

from .. import common, places_kern
from . import alpr_explorer, alpr_page
from . import page as page_mod

esc = html.escape

# A town earns a page at ten cameras. A listed town keeps its page down to eight, so one node
# removed by a mapper does not take a ranking url off the site; below that the url redirects
# to the hub (redirect_lines).
MIN_CAMERAS = 10
FLOOR = 8
READY_SHARE = 0.9
NEAR_KM = 5.0
KM_PER_MILE = 1.609344

# slug -> the town. "places" are Census place names, the first one the town itself. Bakersfield
# is not here on purpose: /surveillance/ is Bakersfield's page and ranks as it.
# Counts on 2026-10-12, cameras inside the places: Shafter 32, Ridgecrest 31, Delano 30,
# McFarland 19, Oildale 13, Tehachapi 12 (city 7, Golden Hills 2, Bear Valley Springs 2,
# Stallion Springs 1), Rosedale 11, Wasco 10. Below the bar that day: Mojave 5, Taft 4,
# Maricopa 2, Rosamond 2, Boron 2, Keene 2, McKittrick 2, California City 0, Arvin 0.
TOWNS = {
    "ridgecrest": {"name": "Ridgecrest", "places": ("Ridgecrest",), "near": True},
    "delano": {"name": "Delano", "places": ("Delano",), "near": True},
    "shafter": {"name": "Shafter", "places": ("Shafter",), "near": True},
    "mcfarland": {"name": "McFarland", "places": ("McFarland",), "near": True},
    "wasco": {"name": "Wasco", "places": ("Wasco",), "near": True},
    "tehachapi": {"name": "Tehachapi", "near": True,
                  "places": ("Tehachapi", "Golden Hills", "Bear Valley Springs", "Stallion Springs")},
    # Unincorporated communities inside the Bakersfield metro. No "near": the land around
    # them is Bakersfield or another community, which the hub covers.
    "oildale": {"name": "Oildale", "places": ("Oildale",), "near": False},
    "rosedale": {"name": "Rosedale", "places": ("Rosedale",), "near": False},
}


def _is_flock(c: dict) -> bool:
    return "flock" in (c.get("manu") or "").lower()


def plan(sources: dict) -> dict:
    """Which town pages this build writes: slug -> {"town", "cams", "near", ...}, in TOWNS order.

    Pure: reads the camera list and the ownership data, writes nothing. The hub calls it for
    its links, build() for the pages, so the two cannot disagree."""
    alpr = sources.get("alpr") or {}
    own = alpr_explorer.load()
    if not alpr.get("ok") or not own:
        return {}
    # "norecord" is written only by a join that covered the county (work/alpr_ownership/
    # county_join.py; the list may be empty). The September join has no such key, and against
    # the old metro-only camera list it reads as 99 percent complete.
    if "norecord" not in own:
        return {}
    cams = alpr_page.merge_cameras(alpr.get("cameras") or [], own)
    if not cams:
        return {}
    cov = alpr_page.coverage(cams)
    if (cov["joined"] + cov["norecord"]) < READY_SHARE * len(cams):
        return {}
    owner_slug = {p: slug for slug, t in TOWNS.items() for p in t["places"]}
    by_town = collections.defaultdict(list)
    by_place = collections.Counter()
    for c in cams:
        pl = c.get("place")
        if pl:
            by_place[pl["name"]] += 1
            if pl["name"] in owner_slug:
                by_town[owner_slug[pl["name"]]].append(c)
    for name, n in by_place.items():
        if n >= MIN_CAMERAS and name not in owner_slug and name != "Bakersfield":
            common.log(f"alpr_towns: {name} has {n} cameras and no town page (not in TOWNS)")
    # Cameras in no place, measured to the nearest place of any kind. One goes on a town's
    # "just outside" list only when that nearest place is the town itself.
    near = collections.defaultdict(list)
    for c, pl, km in _near_hits(cams):
        slug = owner_slug.get(pl["name"])
        if slug and TOWNS[slug]["near"] and pl["name"] == TOWNS[slug]["places"][0]:
            near[slug].append(dict(c, near_km=km, near_kind=pl["kind"]))
    out = {}
    for slug, town in TOWNS.items():
        mine = by_town.get(slug, [])
        tc = alpr_page.coverage(mine)
        if len(mine) < FLOOR or (tc["joined"] + tc["norecord"]) < READY_SHARE * len(mine):
            continue
        out[slug] = {"town": town, "slug": slug, "cams": mine, "coverage": tc,
                     "near": sorted(near.get(slug, []), key=lambda c: c["near_km"]),
                     "flock": sum(1 for c in mine if _is_flock(c)),
                     "asof": alpr.get("asof") or "",
                     "built": (own.get("meta") or {}).get("built", "")}
    return out


def _near_hits(cams: list) -> list[tuple]:
    """(camera, place, km) for each camera in no place whose nearest place boundary of any kind
    is within NEAR_KM."""
    out = []
    for c in cams:
        if c.get("place"):
            continue
        hit = places_kern.nearest(c.get("lat"), c.get("lon"), NEAR_KM)
        if hit:
            out.append((c, hit[0], hit[1]))
    return out


def place_rows(sources: dict) -> list[dict]:
    """Every mapped camera counted once, by the place its point is inside.

    One row for each incorporated city (a city with no mapped camera is a row of 0, so every
    city has its answer on the hub and none needs a page to give it), one for each
    unincorporated community holding a camera, and a last row, name None, for the cameras in
    no place. The "n" of the rows sums to the camera list. "near" is the cameras just outside
    the limits, for cities only: the same measurement the town pages print."""
    alpr = sources.get("alpr") or {}
    cams = alpr_page.merge_cameras(alpr.get("cameras") or [], alpr_explorer.load())
    inside = collections.Counter((c.get("place") or {}).get("name") for c in cams)
    near = collections.Counter(pl["name"] for _, pl, _ in _near_hits(cams) if pl["kind"] == "city")
    rows = [{"name": p["name"], "kind": p["kind"], "n": inside[p["name"]],
             "near": near[p["name"]] if p["kind"] == "city" else None}
            for p in places_kern.load() if p["kind"] == "city" or inside[p["name"]]]
    rows.sort(key=lambda r: (-r["n"], r["name"]))
    if inside[None]:
        rows.append({"name": None, "kind": None, "n": inside[None], "near": None})
    return rows


def hub_links_html(plans: dict, sources: dict) -> str:
    """The "by town" block on /surveillance/: the county's cameras counted by city and
    community, with a link on each place that has a town page. Empty when no town page was
    built."""
    if not plans:
        return ""
    page_of = {pl: slug for slug, p in plans.items() for pl in p["town"]["places"]}
    rows = place_rows(sources)

    def name_cell(r: dict) -> str:
        if r["name"] is None:
            return "In no city or Census place"
        kind = "city" if r["kind"] == "city" else "unincorporated"
        slug = page_of.get(r["name"])
        town = plans[slug]["town"] if slug else None
        if town and town["places"][0] == r["name"]:
            return (f'<a href="{slug}/">{esc(town["name"])} Flock camera map</a> '
                    f'<span class="ax-dim">{kind}</span>')
        on = f', on the <a href="{slug}/">{esc(town["name"])} map</a>' if town else ""
        return f'{esc(r["name"])} <span class="ax-dim">{kind}{on}</span>'

    trs = "".join(f'<tr><td>{name_cell(r)}</td><td class="num">{r["n"]}</td>'
                  f'<td class="num">{"" if r["near"] is None else r["near"]}</td></tr>'
                  for r in rows)
    cities = sum(1 for r in rows if r["kind"] == "city")
    return f"""
    <section class="card ax-towns" id="towns">
      <span class="tag">By town</span>
      <h3>Flock cameras by city and town in Kern County</h3>
      <p>Each camera on the map above is counted in the city or Census place its point is
      inside. All {cities} incorporated cities in Kern County are listed, and every
      unincorporated community with a mapped camera. A linked town has a page of its own: its
      cameras, and for every one the owner of record, the assessed value, the land use and the
      county supervisor district.</p>
      <div class="table-wrap"><table class="data">
        <thead><tr><th>City or community</th><th class="num">Cameras inside</th>
        <th class="num">Just outside the city limits</th></tr></thead>
        <tbody>{trs}</tbody>
        <tfoot><tr><td>Kern County</td><td class="num">{sum(r["n"] for r in rows)}</td><td></td></tr></tfoot>
      </table></div>
      <p>The last column counts cameras in unincorporated county land within
      {NEAR_KM / KM_PER_MILE:.0f} miles of a city&rsquo;s limits. They are not in that
      city&rsquo;s count.</p>
    </section>"""


def redirect_lines() -> str:
    """_redirects lines for listed towns with no page this build: the url goes to the hub,
    temporarily, so a link or a search result does not land on a 404."""
    return "".join(f"/surveillance/{slug}/  /surveillance/  302\n" for slug in TOWNS
                   if not (common.SITE / "surveillance" / slug / "index.html").exists())


# ------------------------------------------------------------------ the page
def _money(v) -> str:
    """The roll's total as dollars, or "not stated". Only a bare number is a value: the roll
    reader once returned "43,817,993 Total Prop. 13 Value 82,791,940" for one parcel."""
    v = str(v or "").strip()
    return "$" + v if re.fullmatch(r"\d[\d,]*", v) else "not stated"


def _district(v) -> str:
    """"2 - Chris Parlier" as the roll and the county site have it -> "District 2, Chris Parlier"."""
    n, _, who = str(v or "").partition(" - ")
    return f"District {n.strip()}, {who.strip()}" if n.strip().isdigit() and who.strip() else "not stated"


def _outside(km: float) -> str:
    """How far past the line. City limits run down the middle of roads and cameras stand on
    those roads, so many of these are a few steps: feet under a tenth of a mile, miles past it."""
    if km < 0.1 * KM_PER_MILE:
        return f"{max(10, round(km * 3280.84 / 10) * 10)} ft"
    return f"{km / KM_PER_MILE:.1f} mi"


def _owner_cell(c: dict) -> str:
    o, nr = c["own"], c.get("nr")
    if o:
        k = alpr_page.type_key(o.get("otype"))
        # a withheld name already says "Private owner": no second label after it
        label = None if o.get("withheld") else alpr_page.TYPE_LABEL.get(k)
        return (f'{esc(alpr_page.relation(o)).capitalize()} a parcel owned by '
                f'<b>{esc(o.get("owner") or "no owner name on the roll")}</b>'
                + (f' <span class="ax-dim">({label})</span>' if label else ""))
    if nr:
        return esc(alpr_page.norecord_line(nr))
    return "Land owner not looked up yet."


def _row(c: dict, places: bool, near: bool, limits: str) -> str:
    o = c["own"] or {}
    loc = alpr_page.loc_of(o) if c["own"] else (alpr_page.loc_of(c["nr"]) if c.get("nr")
                                                else f"Camera {c['id']}")
    cells = [f'<td><a href="#camera/{esc(c["id"])}">{esc(loc)}</a></td>']
    if places:
        cells.append(f'<td>{esc((c.get("place") or {}).get("name", ""))}</td>')
    if near:
        cells.append(f'<td>{_outside(c["near_km"])} outside the {esc(limits)}</td>')
    cells += [f"<td>{_owner_cell(c)}</td>",
              f'<td>{esc(o.get("use") or "")}</td>',
              f'<td class="num">{esc(_money(o.get("val"))) if c["own"] else ""}</td>',
              f'<td>{esc(_district(o.get("district"))) if c["own"] else ""}</td>',
              f'<td>{"Flock Safety" if _is_flock(c) else esc(c["manu"])}</td>',
              f'<td>{esc(c["mapped"] or "")}</td>']
    return "<tr>" + "".join(cells) + "</tr>"


def _table(cams: list, *, places: bool = False, near: bool = False, limits: str = "") -> str:
    head = ["Location"] + (["Place"] if places else []) + (["Distance"] if near else []) + [
        "Land at or beside the camera", "Use on the tax roll", "Assessed value",
        "County supervisor", "Maker", "Mapped on OSM"]
    order = sorted(cams, key=(lambda c: c["near_km"]) if near else
                   (lambda c: (alpr_page.loc_of(c["own"]) if c["own"] else "~", c["id"])))
    return ('<div class="table-wrap"><table class="data"><thead><tr>'
            + "".join(f'<th{" class=num" if h == "Assessed value" else ""}>{h}</th>' for h in head)
            + "</tr></thead><tbody>"
            + "".join(_row(c, places, near, limits) for c in order) + "</tbody></table></div>")


def _words(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _streets(cams: list) -> str:
    """The streets that hold two or more of the town's cameras, with the count for each."""
    n = collections.Counter(c["own"]["loc"] for c in cams if c["own"] and c["own"].get("loc")
                            and c["own"].get("trusted"))
    top = [(s, k) for s, k in n.most_common(3) if k >= 2]
    return _words([f"{k} on {s}" for s, k in top]) if top else ""


def _page(ctx, p: dict, plans: dict) -> str:
    rel = "../../"
    slug, town, cams, near = p["slug"], p["town"], p["cams"], p["near"]
    name, n, flock = town["name"], len(p["cams"]), p["flock"]
    asof, built = p["asof"], p["built"]
    primary = places_kern.by_slug(places_kern.slug(town["places"][0])) or {}
    limits = f"{town['places'][0]} city limits" if primary.get("kind") == "city" else town["places"][0]
    grouped = len({(c.get("place") or {}).get("name") for c in cams}) > 1
    where = name if not grouped else _words(sorted({c["place"]["name"] for c in cams},
                                                   key=lambda s: town["places"].index(s)))

    # The section carries the town's cameras plus the ones just outside its limits, so the panel
    # total is larger than the town's own count. Name the split, or the page reads 12 in its
    # headline and 15 in its map panel.
    note = f"{n} mapped cameras in {where}"
    if near:
        note += f", plus {len(near)} just outside the {limits}"
    explorer, facts = alpr_page.explorer_html(
        [_osm(c) for c in cams + near], asof, len(cams) + len(near), True, where=name,
        scoped=True, scope_note=note)
    explorer = explorer.replace('<section class="ax" id="explorer"',
                                f'<section class="ax" id="explorer" data-src="{alpr_explorer.asset_url(rel)}"', 1)

    counts = collections.Counter(alpr_page.type_key(c["own"].get("otype")) for c in cams if c["own"])
    land = [f"{counts[k]} at or beside {w}" for k, w in (("agency", "public agency land"),
            ("entity", "company land"), ("private", "privately owned land")) if counts[k]]
    streets = _streets(cams)
    tail = alpr_page.coverage_tail(p["coverage"])
    lede = (f"{n} license plate readers are mapped in {where}, {flock} of them Flock Safety "
            f"cameras." + (f" That includes {streets}." if streets else "")
            + (f" {'All ' if p['coverage']['joined'] == n else ''}{p['coverage']['joined']} are "
               f"joined to the Kern County tax-roll parcel at or beside them: {_words(land)}."
               if land else "")
            + (f" {tail[0].upper() + tail[1:]}." if tail else ""))
    newest = max((c["mapped"] for c in cams if c["mapped"]), default="")

    def stat(value, label, cls=""):
        return f'<div class="stat {cls}"><div class="n">{value}</div><div class="l">{label}</div></div>'

    stats = (stat(n, f"license plate readers in {esc(name)}") + stat(flock, "Flock Safety units", "amber")
             + stat(facts["owners"], "owners of record") + stat(esc(newest) or "n/a", "newest mapped on OSM"))

    near_html = ""
    if near:
        near_html = f"""
    <section class="card" id="nearby">
      <h2>Just outside the {esc(limits)}</h2>
      <p>{len(near)} more camera{'s stand' if len(near) != 1 else ' stands'} in unincorporated Kern
      County within {NEAR_KM / KM_PER_MILE:.0f} miles of the {esc(limits)}. They are not counted in
      {esc(name)}&rsquo;s {n}.</p>
      {_table(near, near=True, limits=limits)}
    </section>"""

    others = "".join(f'<li><a href="{rel}surveillance/{s}/">{esc(o["town"]["name"])}</a> '
                     f'<span class="ax-dim">{len(o["cams"])} cameras</span></li>'
                     for s, o in plans.items() if s != slug)
    place_link = (f' Local conditions, incidents and headlines are on the '
                  f'<a href="{rel}places/{slug}/">{esc(name)} page</a>.'
                  if _has_place_page(slug) else "")

    body = f"""
    <div class="pagehead">
      <nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Daily Brief</a> &rsaquo;
      <a href="{rel}trackers/">Trackers</a> &rsaquo;
      <a href="{rel}surveillance/">Flock camera map</a> &rsaquo; {esc(name)}</nav>
      <div class="hero"><p class="kicker">Flock &amp; ALPR map &middot; {esc(name)}</p>
      <h1>{esc(name)} Flock Camera Map</h1>
      <p class="lede">{esc(lede)}</p>
      <div class="meta"><span>Cameras as of <span class="updated">{esc(asof)}</span></span>
      <span class="dot">&bull;</span><span>county tax roll as of {esc(built)}</span></div></div>
    </div>

    <div class="stats">{stats}</div>

    {explorer}

    <section class="card" id="cameras">
      <h2>Every license plate reader in {esc(name)}, and whose land it stands at or beside</h2>
      <p>A camera is joined to the nearest Kern County tax-roll parcel within 60 meters. Most
      stand in a street or setback beside that parcel, not on it, and each row says which. Tap a
      location for the full record: the parcel number, the facing direction and the source for
      every value.</p>
      {_table(cams, places=grouped)}
    </section>
    {near_html}

    <section class="card" id="more">
      <h2>More of the county map</h2>
      <p><a href="{rel}surveillance/">Every mapped license plate reader in Kern County</a>, with
      the weekly change log and the owners with the most cameras at or beside their land.{place_link}</p>
      <ul class="ax-townlinks">{others}</ul>
    </section>

    <p class="note">Camera points: &copy; OpenStreetMap contributors (ODbL), mapped by volunteers;
    a mapped date is not an install date. Town boundaries: U.S. Census Bureau. Owner of record,
    use and assessed value: Kern County assessor roll, read through kerndata.com. Private
    individuals and family trusts are not named. This page offers no guidance on avoiding or
    interfering with these devices.</p>

    <script type="application/json" id="tracker-data">{common.script_json(_payload(cams + near, asof))}</script>"""

    desc = (f"Map of all {n} license plate readers in {name}, {flock} of them Flock Safety "
            f"cameras. Each one is listed with the owner of record for the land at or beside "
            f"it, the assessed value, the land use and the county supervisor district.")
    w, s, e, nn = primary.get("bbox") or (0, 0, 0, 0)
    dataset = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"{name} license plate camera land ownership",
        "description": (f"Automated license plate reader cameras mapped in {where}, Kern County, "
                        f"California: {n} cameras, {p['coverage']['joined']} joined to the nearest "
                        f"Kern County tax-roll parcel and its owner of record."),
        "url": f"https://bakersfieldbrief.com/surveillance/{slug}/",
        "isAccessibleForFree": True,
        "creator": {"@type": "NewsMediaOrganization", "name": "Bakersfield Daily Brief",
                    "url": "https://bakersfieldbrief.com/"},
        "spatialCoverage": {"@type": "Place", "name": f"{name}, Kern County, California",
                            "geo": {"@type": "GeoShape", "box": f"{s} {w} {nn} {e}"}},
        "dateModified": built or asof,
        "isPartOf": "https://bakersfieldbrief.com/surveillance/",
        "isBasedOn": ["https://www.openstreetmap.org/", "https://www.kerndata.com/"],
    }
    js = "assets/js/alpr-explorer.js"
    css = "assets/css/deflock.css"
    return page_mod.render(
        title=f"{name} Flock Camera Map | {n} License Plate Readers",
        desc=desc, canonical=f"/surveillance/{slug}/",
        content=body, current="alpr", rel=rel, built=common.iso_today(),
        jsonld=[page_mod.org_jsonld(), page_mod.website_jsonld(),
                page_mod.webpage_jsonld(f"/surveillance/{slug}/", common.iso_today(),
                                        name=f"{name} Flock Camera Map", desc=desc), dataset],
        statusbar=ctx.statusbar if hasattr(ctx, "statusbar") else "",
        extra_head=(f'<link rel="stylesheet" href="{rel}assets/vendor/leaflet.css">'
                    f'<link rel="stylesheet" href="{rel}{css}?v={page_mod._asset_ver(css)}">'),
        extra_scripts=(f'<script src="{rel}assets/vendor/leaflet.js"></script>\n'
                       f'  <script src="{rel}assets/vendor/leaflet.markercluster.js"></script>\n'
                       f'  <script src="{rel}{js}?v={page_mod._asset_ver(js)}" defer></script>'))


def _has_place_page(slug: str) -> bool:
    from . import places
    return slug in places.PLACES


def _osm(c: dict) -> dict:
    """A merged camera back in the shape the explorer takes (the OSM list's own keys)."""
    return {"id": int(c["id"]) if str(c["id"]).isdigit() else c["id"], "lat": c["lat"],
            "lon": c["lon"], "manufacturer": c["manu"], "operator": c["op"],
            "direction": c["dir"], "mapped": c["mapped"]}


def _payload(cams: list, asof: str) -> dict:
    return {"cameras": [_osm(c) for c in cams], "asof": asof,
            "stats": {"total": len(cams), "flock": sum(1 for c in cams if _is_flock(c))}}


def build(ctx, sources: dict) -> list[str]:
    plans = plan(sources)
    built = []
    for slug, p in plans.items():
        common.write(common.SITE / "surveillance" / slug / "index.html", _page(ctx, p, plans))
        built.append(f"surveillance/{slug}/index.html")
    if not plans:
        common.log("builder alpr_towns: no town pages (camera list, ownership data or coverage "
                   "not ready)")
    return built
