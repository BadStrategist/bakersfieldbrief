"""Server-rendered parts of the land ownership explorer on /surveillance/.

Every camera, owner and parcel is written into the page's own HTML, so the records are crawlable and
readable without JavaScript. assets/js/alpr-explorer.js enhances the same markup: the map, the
filters and the full records at #camera/<id>, #owner/<n> and #parcel/<n>. There is no search box
on this page (removed 2026-09-22 at the owner's request, and the data-q index went with it). Hash
routes are not urls of their own. The same section, given one town's cameras, is the map on
/surveillance/<town>/ (alpr_towns.py).

Copy rule: a camera stands "at or beside" an owner's land, or the parcel is "the nearest parcel".
Never "the parcel under it": most cameras stand in a street or setback beside the joined parcel.

Coverage rule: how many cameras are joined, how many have no roll record to join and how many
are not looked up yet are counted from the data on every build (coverage_sentence). No number
of them is ever typed, and no reason is given for a camera that has not been looked up.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import places_kern
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


def facing_words(v) -> str:
    """Facing for a list row: compass words only. The degrees stay on the camera's record."""
    return ", ".join(_C16[round(a / 22.5) % 16] if a == b
                     else f"{_C16[round(a / 22.5) % 16]} to {_C16[round(b / 22.5) % 16]}"
                     for a, b in dir_arcs(v))


def short_date(iso, year) -> str:
    """A list-row date: "Sep 21", or "Oct 9, 2025" when it is not this year's."""
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    return f"{d:%b} {d.day}" + ("" if str(d.year) == str(year) else f", {d.year}")


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
    no_rec = alpr_explorer.norecord() if own else {}
    out = []
    for c in osm:
        cid = str(c.get("id"))
        o = by_id.get(cid)
        out.append({
            "id": cid, "lat": c.get("lat"), "lon": c.get("lon"),
            "manu": c.get("manufacturer") or (o or {}).get("manu") or "Unspecified",
            "op": c.get("operator") or "", "dir": c.get("direction") or "",
            "mapped": c.get("mapped") or "", "own": o,
            # looked up, and the roll has no record to join (never both this and "own")
            "nr": None if o else no_rec.get(cid),
            # the city or Census place the point is inside, from the boundary, or None
            "place": places_kern.place_of(c.get("lat"), c.get("lon")),
        })
    return out


def norecord_line(nr: dict) -> str:
    """What the lookup found for a camera with no roll record to join."""
    if nr.get("reason") == "apn_not_on_roll":
        which = f"parcel {nr['apn']}, which" if nr.get("apn") else "a parcel that"
        return f"Beside {which} has no owner on the county tax roll."
    return "In a road or right of way: no titled parcel within 60 meters."


def coverage(cams: list[dict]) -> dict:
    """joined / norecord / pending over merged cameras. The three always sum to len(cams)."""
    joined = sum(1 for c in cams if c["own"])
    norec = sum(1 for c in cams if c.get("nr"))
    return {"joined": joined, "norecord": norec, "pending": len(cams) - joined - norec}


def coverage_tail(cov: dict) -> str:
    """The cameras that are not joined, in a clause each. Empty when every camera is joined."""
    parts = []
    n = cov["norecord"]
    if n:
        parts.append(f"{n} stand{'s' if n == 1 else ''} where the tax roll has no parcel to join")
    n = cov["pending"]
    if n:
        parts.append(f"{n} {'has' if n == 1 else 'have'} not been looked up yet")
    return " and ".join(parts)


def _cam_item(c: dict, cutoff: str, year: str = "") -> str:
    o = c["own"]
    nr = c.get("nr")
    is_new = bool(cutoff and c["mapped"] and c["mapped"] >= cutoff)
    flock = "flock" in c["manu"].lower()
    k = type_key(o.get("otype")) if o else "none"
    # The row is for a reader choosing a camera: street, whose land, then the technical line.
    # Parcel number, degrees and the full date are on the record the row opens.
    loc = loc_of(o) if o else (loc_of(nr) if nr else "Street not matched yet")
    facing = facing_words(c["dir"])
    meta = ["Flock" if flock else ("Maker not stated" if c["manu"] == "Unspecified" else esc(c["manu"]))]
    if facing:
        meta.append("faces " + esc(facing))
    if c["mapped"]:
        meta.append("mapped " + esc(short_date(c["mapped"], year)))
    if o:
        chip = f' <span class="ax-chip {k}">{TYPE_LABEL[k]}</span>' if k in TYPE_LABEL else ""
        own_line = (f'{esc(relation(o)).capitalize()} a parcel owned by '
                    f'<b>{esc(o.get("owner") or "no owner name on the roll")}</b>{chip}')
    elif nr:
        own_line = esc(norecord_line(nr))
    else:
        # No reason is given because none is known here.
        own_line = "Land owner not looked up yet."
    return (f'<li class="ax-item" data-id="{esc(c["id"])}" data-k="{k}"'
            f'{" data-new" if is_new else ""}{" data-flock" if flock else ""}>'
            f'<a href="#camera/{esc(c["id"])}">'
            f'<span class="ax-it">{esc(loc)}{" <em class=ax-new>new</em>" if is_new else ""}</span>'
            f'<span class="ax-io">{own_line}</span>'
            f'<span class="ax-im">{" &middot; ".join(meta)}</span></a></li>')


def _owner_item(o: dict) -> str:
    k = type_key(o.get("type"))
    n, np_ = o.get("n", 0), o.get("nparcel", 0)
    chips = f'<span class="ax-chip {k}">{TYPE_LABEL.get(k, "owner")}</span>'
    if o.get("phone") or o.get("email"):
        chips += '<span class="ax-chip ok">contact published</span>'
    return (f'<li class="ax-item" data-oid="{o.get("oid")}" data-k="{k}">'
            f'<a href="#owner/{o.get("oid")}"><span class="ax-it">{esc(o.get("name", ""))}</span>'
            f'<span class="ax-im"><b>{n}</b> camera{"s" if n != 1 else ""} at or beside their land, '
            f'{np_} parcel{"s" if np_ != 1 else ""}</span><span class="ax-io">{chips}</span></a></li>')


def _parcel_item(p: dict, owners: list[dict]) -> str:
    oids = [x for x in p.get("oids", []) if x is not None]
    k = type_key(owners[oids[0]].get("type")) if oids and oids[0] < len(owners) else "other"
    n = p.get("n", 0)
    return (f'<li class="ax-item" data-pid="{p.get("pid")}" data-k="{k}">'
            f'<a href="#parcel/{p.get("pid")}"><span class="ax-it">Parcel {esc(p.get("apn", ""))}</span>'
            f'<span class="ax-im"><b>{n}</b> camera{"s" if n != 1 else ""} on or beside it &middot; {esc(p.get("use") or "use not stated")}</span>'
            f'<span class="ax-io">{esc(", ".join(p.get("owners", [])))}</span></a></li>')


def explorer_html(osm_cams: list[dict], asof: str, total: int, ok: bool, *,
                  where: str = "Kern County", scoped: bool = False,
                  scope_note: str = "") -> tuple[str, dict]:
    """The explorer section. Returns (html, facts) where facts feed the copy around it.

    scoped=True is a town page: osm_cams is that town's cameras, and the owner and parcel tabs
    list only owners and parcels with one of those cameras at or beside them.

    scope_note names the split when the section covers more than the page's own count, which is
    a town page carrying the cameras just outside its limits. Without it the panel would say a
    larger total than the page's own headline and the two numbers would not reconcile."""
    own = alpr_explorer.load()
    cams = merge_cameras(osm_cams, own)
    cams.sort(key=lambda c: (c["mapped"] or ""), reverse=True)
    try:
        cutoff = (dt.date.fromisoformat(str(asof)[:10]) - dt.timedelta(days=28)).isoformat()
    except ValueError:
        cutoff = ""
    all_owners = (own or {}).get("owners", [])
    owners, parcels = all_owners, (own or {}).get("parcels", [])
    if scoped:
        here = {c["id"] for c in cams}
        owners = [o for o in owners if here & {str(x) for x in o.get("cams", [])}]
        parcels = [p for p in parcels if here & {str(x) for x in p.get("cams", [])}]
    cov = coverage(cams)
    joined = cov["joined"]
    counts = {"all": len(cams),
              "new": sum(1 for c in cams if cutoff and c["mapped"] >= cutoff),
              "flock": sum(1 for c in cams if "flock" in c["manu"].lower())}
    for key in ("agency", "entity", "private"):
        counts[key] = sum(1 for c in cams if c["own"] and type_key(c["own"].get("otype")) == key)
    built = (own or {}).get("meta", {}).get("built", "")
    facts = {"joined": joined, "owners": len(owners), "parcels": len(parcels), "built": built,
             "counts": counts, "own": own, "cams": cams, "coverage": cov}

    owners_sorted = sorted(owners, key=lambda o: (-o.get("n", 0), str(o.get("name", ""))))
    parcels_sorted = sorted(parcels, key=lambda p: (-p.get("n", 0), p.get("apn", "")))
    cam_items = "".join(_cam_item(c, cutoff, str(asof)[:4]) for c in cams)
    owner_items = "".join(_owner_item(o) for o in owners_sorted)
    parcel_items = "".join(_parcel_item(p, all_owners) for p in parcels_sorted)

    def chip(f, label):
        return (f'<button type="button" class="ax-f" data-f="{f}" aria-pressed="{"true" if f == "all" else "false"}">'
                f'{label} <b>{counts[f]}</b></button>')

    head = f"{esc(scope_note)}, " if scope_note else ""
    lead = "each" if scope_note else f"All {total} mapped cameras, each"
    if not ok:
        sub = "The camera source (OpenStreetMap) did not load this build."
    elif own and joined == total:
        sub = (f"{head}{lead} joined to the "
               f"owner of record for the land at or beside it (Kern County tax roll, {esc(built)}). "
               f"Tap a camera to open its record.")
    elif own:
        # Counted from this build's data, clause by clause: nothing here is a typed number.
        sub = (f"{head}{total} cameras on the map. {joined} {'is' if joined == 1 else 'are'} joined to "
               f"the owner of record for the land at or beside {'it' if joined == 1 else 'them'} "
               f"(Kern County tax roll, {esc(built)}); {coverage_tail(cov)}.")
    else:
        sub = f"{head}{total} cameras on the map. Land ownership records are unavailable this build."

    html_out = f"""
    <section class="ax" id="explorer" aria-labelledby="ax-h">
      <div class="ax-top">
        <div class="ax-title">
          <h3 id="ax-h">Flock &amp; ALPRs <span>&middot; {esc(where)}</span></h3>
          <p class="ax-sub">{sub}</p>
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
          <div class="ax-head">
            <p class="ax-big"><b>{len(cams)}</b> cameras on this map</p>
            <p class="ax-how">Pick one to see where it points and whose land it stands at or beside.</p>
            <div class="ax-tabs" role="tablist" aria-label="Lists">
              <button type="button" role="tab" id="ax-t-cams" aria-controls="ax-l-cams" aria-selected="true">By camera</button>
              <button type="button" role="tab" id="ax-t-owners" aria-controls="ax-l-owners" aria-selected="false">By land owner</button>
              <button type="button" role="tab" id="ax-t-parcels" aria-controls="ax-l-parcels" aria-selected="false">By parcel</button>
            </div>
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
    tail = coverage_tail(facts["coverage"])
    gap_note = f" Of the rest, {tail}." if tail else ""
    # Written by the county join only: land the roll gives to an agency, which the older label
    # counted under "privately titled".
    pub = st.get("public_parcel")
    public_li = (f"<li><strong>{pub} camera{'s' if pub != 1 else ''}</strong> on or beside a parcel "
                 f"the tax roll gives to a public agency.</li>" if isinstance(pub, int) and pub else "")
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
        {public_li}
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
    # Owners nobody has researched past the tax roll. Said once, here; their records say it too.
    todo = sum(1 for o in owners if o.get("cstat") == "not_researched")
    todo_li = (f"<li>For {todo} of the {len(owners)} owners, the company record and the contact "
               f"routes have not been researched yet. Those records carry the tax-roll facts and "
               f"say that the rest has not been looked up.</li>" if todo else "")
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
        {todo_li}
        <li>A camera is joined to the nearest parcel within 60 meters. {weak} join{"s are" if weak != 1 else " is a"} weak
        match{"es" if weak != 1 else ""}, 30 to 60 meters away, and the record says so.</li>
        <li>This map holds the cameras volunteers have mapped. Flock&rsquo;s own
        <a href="https://transparency.flocksafety.com/bakersfield-ca-pd" rel="noopener">transparency portal</a>
        listed 462 cameras for the Bakersfield Police Department when this research checked it. The portal
        publishes counts, not locations, so the gap needs a public records request to close.</li>
      </ul>
    </section>"""
