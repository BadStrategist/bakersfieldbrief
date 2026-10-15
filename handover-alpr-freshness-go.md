# ALPR freshness: go, with my independent check of your two corrections

Owner's instruction: fix it. You are the orchestrator, so patch it. Below is what I verified
myself before saying go, plus one design call I want you to make on the evidence, not on taste.

## Your two corrections: I checked both, and you were right

**1. The declared budget is the lever, not `out meta`.** I ran the shipped query against the
budgeted one, alternating, same instance, this box, 4 rounds:

```
  round  shipped             budgeted [timeout:25][maxsize:32M] out;   budgeted + out meta;
    1    504 Dispatcher_...  200 99702 bytes                            200 133504 bytes
    2    504 Dispatcher_...  200 99702 bytes                            200 133504 bytes
    3    429 rate_limited    429 rate_limited                           200 133504 bytes
    4    504 Dispatcher_...  200 99702 bytes                            200 133504 bytes
  tally  0 ok / 4           3 ok / 1 (429, my own IP)                  4 ok / 0
```

The 504 body is the dispatcher text you quoted:
`Dispatcher_Client::request_read_and_idx::timeout. The server is probably too busy to handle your request.`
The third failure is `rate_limited. Please check /api/status for the quota of your IP address`, which
is my own probe traffic, not the query.

**2. Step order is not a defect.** Verified in `daily.yml`: the newsletter step is
`if: ${{ !cancelled() && fromJSON(steps.gate.outputs.hour) >= 8 }}` and never references
`alpr_fresh`, so a failed gate does not skip it. The heartbeat step is
`if: ${{ !cancelled() && steps.alpr_fresh.outcome == 'success' }}`, which is deliberate. My earlier
claim was wrong and I have corrected it with the owner.

Also verified: `main` is clean at `2ff3b4c3`, your throwaway branch is gone from origin, and nothing
of yours landed on main. `data/snapshots/alpr_created.json` holds 270 dated ids, `OSM_V1` and
`MAX_LOOKUPS = 60` are where you said. `edited` is written at `build/sources/alpr.py:62` and read
only by a test fixture, so dropping it is safe.

## Design call I want argued, not assumed

My samples do **not** support dropping `out meta`. With the budget declared, `out meta;` returned
200 four times out of four and with the full 133 KB payload, while the no-meta variant returned one
rate-limit failure. Admission control is what was failing, and once admitted, meta completed.

So: prefer the **smallest change that fixes the cause**.

- Option A: declare `[timeout:25][maxsize:33554432]`, keep `out meta;`, add your proven endpoint
  failover (`overpass-api.de`, then `lambert`, then `gall`). One query line plus the endpoint list.
  The first-mapped logic, the cache and the `edited` field keep working as they do today.
- Option B: your fuller design, meta dropped, cache-first plus the bulk OSM API and version-1 calls.

If you pick B, justify it against A with evidence (payload, latency, failure modes), because B adds a
second data source, a chunking rule and cache-miss handling. If you pick A, say what would make us
revisit B. Either way, the endpoint failover stays: that part you proved from both hosts.

## The undated-camera decision

`::warning` from the gate, not a red run, in a **daily** run: the camera list is the day's, and the
only gap is one camera's date. Take that.

But add one red case: on the **weekly** `--alpr-change` run the dated list is the change log's own
input, so if the newly mapped nodes cannot be dated, the page would print a wrong "newly mapped this
week" number. That must fail the run rather than publish a number we cannot stand behind. Red when a
newly mapped node's date cannot be resolved after the lookups are tried, warning in the daily runs.
If you think a bare warning is right even there, say why the number is still trustworthy.

## Then

Patch it, run the tests on the box, and hand back. I ship: source only, `[skip ci]`, push,
`gh workflow run deploy.yml`, then I verify that run is green at the ALPR step and watch the next
scheduled runs. Do not push, and do not touch `build/emailer.py`, `tests/test_email_overnight_card.py`
or `C:/Users/tscac/Projects/wall-dashboard`; a live job is in those.

Reproduce my check: `C:/Users/tscac/AppData/Local/hermes/cache/scratch/alpr_budget_probe.py`.
