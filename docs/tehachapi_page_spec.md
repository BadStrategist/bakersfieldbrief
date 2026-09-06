# Tehachapi Pass Live Tracker — Page Specification

**Status:** Research complete (Sept 5, 2026). Buildable as written. Research only — no repo files were modified to produce this spec.
**Repo:** `C:\Users\tscac\Projects\BakersfieldBrief.com`
**Goal:** A single-topic, live-data page owning the #1 spot for Tehachapi Pass road/weather queries, using the same proven formula as `/grapevine/` (currently #1): big quotable answer → FAQPage JSON-LD with the query as Q1 → live data with honest timestamps → scannable cards.

---

## 1. Target queries (verified SERP)

The winter/storm road-conditions cluster is the strongest, plus wind and forecast. The page should answer all of these.

| # | Exact query | Intent | Winter spike |
|---|-------------|--------|--------------|
| 1 | `is tehachapi pass open` | Transactional, highest urgency | Strong |
| 2 | `tehachapi pass road conditions` | Transactional | Strong |
| 3 | `tehachapi wind` | Informational (driving-wind + wind-farm) | Strong |
| 4 | `tehachapi road conditions today` | Transactional, "today" freshness | Strong |
| 5 | `tehachapi weather forecast` | Informational | Year-round |
| 6 | `tehachapi snow` | Informational/seasonal | Strong (winter) |
| 7 | `sr 58 tehachapi conditions` / `highway 58 tehachapi pass` | Transactional | Strong |

Queries 1–4 are the ones to put in the H1, meta, and FAQ. 5–7 are secondary copy targets.

## 2. Live data availability (all keyless — VERIFIED live this session)

### 2a. SR-58 Caltrans conditions — ALREADY FETCHED, zero new fetch
The existing `build/sources/roads.py` parses SR-58 (route `58`, slug `sr58`, `pass=False`) on every build for `/grapevine/`. The Tehachapi page reuses `results["roads"]["routes"]` directly.

**Live verification (run this session, 2026-09-05 ~08:00 PM PDT):**
```
sr58  status=OPEN  pass_status=OPEN
  reported_as_of = "Saturday, September 5th, 2026 at 07:59 PM"
  sections = [ { region: "CENTRAL CALIFORNIA", text: "No traffic restrictions reported.", status: OPEN } ]
```
Per-route fields the page can use: `status` (OPEN/RESTRICTIONS/CLOSED), `pass_status`, `sections[].{region,text,status}`, `reported_as_of` (Caltrans' own verbatim timestamp — display it, never replace with build time), `hash`, `name`, `slug`.

**Honesty caveat (critical):** SR-58's Caltrans text is a single **Central California area** section — it is *not* pass-specific. It *will* name the pass ("SR-58 is closed over the Tehachapi Pass...") when a pass closure is active, but when clear it only says "No traffic restrictions reported." So the big answer must be worded **"SR-58 is reported OPEN by Caltrans (Central California area)"**, NOT "Tehachapi Pass is OPEN." Showing the verbatim section text under the status keeps this honest. (For I-5 the grapevine builder highlights the Central section as the pass; for SR-58 do the same but keep the "Central California area" wording visible.)

### 2b. NWS forecast — keyless (api.weather.gov)
Existing `weather.py` already demonstrates the keyless NWS pattern, but it is hardcoded to **Bakersfield** (point `35.3733,-119.0187`, station KBFL). The Tehachapi page needs its **own gridpoint** — either a small new source or a parameterized helper.

**Verified gridpoint (this session):** point `35.1322,-118.4490` (Tehachapi) → grid **HNX/87,20**, `forecastZone=CAZ334`, `county=CAC029`. Forecast periods include `temperature` + `windSpeed` + `windDirection` (forecast wind). Hourly gridpoint (`forecastHourly`) gives temp + wind + windGust per hour.

### 2c. NWS current conditions — keyless, live at the pass
Real-time observations for Tehachapi Pass via `https://api.weather.gov/stations/<ID>/observations/latest`:
- **KTSP (Tehachapi Municipal Airport)** — the primary station. **Verified live this session: 68°F, wind 29 mph from 280°, Clear, 2026-09-06 02:35Z.**
- CWOP `C1020` (CW1020 Tehachapi) — backup residential station.
- SE067 (SCE Cummings Valley, elev 3,930 ft) — close to the pass crest; NWS' own "current conditions" pick for CAZ334.

These give the page a real **current wind speed + gust** for the `tehachapi wind` query.

### 2d. NWS alerts — keyless, already wired
`weather.py` already pulls Kern-county alerts (`/alerts/active?area=CA`, filtered on "Kern" in areaDesc). Tehachapi is in Kern County → **the existing Kern alert feed already covers the pass.** A pass-specific list is also available at `/alerts/active/zone/CAZ334`. Verified: **0 active Kern alerts right now** — the block must render an honest "No active NWS advisories for the Tehachapi area" state.

### 2e. Elevation & relationship
- Tehachapi Pass summit ≈ **4,067 ft** (SR-58 crest).
- It is the **direct mountain-pass alternative to the Grapevine (I-5/Tejon Pass)** — same LA↔Bakersfield corridor. The page must own this relationship (and link to `/grapevine/`).

**Data-block summary (all keyless, all live-verified):**

| Block | Source | Keyless | Verified |
|-------|--------|:---:|:---:|
| SR-58 status + verbatim text | roads.py (already fetched) | ✅ | ✅ OPEN |
| Current temp / wind / gust | KTSP observation | ✅ | ✅ 68°F, 29mph |
| NWS forecast (temp + wind) | HNX/87,20 gridpoint | ✅ | ✅ |
| Kern / CAZ334 alerts | weather.py + zone endpoint | ✅ | ✅ 0 active |
| Elevation / pass fact | static | ✅ | ✅ |

## 3. Competitive scan (what we're beating)

SERP sampled for `tehachapi pass road conditions`, `tehachapi wind`, `is tehachapi pass open`, `tehachapi weather forecast`.

1. **roads.dot.ca.gov/?roadnumber=58 (Caltrans, #1)** — raw official text only. No local framing, no wind/forecast, no FAQ, no alternates, no human age-hint. Authoritative but a dead end for the user.
2. **localconditions.com Tehachapi Traffic** — interactive map + a **generic state-wide alert feed** (shows collisions in Placer County / Gold Hill, i.e. *not* Tehachapi), heavy donation/paywall banner, "Do not drive while using" disclaimer. Not pass-specific, cluttered, no status word.
3. **visitbakersfield.com/plan/road-conditions** — static reference table that just links out to Caltrans. **No live data at all.**
4. **NWS CAZ334 zone forecast** — authoritative forecast + wind-gust text and a Cummings Valley current-conditions card, but a data dump with no road integration, no FAQ targeting the query, timestamps not surfaced in a friendly way.
5. **weatherbug / AccuWeather driving-weather** — generic ad-heavy city widgets, partly paywalled, not pass-specific.
6. **willyweather / windfinder / windalert** — wind-focused but **recreational** (kitesurfing/windsurfing), not road-travel intent.

**The gap:** *No page* combines (a) live SR-58 status word with an honest timestamp, (b) live pass wind/temp, (c) NWS forecast + Kern alerts for the pass, (d) the Grapevine-vs-Tehachapi alternate relationship, and (e) FAQ structured to the exact queries — with no paywall and no noise. That is exactly the `/grapevine/` formula, applied to a second high-value pass. The pass-specific, clean, timestamped, FAQ-structured page beats every incumbent on relevance and freshness.

## 4. Page spec

### 4a. URL, title, meta
- **URL:** `/tehachapi-pass/` (canonical). Distinct from `/grapevine/` and unambiguous about "pass," not "town weather." (If a town-weather play is wanted later, `/tehachapi/` can be a separate page; don't overload one URL for both intents.)
- **Title (`<title>`):**
  `Is Tehachapi Pass (SR-58) open right now? | Bakersfield Daily Brief`
- **Meta description (~155 chars):**
  `Live SR-58 conditions over Tehachapi Pass — the LA-to-Bakersfield alternative to the Grapevine — plus Tehachapi wind, weather, and NWS alerts. Updated 3x daily.`
- **H1 (visible + first heading):** `Is Tehachapi Pass (SR-58) open right now?`
- **Lede:** "Live SR-58 conditions over Tehachapi Pass (elevation 4,067 ft) — the mountain alternative to the Grapevine — plus live wind, the NWS forecast, and Kern alerts."

### 4b. Direct quotable answer (the SEO/GEO core — first text after the H1)
Mirror grapevine's `direct_answer` pattern, worded honestly:
> **"As of {Caltrans reported_as_of}, SR-58 is reported {label} by Caltrans (Central California area).** {note}"

- `label` from the same OPEN/RESTRICTIONS/CLOSED → big-word copy map as grapevine (`_STATUS_COPY`).
- Because SR-58 is area-wide text, use `sr58["status"]` for the word and always render the verbatim section text underneath. Do **not** say "Tehachapi Pass is OPEN" as a bare claim.
- Note when it differs: if Caltrans flags wind/restrictions in the SR-58 text, the note should say so and cross-link the wind block.
- Show the Caltrans timestamp verbatim + `_report_age_hint()` (reuse grapevine's helper, e.g. "(7 min ago)").

### 4c. Live data blocks (top to bottom)
1. **Big status card** — SR-58 pass_status with the word (Open / Restrictions / Closed), colored (green/amber/red), the verbatim Central-California section text, and the Caltrans timestamp + age hint.
2. **Live wind & temp card (the `tehachapi wind` answer)** — KTSP current observation: temp, wind speed, gust, direction (cardinal), observed time. Header: **"Current conditions at the pass."** When KTSP fails, fall back to SE067/C1020, or the hourly-gridpoint forecast wind, each labeled with its true source.
3. **NWS forecast block** — today high/low + a few periods with temp and wind/gust, from the HNX/87,20 gridpoint. Label source "National Weather Service."
4. **NWS alerts block** — Kern alerts (already wired); show event/severity/headline or a clean "No active NWS advisories for the Tehachapi area." Link to the zone (`CAZ334`) and weather.gov.
5. **Route cards** — SR-58 status (the focus) plus compact SR-99 and I-5 Grapevine so the traveler can compare the corridor at a glance (reuse the roads result already in hand).
6. **Grapevine-vs-Tehachapi alternates card** — "SR-58 over Tehachapi Pass is the usual detour when the Grapevine closes — and vice versa." Cross-link `/grapevine/`. Include Caltrans phone `1-800-427-7623` and roads.dot.ca.gov.
7. **Why Tehachapi Pass closes** — original explainer copy: snow/ice (it routinely closes with winter storms), **high winds** (trucks are the frequent casualty, wind advisories common), fog; elevation 4,067 ft; chain-control notes.
8. **Recent changes log** — reuse `roads["log"]` for SR-58 status flips (already tracked).

### 4d. FAQ (visible on page + FAQPage JSON-LD), with draft answers
Q1 must be the exact top query. Its answer is injected with the **live** status (grapevine's proven pattern) so AI/featured snippets quote the real current state, not "check this page."

1. **"Is Tehachapi Pass open right now?"**
   → Live answer: *"SR-58 over Tehachapi Pass is reported {label} by Caltrans as of {reported_as_of}. {note} {stale_suffix}"* (fallback if no data: "Caltrans conditions are unavailable this build — see roads.dot.ca.gov or call 1-800-427-7623.")
2. **"What are the road conditions on Highway 58 through Tehachapi Pass?"**
   → "Caltrans reports SR-58 as {label} (Central California area) as of {timestamp}. {verbatim section text}. Confirm on roads.dot.ca.gov before driving."
3. **"How windy is Tehachapi Pass right now?"**
   → Live: *"As of {observed}, the Tehachapi Municipal Airport weather station reports {wind} mph with gusts to {gust} mph from {direction}."*
4. **"How do I check SR-58 Tehachapi Pass conditions?"**
   → "Call Caltrans at 1-800-427-7623 or visit roads.dot.ca.gov. This page refreshes 3 times daily."
5. **"Why does Tehachapi Pass close?"**
   → "Snow and ice in winter storms, and high winds that tip high-profile vehicles. Caltrans posts chain controls (R2/R3) at the base of the grade."
6. **"What is the best alternate route if Tehachapi Pass is closed?"**
   → "The Grapevine (I-5/Tejon Pass) is the usual detour — check its status above — or SR-14/US-395 around the east side, which stays open when both passes close."

### 4e. Staleness handling (non-negotiable per project requirement)
Reuse grapevine's exact guards:
- **Age hint:** render the Caltrans verbatim `reported_as_of` + `_report_age_hint()` ("(3 hr ago)"). Never replace the agency timestamp with build time.
- **Live vs stale flag:** when `roads["stale"]`/`last_good` is set, show the errorbox: "Caltrans is unreachable right now. The conditions below are from the most recent report and may be out of date. Confirm live status before driving: roads.dot.ca.gov or 1-800-427-7623."
- **Last-known fallback:** the roads source already falls back to `roads_last.json` and flags `stale=True` — the builder renders the fallback with the original timestamp, never asserts freshness.
- **Wind/forecast failure:** each weather block must stand alone — if KTSP fails, degrade to the labeled fallback or omit the block; never show an empty card as live. Any block with no data shows an honest "unavailable this build."
- **Missing data → no claim:** if no SR-58 data at all, do NOT render a status word; show the errorbox + official links.
- Add a per-source micro-note under each live block naming the exact source and its last-update time (Caltrans / KTSP / NWS).

### 4f. FAQPage JSON-LD
Mirror `grapevine._faq_jsonld()` exactly: `FAQPage` → `mainEntity[]` of `Question`/`acceptedAnswer.Answer`, Q1's text carrying the **live** status string (strip HTML via the same regex used in grapevine). Questions 1–6 above. Keep every non-live answer short, factual, and static so the schema is stable except for the live Q1/Q3 strings.

## 5. Implementation wiring (for the builder — do not build in this phase)

- **New source (recommended):** `build/sources/tehachapi_weather.py` with `run(ctx)` returning `{"ok": bool, "current": {...KTSP obs...}, "forecast": [...periods...], "alerts": [...], "asof": ...}`. All keyless NWS calls (points → gridpoint forecast/forecastHourly → KTSP observation → CAZ334 or reuse Kern alerts). Failures degrade to partial dicts, never raise. Register in `SOURCES` in `build/sources/__init__.py`.
  - *Alternative (no new source):* extend `weather.py` with a parameterized Tehachapi block. A separate module is cleaner and keeps the Bakersfield page untouched.
- **New builder:** `build/builders/tehachapi.py` with `build(ctx, results)` reading `results["roads"]` (reuse, zero new fetch) + `results["tehachapi_weather"]`. Reuse `grapevine._report_age_hint`, `page_mod.render`, `page_mod.org_jsonld/website_jsonld`, the `_STATUS_COPY` map (import or duplicate). Write to `common.SITE / "tehachapi-pass" / "index.html"`, canonical `/tehachapi-pass/`, and set `ctx.build_report["tehachapi"]`.
- **Register the builder** in the `builders` list in `build/build_all.py` (after grapevine).
- **Sitemap + nav:** add the page to the sitemap builder and to any homepage/section links that already list `/grapevine/` (build_all.py lines ~207, 281, 315 and `numbers.py` tile) so it's discoverable and cross-linked both ways.
- **Tests:** mirror `tests/test_grapevine_liveliness.py` — assert the age-hint helper, the stale-source render path, and that a data-less source never emits a bare status word.

## 6. Risks & honesty rules (the project's hard requirement)

1. **Never overclaim "pass is OPEN/CLOSED"** from area-wide SR-58 text. Always word as "SR-58 reported {status} (Central California area)" + show verbatim text. The status word must match what Caltrans actually reports.
2. **Don't invent numbers.** Wind/temp come only from KTSP (or labeled fallback); never fabricate a current reading. If KTSP is down, say so.
3. **Weather and road status are independent data.** A wind advisory (RESTRICTIONS) ≠ closed. Present each in its own block; the FAQ Q1 answer reflects the *road* status while the wind block answers separately.
4. **0 active alerts is a valid, renderable state** — show "No active NWS advisories" rather than hiding the block.
5. **Timestamps are sacred:** display Caltrans/KTSP/NWS's own timestamps verbatim; the "refreshes 3× daily" line is about the site's build cadence, not the data's.
6. **Don't let the page go stale silently** — the stale fallback banner must appear whenever the live fetch fails.
7. Seasonal honesty: `tehachapi snow`-type phrasing only makes claims backed by the forecast/alerts data at build time.

## 7. Verification done for this spec
- Ran the live roads source: **SR-58 OPEN**, "No traffic restrictions reported," Central California, as of 2026-09-05 07:59 PM (also cross-checked roads_last.json snapshot). ✅
- Queried NWS keyless: gridpoint **HNX/87,20**, zone **CAZ334**, county **CAC029**; forecast + hourly wind/temp returned. ✅
- Queried **KTSP** latest observation live: 68°F, 29 mph, 280°, Clear. ✅
- Kern alerts feed: **0 active** (weather.py runs clean). ✅
- Sampled SERPs for all four primary queries and profiled 6 competitor page types. ✅
