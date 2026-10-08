# BakersfieldBrief.com — overnight Kern County scanner pipeline

## Pipeline (kern_overnight)
`--phase1` early fetch+transcribe (cron 03:00) → `--phase2` tail transcribe (cron 05:20) → `--extract-only` → write brief → publish (cron 07:30, backstop 07:40). Full solo run: `.venv\Scripts\python.exe -m kern_overnight.run`.

- Cron jobs are **no_agent scripts** now (`ko_phase1_cron.py`, `ko_phase2_cron.py` in `~/AppData/Local/hermes/scripts`). They spawn the project venv detached and wait. Each writes a `.lock` next to itself — never run two phases at once.
- **Never re-run fetch/extraction when a transcript already exists** — use `--extract-only`. Re-fetching with a transcript on disk caused a ~60-minute hang.
- Nothing auto-publishes. Drafts are delivered for human review.

## STT
faster-whisper `large-v3` on this PC (`KO_WHISPER_MODEL`, default `Systran/faster-whisper-large-v3`). The vocab priming cap is 224 tokens, and Whisper silently cuts overflow from the FRONT, so the highest-value terms go LAST in `vocab.txt`. Street names are verified against `kern_overnight/streets.txt` (6,275 entries).

## ALPR (/surveillance/)
One page. The Overpass diff runs in CI (`weekly.yml`, Monday) with `--alpr-change`: it appends the change-log row, advances the node snapshot, commits the artifacts, deploys, and fails loudly if the row for the Pacific date did not land. The local `~/AppData/Local/hermes/scripts/alpr_weekly.sh` is retired (it needed the box awake, and Overpass 406s from this machine). Never add a second Monday writer: the date guard in `append_change_log` refuses the twin row.

Daily freshness: every `daily.yml` run ends with `scripts/check_alpr_fresh.py`, which fails the run and alerts ops Discord unless the camera list was fetched from Overpass on that run and is dated the Pacific date. The last-good-list fallback in `build/sources/alpr.py` stays (it keeps the page from showing zero cameras), but it returns `stale: True` for CI to read; `ok: True` there means "renderable", not "healthy". That flag never reaches a page, a card, an email or schema: the answer to stale data is a red run and an alert, never page copy. The daily run proves freshness only: it never writes the change log or `alpr_nodes.json`, so "newly mapped" keeps meaning "since last Monday". The land ownership join is manual (local box); the weekly run posts a reminder when it falls behind.

## Git (main carries data by design)
`main` carries source AND generated data. Two writers, disjoint paths:
- **CI owns** every path under `data/`, `email/` and `drafts/` EXCEPT the box-owned ones below. `scripts/ci_push.sh` stages by that exclusion, and aborts if a box-owned path reaches the index. It must be an exclusion list, not a fixed list of names: a whitelist silently stopped committing `data/fog_delays/log.json` and `data/last_guide.json` the day after it was written.
- **The box owns** `transcripts/`, `incidents/`, `data/overnight_reports/`, `data/geo_cache.json`, `data/incidents_geo.json`. Writers: `kern_overnight/transcribe.py` (transcripts), `ko_publish.py` (the nightly report and `incidents/<date>.json`), `kern_overnight/geo.py` (the geocode cache).

Local work commits SOURCE ONLY; never `git add -A`. The five content workflows share the `pages` concurrency group, so CI never races CI. Because the two writers' paths are disjoint, a plain `pull --rebase` should never conflict. If one does, it is an ownership violation: stop and fix the ownership, do not auto-resolve. Scoped recovery for a local rebase conflict on a CI-owned path: `git rebase --abort`, `git checkout origin/main -- <that CI path>`, re-stage, commit source only. Never bulk-checkout the box-owned paths: that reverts an unpushed overnight report.

## Things that are already correct — don't "fix" them
- Sender auth: SPF `include:_spf.mlsend.com` + DKIM `litesrv._domainkey` CNAME. Mail lands in the inbox.
- SEO: single-topic posts only.
- Competitor scanner sites are never covered or linked; point readers to our live map (`/map/`).