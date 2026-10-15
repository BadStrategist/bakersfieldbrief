# Handover: Bakersfield traffic cameras page (rank in search AND in AI answers)

You are the orchestrator. Hermes has done the external recon and will verify your work
against the deployed site. Build it, test it, report honestly what is done and what is not.

## Mission

Ship a live traffic camera + road status page for Kern County that ranks locally in Google
and gets quoted by AI answer engines (ChatGPT, Perplexity, Google AI Overviews, Claude).
Second, put camera blocks inside the trackers we already have.

Target query set, in priority order:
1. `bakersfield traffic cameras` / `bakersfield live traffic cameras`
2. `kern county traffic cameras`
3. `i-5 grapevine camera` / `sr-58 tehachapi camera` / `sr-99 bakersfield camera`
4. `is the grapevine open today` (already ours, must not cannibalize)

## Verified external facts (Hermes, 2026-10-11). Do not re-derive, do not assume beyond this.

Data source, both endpoints live and fast (0.8 s / 0.3 s):
- D6: `https://cwwp2.dot.ca.gov/data/d6/cctv/cctvStatusD06.json` — `{"data": [...]}`, 128 entries, 34 Kern.
- D9: `https://cwwp2.dot.ca.gov/data/d9/cctv/cctvStatusD09.json` — `{"data": [...]}`, 23 entries, 10 Kern.
- **44 Kern cameras total** (34 D6 + 9 D9). **43 have `inService` == `"true"`; exactly one is
  `"false"`: `SR-58 : Cameron Road` (D9).** That is the real out-of-service case, use it in a test.

Exact per-entry shape (strings everywhere, including booleans and numbers):

    index, recordTimestamp{recordDate, recordTime, recordEpoch},
    location{district, locationName, nearbyPlace, longitude, latitude, elevation,
             direction, county, route, routeSuffix, postmilePrefix, postmile,
             alignment, milepost},
    inService: "true" | "false",
    imageData{imageDescription, streamingVideoURL (D6 only),
              static{currentImageUpdateFrequency, currentImageURL,
                     referenceImageUpdateFrequency,
                     referenceImage1UpdatesAgoURL ... referenceImage12UpdatesAgoURL}}

- `location.route` is inside `location`, not top level (e.g. `I-5`, `SR-58`, `SR-99`, `SR-204`,
  `US-395`, `SR-14`, `SR-178`, `SR-184`, `SR-33`). `location.county` is the string `Kern` for ours.
- **`static.currentImageUpdateFrequency` is `"1"` — the still refreshes every 60 seconds.**
  `referenceImageUpdateFrequency` is `"15"` minutes. Proven live: three city cameras fetched twice
  75 s apart, all HTTP 200, all three hashes changed. So a 60 s on-page refresh is honest.
- The current still URL, verbatim, one real example:
  `https://cwwp2.dot.ca.gov/data/d6/cctv/image/ker5attruckescaperampshoulder/ker5attruckescaperampshoulder.jpg`
- **Always read image URLs out of the JSON. Never construct one.** Patterned guesses failed 4 of 4
  in testing. The JPEGs and the JSON both answer with `Access-Control-Allow-Origin: *`.
- `location.direction` is a compass word (North/South/East/West), not travel direction.
  `location.locationName` is the identifier, e.g. `KER-99-AT UNION AVE`, `KER-58-AT H ST`.
- D9 has four entries named `US-395 : North of SR-14 1..4` at **identical lat/lon**. Dedupe or
  label them explicitly; do not render four identical-looking cards at one point.

**Video: do NOT ship it.** 34 D6 cameras carry `streamingVideoURL` (`wzmedia.dot.ca.gov` HLS) but
the playlists are flaky (12 of 12 probes on three known-good URLs returned 404 during the liveness
test) and Caltrans TOPP 97-1 requires a paid 3-year Subscription Agreement for direct live video.
Stills are public domain, CORS-open, keyless and proven refreshing. The page is snapshots only.
Do not add an HLS player, not even hidden behind a flag.

## House rules you must follow (repo conventions, read them before writing)

- `AGENTS.md` at the repo root, and the **Grapevine page is the model**: `build/builders/grapevine.py`
  plus `build/sources/roads.py`. Study both first. That page already solves the exact problem in this
  handover: a big plain answer, a verbatim Caltrans "latest reported as of" timestamp, a changes log,
  original explainer copy, and **spoken forms for status so an answer engine can quote the sentence
  as English** ("the pass is open with restrictions", never "the pass is Restrictions").
- Source modules live in `build/sources/<name>.py` with a `run(ctx)` entry, `common.fetch`,
  a graceful stale fallback, and a change log under `data/change_logs/`. Add `build/sources/cameras.py`.
- Page builders live in `build/builders/<name>.py`; pages render through `templates/tracker.html`
  and `templates/layout.html`. Add `build/builders/traffic_cameras.py`.
- Live refresh is a Pages Function under `functions/api/` plus an `assets/js/` script, same shape as
  `functions/api/fog-delays.js` + `assets/js/fog-delays.js`. Use one to proxy and edge-cache the
  stills (60 s) instead of hotlinking Caltrans, so we control caching, referrer and failure states.
- `assets/js/webmcp-alpr.js` already exposes a widget as a WebMCP tool. After the page works, mirror
  that pattern so an AI agent can ask our page for current camera and road status. Phase 2 only.
- House style, non-negotiable: no em dashes anywhere, code comments included. Light palette, and it
  must not flip with `prefers-color-scheme` (a reader runs Windows dark mode and reading it as a bug).
  Mobile-first at 390 px with zero horizontal overflow, 44 px tap targets, correct heading order.
  Real content only. Never invent copy, never print a zero where the truth is "no data".

## Page spec

Route: `/traffic-cameras/`. Title targets `Bakersfield Traffic Cameras` plus Kern County, without
touching the Grapevine page's query.

Order on the page, top to bottom:
1. **The answer, in plain English, first.** What is open, what is restricted, what is closed on
   I-5 through Tejon Pass, SR-58, SR-99, with chain control and fog status if we have it. Reuse the
   Grapevine page's classification and its spoken-form wording rather than writing a second opinion.
   Every fact must be plain HTML in the first paint. No JS-only facts, because that is what search and
   AI crawlers read.
2. **A visible "as of" timestamp**, taken verbatim from the source, never our build time, plus one
   short line saying the camera pictures refresh about every minute.
3. **The camera grid, as evidence.** Each card: the picture, the name, route with direction, the
   nearby place, and the frame's age. Tapping a card opens a larger frame. This is the
   **conservative, state-first treatment** from the mockup
   (`C:\Users\tscac\Desktop\bb-redesign\mockup-traffic-cameras.html`); the picture-led variant stays
   available as a reference but is not the default. Match this site's real palette and card treatment,
   lifted from our own stylesheets, not a new look.
4. **Two empty states, both required and both tested.** Camera out of service (`inService == "false"`):
   say the camera is out of service. Feed unreachable or image 404: say the picture is unavailable
   right now and keep the card's name, route and place. Neither one prints `0`, `--`, or a blank frame.
5. **Original explainer copy** the thin template farms do not have: who runs these cameras (Caltrans
   District 6 and District 9), how often the pictures update, why Tehachapi and the Grapevine go socked
   in, what chain control means here, and what these cameras are not (they are not a surveillance
   record, see below). This is the section that earns the ranking, so make it genuinely useful.

**Never confuse this page with `/surveillance/`.** That page is about Flock ALPR surveillance
cameras and its no-staleness-disclosure rule binds it alone. This page is Caltrans traffic cameras.
They must not share copy, schema, cards or internal-link wording, and this page must never say
anything about how fresh the ALPR data is.

## Ranking requirements

- Search and AI crawlers are already correct on the live site, verified today: Googlebot, Bingbot,
  Applebot, DuckDuckBot, OAI-SearchBot, ChatGPT-User, PerplexityBot, Perplexity-User and Claude-User
  all get 200; the training bots (GPTBot, ClaudeBot, CCBot, Bytespider, Amazonbot) get 403. Do not
  change robots.txt or edge policy, and re-check that this stays true after deploy.
- Keep every existing JSON-LD node working and add what fits: a breadcrumb, an FAQ block answering
  the real questions, and an ordered list of the cameras. Only facts that are visible on the page.
- Add the page to the sitemap and to internal links from the Grapevine page, `/roads/`, `/fog-delays/`
  and the home page band. One clear anchor phrase each, no keyword stuffing.
- Facts must render server-side. Verify by fetching the deployed HTML and grepping for the answer text.

## Tests

Add tests in the existing suite (567 pass today, keep them passing):
- the Kern filter returns 44 cameras from fixtures of both districts;
- a `inService == "false"` camera renders the out-of-service state and never a zero;
- a failing image renders the unavailable state, not a blank frame;
- no em dash in any generated page or template;
- image URLs come only from parsed JSON (assert no URL is built by string concatenation);
- the status wording for each state matches the Grapevine page's spoken form.

## Ship and acceptance

Publish path: source-only commit, `[skip ci]` in the message, push, then
`gh workflow run deploy.yml` (it builds `--no-llm`, runs tests, deploys). Never `git add -A`,
never touch `site/` (gitignored build output), never push while a CI run is in flight. Check
`gh run list` first. If a scheduled job is mid-flight, wait and say so in your report.

Acceptance, and Hermes will verify each one against the deployed page, not the source:
1. `https://bakersfieldbrief.com/traffic-cameras/` returns 200 and contains the plain status answer
   and the "as of" timestamp in the raw HTML with JavaScript disabled.
2. Camera pictures load, card count matches the in-service count, and the frame age is shown.
3. No horizontal overflow at a true 390 CSS px, 44 px tap targets, correct heading order.
4. Zero em dashes in the rendered page.
5. The one dead camera (`SR-58 : Cameron Road`) shows the out-of-service state, not a broken image.
6. Crawler probe still shows search and AI retrieval bots at 200 after deploy.
7. Sitemap includes the URL, and the Grapevine, roads, fog and home pages link to it.

## Report back

Write `<this file>.claude-result.md` with: what you built, the exact files, the test output, the
deploy result, what you did not finish, and anything you found that contradicts this handover.
Hermes will then verify the deployed page point by point and report to the user.
