# BakersfieldBrief.com — overnight Kern County scanner pipeline

## Pipeline (kern_overnight)
`--phase1` early fetch+transcribe (cron 03:00) → `--phase2` tail transcribe (cron 05:20) → `--extract-only` → write brief → publish (cron 07:30, backstop 07:40). Full solo run: `.venv\Scripts\python.exe -m kern_overnight.run`.

- Cron jobs are **no_agent scripts** now (`ko_phase1_cron.py`, `ko_phase2_cron.py` in `~/AppData/Local/hermes/scripts`). They spawn the project venv detached and wait. Each writes a `.lock` next to itself — never run two phases at once.
- **Never re-run fetch/extraction when a transcript already exists** — use `--extract-only`. Re-fetching with a transcript on disk caused a ~60-minute hang.
- Nothing auto-publishes. Drafts are delivered for human review.

## STT
faster-whisper `large-v3` on this PC (`KO_WHISPER_MODEL`, default `Systran/faster-whisper-large-v3`). The vocab priming cap is 224 tokens, and Whisper silently cuts overflow from the FRONT, so the highest-value terms go LAST in `vocab.txt`. Street names are verified against `kern_overnight/streets.txt` (6,275 entries).

## ALPR (/surveillance/)
One page. The Overpass diff runs in CI now (`.github/workflows/alpr-weekly.yml`, Monday): it appends the change-log row, advances the node snapshot, commits those two artifacts, and deploys. The local `~/AppData/Local/hermes/scripts/alpr_weekly.sh` is retired (it needed the box awake and Overpass 406s from this machine).

## Git (main carries data by design)
CI and the local box BOTH commit generated artifacts (`data/`, `email/`, `drafts/`) to `main`. All five content workflows share the `pages` concurrency group, so CI runs never race each other. `scripts/ci_push.sh` is the only CI pusher; the box's `ko_publish.py` is the other writer.

Local work commits SOURCE ONLY. On a rebase conflict in the artifact paths, do not hand-resolve it: `git rebase --abort`, then `git checkout origin/main -- data email drafts`, then re-stage and commit your source changes. Never `git add -A`.

## Things that are already correct — don't "fix" them
- Sender auth: SPF `include:_spf.mlsend.com` + DKIM `litesrv._domainkey` CNAME. Mail lands in the inbox.
- SEO: single-topic posts only.
- Competitor scanner sites are never covered or linked; point readers to our live map (`/map/`).