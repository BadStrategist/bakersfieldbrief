# Bakersfield Daily Brief

An automated civic-news brief for Bakersfield and Kern County, CA. Built fresh
every morning from public data, published as a fully static site on GitHub
Pages, monetized with AdSense. Modeled on tucsondailybrief.com.

**Everything is static.** Python scripts fetch data at build time and bake it
into HTML via a `/*__DATA__*/null` placeholder. No server, no database, no
client-side API calls. GitHub Actions cron jobs rebuild and publish daily.

---

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env                                # add your keys (see Secrets)
python build/build_all.py                           # full fetch + build → site/
python -m http.server 8123 --directory site         # preview
python scripts/verify_site.py                       # link checker (0 errors expected)
```

Useful flags:

- `--skip-sources` — build from the cached fetch (fast iteration on layout)
- `--no-llm` — force the deterministic digest (no LLM calls)

## Repo layout

```
build/
  common.py          paths, .env loader, snapshots, safe fetch
  llm.py             headline/agenda synthesis (keyless-safe, 503 retry w/ 70s)
  build_all.py       entry point: fetch all sources → run all builders
  sources/           one module per data source (never raises, fail-soft)
  builders/          one module per site section (daily, cityhall, openings,
                     trackers, places, static)
templates/layout.html   shared shell (nav, footer, schema)
assets/              css / js (copied into site/)
data/                committed state: snapshots, change logs, briefs archive
drafts/              review-only recap drafts (never deployed)
scripts/             verify_site.py, debug helpers
site/                built output (gitignored; CI deploys it)
```

## How it works

1. **Sources** (`build/sources/*.py`) — each returns `{"ok": bool, ...}` and
   never raises. If one fails, its block is omitted and the site still
   publishes. Currently: City meetings (eSCRIBE JSON), Kern County Board agenda
   (PDF), CA ABC license applications, KGET + 23ABC RSS, Google News RSS
   (per-place), NWS alerts/forecast, EPA AirNow AQI, CHP incidents, Isabella
   Lake (CDEC), food-facility closures, ALPR cameras (Overpass/OSM).
2. **Builders** (`build/builders/*.py`) — one per section, each renders static
   HTML from the source payloads and writes into `site/`.
3. **Schedules** — `.github/workflows/daily.yml` (6am Pacific) +
   `.github/workflows/weekly.yml` (Monday) rebuild and deploy via
   `actions/deploy-pages`.

### Adding a new data source (~30 min)

1. Write `build/sources/<name>.py` with a `run(ctx)` returning a dict with
   `"ok"`. Guard every external call; never raise.
2. Register it in `build/sources/__init__.py` (`SOURCES` dict).
3. Consume `sources.get("<name>", {})` in a builder; render with `rel`,
   `html.escape`, and the `/*__DATA__*/null` placeholder pattern for JSON.
4. Rebuild locally, run `scripts/verify_site.py`.
5. Commit — the daily cron picks it up automatically.

### Adding a place or tracker

- **Place** (hyperlocal page): add a 5-line entry to `PLACES` in
  `build/builders/places.py` (name, aliases, center, radius, NWS point).
- **Tracker** (evergreen data page): add an entry to `TRACKERS` in
  `build/builders/trackers.py` plus a render function — it appears on
  `/trackers/` automatically.

## GitHub setup

### 1. Create repo + enable Pages

```bash
gh repo create bakersfieldbrief --public --source . --push
# enable Pages with "GitHub Actions" as the source:
gh api repos/BadStrategist/bakersfieldbrief/pages -f build_type=workflow
```

### 2. Secrets (Settings → Secrets and variables → Actions)

| Secret | Required? | Used for |
|---|---|---|
| `LLM_API_KEY` | optional | LLM headline/agenda synthesis. Without it the built-in deterministic digest runs — identical output, zero cost |
| `AIRNOW_API_KEY` | optional | Live AQI in the Conditions strip. Without it the chip says "Waiting for EPA AirNow key" (register free at docs.airnowapi.org) |

The workflows pass both via `env:`; local builds read the same names from
`.env` (never committed).

### 3. Custom domain DNS

Point the apex at GitHub Pages:

| Record | Name | Target |
|---|---|---|
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |
| CNAME | `www` | `badstrategist.github.io` |

The repo already contains a `CNAME` file (`bakersfieldbrief.com`), copied into
the built artifact every build. After DNS propagates, set the custom domain in
Pages settings (or `gh api -X PUT repos/BadStrategist/bakersfieldbrief/pages \
-f cname=bakersfieldbrief.com`) and enable "Enforce HTTPS".

## AdSense submission checklist

- [ ] Substantial original copy on every page template (About, Privacy,
      Contact, methodology blocks, tracker explainers) — no thin/scraped pages
- [ ] News = headlines + links out only; article text is never republished
- [ ] Neutral, factual tone throughout (no opinion or editorializing)
- [ ] Ad slots: labeled placeholders (`data-ad-slot`), placed away from
      interactive elements (hero end, mid-content, pre-footer)
- [ ] Required pages live: Privacy Policy, About, Contact (mailto + address)
- [ ] `robots.txt` + `sitemap.xml` present and linked
- [ ] `ads.txt` placeholder at `/ads.txt` with your real pub ID (replace
      `pub-0000000000000000` when approved)
- [ ] Attribution: OpenStreetMap data © OSM contributors (ODbL); all data
      sources credited on-page and in the footer
- [ ] Google Search Console: verify `bakersfieldbrief.com`, submit sitemap
- [ ] No content behind interaction; site works with JS disabled (map pages
      degrade to the stats/list)
- [ ] Mobile: no horizontal scroll; focus states visible; reduced-motion OK

## Cost

~zero. GitHub Actions free tier (2000 min/mo): ~61 daily runs ≈ 5 min each ≈
305 min. All data sources are free public feeds (two optional free API keys:
OpenAI-compatible LLM, EPA AirNow).
