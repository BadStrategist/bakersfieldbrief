# Broadcastify Calls Node 6225 — Build Design for the Kern Overnight Pipeline

Status: design doc. No code changed. Authored 2026-09-20.

## 1. What node 6225 is (verified)

- Broadcastify Calls node "Kern County / Bakersfield", Trunk Recorder (Conventional),
  county id 197 (`ctid197.html`, `/calls/node/6225`). Only ingest node for the county;
  first seen 2026-06-04.
- Four conventional frequencies captured (from `/calls/fids/6225` seen counts):
  - 153.785 — KRN Fire 1 Dispatch (Kern County Fire)
  - 154.070 — FIRE 1 Dispatch Bakersfield (Bakersfield Fire)
  - 154.800 — BPD2 Police Dispatch West
  - 155.310 — BPD1 Police Dispatch East (primary when combined)
- Per transmission, Calls delivers an individual call record with timestamp,
  source frequency, duration, and a display/description label.
- Per-frequency listening exists at `/calls/fid/<fid>`; per-node live list at
  `/calls/node/6225`. Node-level live listening was removed by Broadcastify.
- Saved raw pages for reference:
  `C:\Users\tscac\AppData\Local\hermes\cache\scratch\bcfy\` (`node.html`,
  `node_fids.html`, `node_calls.html`, `calls_coverage_law.html`).

### API surface — what is verified vs unverified

Verified (present in the saved live page's own JS, `node.html` / `live.js?v=231`):
the node page pulls data via XHR endpoints matching `apis/callDetails.php` and
`apis/groupDetails.php`, and the page's `callsTable` is populated from a JSON
array of calls. These are internal, undocumented endpoints; parameter shapes
were not captured in the saved pages.

UNVERIFIED (settle during the phase 0 spike with the premium cookie already
stored at `kern_overnight/.bcfy_cookie.json`; never print credentials):

1. The exact list endpoint + parameters for calls in a time range for node 6225
   or per-fid (candidates: `https://www.broadcastify.com/calls/api/groupDetails.php?gid=6225`,
   a `calls.php` with a node/fid + date filter, or the `node/<id>/data` XHR the
   live page uses). Settle with: `GET <endpoint> -b "bcfyuser1=<cookie>"` and
   inspect the JSON keys.
2. The per-call audio URL format (likely an m4a/mp3 behind an authed host).
3. Retention window: how many days/hours of call history the API returns for
   node 6225. This decides how much of the 21:00–06:00 backfill is possible
   the next morning. Settle by requesting yesterday's range and the oldest
   available call.
4. Whether the call "description" label is a fixed channel name, a radio
   alias, or a talkgroup-like tag — this decides how much agency attribution
   is free vs. derived from frequency.
5. Rate limits on these endpoints.

Everything below that depends on 1–3 is flagged and gated behind the spike.

## 2. Value ranking: what Calls enables that the mixed 30-min block cannot

Ranked by value per hour of build effort.

### Tier 1 (highest value, lowest cost)

**T1-a. Agency/channel attribution from metadata, no audio work at all.**
Each call record already carries source frequency + label. Mapping
`{153.785: KCFD dispatch, 154.070: BFD dispatch, 154.800: BPD west,
155.310: BPD east}` turns every transcript row into a named-agency row with
zero audio processing. Today the report guesses agency from transcript text
("engine", "medic", unit prefixes). Build cost: a JSON mapping table plus one
join. This alone is the single best hour of work in the project.

**T1-b. Second-accurate timestamps and true durations.**
Call records carry their own start epoch and duration. Rows stop being
"somewhere inside 14:30's 30-min block" and become `05:42:17 (+/-0s)`. Directly
improves report times and the map feed's incident dots. Build cost: use the
call's epoch instead of `block_epoch + segment offset`. Small.

**T1-c. Redundancy / two-source confirmation.**
Same overnight event appears in feed 14029 mixed blocks AND node 6225
per-call records. An incident asserted only when both sources surface it
(within a tolerance window, e.g. same 10-min bin and same generalized
location) raises precision and cuts ASR-hallucination false positives.
Implementable purely on transcript text matching; no new audio. Medium cost,
high report-quality payoff.

### Tier 2 (real value, moderate cost)

**T2-d. Per-call audio downloads → cheaper, cleaner ASR.**
Download only individual calls (speech-only audio; no 30 min of dead air),
preprocess per call, VAD + whisper per call. Cuts total audio volume to
roughly the speech fraction (scanner feed is ~85–90% silence per
`transcribe.py`), so wall-clock transcription should drop well below tonight's
~10 min/block, even at 4 channels. Also removes cross-channel crosstalk bleed
from the mixed feed, which the 250–3400 Hz band-pass cannot separate. ASR
accuracy gain expected but UNQUANTIFIED until the A/B spike (spike S2).

**T2-e. Per-incident source confidence scoring.**
Row-level confidence today is whisper `avg_logprob` only. With Calls, an
incident gets a composite score: both sources present > single source;
metadata duration matches transcript duration; per-channel (isolated) ASR
confidence is higher than the mixed-feed confidence for the same text.
Gates what reaches the report and the map. Build on top of T1-c's matcher.

**T2-f. Coverage-hole patch (05:00–06:00).**
Calls retention (unverified, item 3) may cover the 05:00–06:00 hour that the
archive path structurally cannot fetch at 05:20. If retention spans it, a
06:05 Calls-only backfill closes the hole without touching the cron lattice.
If retention is too short, this is cut.

### Tier 3 (defer unless T1/T2 are in)

- **Per-call clip archive for the map** (clicking a dot to hear the call):
  violates the privacy posture in spirit and invites abuse; see cuts.
- **Live polling during the night** instead of morning backfill: raises
  Broadcastify load, complicates idempotency, and the report is a morning
  product anyway. Deferred.
- **Playlists / status pages integration**: no pipeline value.

## 3. Privacy hard rules — features cut and why

The repo's hard rules: no names, no plates, no callback numbers, no patient
details, no exact addresses (generalize to block or cross-street), nothing
from ambulance-to-hospital traffic.

CUT (would violate these):

- **Publishing per-call audio clips** on the site or map. A clip is the raw
  transmission: it can contain a name, plate, callback number, patient detail,
  or tactical address that the LLM report layer strips today. Serving clips
  bypasses every sanitizer. The pipeline may keep clips transiently for ASR
  (they are deleted after transcription), but they must never reach
  `docs/`, the site, or `data/incidents_geo.json`.
- **Publishing channel/frequency per incident on the public site.** Stating
  "this call was on BPD East dispatch 155.310 at 05:42" lets a reader
  reconstruct which dispatcher/sector handled an incident and, with the
  timestamp, approximate tactical position of units. Attribution is for
  internal confidence scoring and coarse agency naming in prose ("Bakersfield
  police handled..."), never the raw frequency or channel label on the public
  page. The public report keeps the existing generalized phrasing; the
  source-frequency field stays in the private JSONL only.
- **Sub-second tactical timing on the public map.** Second-accurate times are
  used internally; the map/report keeps the current minute-level granularity.
  A reader combining second-level times with a live scanner could track a unit.
- **Enriching the map with unit identifiers** from call labels. Even if the
  Calls display label contains unit aliases, they never propagate to output.

## 4. Integration architecture

### Where the new source sits

```
kern_overnight/calls_fetch.py   NEW  stage 1b: Calls metadata + audio download
kern_overnight/transcribe.py    EDIT accepts per-call audio dirs (calls source tag)
kern_overnight/digest.py        EDIT merges + dedups two sources
kern_overnight/confirm.py       NEW  two-source matcher + incident confidence
kern_overnight/run.py           EDIT phase 1/2 call the new fetch, degrade gracefully
```

`fetch.py` is untouched. `calls_fetch.py` is a sibling stage, not a replacement.

### Data shapes

New JSONL per night: `transcripts/calls/<date>.jsonl` — one row per call, so
the existing reader (`digest.py`) only learns one new field. Row shape,
superset of today's:

```json
{"time_local": "05:42:17", "epoch": 1758415337, "duration": 8.4,
 "text": "...", "confidence": -0.21, "engine": "faster-whisper:...",
 "source_file": "calls/6225/fid_193106_call_123456789.m4a",
 "source": "calls", "freq": "155.310", "agency": "BPD East dispatch",
 "call_id": "123456789"}
```

The existing `transcripts/<date>.jsonl` gains `"source": "archive14029"` on
its rows (default backfilled by the reader when absent, so old files stay
valid). `source` is the single tag that prevents double counting: digest.py
groups by source and confirm.py matches across sources.

Incident confidence, written to the private side only
(`data/incidents_calls_conf.json`, gitignored), keyed by incident id in
`incidents/<date>.json`:

```json
{"inc_id": "2026-09-20-0542-bpd-east",
 "sources": ["archive14029", "calls"],
 "calls_ids": ["123456789"], "time_spread_s": 0,
 "conf_score": 0.92,
 "conf_reason": "both sources, 2 rows, isolated-channel ASR"}
```

The public `data/incidents_geo.json` schema does not change. It gains nothing
per the privacy cuts; confirmed incidents simply stop including
single-source low-confidence noise.

### calls_fetch.py design

- `fetch_calls(date, tz) -> list[dict]`: query the Calls API for node 6225's
  window 21:00 prev → 06:00, filter to the four fids, save metadata to
  `audio/<date>/calls_meta.json`, download call audio to
  `audio/<date>/calls/` named `<fid>_<call_id>.<ext>`. Same cookie-reuse +
  relogin-on-403 pattern as `fetch.py` (`_load_cookie`/`_login` are reusable
  via import; factor them into `kern_overnight/bcfy_auth.py` in phase 1 so
  both fetchers share one login path without duplicating credentials logic).
- Idempotency: `audio/<date>/calls_meta.json` keyed by `call_id`; re-runs skip
  existing call_ids and existing audio files (mirror of
  `_download_archive`'s size check). Transcript rows dedupe on
  `source_file`+`call_id`, mirroring `transcribe.py`'s `done` set on
  `source_file`.
- Graceful degradation: `run.py` calls `fetch_calls` in a try/except; on any
  failure it prints a `[ko-calls]` line, emits an empty
  `transcripts/calls/<date>.jsonl`, and the pipeline proceeds exactly as
  today on archive-only. `confirm.py` treats a missing/empty calls file as
  "no confirmation available" and passes archive incidents through with
  `conf_reason: "single-source (calls unavailable)"` rather than dropping
  them. The system never gets worse because Calls broke.

### transcribe.py changes (minimal)

`transcribe()` already globs `audio_dir/*.mp3` and keys dedupe on
`source_file`. Phase 2 adds a sibling entry point
`transcribe_calls(calls_dir, out_jsonl, ...)` reusing `_preprocess`, `_vad_*`,
`_merge_segments`, `_transcribe_whisper` unchanged — per-call files are just
short blocks with known epoch. The `source`/`freq`/`agency` fields are added
from `calls_meta.json` at write time. Same model, same workers=2, same
MIN_CONFIDENCE gate, so no double-count risk and no accuracy regression path.

### digest.py changes

Read both JSONL files, keep the existing filters, and tag each printed row
with its source. When `confirm.py` runs first, digest annotates rows with
`confirmed: true/false`. The LLM report prompt gains one line: confirmed
incidents may be stated with normal confidence; single-source-only incidents
are hedged or omitted per existing editorial rules.

## 5. Cost and practicality

### Storage per night (quantified)

Current: 16 blocks × ~3.65 MB ≈ 58 MB/night archive MP3, deleted on
retention policy. Calls audio: assume per-call MP3s average 10 s at ~16 kbps
≈ 20 KB/call. Typical dispatch traffic on 4 dispatch channels overnight is
roughly 400–800 calls/night (UNVERIFIED — spike S1 measures the real count;
node_fids seen counts show the node is active but overnight call volume on
dispatch-only channels is plausibly much lower than daytime). Estimate:
600 calls × 20 KB ≈ 12 MB/night, less than the archive path. Even at 2000
calls it is ~40 MB. Keep the same retention as `audio/<date>` (delete after
the report ships). Metadata JSON is negligible. Clips never leave disk and
are deleted after transcription — enforced by the same temporary-dir pattern
`transcribe.py` already uses, plus an explicit post-run delete of
`audio/<date>/calls/`.

### CPU for transcription

Current: large-v3-turbo int8, cpu_threads=8, 2 parallel workers,
~9.9 min per 30-min block × 16 blocks ≈ 160 min wall-clock per night
(memory-bound at 2 workers on the 16 GB rig, per transcribe.py notes).
Calls path: total audio drops from 480 min to the speech fraction. If
overnight speech is 10–15% of channel time, that is ~50–70 min of audio;
whisper fixed per-call decode overhead is offset by no dead-air VAD passes
and no block-level model warmup. Expected wall-clock: well under half of
tonight's, with the caveat that per-call fixed overhead (~1 s decode) is paid
600+ times; if that shows up, batch calls per fid into synthetic 5-min
stitched WAVs with a segment-offset table (a phase 3 optimization, only if
needed). Net: Calls transcription can run as a *replacement* or alongside;
recommend alongside (redundancy) with the storage note above.

### Cron schedule changes

Minimal. Phase 1 backfill design: extend the existing 05:20 tail job (or add
a 06:05 job) to also run `calls_fetch` for the 05:00–06:00 window if
retention allows; the 07:00–07:45 watchdogs already exist and would cover a
hung calls fetch via the same completion-check mechanism. No new job cadence
beyond one added invocation inside existing jobs. No polling during the
night (deferred, §2).

## 6. Phased build plan

### Phase 0 — verification spike (< 1 hour, throwaway script, no repo code)

Goal: prove Calls audio is downloadable and ASR-usable, and nail the UNVERIFIED
API items 1–4.

S1: with the stored cookie, hit the node 6225 list endpoint variants and
capture: JSON key names, per-call fields (epoch, duration, freq, fid,
call_id, description), retention depth (oldest call available), and one
downloaded call file. Then: run that one call through the existing
`_preprocess` + whisper and eyeball the text vs the mixed-feed rows for the
same minute.

Acceptance: (a) ≥1 call JSON with all fields listed; (b) audio plays /
ffprobe reports sane 8–16 kHz mono; (c) whisper output contains recognizable
dispatch phrasing; (d) retention depth recorded (hours or days).

S2 (30 min, same night): if S1 passes, pull one 30-min window of Calls audio
and the matching archive block, transcribe both, and compare street MATCH
rate (streetcheck gazetteer) and row counts. This is the A/B that decides
phase 2 vs stopping at metadata-only (T1).

### Phase 1 — metadata-only integration (T1-a, T1-b)

Files: new `kern_overnight/calls_fetch.py`, new `kern_overnight/bcfy_auth.py`
(factored from fetch.py's login), edits to `digest.py` and `run.py`.

Acceptance tests:
- `pytest tests/test_calls_fetch.py` with a recorded fixture: idempotent
  second run downloads nothing new; 403 triggers one relogin; API failure
  yields empty JSONL and run.py continues archive-only.
- One real night: every `transcripts/calls/<date>.jsonl` row carries a valid
  `agency` for one of the four fids; report prompt receives agency-tagged
  rows; public report wording unchanged from today's rules.

### Phase 2 — per-call ASR + two-source confirmation (T2-d, T1-c, T2-e)

Files: `transcribe.py` gets `transcribe_calls()`; new `kern_overnight/confirm.py`;
digest.py merge; `data/incidents_calls_conf.json` gitignored.

Acceptance tests:
- S2's A/B must show Calls-only ASR street MATCH ≥ archive baseline
  (48.6% floor from the Aug-2026 A/B) before this phase ships.
- A synthetic double-annotation test (same incident seeded in both sources
  with ±2 min) produces one confirmed incident; a single-source incident
  gets conf_reason "single-source" and is not dropped when Calls is the
  absent source.
- Public output diff vs. previous night: no new fields, no names/plates/
  addresses/frequencies — an automated grep gate on the report for the
  forbidden patterns.

### Phase 3 — coverage-hole patch + tuning (T2-f)

Only if retention (spike item 3) covers 05:00–06:00.

Files: `run.py` phase 2 gains a calls-only 05:00–06:00 backfill; cron edit
inside the existing 05:20/06:45 jobs.

Acceptance: a night where the archive tail job fails still yields 05:00–06:00
rows from Calls alone; watchdog stays green.

## 7. Decision table

| Item | Decision | Reason | Risk |
|---|---|---|---|
| T1-a agency attribution from call metadata | BUILD (phase 1) | free accuracy, zero audio work | API shape unverified → phase 0 |
| T1-b second-accurate timestamps | BUILD (phase 1) | fixes block-level guessing cheaply | public output stays minute-level (privacy cut) |
| T1-c two-source confirmation | BUILD (phase 2) | precision up, false positives down | matcher false-negatives → must not drop archive incidents (graceful path specced) |
| T2-d per-call ASR | BUILD (phase 2) gated on S2 A/B | less audio, no crosstalk, likely faster | per-call overhead; storage small |
| T2-e incident confidence score | BUILD (phase 2) | gates report + map quality | score tuning is editorial, needs a week of nights |
| T2-f 05:00–06:00 hole patch | DEFER to phase 3 | depends entirely on unverified retention | none if absent — archive behavior unchanged |
| Per-call clips on site/map | REJECT | clips bypass every sanitizer; privacy hard fail | — |
| Publishing frequency/channel per incident | REJECT | reveals sector/tactical position; hard fail | — |
| Sub-second public timing | REJECT | enables live unit tracking; hard fail | — |
| Unit identifiers from labels | REJECT | identifies units/people; hard fail | — |
| Live polling during the night | DEFER | report is a morning product; load + idempotency cost | revisit only if a live product is wanted |
| Playlists/status integration | REJECT | no pipeline value | — |
