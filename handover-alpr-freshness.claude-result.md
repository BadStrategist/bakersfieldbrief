# Claude result for handover-alpr-freshness.md

- ran: 2026-10-12 11:38 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

# ALPR freshness: findings and plan (no patches made yet)

Your reading is wrong in two places, and both change the fix. The root cause is Overpass admission control, not `out meta`, and the step order in `daily.yml` is not a defect.

## 1. Runner reachability (answered first)

`api.openstreetmap.org` is reachable from a GitHub runner. Run 38293808208 (throwaway branch `probe/alpr-fetch`, since deleted; no secrets, no deploy, nothing on main) at 18:52 UTC:

| Call from the runner | Result |
|---|---|
| Bulk `nodes.json?nodes=<270 ids>` | 200, 0.4 s, 270 of 270 with a timestamp, 0 deleted |
| `node/{id}/1.json`, three nodes | 200, 0.3 s each, creation dates returned |
| Versions across the 270 | v1: 229, v2: 37, v3: 4, so 41 above version 1 |

## 2. The real cause: the query declares no budget

The 504 body, identical on the box and the runner, is:

```
Dispatcher_Client::request_read_and_idx::timeout. The server is probably too busy to handle your request.
```

That is Overpass refusing to admit the request, not a metadata stage dying. The shipped query declares no `[timeout:]` or `[maxsize:]`, so it asks for the defaults (180 s, 512 MB) and is turned away whenever the server is loaded.

Same query filters, alternated in the same minutes, 6 s apart:

| Query | Box | Runner |
|---|---|---|
| Shipped (default budget, `out meta;`) | 3 of 16 | 1 of 6 |
| Default budget, `out;` | 6 of 10 | not run |
| `[timeout:25][maxsize:32M]`, `out meta;` | 2 of 2 (3 more hit 429) | not run |
| `[timeout:25][maxsize:32M]`, `out;` on overpass-api.de | 11 of 11 | 6 of 6 |
| Same, on `lambert.openstreetmap.de` | 5 of 6 (one 429) | 6 of 6 |
| Same, on `gall.openstreetmap.de` | 6 of 6 | 6 of 6 |

- **`out;` alone is not the fix.** At the default budget it still failed 4 times in 10 from this box. Your probe caught it on a good minute.
- **The declared budget is the main lever.** Dropping `out meta` helps as well, so the plan does both.
- **The 429s are per-IP rate limiting**, largely caused by my own probe's rejected requests holding slots. The existing 20 s and 40 s retry waits cover that.
- **Thin spot:** small budget with `out meta` has only two clean samples, and the 2x2 was not repeated on the runner.

## 3. Fetch design

1. **Query:** `[out:json][timeout:25][maxsize:33554432];` plus the same filters, ending `out;`. The reply is about 100 KB, so 32 MB is ample headroom.
2. **Endpoints:** `overpass-api.de` with the existing three tries, then one try each on `lambert` and `gall`. Those are the two backends its own status page announces, and unlike the mirrors they measured working from both hosts.
3. **First-mapped dates:** the cache `data/snapshots/alpr_created.json` already holds all 270, so a normal build makes zero OSM API calls. Only ids missing from the cache are looked up:
   - one bulk `nodes.json` call, chunked at 300 ids;
   - version 1: its timestamp is the creation date;
   - above version 1: `node/{id}/1.json`, capped at the existing `MAX_LOOKUPS = 60`.
4. **Cap:** a cold cache today needs 41 version-1 calls, under the cap. Past 60, the rest resolve on the next build.
5. **Re-tagged cameras:** a node above version 1 never takes its edit date. If its lookup fails it gets the change-log week or stays blank and is retried, as now.
6. **`edited` field:** drop it. Nothing in `build/`, `scripts/` or the page code reads it, and keeping it would mean an OSM API call on every build for an unused value.
7. **Unchanged:** the remark guard, the 60% truncation guard, the last-good fallback, `stale`, and the gate.

If both backends refuse even a 25 s, 32 MB query, the run goes red; that is upstream truth and the alert is correct.

## 4. Step order: no change

The newsletter step carries `if: !cancelled() && hour >= 8`, so it runs after a failed gate.

| Run | Pacific time | Gate | Newsletter step |
|---|---|---|---|
| 38165417200 | 11:49, Oct 11 | failed | ran, "already sent … skipping" |
| 38161914740 | 10:59, Oct 11 | failed | ran, succeeded |
| 38264636545 | 07:40, Oct 12 | failed | skipped by the hour gate |
| 38237530689 | 03:37, Oct 12 | failed | skipped by the hour gate |

The heartbeat skip is by design: it pings only on a proven-fresh fetch. I did not trace the 2026-10-11 social post with no brief body; nothing in `daily.yml` step order explains it, and social posting runs on the box.

`gh secret list` shows neither `DISCORD_WEBHOOK_URL` nor `UP_ALPR_PING_URL` is set. Discord alerts therefore cannot send, and the heartbeat pings nothing even on green runs. The ops issue comment did succeed on the red runs. Setting those two secrets is yours.

## 5. Plan

| File | Change | What proves it |
|---|---|---|
| `build/sources/alpr.py` | New query, endpoint list, cache-first `_first_mapped`, drop `edited`, rewrite the comment at lines 19-25 with today's measurements | Box: pytest. Runner: `deploy.yml` run prints `stale=False` |
| `scripts/backfill_alpr_history.py` | Give it its own `out meta` query, since it imports `alpr.QUERY` and needs timestamps (outside your scope list, one line) | Box: import check |
| `tests/test_alpr_freshness.py` | Fake fetch answers Overpass, bulk and version-1 URLs. New cases: declared budget in the query, backend failover, full cache means no OSM call, bulk failure leaves the date blank | Box: pytest |
| `tests/test_pipeline_fixes.py` | Rewrite `test_first_mapped_ignores_later_edits` for the bulk-then-version-1 path | Box: pytest |
| `tests/test_alpr_freshness.py` (wiring) | Pin that the send step keeps `!cancelled()` and never references `alpr_fresh` | Box: pytest |
| `daily.yml`, `deploy.yml`, `grapevine.yml`, `guide.yml`, `sunday-read.yml`, `build/common.py`, `scripts/check_alpr_fresh.py` | None | n/a |

Ship: commit source only with `[skip ci]`, push, `gh workflow run deploy.yml`. Done means that run is green at the ALPR step, then 24 hours of scheduled runs with no ALPR red.

## Decision for you

When a newly mapped camera's date lookup fails, the list is still today's but that camera is undated and missing from "new this week" until the next build. I recommend a `::warning` annotation from the gate script, not a red run, since the page's list is fresh. Failing the run instead is the stricter option, but it would serve the last good list without the new camera. Say which, and say go, and I'll patch.

Left behind: three probe scripts in `hermes/cache/scratch/` (`alpr_split_probe.py`, `alpr_504_probe.py`, `alpr_design_probe.py`) and the probe run in Actions history.

--- exit: 0 ---
