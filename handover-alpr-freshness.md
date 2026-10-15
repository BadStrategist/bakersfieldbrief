# ALPR freshness: why every red run is this step, and the fix path I proved

You are the orchestrator on this one. I gathered the evidence below from the live system on
2026-10-12. Decide the fix, or argue back if my reading is wrong. Do not bandaid it.

## 1. What is red, and how often

`gh run list --limit 25` on main: 9 runs red, and **every one of them failed at the same step**,
"Verify the ALPR camera data is today's". The second failing step is always just the notifier
("Notify ops Discord on failure"), which also fails because `DISCORD_WEBHOOK_URL` is not set as a
repo secret.

Red runs (all ALPR): 38275072636, 38264636545, 38237530689, 38166794109, 38165417200,
38163636875, 38161914740, 38121747255, 38121418967. Green runs in the same window: 38271720892,
38265497100, 38231592488, 38188061797, 38186129315, 38184693547, 38184232616, 38183794154,
38171214850, 38168170934, 38163726093, 38160494357, 38140083817, 38127764483, 38117786167,
38115591525.

## 2. The exact failure, and why the page is not actually wrong

Run 38264636545, step log:

```
alpr freshness: ok=True stale=True asof=2026-10-12 cameras=270 run_date(PT)=2026-10-12 built_at=2026-10-12T07:44:48-07:00
##[error]the Overpass fetch failed; /surveillance/ is serving the last good list from 2026-10-12:
HTTPError: 504 Server Error: Gateway Timeout for url: https://overpass-api.de/api/interpreter
```

Read that payload: `ok=True`, 270 cameras, `asof` is the run date. The page carried **today's**
data. The run is red only because this build's refresh attempt failed and the source fell back to
the last good list and set `stale=True`.

`scripts/check_alpr_fresh.py` fails when `stale` is not exactly `False` (lines 87-93). `AGENTS.md`
documents that as deliberate: the last-good-list fallback keeps the page from showing zero cameras,
`ok: True` there means "renderable" and not "healthy", and the answer to stale data is a red run
plus an alert, never page copy. So the gate is not the defect here. **The defect is that the daily
fetch fails at all.** The owner's standing instruction on this page is: make sure the tracker is up
to date, and will remain up to date, every day, with no bandaids.

## 3. The upstream half: my probe found the real cause

I probed from the local box with a policy User-Agent, 2026-10-12 18:28 UTC. Same instance, same
minute, four variants of the same query:

```
api.de  real query (as shipped: ... out meta;)      504    7.3s
api.de  real query, [timeout:180] prepended         504   13.9s
api.de  same filters, "out;" instead of "out meta;"  200    1.8s  elements=270 bytes=99702
osm.ch  real query (as shipped)                      200    1.3s  (body is an error page, 646 bytes)
osm.ch  same filters, "out;"                         200    1.1s  elements=0
api.de  bbox split in two, "out meta;"               504    8.3s
```

**`out meta` is the failing half.** The same instance answers the same filters in 1.8 s and 99 KB
when `out meta` is dropped, and 504s on `out meta` even with a 180 s server-side budget, so it is
not our client timeout and not the query's complexity: the metadata stage dies on the server.

Mirrors, measured the same day from this box with the same User-Agent (the comment at
`build/sources/alpr.py:19-23` recorded a similar sweep from a runner on 2026-10-05, so this
confirms there is still no working fallback):

```
overpass-api.de                 count query 200 1.9s   real query 504 8.8s
overpass.kumi.systems           504 35.9s / timeout
overpass.private.coffee         timeout 60.4s
overpass.osm.jp                 TLS hostname mismatch
overpass.osm.ch                 200, but 0 elements for this tag set: its copy cannot serve this
maps.mail.ru                    200 on a trivial query, 504 1.8s on the real one
overpass.openstreetmap.ru       connection refused (WinError 10060)
overpass.osm.rambler.ru         DNS dead
```

Also: the earlier "this box sees 406" note is explained. A stdlib User-Agent gets an instant 406
from Apache; with a named User-Agent the request is accepted and then 504s. The 406 was a header
rejection, not a different network fault. `build/common.py:110` already sends a named UA, so CI and
this box hit the same 504.

## 4. The fix path I proved end to end from this box

Split the fetch so the live path never depends on `out meta`:

1. Overpass, same filters, **`out;` instead of `out meta;`**: HTTP 200, 270 nodes, 99,702 bytes,
   1.8 s.
2. One bulk call for the metadata of all 270 ids:
   `https://api.openstreetmap.org/api/0.6/nodes?nodes=<id,id,...>` (url length 3,289):
   **HTTP 200, 0.8 s, 137,451 bytes, 270 of 270 nodes carrying a timestamp.**

Caveat you must design around: the bulk endpoint returns the **current** version. Only version 1
nodes give their creation date, which is what "first mapped" needs. Measured versions across the
270 nodes: 1, 2 and 3 are all present. `build/sources/alpr.py:143` already has
`OSM_V1 = "https://api.openstreetmap.org/api/0.6/node/{id}/1.json"` for this, so the honest design
is bulk first, then a bounded number of `{id}/1.json` calls for the nodes whose bulk version is
above 1 (count them before choosing the cap). If that is too many requests for a runner, say so and
propose the alternative, but do not silently let a re-tagged camera count as newly mapped: that bug
is already fixed once (4 of 15 "new in 4 weeks" were edits, 2026-09-22).

Unproven and yours to verify: whether `api.openstreetmap.org` is reachable from a GitHub runner.
My evidence is from this box only. If it is not, the fallback chain has to change shape, so probe
that first and state the result before designing around it.

## 5. Second defect: the gate sits in front of things that are not its business

`daily.yml` step order (line numbers): build 80, ping UptimeRobot 89, test suite 104, commit
generated artifacts 110, MailerLite secrets 134, **deploy 147, ALPR gate 170, ALPR heartbeat ping
181, send daily newsletter 195**, comment on the ops issue 216, notify Discord 239.

Steps after a failed step never run. So a 504 at 170 also **skips the heartbeat ping and the
newsletter send**. Today a later green run covered the email, but that is luck, not design: on
2026-10-11 the same class of failure left the social post with no brief body.

## 6. Constraints

- No bandaids. The `/surveillance/` page copy must never carry a staleness disclosure, and the page
  must keep serving a real camera list (the `ok=True` fallback exists for a reason: on 2026-09-22 a
  short outage rebuilt the site's top search page with zero cameras).
- The `stale` flag's only reader is CI.
- This repo builds and deploys from GitHub Actions. Source-only fixes ship with `[skip ci]` plus a
  manual `deploy.yml` run. Generated data (`incidents/`, `data/briefs/`, `email/`) is CI-owned, do
  not hand-edit it.
- Scope: `build/sources/alpr.py`, `build/common.py`, `scripts/check_alpr_fresh.py`,
  `.github/workflows/daily.yml`, `deploy.yml`, `grapevine.yml`, `guide.yml`, `sunday-read.yml`,
  and their tests. **Do not edit** `C:/Users/tscac/Projects/wall-dashboard`,
  `build/emailer.py`, or `tests/test_email_overnight_card.py`: another job is live in them.
- Environment: Windows box, git-bash. Project interpreter is
  `C:/Users/tscac/Projects/BakersfieldBrief.com/.venv/Scripts/python.exe`, tests with
  `.venv/Scripts/python.exe -m pytest`. Never `python -` with a heredoc here (exit 124).
- Reproduce my probes: `C:/Users/tscac/AppData/Local/hermes/cache/scratch/alpr_mirrors.py`,
  `alpr_query_probe.py`, `alpr_meta_probe.py`. Full run log: `gh run view 38264636545 --log-failed`.

## 7. What I want back

1. **Do not loosen the gate.** `AGENTS.md` documents it as the intended signal, and the owner wants
   a red run when the page is not today's. Make the daily fetch succeed instead. If, after your fix,
   a day still fails because upstream is genuinely down, say so plainly: that is upstream truth and
   the alert is correct. Your call is the fetch design, not the threshold.
2. The fetch design that removes the `out meta` dependency without losing honest "first mapped"
   dates, with the runner-reachability question answered first.
3. The step-order fix, so no upstream flake can skip the newsletter or the heartbeat.
4. A written plan before patches: files, changes, and what proves each one. Where a claim needs a
   live probe, name the host that must run it (runner or this box).
