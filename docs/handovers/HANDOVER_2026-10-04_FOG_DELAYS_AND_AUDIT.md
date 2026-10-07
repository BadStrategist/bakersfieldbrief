# Handover: fog delays page and site audit (2026-10-04)

For Hermes. Everything below is live on `origin/main` as of commit `fc2700ec`.
Five commits: `a985bacf` (fog delays page), `46e59b7a` (Pages secret step),
`6012953f` (audit fixes), `a3660ed9` (live checks, CAL FIRE fix, schedule
shift), `fc2700ec` (Overpass probe result).

## Do this first: sync the local checkout

The local checkout at `C:\Users\tscac\Projects\BakersfieldBrief.com` was NOT
updated. These commits were pushed from temporary worktrees so the dirty
working tree (staged `email/latest/*`, modified `scripts/brief_reel/render_reel.py`)
was never touched.

- Local `main` holds one commit, `bfcd9a4c`, that is a duplicate of `a985bacf`
  on the remote. `git pull --rebase` should drop it as already applied.
- Follow the usual AGENTS.md rule for `data/` and `email/` conflicts.
- Until you pull, local files for everything listed below are stale.

## New page: /fog-delays/

Kern County school delays and closures, read from the Kern County
Superintendent of Schools' AlertLine.

| Piece | File | What it does |
|---|---|---|
| Source | `build/sources/alertline.py` | Reads the AlertLine API each build; logs the day's alerts |
| Season log | `data/fog_delays/log.json` | Created on the first day a district posts an alert |
| Builder | `build/builders/fog_delays.py` | Writes the page |
| Live endpoint | `functions/api/fog-delays.js` | Cloudflare Pages Function, edge-cached 3 minutes |
| Client script | `assets/js/fog-delays.js` | Redraws the board every 3 minutes while open |
| Certificate | `build/sources/certs/geotrust_tls_rsa_ca_g1.pem` | DigiCert public intermediate |
| Tests | `tests/test_fog_delays.py` | 9 tests |

Rules for this page:

- **Never rewrite or backfill `data/fog_delays/log.json`.** AlertLine only
  publishes today, so that file is the only record of past fog days. It does
  not exist until the first alert is logged; that is expected.
- **Never claim a school is "on time".** AlertLine lists only schools that
  posted something. The page says a missing school "has posted nothing".
- **Never set `verify=False`.** AlertLine serves an incomplete certificate
  chain. The source verifies against certifi plus the bundled intermediate.
  That intermediate expires 2027-11-02; if the source starts failing with an
  SSL error around then, replace the file from DigiCert.
- **The API key rides in the URL path.** `alertline._scrub()` strips it from
  error strings. Do not log the request URL.
- **Limit is 1,000 requests a day.** Do not shorten the 3-minute cache in the
  Function or add another poller.

Secret: `ALERTLINE_API_KEY` is a GitHub secret, passed to all five build
workflows. `grapevine.yml` also copies it into the Cloudflare Pages project
(step "Push the AlertLine key into the Pages project") so the Function can
read it. It is not in the local `.env`, so a local build reports
`source alertline: FAIL`. That is expected, not a bug.

## Audit fixes (commit 6012953f)

**Road change log** (`build/sources/roads.py`, shown on /grapevine/, /roads/,
/tehachapi-pass/)

- The log used the statewide route status while labelling rows "Grapevine
  (Tejon Pass)". A closure anywhere on I-5 was logged as the Grapevine closing.
- It now follows the Kern corridor only (`corridor_state()`), and records the
  time of day.
- Entries written before this change are relabelled "I-5, anywhere in
  California" / "whole route", with a note under the table. Do not delete
  them; they age out of the 60-entry log on their own.
- `data/snapshots/roads.json` now carries `corridor` and `corridor_hash`.

**Air quality** (`build/sources/airnow.py`)

- AirNow retired its per-zip web services on 2026-10-01. They return HTTP 410.
- Moved to the replacement `ziplatlong` services. Same key, new field names
  (`nowcastAQI`, `aqiCategoryName`, `dateValid`).
- AQI is back on the home page, place pages and /numbers/.

**Evening weather** (`build/builders/daily.py`, `build/builders/places.py`)

- Evening builds printed "n/a" because today's forecast has no daytime period
  left. The home card now shows the observed temperature and tonight's low;
  place pages show tonight's low.

**Fair page** (`build/builders/fair.py`)

- Reads as a record once `ctx.today` is past `FAIR_END` (from 2026-10-05).
- Next year: update `FAIR_START`, `FAIR_END`, `FAIR_YEAR` and the lineup.

**SEO**

- `build/builders/page.py`: when a title is over 60 characters and ends with
  " | Bakersfield Daily Brief", the suffix is dropped. `og:title` keeps it.
  The leading words of every title are unchanged. Do not re-add the suffix to
  long titles.
- Trackers hub: new title and description that mention roads, fog delays and
  fires.
- /water/: new FAQ entry "How deep is Lake Isabella?". It gives the full-lake
  average (568,000 acre-feet over about 11,000 acres, about 52 ft) and how far
  the surface is below full pool. It deliberately gives no maximum depth:
  published dam heights disagree (98 ft and 185 ft both appear) and no agency
  publishes one. Do not add a maximum depth without a primary source.
- /oversight/ is `noindex, follow`. `_sitemap()` now skips any noindex page.

**CI** (`.github/workflows/daily.yml`)

- Pushes that change only `**.md` or `docs/**` no longer trigger the daily
  build.

Tests: `tests/test_audit_2026_10.py` (8 tests). Full suite: 235 passed in CI.

## Live checks and schedule shift (commits a3660ed9, fc2700ec)

**`/api/fires` works again** (`functions/api/fires.js`, `build/sources/calfire.py`)

- Cause: CAL FIRE moved the API to `incidents.fire.ca.gov`. The old
  `www.fire.ca.gov` address only redirects, and answers 403 to any request
  that claims to be a desktop browser. The Function sent a Chrome user agent.
- Fix: both the Function and the build source use the new host, and the
  Function sends the site's own user agent.
- **Do not put a browser user agent back in any Function.** Name the site.

**/tehachapi-weather/ has a live reading** (`functions/api/tehachapi-weather.js`,
`assets/js/live-tehachapi-weather.js`)

- Reads the same NWS stations as the build (KTSP, then SE067, C1020).
- The page swaps in a reading only when its timestamp is newer than the built
  one (`data-ts` on `#tw-now`). The FAQ text stays as built; it carries its
  own observation time.
- Edge-cached 5 minutes.

**/water/ flags a newer reading** (`functions/api/lake-isabella.js`,
`assets/js/live-water.js`)

- Lake Isabella is reported once a day. CDEC's hourly series runs about a day
  behind, so there is no fresher feed to show.
- The script only adds a notice above the level card when CDEC has a day the
  page does not (`data-reading-date` on `#isb-now`). It never rewrites the
  page's own figures; the chart, weekly change and FAQ all derive from the
  built reading. Keep it that way.
- Edge-cached 30 minutes.

**Schedules moved off :00 and :30** (all five workflows)

- Daily Brief runs at minute 7, the others at minute 37. Same Pacific hours,
  so the "Gate to 6am Pacific" step is unchanged.
- Whether this shortens GitHub's start delay is unproven. Check start times
  over the next few days before relying on it.

**Camera data (Overpass) has no usable mirror**

- Tested from a GitHub runner on 2026-10-05 with the real query: the main
  server answered in 2.4 s; four mirrors failed (two timeouts, a 504, a TLS
  error). Result is recorded in a comment in `build/sources/alpr.py`.
- The last-good camera list remains the fallback. Do not add a mirror without
  testing it from a runner.

## Things worth knowing

- **Any other push to `main` runs the full Daily Brief workflow**: build, test
  gate, deploy, newsletter step. The newsletter step skips itself when today's
  campaign already went out ("already sent ... skipping").
- **Scheduled builds start late.** GitHub ran the 13:00 UTC builds one to four
  hours late on the days checked. /grapevine/, /roads/, /tehachapi-pass/ and
  /fog-delays/, /fires/ and /tehachapi-weather/ have live refresh; /water/
  shows a notice when a newer daily reading exists.
- **Verified live after deploy**: Grapevine status matched Caltrans within a
  minute; `/api/fog-delays` returns `ok: true`; AQI and home weather show
  real values.

## Not fixed (needs Tyler, or left alone on purpose)

1. **`workers` workflow fails every run since 2026-09-23.** "Deploy
   grapevine-watchdog" gets "No access to the specified resource". The
   Cloudflare API token in GitHub secrets lacks Workers permission. Needs a
   new token from Tyler's Cloudflare account.
2. **`www.bakersfieldbrief.com` serves a duplicate site** instead of
   redirecting. Needs a Cloudflare redirect rule. Do not use a Pages
   `_middleware`.
3. **No backup server exists for the camera data.** See "Live checks" above.
4. (fixed: `/api/fires`, see "Live checks" above.)
5. **CHP source is intermittent.** On 2026-10-05 UTC it failed in three of
   five builds within about 70 minutes (01:16 fail, 01:21 ok, 01:55 fail,
   02:18 ok, 02:25 fail). The build log does not record the error, only
   `source chp: FAIL`. Feed: `https://media.chp.ca.gov/sa_xml/sa.xml`.
   Not investigated.
6. **Search Console**: request indexing for /fog-delays/, and remove the two
   bogus "sitemaps" (`/briefs/`, `/overnight/`). Both need the UI; API access
   is read-only.
7. **Season log capture is unproven.** A fog day is logged only if a build
   runs while the alerts are still posted. Check `data/fog_delays/log.json`
   after the first real fog morning.
