#!/usr/bin/env python3
"""Home page body (index.html), v5 design. Called by daily.build().

  glance strip -> lead (h1 + top story) -> The Kern Overnight band -> Conditions tiles
  -> newsletter row -> Headlines -> This week at City Hall + newsletter form
  | Trackers + Past briefs -> About this brief

Rendered through templates/home.html with assets/css/home.css, not the shared layout.
Every number printed here is read from a source dict or a data file at build time. A block
whose source failed says so; it never prints a remembered or invented value.
"""
from __future__ import annotations

import datetime as dt
import html
import re

from .. import common
from . import daily, images, night_counts, overnight
from . import page as page_mod

SITE = "https://bakersfieldbrief.com/"
ORG_ID = SITE + "#org"
DESC = ("The daily civic brief for Bakersfield and Kern County: the top story, what happened "
        "overnight, live conditions, local headlines with links, and this week's public "
        "meetings. Updated every morning at 6 AM PT.")

_ARROW = ('<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
          '<path d="M4 12h15M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.4" '
          'stroke-linecap="round" stroke-linejoin="round"/></svg>')
_CHEVRON = ('<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')

# EPA AirNow scale: the six category colors and the top of each band.
_AQI_COLORS = ("#00E400", "#FFFF00", "#FF7E00", "#FF0000", "#8F3F97", "#7E0023")
_AQI_TOPS = (50, 100, 150, 200, 300, 500)
_POLLUTANT = {"OZONE": "ozone", "O3": "ozone", "PM2.5": "fine particles (PM2.5)",
              "PM10": "dust and coarse particles (PM10)"}

_u = html.escape   # attribute values and URLs: escaped, otherwise untouched


def _e(text) -> str:
    """Escape feed text for the page. Feed text (headlines, stored brief summaries) carries
    em and en dashes; the page prints none, so a spaced dash becomes a comma."""
    s = re.sub(r"\s+[—–]\s+", ", ", str(text))
    return html.escape(re.sub(r"[—–]", "-", s))


def render(ctx, today, built_iso, rel, top, headlines, weather, chp, isa, escribe, board,
           alpr, airnow, calfire, roads) -> tuple[str, str, list]:
    """-> (main content, glance strip, JSON-LD blocks) for page_mod.render()."""
    groups = _headline_groups(top, headlines)
    past = [e for e in daily._load_archive()
            if _iso_md(e.get("date")) and str(e["date"]) < built_iso][-5:][::-1]
    night, night_info = _night(rel, chp, built_iso)
    ctx.build_report["_overnight_band"] = night_info

    content = f"""
<div class="wrap">
{_lead(top, today, rel, built_iso)}
</div>
{night}
<div class="wrap">
{_conditions(weather, isa, airnow, calfire, roads, built_iso, rel)}

  <div class="nl-row">
    <p><b>Get the Brief by email.</b> One email each morning. Free.</p>
    <a class="btn dark" href="#signup">Sign up</a>
  </div>

{_headlines(groups)}

  <div class="split">
    <div>
{_week(today, rel, escribe, board)}
{_newsletter(rel)}
    </div>
    <div>
{_trackers(rel, alpr)}
{_past(rel, past)}
    </div>
  </div>

{_about(rel)}
</div>
{_modal()}"""
    return content, _glance(weather, airnow, built_iso), [_jsonld(today, built_iso, top, groups, past)]


# ---------------------------------------------------------------- small helpers
def _md(d) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _iso_md(iso: str) -> str:
    """'2026-10-05...' -> 'Oct 5'; anything unparseable -> ''."""
    try:
        return _md(dt.date.fromisoformat(str(iso)[:10]))
    except ValueError:
        return ""


def _by(source: str, asof, built_iso: str, extra: str = "", grace_days: int = 0) -> str:
    """Tile source line. A reading from before the build date (less grace_days) is marked as
    old data."""
    asof = str(asof or "")[:10]
    floor = (dt.date.fromisoformat(built_iso) - dt.timedelta(days=grace_days)).isoformat()
    stale = " is-stale" if asof and asof < floor else ""
    when = extra or _iso_md(asof)
    return f'<p class="by{stale}">{_e(source)}{", " + _e(when) if when else ""}</p>'


def _clock(iso: str) -> str | None:
    """'2026-10-07T17:15:00' -> '5:15 PM'; 12:00 -> 'Noon'; no time on the record -> None."""
    s = str(iso or "")
    try:
        d = dt.datetime.fromisoformat(s[:19])
    except ValueError:
        return None
    if len(s) <= 10 or (d.hour == 0 and d.minute == 0):
        return None
    if (d.hour, d.minute) == (12, 0):
        return "Noon"
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


# ---------------------------------------------------------------- glance strip
def _glance(weather, airnow, built_iso) -> str:
    """One line of conditions under the header, at every width. With an active weather alert
    the strip turns into the alert bar and the alert headline goes first."""
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    alerts = (weather or {}).get("alerts", []) or []
    bits, spoken = [], []
    if alerts:
        ev = alerts[0].get("event", "Weather alert")
        bits.append(f"<span><b>{_e(ev)}</b> in effect</span>")
        spoken.append(f"{ev} in effect")
    if cur is not None:
        tail = f" &middot; high {hi}&deg;" if hi is not None else (
            f" &middot; low {lo}&deg; tonight" if lo is not None else "")
        bits.append(f"<span><b>{cur}&deg;</b> now{tail}</span>")
        spoken.append(f"{cur} degrees now" + (f", high {hi} today" if hi is not None else ""))
    elif hi is not None:
        bits.append(f"<span>High <b>{hi}&deg;</b> today</span>")
        spoken.append(f"high {hi} today")
    if (airnow or {}).get("ok") and airnow.get("aqi") is not None:
        cat = (airnow.get("category") or "").lower()
        color = _AQI_COLORS[min(max(int(airnow.get("category_num") or 1), 1), 6) - 1]
        bits.append(f'<span><span class="swatch" style="background:{color}"></span>Air quality '
                    f'<b>{airnow["aqi"]}</b>{": " + _e(cat) if cat else ""}</span>')
        spoken.append(f"air quality index {airnow['aqi']}" + (f", {cat}" if cat else ""))
    if not bits:
        return ""
    label = f"Conditions, updated {_iso_md(built_iso)}: {'. '.join(spoken)}. Go to conditions."
    cls = "glance is-alert" if alerts else "glance"
    return (f'<div class="{cls}"><div class="wrap">'
            f'<a href="#conditions" aria-label="{_e(label)}">{"".join(bits)}</a></div></div>')


# ---------------------------------------------------------------- 1. lead
def _lead(top, today, rel, built_iso) -> str:
    if top:
        story = (f'<h2 id="h-lead"><a href="{_u(top.get("url", "#"))}" rel="noopener">'
                 f'{_e(top["title"])}</a></h2>\n'
                 f'      <span class="src">{_e(top.get("source", "Local news"))}</span>')
    else:
        story = '<h2 id="h-lead">No lead story was fetched this build</h2>'
    return f"""    <section class="lead" aria-labelledby="h-lead">
      <h1>{_e(daily._brief_h1(today))}</h1>
      <span class="kicker">Top story</span>
      {story}
      <a class="btn ghost" href="{rel}briefs/{built_iso}/">Read today's full brief {_ARROW}</a>
    </section>"""


# ---------------------------------------------------------------- 2. overnight band
def _check_band(band: str) -> None:
    """Read the numbers back out of the rendered band. The rows must sum to the headline."""
    m = re.search(r'<span class="num">(\d+)</span>', band)
    shown = [int(n) for n in re.findall(r"<li><b>(\d+)</b>", band)]
    if m and shown and sum(shown) != int(m.group(1)):
        raise night_counts.NightCountError(
            f"overnight band: chips {' + '.join(map(str, shown))} = {sum(shown)}, "
            f"headline {m.group(1)}")
    if bool(m) != bool(shown):
        raise night_counts.NightCountError("overnight band: a count without chips, or chips "
                                           "without a count")


def _night(rel, chp, built_iso) -> tuple[str, dict]:
    """The flagship band. The total and every chip are counted from the same rows of
    incidents/<report date>.json (see night_counts). With no file there is no number."""
    links = f"""<p class="links">
      <a href="{rel}map/">Live map</a>
      <a href="{rel}overnight/archive/">Past nights</a>
      <a href="https://quickmap.dot.ca.gov/" rel="noopener">Caltrans QuickMap</a>
    </p>
    <a class="btn go" href="{rel}overnight/">Read the full overnight log {_ARROW}</a>"""
    reps = overnight._published_reports()
    if not reps:
        return f"""<section class="night" aria-labelledby="h-night">
  <div class="wrap">
    <p class="night-tag">The Kern Overnight</p>
    <h2 id="h-night"><span class="say">Police, fire and EMS calls, 7 PM to 7 AM</span></h2>
    <p class="when">No overnight report has been published yet.</p>
    {links}
  </div>
</section>""", {"date": None, "count": None}

    rep = reps[0]
    night = dt.date.fromisoformat(rep["date"])
    eve = night - dt.timedelta(days=1)
    when = f"7 PM {eve.strftime('%A')} to 7 AM {night.strftime('%A')}, {_md(night)}"
    if rep["date"] != built_iso:
        when = "Latest report: " + when
    incs = overnight._incidents(rep["date"])

    notable = ""
    lead = overnight._top_incident([rep])
    if lead:
        notable = f"""
      <p class="notable">
        <b>Notable call</b>
        <a href="{rel}overnight/{rep['date']}/">{_e(lead)}</a>
        <span>From the overnight report. Details are preliminary until an official source confirms them.</span>
      </p>"""

    info = {"date": rep["date"], "count": len(incs) or None, "chips": [], "other": "",
            "unmapped": []}
    if incs:
        chips, inside, unmapped = night_counts.chips(incs)
        info.update(chips=chips, other=inside, unmapped=unmapped)
        say = "call while Kern slept" if len(incs) == 1 else "calls while Kern slept"
        head = f'<span class="num">{len(incs)}</span> <span class="say">{say}</span>'
        # The Other row carries its own breakdown, so no call is hidden behind the word.
        lis = "".join(
            f"\n      <li><b>{n}</b><span>{_e(label)}</span>"
            + (f"<small>{_e(inside)}</small>" if label == night_counts.OTHER else "") + "</li>"
            for label, n in chips)
        body = f"""
            <p class="types-h">Calls by type, most serious first</p>
            <ul class="types" aria-label="Calls by type">{lis}
            </ul>"""
    else:
        head = f'<span class="say">{_e(rep["title"])}</span>'
        body = '\n    <p class="note t13 muted">Call counts for this report are not available.</p>'

    # CHP's own count, only when it is of the same morning as the report above.
    chp_line = ""
    if (chp or {}).get("ok") and str(chp.get("asof", ""))[:10] == rep["date"]:
        n = len(chp.get("overnight", []) or [])
        logged = ("no road incidents" if n == 0 else
                  "1 road incident" if n == 1 else f"{n} road incidents")
        chp_line = (f'\n    <p class="chp t13 muted">A separate count from a different source: CHP '
                    f'logged {logged} overnight (Caltrans QuickMap). Some can be the same events '
                    f'as the calls above.</p>')

    band = f"""<section class="night" aria-labelledby="h-night">
  <div class="wrap">
    <div class="night-head">
      <div>
        <p class="night-tag">The Kern Overnight</p>
        <h2 id="h-night">{head}</h2>
        <p class="when">{_e(when)}</p>
      </div>{notable}
    </div>{body}{chp_line}
    {links}
  </div>
</section>"""
    _check_band(band)
    return band, info


# ---------------------------------------------------------------- 3. conditions
def _weather_tile(weather, built_iso) -> str:
    fc = (weather or {}).get("forecast", {}) or {}
    cur, hi, lo = fc.get("current"), fc.get("high"), fc.get("low")
    alerts = (weather or {}).get("alerts", []) or []
    if cur is not None:
        big = f'{cur}&deg;<small>F now</small>'
    elif hi is not None:
        big = f'{hi}&deg;<small>F high</small>'
    else:
        big = ""
    # Evening builds have no daytime period left, so there is no high: say tonight's low.
    if cur is not None and hi is not None:
        say = f"High {hi}&deg; today"
    elif cur is not None and lo is not None:
        say = f"Low {lo}&deg; tonight"
    elif cur is None and lo is not None:
        say = f"Low {lo}&deg;"
    else:
        say = ""
    if not big:
        body = '<p class="say">Unavailable this build</p>'
    else:
        sub = []
        if fc.get("condition"):
            sub.append(f'<p class="sub">{_e(str(fc["condition"]))}'
                       + (f', humidity {fc["humidity"]}%' if fc.get("humidity") is not None else "")
                       + "</p>")
        if alerts:
            sub.append(f'<p class="sub"><span class="sq"></span>{_e(alerts[0].get("event", "Weather alert"))} in effect</p>')
        elif (weather or {}).get("ok"):
            sub.append('<p class="sub"><span class="dot"></span>No active alerts</p>')
        body = (f'<p class="big">{big}</p>' + (f'<p class="say">{say}</p>' if say else "")
                + "".join(sub))
    obs = f"{_iso_md((weather or {}).get('asof'))}, {fc['observed']}" if fc.get("observed") else ""
    return (f'<a class="tile" href="https://forecast.weather.gov/MapClick.php?lat=35.3733&amp;lon=-119.0187" rel="noopener">'
            f'<h3>Bakersfield weather</h3>{body}'
            f'{_by("National Weather Service", (weather or {}).get("asof"), built_iso, obs)}</a>')


def _aqi_marker(aqi: int) -> float:
    """Marker position (percent) on six equal bands of the EPA scale."""
    lo = 0
    for i, top in enumerate(_AQI_TOPS):
        if aqi <= top:
            return round((i + (aqi - lo) / (top - lo)) / 6 * 100, 1)
        lo = top
    return 100.0


def _aqi_tile(airnow, built_iso) -> str:
    airnow = airnow or {}
    if airnow.get("ok") and airnow.get("aqi") is not None:
        aqi = int(airnow["aqi"])
        pol = str(airnow.get("parameter") or "")
        pol = _POLLUTANT.get(pol.upper(), pol)
        bands = "".join(f'<i style="background:{c}"></i>' for c in _AQI_COLORS)
        body = (f'<p class="big">{aqi}<small>AQI</small></p>'
                f'<p class="say">{_e((airnow.get("category") or "").capitalize())}</p>'
                + (f'<p class="sub">Main pollutant: {_e(pol)}</p>' if pol else "")
                + f'<div class="meter" aria-hidden="true">{bands}<u style="left:{_aqi_marker(aqi)}%"></u></div>')
    elif airnow.get("needs_key"):
        body = '<p class="say">Waiting for the EPA AirNow key</p>'
    else:
        body = '<p class="say">Unavailable this build</p>'
    return (f'<a class="tile" href="https://www.airnow.gov/?city=Bakersfield&amp;state=CA&amp;country=USA" rel="noopener">'
            f'<h3>Air quality</h3>{body}{_by("EPA AirNow", airnow.get("asof"), built_iso)}</a>')


def _lake_tile(isa, built_iso, rel) -> str:
    isa = isa or {}
    last = isa.get("last")
    if last and isa.get("pct") is not None:
        pct = isa["pct"]
        body = (f'<p class="big">{pct}%<small>full</small></p>'
                f'<p class="say">{int(last["value"]):,} acre-feet</p>'
                f'<div class="fill" aria-hidden="true"><i style="width:{min(float(pct), 100)}%"></i></div>'
                + (f'<p class="sub" style="margin-top:8px">Capacity {int(isa["capacity_af"]):,} acre-feet</p>'
                   if isa.get("capacity_af") else ""))
        # CDEC posts yesterday's storage: a reading up to two days old is the current one.
        by = _by("CA DWR / CDEC", last.get("date"), built_iso,
                 f"{_iso_md(last.get('date'))} reading" if last.get("date") else "", grace_days=2)
    else:
        body = '<p class="say">Unavailable this build</p>'
        by = _by("CA DWR / CDEC", "", built_iso)
    return f'<a class="tile" href="{rel}water/"><h3>Lake Isabella</h3>{body}{by}</a>'


def _pass_row(route, name: str, href: str) -> str:
    """One mountain pass. The status is the pass itself, never Caltrans' statewide text."""
    if not route:
        st, sub = "Status unavailable this build", ""
    else:
        scope = route.get("scope")
        items = (scope or {}).get("on_pass_items") or []
        if scope is None:
            status = route.get("pass_status") or route.get("status") or ""
        elif scope.get("on_pass_reported"):
            status = scope.get("on_pass") or route.get("pass_status") or ""
        else:
            status = "NONE"
        sub = ""
        if status == "CLOSED":
            st = '<span class="sq"></span>Reported closed'
        elif status == "RESTRICTIONS":
            st = '<span class="sq"></span>Open, with restrictions or an advisory'
        elif status == "OPEN":
            st = '<span class="dot"></span>Open'
        elif status == "NONE":
            st = '<span class="dot"></span>Open. No closures or restrictions reported on the pass.'
        else:
            st = "Status unavailable this build"
        if items and items[0].get("text"):
            sub = f'<span class="sub t13 muted">{_e(overnight._clip(str(items[0]["text"]), 170))}</span>'
        elif scope is None and status:
            sub = '<span class="sub t13 muted">From the area-wide Caltrans text, which covers more than the pass.</span>'
    return (f'<li><a href="{href}"><b>{name}</b><span class="st">{st}</span>{sub}</a></li>')


def _passes_tile(roads, built_iso, rel) -> str:
    routes = {r.get("slug"): r for r in (roads or {}).get("routes", []) or []}
    stamp = next((str(r.get("reported_as_of")) for r in routes.values() if r.get("reported_as_of")), "")
    m = re.search(r"(\w+) (\d+)\w*, \d{4} at 0?(\d+:\d+ [AP]M)", stamp)
    extra = f"{m.group(1)[:3]} {m.group(2)}, {m.group(3)}" if m else ""
    return (f'<div class="tile wide"><h3>Mountain passes</h3><ul class="pass">'
            f'{_pass_row(routes.get("i5"), "I-5 Grapevine (Tejon Pass)", rel + "grapevine/")}'
            f'{_pass_row(routes.get("sr58"), "SR-58 Tehachapi Pass", rel + "tehachapi-pass/")}'
            f'</ul>{_by("Caltrans", (roads or {}).get("asof"), built_iso, extra)}</div>')


def _fire_tile(calfire, built_iso, rel) -> str:
    calfire = calfire or {}
    if calfire.get("ok"):
        kern = [f for f in calfire.get("incidents", []) or [] if "Kern" in str(f.get("county", ""))]
        word = "active wildfire" if len(kern) == 1 else "active wildfires"
        body = (f'<p class="row"><span class="big">{len(kern)}</span>'
                f'<span class="say">{word} on the CAL FIRE list</span></p>'
                '<p class="sub">The list does not include building fires or small local fires. '
                'Those are in The Kern Overnight.</p>')
    else:
        body = '<p class="say">Unavailable this build</p>'
    return (f'<a class="tile wide" href="{rel}fires/"><h3>CAL FIRE incidents in Kern County</h3>'
            f'{body}{_by("CAL FIRE", calfire.get("asof"), built_iso)}</a>')


def _conditions(weather, isa, airnow, calfire, roads, built_iso, rel) -> str:
    return f"""    <section class="cond" id="conditions" aria-labelledby="h-cond">
      <div class="sec-head">
        <h2 id="h-cond">Conditions</h2>
        <p class="sec-meta">Updated <time datetime="{built_iso}">{_iso_md(built_iso)}</time></p>
      </div>
      <div class="tiles">
        {_weather_tile(weather, built_iso)}
        {_aqi_tile(airnow, built_iso)}
        {_lake_tile(isa, built_iso, rel)}
        {_passes_tile(roads, built_iso, rel)}
        {_fire_tile(calfire, built_iso, rel)}
      </div>
    </section>"""


# ---------------------------------------------------------------- 4. headlines
def _headline_groups(top, headlines, limit: int = 12) -> list[tuple[str, list[dict]]]:
    """[(group label, [headline, ...])]. Each story is on the page once: the top story is in
    the lead, and a headline lands in the first group that matches it. Round-robin across
    outlets so no source dominates. Only links to the outlet's own page are kept."""
    top_title = (top or {}).get("title")
    pool = [h for h in headlines
            if h.get("title") and h.get("title") != top_title
            and str(h.get("url", "")).startswith("http") and "news.google.com" not in h.get("url", "")]
    pool = daily._balanced(pool, limit)
    buckets: dict[str, list] = {label: [] for label, _ in daily._TOPIC_BUCKETS}
    rest = []
    for h in pool:
        for label, keywords in daily._TOPIC_BUCKETS:
            if daily._matches(h, keywords):
                buckets[label].append(h)
                break
        else:
            rest.append(h)
    groups = [(label.replace(" & ", " and "), buckets[label][:4])
              for label, _ in daily._TOPIC_BUCKETS if buckets[label]]
    overflow = [h for label, _ in daily._TOPIC_BUCKETS for h in buckets[label][4:]]
    if overflow or rest:
        groups.append(("More headlines", (overflow + rest)[:4]))
    return groups


def _headlines(groups) -> str:
    if not groups:
        body = ('<p class="t15 muted" style="margin-top:10px">No headlines were fetched this '
                'build. This block returns with the next build.</p>')
    else:
        cols = []
        for label, items in groups:
            lis = "".join(
                f'\n          <li><a href="{_u(h["url"])}" rel="noopener">{_e(h["title"])}</a>'
                f'<span class="src">{_e(h.get("source", ""))}</span></li>' for h in items)
            cols.append(f"""
      <div>
        <h3>{_e(label)}</h3>
        <ul class="hl">{lis}
        </ul>
      </div>""")
        body = (f'<div class="groups">{"".join(cols)}\n    </div>\n'
                '    <p class="credit t13 muted">Reporting by KGET 17, 23ABC and Bakersfield Now. '
                "Each headline links to the article on the outlet's own site. No article text is "
                'republished here.</p>')
    return f"""  <section aria-labelledby="h-news" id="the-news">
    <h2 class="sec" id="h-news">Headlines</h2>
    {body}
  </section>"""


# ---------------------------------------------------------------- 5. this week
def _watch(upcoming, today) -> str:
    """One agenda item from a meeting in the next seven days, picked by daily._score."""
    best = None
    for m in upcoming:
        for it in (m.get("items") or [])[:40]:
            if not it.get("title"):
                continue
            c = {"meeting": m.get("name", "City meeting"), "item": it["title"],
                 "text": it.get("text", ""), "m": m}
            if best is None or daily._score(c) > daily._score(best):
                best = c
    if not best:
        return ""
    m = best["m"]
    day = dt.date.fromisoformat(m["start_iso"][:10])
    when = "today" if day == today else day.strftime("%A")
    clock = _clock(m["start_iso"])
    return f"""
        <p class="watch">
          <b>One thing to watch {when}</b>
          <a href="{_u(m.get('url', '#'))}" rel="noopener">{_e(overnight._clip(str(best['item']), 140))}</a>
          <span class="t15 muted" style="display:block;margin-top:2px">{_e(best['meeting'])}{', ' + clock if clock else ''}. Agendas can change. Confirm on the official agenda.</span>
        </p>"""


def _week(today, rel, escribe, board) -> str:
    """Public meetings for today and the six days after, with their posted start times."""
    escribe = escribe or {}
    end = today + dt.timedelta(days=6)
    upcoming = sorted((m for m in escribe.get("upcoming", []) or []
                       if today.isoformat() <= str(m.get("start_iso", ""))[:10] <= end.isoformat()),
                      key=lambda m: str(m.get("start_iso", "")))
    board_day = daily._board_date(board)
    cols = []
    for i in range(7):
        d = today + dt.timedelta(days=i)
        rows = []
        for m in upcoming:
            if m["start_iso"][:10] != d.isoformat():
                continue
            clock = _clock(m["start_iso"])
            time = (f'<p class="time">{clock}</p>' if clock
                    else '<p class="time none">Time not posted</p>')
            rows.append(f'\n              <li><a href="{_u(m.get("url") or rel + "city-hall/")}" rel="noopener">'
                        f'{_e(m.get("name", "Public meeting"))}</a>{time}</li>')
        if board_day == d.isoformat():
            rows.append(f'\n              <li><a href="{rel}city-hall/county-board/">Kern County Board of '
                        f'Supervisors</a><p class="time none">Time not posted</p></li>')
        if rows:
            tag = " <em>Today</em>" if i == 0 else ""
            cols.append(f"""
          <div>
            <h3>{d.strftime('%a')} {d.day}{tag}</h3>
            <ul>{''.join(rows)}
            </ul>
          </div>""")
    if cols:
        days = f'<div class="days">{"".join(cols)}\n        </div>'
    elif escribe.get("ok"):
        days = '<p class="t15 muted" style="margin-top:10px">No public meetings are posted for the next seven days.</p>'
    else:
        days = '<p class="t15 muted" style="margin-top:10px">The city meeting calendar was unavailable this build.</p>'

    recent = ""
    rec = (escribe.get("recent") or [None])[0]
    if rec and rec.get("url") and _iso_md(rec.get("start_iso")):
        recent = (f'\n          <a href="{_u(rec["url"])}" rel="noopener">{_e(rec.get("name", "Recent meeting"))} '
                  f'met {_iso_md(rec["start_iso"])}: official agenda</a>')
    return f"""      <section aria-labelledby="h-week">
        <div class="sec-head">
          <h2 id="h-week">This week at City Hall</h2>
          <p class="sec-meta">{_md(today)} to {_md(end)}</p>
        </div>{_watch(upcoming, today)}
        {days}
        <p class="links" style="margin-top:8px">{recent}
          <a href="{rel}city-hall/">All of City Hall and County</a>
          <a href="{rel}events/">Events</a>
        </p>
      </section>"""


# ---------------------------------------------------------------- 6. newsletter
def _newsletter(rel) -> str:
    """The one signup form on the page. Same target as every other page: it posts to the
    Cloudflare Pages Function /api/newsletter, and main.js finds it by id="nl-form"."""
    info = images._info("bakersfield")
    img = ""
    if info:
        w, h = info.get("width", ""), info.get("height", "")
        img = (f'<img src="{rel}{info.get("file") or "assets/img/bakersfield.jpg"}" '
               f'alt="{_e(info.get("alt") or "")}" loading="lazy"'
               + (f' width="{w}" height="{h}"' if w and h else "") + ">")
    return f"""      <section class="nl card" id="signup" aria-labelledby="h-nl">
        {img}
        <div class="nl-body">
          <h2 id="h-nl">Get the Brief by email</h2>
          <p class="t15 muted" style="margin-top:4px">News, conditions, and what is coming up. One email each morning. Free. Unsubscribe any time.</p>
          <form id="nl-form" action="/api/newsletter" method="POST">
            <label class="vh" for="nl-email">Your email</label>
            <input id="nl-email" type="email" name="email" placeholder="your@email.com" autocomplete="email" required>
            <button type="submit" class="btn dark">Get the Brief</button>
          </form>
        </div>
      </section>"""


def _modal() -> str:
    """Thank-you card, opened by main.js after the form is sent."""
    return """
<div class="nl-modal" id="nl-modal" role="dialog" aria-modal="true" aria-labelledby="nl-modal-title" aria-hidden="true">
  <div class="nl-card">
    <button type="button" class="nl-card-close" data-nl-close aria-label="Close">&times;</button>
    <div class="nl-card-body">
      <h3 id="nl-modal-title">You are on the list</h3>
      <p class="nl-card-sub">Thanks for subscribing to the Bakersfield Daily Brief. Every morning you get:</p>
      <ul class="nl-card-list">
        <li><b>The Kern Overnight.</b> Police, fire and EMS calls from the night before.</li>
        <li><b>Weather and conditions.</b> High, low, air quality, alerts and fires.</li>
        <li><b>Top stories and what is coming up.</b> Kern County news, meetings and events.</li>
        <li><b>Free, always.</b> No spam, no paywall. Unsubscribe any time.</li>
      </ul>
      <button type="button" class="btn dark" data-nl-close>Close</button>
    </div>
  </div>
</div>"""


# ---------------------------------------------------------------- 7. trackers, 8. past briefs
def _trackers(rel, alpr) -> str:
    alpr = alpr or {}
    total = (alpr.get("stats") or {}).get("total") if alpr.get("ok") else None
    if total is not None:
        # Same count /surveillance/ shows: cameras first mapped in the 28 days to the data date.
        try:
            cut = (dt.date.fromisoformat(str(alpr.get("asof", ""))[:10]) - dt.timedelta(days=28)).isoformat()
        except ValueError:
            cut = ""
        new = sum(1 for c in alpr.get("cameras", []) if cut and (c.get("mapped") or "") >= cut)
        alpr_line = f"{total} cameras mapped." + (
            f" Up {new} in 4 weeks." if new else " No new cameras in 4 weeks." if cut else "")
    else:
        alpr_line = "Camera count unavailable this build."
    return f"""      <section aria-labelledby="h-track">
        <h2 class="sec" id="h-track">Trackers</h2>
        <div class="track">
          <a href="{rel}surveillance/"><span><b>Flock and ALPR camera map</b><span>{alpr_line}</span></span>{_CHEVRON}</a>
          <a href="{rel}roads/"><span><b>Kern road conditions</b><span>I-5, SR-58 and SR-99 on one page.</span></span>{_CHEVRON}</a>
        </div>
        <p class="links"><a href="{rel}trackers/">All trackers</a></p>
      </section>"""


def _past(rel, past) -> str:
    if past:
        rows = []
        for e in past:
            d = dt.date.fromisoformat(str(e["date"]))
            rows.append(f'\n          <li><a href="{rel}briefs/{d.isoformat()}/"><b>{d.strftime("%a")}, {_md(d)}</b>'
                        f'<span>{_e(daily._entry_label(e))}</span></a></li>')
        body = f'<ul>{"".join(rows)}\n        </ul>'
    else:
        body = '<p class="t15 muted" style="margin-top:10px">The archive starts with today\'s brief.</p>'
    return f"""      <section class="past" aria-labelledby="h-past">
        <h2 class="sec" id="h-past">Past briefs</h2>
        {body}
        <p class="links"><a href="{rel}briefs/">All daily briefs</a></p>
      </section>"""


# ---------------------------------------------------------------- 9. about
def _about(rel) -> str:
    return f"""  <section class="about" aria-labelledby="h-about">
    <h2 class="sec" id="h-about">About this brief</h2>
    <p class="t15" style="margin-top:10px">The Daily Brief is built automatically every morning from public data. Parts are written by AI. We summarize, link, and attribute. We do not editorialize or republish article text.</p>
    <p class="t15">If one source is unavailable, its block says so and the rest of the brief still publishes.</p>
    <p class="t15">Sources: National Weather Service, EPA AirNow, California DWR (CDEC), Caltrans, CHP, CAL FIRE, City of Bakersfield and Kern County agendas, OpenStreetMap, and headlines from KGET 17, 23ABC and Bakersfield Now.</p>
    <p class="links"><a href="{rel}about/">Sources and how it works</a><a href="{rel}corrections/">Corrections</a></p>
  </section>"""


# ---------------------------------------------------------------- JSON-LD
def _jsonld(today, built_iso, top, groups, past) -> dict:
    """One @graph: NewsMediaOrganization, WebSite, WebPage, BlogPosting and two ItemLists.
    The headline list is the page's own: the top story, then the Headlines section in order."""
    name = daily._brief_h1(today)
    org = {k: v for k, v in page_mod.org_jsonld().items() if k != "@context"}
    org = {"@type": org.pop("@type"), "@id": ORG_ID, **org,
           "alternateName": "Bakersfield Brief",
           "sameAs": ["https://www.facebook.com/bakersfieldbrief"]}
    site = {k: v for k, v in page_mod.website_jsonld().items() if k != "@context"}
    site = {"@type": site.pop("@type"), "@id": SITE + "#website", **site, "inLanguage": "en-US",
            "publisher": {"@type": "Organization", "@id": ORG_ID, "name": page_mod.SITE_NAME}}
    brief_url = f"{SITE}briefs/{built_iso}/"
    stories = ([top] if top and str(top.get("url", "")).startswith("http") else []) + [
        h for _, items in groups for h in items]
    return {
        "@context": "https://schema.org",
        "@graph": [
            org,
            site,
            {"@type": "WebPage", "@id": SITE + "#webpage", "url": SITE, "name": name,
             "isPartOf": {"@id": SITE + "#website"}, "publisher": {"@id": ORG_ID},
             "dateModified": built_iso, "inLanguage": "en-US",
             "mainEntity": {"@id": SITE + "#headlines"}},
            {"@type": "BlogPosting", "@id": brief_url + "#post", "headline": name,
             "url": brief_url, "mainEntityOfPage": brief_url,
             "datePublished": built_iso, "dateModified": built_iso, "inLanguage": "en-US",
             "isAccessibleForFree": True, "image": page_mod.publisher_logo(),
             "author": {"@id": ORG_ID}, "publisher": {"@id": ORG_ID},
             "isPartOf": {"@id": SITE + "#website"}},
            {"@type": "ItemList", "@id": SITE + "#headlines",
             "name": f"Bakersfield and Kern County headlines, {today.strftime('%B')} {today.day}, {today.year}",
             "itemListOrder": "https://schema.org/ItemListOrderAscending",
             "numberOfItems": len(stories),
             "itemListElement": [{"@type": "ListItem", "position": i, "name": html.unescape(_e(h["title"])), "url": h["url"]}
                                 for i, h in enumerate(stories, 1)]},
            {"@type": "ItemList", "@id": SITE + "#recent", "name": "Recent daily briefs",
             "itemListOrder": "https://schema.org/ItemListOrderDescending",
             "numberOfItems": len(past),
             "itemListElement": [
                 {"@type": "ListItem", "position": i,
                  "name": daily._brief_h1(dt.date.fromisoformat(str(e["date"]))),
                  "url": f"{SITE}briefs/{e['date']}/"} for i, e in enumerate(past, 1)]},
        ],
    }
