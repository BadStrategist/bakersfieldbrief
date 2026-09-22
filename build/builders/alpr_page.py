"""Server-rendered parts of the land ownership explorer on /surveillance/.

Every camera, owner and parcel is written into the page's own HTML, so the records are crawlable and
readable without JavaScript. assets/js/alpr-explorer.js enhances the same markup: map, search,
filters and full records at #camera/<id>, #owner/<n> and #parcel/<n>. Hash routes are not urls of
their own: /surveillance/ stays the only ALPR page.

Copy rule: a camera stands "at or beside" an owner's land, or the parcel is "the nearest parcel".
Never "the parcel under it": most cameras stand in a street or setback beside the joined parcel.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from . import alpr_explorer

esc = html.escape

TYPE_KEY = {"government": "agency", "entity": "entity", "individual": "private",
            "person": "private", "trust": "private"}
TYPE_LABEL = {"agency": "public agency", "entity": "company", "private": "private owner"}

_C16 = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast",
        "southeast", "south-southeast", "south", "south-southwest", "southwest", "west-southwest",
        "west", "west-northwest", "northwest", "north-northwest"]


def type_key(t) -> str:
    return TYPE_KEY.get(str(t or "").lower(), "other")


def dir_arcs(v) -> list[tuple[int, int]]:
    """OSM states facing four ways: "325", "338-23", "140;170;180", "345;270:360"."""
    out = []
    for part in [x.strip() for x in str(v or "").split(";") if x.strip()]:
        m = re.match(r"^(\d{1,3})\s*[-:]\s*(\d{1,3})$", part)
        if m:
            out.append((int(m.group(1)) % 360, int(m.group(2)) % 360))
        elif re.match(r"^\d{1,3}$", part):
            d = int(part) % 360
            out.append((d, d))
    return out


def dir_text(v) -> str:
    arcs = dir_arcs(v)
    return ", ".join(f"{a}° {_C16[round(a / 22.5) % 16]}" if a == b else f"{a}° to {b}°"
                     for a, b in arcs)


def short_addr(a) -> str:
    keep = []
    for p in [x.strip() for x in str(a or "").split(",")]:
        if not p or re.match(r"^(Bakersfield|Kern County|California|CA|United States|USA|US)$", p, re.I):
            continue
        if re.match(r"^\d{5}(-\d{4})?$", p):
            continue
        keep.append(p)
    if len(keep) > 1 and keep[0].isdigit():
        keep[0:2] = [keep[0] + " " + keep[1]]
    return ", ".join(keep)


def loc_of(c: dict) -> str:
    return c.get("loc") or short_addr(c.get("addr")) or f"Camera {c.get('id')}"


def relation(c: dict) -> str:
    """Where the camera stands relative to the joined parcel, in reader words."""
    land = c.get("land") or ""
    if "Street/ROW" in land:
        return "in the street beside"
    if "inside" in (c.get("match") or ""):
        return "on"
    return "beside"


def merge_cameras(osm: list[dict], own: dict | None) -> list[dict]:
    """OSM is the live camera list (weekly). Ownership is a dated research snapshot. Join by node id;
    a camera mapped after the snapshot is listed and mapped, marked as not yet joined."""
    by_id = {str(c["id"]): c for c in (own or {}).get("cams", [])}
    out = []
    for c in osm:
        cid = str(c.get("id"))
        o = by_id.get(cid)
        out.append({
            "id": cid, "lat": c.get("lat"), "lon": c.get("lon"),
            "manu": c.get("manufacturer") or (o or {}).get("manu") or "Unspecified",
            "op": c.get("operator") or "", "dir": c.get("direction") or "",
            "mapped": c.get("mapped") or "", "own": o,
        })
    return out


def _cam_item(c: dict, cutoff: str) -> str:
    o = c["own"]
    is_new = bool(cutoff and c["mapped"] and c["mapped"] >= cutoff)
    flock = "flock" in c["manu"].lower()
    k = type_key(o.get("otype")) if o else "none"
    loc = loc_of(o) if o else f"Camera {c['id']} (mapped {c['mapped'] or 'date not stated'})"
    facing = dir_text(c["dir"])
    meta = [esc(c["manu"])]
    if facing:
        meta.append("facing " + esc(facing))
    if c["mapped"]:
        meta.append("mapped " + esc(c["mapped"]))
    if o:
        own_line = (f'{esc(relation(o)).capitalize()} parcel {esc(o.get("apn") or "")}: '
                    f'<b>{esc(o.get("owner") or "no owner name on the roll")}</b>')
        hay = " ".join([loc, o.get("owner") or "", o.get("apn") or "", o.get("use") or "",
                        c["id"], c["manu"], c["op"]])
    else:
        own_line = "Ownership not joined yet: mapped after the county records snapshot."
        hay = " ".join([loc, c["id"], c["manu"], c["op"]])
    return (f'<li class="ax-item" data-id="{esc(c["id"])}" data-k="{k}"'
            f'{" data-new" if is_new else ""}{" data-flock" if flock else ""}'
            f' data-q="{esc(hay.lower())}"><a href="#camera/{esc(c["id"])}">'
            f'<span class="ax-it">{esc(loc)}{" <em class=ax-new>new</em>" if is_new else ""}</span>'
            f'<span class="ax-im">{" &middot; ".join(meta)}</span>'
            f'<span class="ax-io">{own_line}</span></a></li>')


def _owner_item(o: dict) -> str:
    k = type_key(o.get("type"))
    n, np_ = o.get("n", 0), o.get("nparcel", 0)
    chips = f'<span class="ax-chip {k}">{TYPE_LABEL.get(k, "owner")}</span>'
    if o.get("phone") or o.get("email"):
        chips += '<span class="ax-chip ok">contact published</span>'
    return (f'<li class="ax-item" data-oid="{o.get("oid")}" data-k="{k}" data-q="{esc(str(o.get("name", "")).lower())}">'
            f'<a href="#owner/{o.get("oid")}"><span class="ax-it">{esc(o.get("name", ""))}</span>'
            f'<span class="ax-im"><b>{n}</b> camera{"s" if n != 1 else ""} at or beside their land, '
            f'{np_} parcel{"s" if np_ != 1 else ""}</span><span class="ax-io">{chips}</span></a></li>')


def _parcel_item(p: dict, owners: list[dict]) -> str:
    oids = [x for x in p.get("oids", []) if x is not None]
    k = type_key(owners[oids[0]].get("type")) if oids and oids[0] < len(owners) else "other"
    n = p.get("n", 0)
    return (f'<li class="ax-item" data-pid="{p.get("pid")}" data-k="{k}" '
            f'data-q="{esc((p.get("apn", "") + " " + " ".join(p.get("owners", [])) + " " + (p.get("use") or "")).lower())}">'
            f'<a href="#parcel/{p.get("pid")}"><span class="ax-it">Parcel {esc(p.get("apn", ""))}</span>'
            f'<span class="ax-im"><b>{n}</b> camera{"s" if n != 1 else ""} on or beside it &middot; {esc(p.get("use") or "use not stated")}</span>'
            f'<span class="ax-io">{esc(", ".join(p.get("owners", [])))}</span></a></li>')


def explorer_html(osm_cams: list[dict], asof: str, total: int, ok: bool) -> tuple[str, dict]:
    """The explorer section. Returns (html, facts) where facts feed the copy around it."""
    own = alpr_explorer.load()
    cams = merge_cameras(osm_cams, own)
    cams.sort(key=lambda c: (c["mapped"] or ""), reverse=True)
    try:
        cutoff = (dt.date.fromisoformat(str(asof)[:10]) - dt.timedelta(days=28)).isoformat()
    except ValueError:
        cutoff = ""
    owners = (own or {}).get("owners", [])
    parcels = (own or {}).get("parcels", [])
    joined = sum(1 for c in cams if c["own"])
    counts = {"all": len(cams),
              "new": sum(1 for c in cams if cutoff and c["mapped"] >= cutoff),
              "flock": sum(1 for c in cams if "flock" in c["manu"].lower())}
    for key in ("agency", "entity", "private"):
        counts[key] = sum(1 for c in cams if c["own"] and type_key(c["own"].get("otype")) == key)
    built = (own or {}).get("meta", {}).get("built", "")
    facts = {"joined": joined, "owners": len(owners), "parcels": len(parcels), "built": built,
             "counts": counts, "own": own}

    owners_sorted = sorted(owners, key=lambda o: (-o.get("n", 0), str(o.get("name", ""))))
    parcels_sorted = sorted(parcels, key=lambda p: (-p.get("n", 0), p.get("apn", "")))
    cam_items = "".join(_cam_item(c, cutoff) for c in cams)
    owner_items = "".join(_owner_item(o) for o in owners_sorted)
    parcel_items = "".join(_parcel_item(p, owners) for p in parcels_sorted)

    def chip(f, label):
        return (f'<button type="button" class="ax-f" data-f="{f}" aria-pressed="{"true" if f == "all" else "false"}">'
                f'{label} <b>{counts[f]}</b></button>')

    if not ok:
        sub = "The camera source (OpenStreetMap) did not load this build."
    elif own and joined == total:
        sub = (f"All {total} mapped cameras, each joined to the owner of record for the land at or beside "
               f"it (Kern County tax roll, {esc(built)}). Tap a camera, or search.")
    elif own:
        sub = (f"{total} cameras on the map. {joined} are joined to the owner of record for the land at "
               f"or beside them (Kern County tax roll, {esc(built)}); newer cameras join at the next "
               f"records refresh.")
    else:
        sub = f"{total} cameras on the map. Land ownership records are unavailable this build."

    html_out = f"""
    <section class="ax" id="explorer" aria-labelledby="ax-h">
      <div class="ax-top">
        <div class="ax-title">
          <h3 id="ax-h">Flock &amp; ALPRs <span>&middot; Kern County</span></h3>
          <p class="ax-sub">{sub}</p>
        </div>
        <div class="ax-search" role="search">
          <label class="sr" for="ax-q">Search cameras, streets, owners or parcel numbers</label>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15.5 15.5 21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
          <input id="ax-q" type="search" placeholder="Search a street, business, owner or parcel number"
                 autocomplete="off" autocapitalize="none" spellcheck="false" enterkeyhint="search">
        </div>
        <div class="ax-filters" role="group" aria-label="Show cameras">
          {chip("all", "All")}{chip("new", "New, last 28 days")}{chip("flock", "Flock Safety")}{chip("agency", "Public agency land")}{chip("entity", "Company land")}{chip("private", "Private land")}
        </div>
      </div>
      <div class="ax-grid">
        <div class="ax-mapcol">
          <div class="ax-mapbox">
            <div id="alpr-map" class="ax-map" role="region" aria-label="Map of license plate reader camera locations"></div>
            <div class="ax-maphint" id="ax-maphint" hidden>Use Ctrl + scroll to zoom the map</div>
            <div class="ax-peek" id="ax-peek" hidden></div>
          </div>
          <p class="ax-legend"><span class="ax-sw flock"></span>Flock Safety <span class="ax-sw other"></span>other ALPR <span class="ax-sw ring"></span>mapped in the last 28 days <span class="ax-cone"></span>facing, at street zoom</p>
        </div>
        <div class="ax-panel" id="ax-panel">
          <div class="ax-tabs" role="tablist" aria-label="Lists">
            <button type="button" role="tab" id="ax-t-cams" aria-controls="ax-l-cams" aria-selected="true">Cameras <b>{len(cams)}</b></button>
            <button type="button" role="tab" id="ax-t-owners" aria-controls="ax-l-owners" aria-selected="false">Owners <b>{len(owners)}</b></button>
            <button type="button" role="tab" id="ax-t-parcels" aria-controls="ax-l-parcels" aria-selected="false">Parcels <b>{len(parcels)}</b></button>
          </div>
          <p class="ax-count" id="ax-count" aria-live="polite"></p>
          <div class="ax-scroll" id="ax-scroll">
            <ol class="ax-list" id="ax-l-cams" role="tabpanel" aria-labelledby="ax-t-cams">{cam_items}</ol>
            <ol class="ax-list" id="ax-l-owners" role="tabpanel" aria-labelledby="ax-t-owners" hidden>{owner_items}</ol>
            <ol class="ax-list" id="ax-l-parcels" role="tabpanel" aria-labelledby="ax-t-parcels" hidden>{parcel_items}</ol>
            <p class="ax-empty" id="ax-empty" hidden></p>
            <button type="button" class="ax-more" id="ax-more" hidden>Show all</button>
            <article class="ax-detail" id="ax-detail" hidden tabindex="-1" aria-live="polite"></article>
          </div>
        </div>
      </div>
      <noscript><p class="note">The map needs JavaScript. Every camera, owner and parcel is listed above
      without it.</p></noscript>
    </section>"""
    return html_out, facts


def ownership_html(facts: dict, total: int) -> str:
    """Crawlable summary of the ownership join: the numbers, the land classes, the top owners."""
    own = facts.get("own")
    if not own:
        return ""
    st = alpr_explorer.stats()
    owners = sorted(own.get("owners", []), key=lambda o: (-o.get("n", 0), str(o.get("name", ""))))
    top = [o for o in owners if o.get("n", 0) > 1][:10]
    top_li = "".join(
        f'<li><a href="#owner/{o["oid"]}">{esc(o["name"])}</a> <span class="ax-dim">&middot; '
        f'{TYPE_LABEL.get(type_key(o.get("type")), "owner")}</span>: <b>{o["n"]}</b> cameras at or beside '
        f'their land, across {o.get("nparcel", 0)} parcel{"s" if o.get("nparcel", 0) != 1 else ""}</li>'
        for o in top)
    joined = facts["joined"]
    gap = total - joined
    gap_note = (f" The {gap} camera{'s' if gap != 1 else ''} mapped since then {'join' if gap != 1 else 'joins'} "
                f"at the next records refresh." if gap > 0 else "")
    private_note = ("" if alpr_explorer.PUBLISH_PRIVATE_NAMES else
                    " Private individuals and family trusts are not named on this page: their records keep"
                    " the camera, the parcel and the public sources, and the name stays with the county.")
    return f"""
    <section class="card ax-own" id="ownership">
      <span class="tag amber">Land ownership</span>
      <h2>Who owns the land at or beside each camera</h2>
      <p>Each camera is joined to the nearest Kern County tax-roll parcel and to that parcel&rsquo;s
      owner of record: <strong>{joined} of the {total} mapped cameras</strong>, <strong>{facts['owners']}
      owners of record</strong> and <strong>{facts['parcels']} parcels</strong>, from county records as of
      {esc(facts['built'])}.{gap_note} The public source is printed on every record.{private_note}</p>
      <p>Where the cameras stand, as the assessor roll has it:</p>
      <ul>
        <li><strong>{st['private_parcel']} cameras</strong> on or beside a privately titled parcel, with the owner on the tax roll.</li>
        <li><strong>{st['street_row']} cameras</strong> in a street, right of way or setback. The parcel named is the
        nearest one, not land the camera stands on.</li>
        <li><strong>{st['city_owned']} cameras</strong> on or beside land with a City of Bakersfield interest. The
        city&rsquo;s GIS layer and the tax roll can name different parties for the same parcel, and the record prints both.</li>
      </ul>
      <h3>Owners with the most cameras at or beside their land</h3>
      <ol class="ax-top-owners">{top_li}</ol>
      <p><strong>{st['multi_owner']} owners</strong> have more than one camera at or beside their land, and
      <strong>{st['contact_owners']} owners</strong> have a published phone, email or mailing address.
      Open any camera on the map for its parcel number, its owner of record and the source behind every value.</p>
    </section>"""


def sources_html(facts: dict, total: int) -> str:
    own = facts.get("own")
    if not own:
        return ""
    owners = own.get("owners", [])
    with_sos = sum(1 for o in owners if o.get("sos"))
    weak = sum(1 for c in own.get("cams", []) if "weak" in (c.get("match") or ""))
    return f"""
    <section class="card ax-sources" id="sources">
      <span class="tag">Sources</span>
      <h3>Where every fact on the map comes from</h3>
      <dl class="ax-kv">
        <dt>Camera points</dt><dd>OpenStreetMap, mapped by volunteers (<a href="https://www.openstreetmap.org/copyright" rel="noopener">ODbL licence</a>). Every record links its OSM node.</dd>
        <dt>Owner of record</dt><dd>Kern County assessor roll, read through <a href="https://www.kerndata.com/" rel="noopener">kerndata.com</a>.</dd>
        <dt>Parcel facts</dt><dd>Kern County assessor: land and building values, use code, supervisor district and recorded document numbers.</dd>
        <dt>City land checks</dt><dd>City of Bakersfield GIS: city limits and the city property inventory (<a href="https://gis.bakersfieldcity.us" rel="noopener">city GIS</a>).</dd>
        <dt>Company records</dt><dd>California Secretary of State business search (<a href="https://bizfileonline.sos.ca.gov/search/business" rel="noopener">bizfile</a>) and public registry mirrors.</dd>
        <dt>City contacts</dt><dd>Official <a href="https://www.bakersfieldcity.us" rel="noopener">bakersfieldcity.us</a> pages.</dd>
      </dl>
      <h3>What is complete, and what is not</h3>
      <ul>
        <li>{facts['joined']} of {total} cameras have a parcel, an owner of record and an assessed value.</li>
        <li>{with_sos} of {len(owners)} owners carry a California registration number. Officer names come from
        registry mirrors, so read them as reported, not state certified.</li>
        <li>A camera is joined to the nearest parcel within 60 meters. {weak} join{"s are" if weak != 1 else " is a"} weak
        match{"es" if weak != 1 else ""}, 30 to 60 meters away, and the record says so.</li>
        <li>This map holds the cameras volunteers have mapped. Flock&rsquo;s own
        <a href="https://transparency.flocksafety.com/bakersfield-ca-pd" rel="noopener">transparency portal</a>
        listed 462 cameras for the Bakersfield Police Department when this research checked it. The portal
        publishes counts, not locations, so the gap needs a public records request to close.</li>
      </ul>
    </section>"""
