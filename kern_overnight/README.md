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
| fetch | `broadcastify-cli` (preferred) OR `RR_USER` + `RR_PASS` (RadioReference premium) |
| transcribe | `ffmpeg`, `torch` + `silero-vad`, `faster-whisper` (large-v3, CPU int8) |
| extract / write | `LLM_API_KEY` (LLM_MODEL / LLM_BASE_URL optional) |

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
