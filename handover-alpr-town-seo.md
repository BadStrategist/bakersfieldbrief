> NOTE (Hermes, rerun): the working tree ALREADY holds YOUR edits from the 15:48 run that hit the
> session limit after it wrote them (modified: assets/css/deflock.css, build/builders/alpr_towns.py,
> build/builders/daily.py, tests/test_alpr_towns.py; untracked: build/alpr_town_records.json). REVIEW
> and FINISH what is on disk instead of starting over, and write the summary you owe (per-page
> ranking verdict, the query set, the fixes, what blocks top 3) as your final reply, which the runner
> saves to handover-alpr-town-seo.claude-result.md.

# Audit the ALPR town pages for a top-3 goal

The owner asks, verbatim: **"Have claude make sure the individual sections like
https://bakersfieldbrief.com/surveillance/ridgecrest/ and https://bakersfieldbrief.com/surveillance/tehachapi/
etc will rank high. Must rank in the top 3. So have it audit and make sure they will."**

You are the orchestrator. Audit the eight live town pages against the queries a person actually types,
name what is missing, and fix what the evidence supports. **Nothing is pushed from this handover.**
Hermes builds, verifies the rendered deployed pages, and reports back.

## The pages, live as of 2026-10-12

| URL | cameras | visible words | title | meta description |
|---|---|---|---|---|
| `/surveillance/` (hub) | 455 | 23,941 | `Bakersfield Flock Camera Map \| Live ALPR Tracker` (48) | 296 chars |
| `/surveillance/ridgecrest/` | 31 | 3,295 | `Ridgecrest Flock Camera Map \| 31 License Plate Readers` (54) | 226 |
| `/surveillance/delano/` | 30 | 3,062 | `Delano Flock Camera Map \| 30 License Plate Readers` (50) | 222 |
| `/surveillance/mcfarland/` | 19 | | | |
| `/surveillance/oidale/` | 13 | | | |
| `/surveillance/rosedale/` | 11 | | | |
| `/surveillance/wasco/` | 10 | | | |
| `/surveillance/tehachapi/` | 12 (city 7 + 5 in Golden Hills, Bear Valley Springs, Stallion Springs) | 2,025 | `Tehachapi Flock Camera Map \| 12 License Plate Readers` (53) | 225 |

Measured on the live HTML today, cache-busted, with a plain crawler user agent:

- Every town page: canonical correct, one H1 (`<Town> Flock Camera Map`), six H2s
  ("Every license plate reader in <town>, and whose land it sits on", "Just outside the <city> limits",
  "More of the county map", "Sections", "Trackers", "About").
- Town-page schema types: `BreadcrumbList, Dataset, GeoShape, Place, WebPage, Organization, ImageObject,
  ListItem, ContactPoint`. **No `FAQPage` on a town page** (the hub has one).
- **Only 8 distinct internal link targets per town page.** Sibling town pages are not linked from a town
  page; the hub links down, the spokes do not link across.
- Town-page meta descriptions are 222 to 226 chars (over the ~155 to 160 that is usually shown whole).
- "flock" appears 41 to 75 times per town page; "license plate" 5 times.

## What ranks today

**"tehachapi flock camera map"** (searched 2026-10-12):

1. `mytownview.com/california/kern/tehachapi/community/surveillance` - "Flock Cameras in Tehachapi,
   California: 7 Locations". Their own copy admits: "Public records document at least 7 surveillance
   camera locations", "coverage is volunteer-driven and may be incomplete". Content: a dot map, an
   address-distance box, an FAQ, links to Google Maps.
2. MyTownView Lancaster (internal-link neighbour page).
3. `areyouflocked.com/california` - state page; "Markers sit at the municipality or agency, never at a
   guessed camera pole"; lists Tehachapi at "7 mapped cameras".
4. **`bscc.ca.gov` grant PDF for the Tehachapi Police Department** - states the department "is to
   install 16 Automatic License Plate Readers (ALPR) throughout the city along high traffic areas",
   names the three Highway 58 ramps, the two other exit roads, and "2 ALPRs ... at the primary
   intersection centered in the business district", Flock Safety as the vendor, 3-year term.
5. `ceqanet.lci.ca.gov/2026040438` - the Kern County Sheriff's Office Flock installation notice, with
   cross streets "Woodford-Tehachapi Rd, Claymine Rd" and lat/long for several poles.

**"ridgecrest flock cameras"** (searched 2026-10-12): a news SERP, no map page in the top 5.

1. NewsBreak / KGET - Ridgecrest's police chief amending the Flock contract after resident pushback.
2. ground.news - Ridgecrest Daily Independent mayor-candidate Q&A on the Flock contract.
3. **our own `/briefs/2026-10-08/`** - the brief that summarized the KGET story.
4. `ridgecrestca.com/news/local/` - the publisher's own page.
5. `citizenportal.ai` - residents urging cancellation; says the city has "24 automated license-plate and
   object-recognition cameras" and names contract clauses 5.3 and 4.3.

Two facts to weigh: our own dated brief page outranks any map page for the Ridgecrest query, and the
camera counts in the press (24 for Ridgecrest) differ from the mapped count we publish (31).

## Indexation, as of today

`site:bakersfieldbrief.com surveillance` returns the hub with **old copy** (270 cameras, 240 Flock,
"as of 2026-10-10", and the staleness sentence the owner removed). No town page appears in the index yet.
All eight town URLs are in `sitemap.xml`. **Search Console is not connected**, so there is no impression
or query data and no way to request indexing from this box.

## What to deliver

1. **A query set per town**, the real phrasing (map, locations, "does <town> have flock cameras",
   "<town> license plate readers", "<town> ALPR", "<town> surveillance cameras"), with the current
   occupiers and their content type, so the target is named rather than assumed.
2. **An on-page audit** of all eight pages: title, meta, H1/H2 shape, schema, content depth, internal
   links, crawlability, duplication between towns, and anything that reads as a doorway set. Say which
   gaps are real ranking factors and which are not, with the reason.
3. **Prioritized fixes**, patches where the fix is clear. Judge at least: whether a town page needs
   `FAQPage`; whether sibling links and a town-to-hub-to-town path should exist; whether the meta
   descriptions should be trimmed; whether the pages need the public-record context they are missing
   (the Tehachapi BSCC grant for 16 units, the CEQAnet poles, the Ridgecrest contract story, the
   differing counts in the press) and where to cite it without inventing copy; whether the hub's
   "What is complete, and what is not" block (still live) helps or hurts this goal.
4. **A plain statement of what cannot be promised.** Nobody can promise a position. Name what would
   block top 3 for each page (no Search Console, brand-new URLs with no history, news-dominated SERPs,
   MyTownView's existing links and age, eight thin-ish spokes versus one hub) and say which pages can
   plausibly reach it and which cannot.

## Constraints that are not negotiable

- No em dashes anywhere, code comments included. Simplified Technical English for anything technical.
- Real data only. Never invent, never hardcode reader copy, never imitate a competitor from vibes.
- Light palette, mobile-first at 390 px, no horizontal page overflow, 44 px tap targets, correct
  heading order, keep every existing JSON-LD node.
- No ads on tracker or alert pages (Google's publisher policy bans ads on alert and navigation pages).
- The owner banned a staleness disclosure on the surveillance pages. Do not reintroduce one.
- Do not break the existing tests. The suite is the gate. `pytest -q` must stay green.
- Any claim about a page is checked against the LIVE deployed HTML, not the source file.
