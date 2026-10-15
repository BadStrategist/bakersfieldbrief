# Claude result for handover-alpr-freshness-go.md

- ran: 2026-10-12 12:02 PDT
- workdir: /c/Users/tscac/Projects/BakersfieldBrief.com

Patched with Option A and not pushed. The full suite passes on the box (625 tests, exit 0), and one live call of the new fetch from this box returned 270 nodes in 2.9 s from `overpass-api.de`.

## Design call: Option A

Your samples settle it. With the budget declared, `out meta;` is 6 of 6 across your run and mine, with no dispatcher 504. The extra metadata costs about 34 KB (133 KB against 100 KB), which is nothing against a 32 MB cap. B would add a second data source, a chunking rule and cache-miss handling to fix a failure that isn't there.

So `out meta;`, the first-mapped logic, the cache and the `edited` field are all unchanged. `scripts/backfill_alpr_history.py` needs no edit either, since it still gets timestamps from `alpr.QUERY`.

Revisit B if the budgeted `out meta;` query starts failing where a budgeted `out;` passes in the same minutes: a dispatcher 504 or a timeout remark, not a 429. That would show metadata costing admission, which today's samples do not.

## What changed

| File | Change |
|---|---|
| `build/sources/alpr.py` | Query declares `[timeout:25][maxsize:33554432]`. The fetch tries `overpass-api.de` with the existing three tries, then `lambert` and `gall` once each. A timeout remark also fails over, and the error names every server that refused. The "no working mirror" comment is rewritten with today's measurements. |
| `build/sources/alpr.py` | On `--alpr-change`, a new id with no first-mapped date raises before the row is written. |
| `scripts/check_alpr_fresh.py` | Prints a `::warning` naming any camera with no first-mapped date, and still exits 0 with no alert file. |
| `.github/workflows/weekly.yml` | The verify step's stale error now prints the source's own reason. No other workflow is touched. |
| `tests/test_alpr_freshness.py` | 11 new tests: budget in the query, failover order, remark failover, the undated cases on both run types, the gate warning, and the send step keeping `!cancelled()` with no `alpr_fresh` reference. |
| `AGENTS.md` | One sentence on the budget, the fetch order and the undated rule. |

## Undated cameras

Daily is a warning and weekly is red, as you asked. Three things you should know about how the weekly case works:

- **The reason is slightly different from the one you gave.** The change-log row's count is a snapshot diff and does not read dates, so the row itself would not be wrong. The harm is that once the row lands, `_first_mapped` lets the row's own date stand in for the missing one. The camera would then count as "new this week" on a date nobody looked up. Red is still the right call.
- **The red run serves the last good list, not Monday's fresh one.** The raise takes the existing fallback path: no row, the snapshot stays put, and the verify step fails on `stale`. The date guard still allows a re-run, which logs the camera once it can be dated.
- **Only that week's new ids trigger it.** An older camera that is still undated stays a daily warning and does not block the Monday row.

All 270 cameras are dated today, so the warning will not fire on current data.

## For your ship

- Source only: the five modified files above; the six `handover-*.md` files are untracked and not mine to commit.
- The `deploy.yml` run exercises the new query and the gate, but not the weekly path. That first runs for real next Monday, 2026-10-19.
- `DISCORD_WEBHOOK_URL` and `UP_ALPR_PING_URL` were both unset when I last looked, so a red run reaches only the ops issue until they are set.

--- exit: 0 ---
