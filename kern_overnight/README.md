# The Kern Overnight — scanner-to-newsletter pipeline

Nightly: Broadcastify feed **14029** (Bakersfield Police, Fire and EMS) →
transcript → incidents → morning brief draft for human review.

## Run it

```bash
# Full pipeline for last night (default) or a specific date:
python -m kern_overnight.run                  # covers 21:00 → 06:00 last night
python -m kern_overnight.run 2026-08-07       # specific date

# Or stage by stage:
python -m kern_overnight.fetch   2026-08-07   # 1: audio blocks → audio/DATE/
python -m kern_overnight.transcribe 2026-08-07  # 2: → transcripts/DATE.jsonl
python -m kern_overnight.extract 2026-08-07   # 3: → incidents/DATE.json
python -m kern_overnight.write   2026-08-07   # 4: → briefs/DATE.md
```

Cron: `15 6 * * *` America/Los_Angeles (the Hermes cron job "Kern Overnight").

## Requirements (fail loudly if missing)

| Stage | Needs |
|---|---|
| fetch | `RR_USER` + `RR_PASS` in `.env` (RadioReference premium). Optional: `broadcastify-cli` |
| transcribe | `ffmpeg`, `torch` + `silero-vad`, `faster-whisper` (large-v3, CPU int8) |
| extract / write | `LLM_API_KEY` (LLM_MODEL / LLM_BASE_URL optional) |

## Broadcastify archive API (verified Aug 2026 — the CLI's endpoints are dead)

The published `broadcastify-cli` targets removed endpoints (`ajax.php`,
`downloadv2`). The live API, driven with the `bcfyuser1` session cookie from
`POST https://www.broadcastify.com/login/` (form: username, password,
action=auth, redirect):

- Listing: `GET https://www.broadcastify.com/archives/api/archives.php?feedId=14029&date=MM%2FDD%2FYYYY`
  → `{"archives":[{"id":"14029-<startTs>","startTs":...,"endTs":...}]}`
- Audio URL: `GET https://www.broadcastify.com/archives/api/play.php?id=14029-<startTs>`
  → `{"url":"https://archives.broadcastify.com/...mp3"}`
- Archive blocks are **not** 30-min aligned (start at :12/:42 offsets) —
  filter by epoch range, never by exact alignment.

## Privacy HARD RULEs (enforced in the extraction prompt AND reviewed by hand)

No names, plates, callback numbers, patient details, ambulance-to-hospital
traffic, exact addresses, or unit numbers. Locations generalized to block /
cross streets. Garbled audio is skipped, never guessed. Everything is
preliminary dispatch information.

## Attribution (appended in code, cannot be omitted)

Every brief ends with:
> Audio Provided by Broadcastify.

plus the preliminary-details disclaimer.

## Files

- `audio/DATE/`            MP3 blocks (unix-epoch filenames)
- `transcripts/DATE.jsonl` one JSON row per transmission
- `incidents/DATE.json`    append-only incident dataset (feeds future trends)
- `briefs/DATE.md`         the draft — **a human edits and approves before
  anything is published** (published copies go to `data/overnight_reports/`)
- `vocab.txt`              the operator's accuracy lever — edit freely

## Roadmap (not built, not precluded)

Engine A/B (Deepgram Nova behind the same interface), long-form single-
incident stories, SDRTrunk phase-2 local recordings, SQLite trend store.
