# Kern County Feed Provider Audit (Broadcastify ctid/197)

Measured 2026-09-20 ~15:48 PDT by direct requests with the repo's premium
session cookie (`kern_overnight/.bcfy_cookie.json`, key `bcfyuser1`). Every
number below came from a command actually run (commands shown inline).
Scratch evidence: `%LOCALAPPDATA%\hermes\cache\scratch\bcfy\` (feed pages,
`audit_archives.json`, `samples\*.mp3`).

## 1. Feed inventory (county page https://www.broadcastify.com/listen/ctid/197)

| Feed | Exact name | What it carries | Coverage vs 14029 | Relation |
|---|---|---|---|---|
| 45166 | *Kern County Fire | Kern Co Fire, Bakersfield FD, local fire dispatches ("Provided by Remotely Located Critical Infrastructure") | Fire-only; no police/EMS | Subset (fire only) |
| 45474 | Bakersfield Fire / Kern County Fire / USFS | BFD dispatch + ops, KCF, USFS | Fire-only | Subset (fire only) |
| 47440 | Bakersfield Police / Kern County Sheriff | BPD dispatch + KCSO dispatch | Police-only, no fire/EMS | Subset (police only) |
| 14029 | Bakersfield Police, Fire and EMS | BPD, BFD, KCF, KCSO, EMS dispatch - our main feed | Baseline | Superset (best single source) |
| 46687 | CHP - Bakersfield Dispatch | CHP Bakersfield (3 and 4) | Different content (CHP not in 14029's core) | Different |
| 46383 | KCSO West Dispatch/Taft PD/CHP Brown | KCSO West area, Taft PD, CHP Brown | Partial overlap (KCSO West only) | Partial overlap |
| 40009 | Kern County Fire | Second Kern Co fire feed (county-wide fire) | Fire-only | Subset (fire only) |
| 36357 | KR6DK Repeater Network | Amateur radio linked repeater net (bilingual) | Different content, not public safety | Different |

## 2. Measured audio quality

One real archive block per feed was downloaded via
`play.php?id=<archive_id>` then probed:

```
ffprobe -v error -show_entries stream=codec_name,bit_rate,sample_rate,channels -of default=nw=1 <file>
```

| Feed | Sample file | codec | bitrate | sample rate | channels |
|---|---|---|---|---|---|
| 14029 | 14029-1789846140.mp3 | mp3 | 16000 | 22050 | 1 |
| 45166 | 45166-1789847065.mp3 | mp3 | 16000 | 16000 | 1 |
| 45474 | 45474-1789845792.mp3 | mp3 | 16000 | 22050 | 1 |
| 47440 | 47440-1789845793.mp3 | mp3 | 16000 | 22050 | 1 |
| 46687 | 46687-1789845492.mp3 | mp3 | 16000 | 22050 | 1 |
| 46383 | 46383-1789844376.mp3 | mp3 | 16000 | 22050 | 1 |
| 40009 | 40009-1789845618.mp3 | mp3 | 16000 | 22050 | 1 |
| 36357 | 36357-1789844366.mp3 | mp3 | 8000 | 8000 | 1 |

Conclusion: no feed offers higher quality than 14029. Six of eight are the
identical 16 kbps / 22050 Hz mono; 45166 is 16 kHz (slightly worse); 36357 is
8 kbps / 8 kHz amateur audio (much worse, irrelevant anyway).

## 3. Archive availability, retention, access control

`GET https://www.broadcastify.com/archives/api/archives.php?feedId=<id>&date=09%2F19%2F2026`
with the premium cookie returned **HTTP 200 for all 8 feeds** (46-49 blocks
each, first block ~00:03-00:27, last block ending ~00:10-00:25 next day).
`play.php` and the MP3 GET also returned 200 for all 8 (sample downloads
0.5-3.7 MB each). This premium account does not own any of these feeds, so
archive access is a premium-account privilege, not feed-ownership-gated.

Retention probes (blocks returned):

| Date probed | 14029 | 45166 | 36357 |
|---|---|---|---|
| 2026-08-01 | 48 | 48 | 49 |
| 2026-01-01 | 48 | 48 | 49 |
| 2025-09-20 | 17 | 17 | 18 |

Archives go back at least one year (2025-09-20 still has blocks, partial
coverage). Practical retention: >= 1 year.

## 4. Timeline reality check (why the 05:20 fetch misses the tail)

For date 2026-09-20 (queried 15:48 PDT same day), the 05:00-06:00 window
blocks already existed for every feed probed, with these measured rollovers:

- 14029: blocks 05:23-05:53, 05:53-06:23, 06:23-06:53 (and 06:52-07:22) present
- 45166: 05:08-05:38, 05:38-05:53, 06:08-06:38, 06:38-07:08 present
- 47440: 05:17-05:47, 05:47-06:17, 06:17-06:47 present

A block appears only after it closes. The last block covering 06:00 closes
between ~06:17 (47440) and ~06:53 (14029's 06:23-06:53 block). Measured
upper bound: at 15:48 everything through ~06:53 was downloadable, so the
available-to-close latency is under 9 hours; the conservative scheduling
rule is **fetch at/after ~06:55** to guarantee the entire 21:00-06:00
window. A 05:20 job can never see blocks that close at 05:53 or later.

## 5. Failover plan for missing 14029 blocks

No backup feed is equivalent to 14029; the county has no other combined
police+fire+EMS feed. Backup is therefore compositional:

- Police coverage gap -> 47440 (BPD + KCSO dispatch; exact same agencies,
  dispatch-only, no EMS talkgroups).
- Fire/EMS gap -> 45474 (BFD/KCF/USFS) or 40009 / 45166 (county fire;
  45166 is 16 kHz audio). Fire-only feeds cannot replace a police block
  and carry no EMS.
- 46687 (CHP) and 46383 (KCSO West / Taft / CHP Brown) are extra coverage,
  not substitutes; 36357 (amateur radio) is unusable.

Concrete code path in `kern_overnight/fetch.py`:

1. After the main loop, compute missing windows: for each expected
   `(start_ts, end_ts)` from `overnight_blocks()`, if no
   `14029-<startTs>.mp3` with `size > 50_000` exists, add it to `gaps`.
2. For each gap, call a new `backup_fetch(gap, audio_dir)` that iterates
   `BACKUP_FEEDS = {"police": [47440], "fire": [45474, 40009, 45166]}`
   in priority order, queries `archives.php?feedId=<fid>&date=<gap date>`,
   picks entries whose `[startTs, endTs)` overlaps the gap, downloads with
   the existing `_audio_url()` + `_download_archive()` helpers (cookie /
   `_login()` retry logic is feed-agnostic; play.php returned 200 for all
   feeds tested), and saves as `<fid>-<startTs>.mp3`.
3. Naming: keep Broadcastify's own `<feedId>-<startTs>.mp3` convention.
   The leading feed id already tags the source, so transcribers can derive
   `source = "14029"` (primary) vs `"47440"` / `"45474"` (backup) and the
   digest can attribute blocks correctly. Optionally emit
   `audio/<date>/manifest.json` mapping each expected primary block to
   `{filled_by: fid, path, overlap_seconds}`.
4. Dedup: fill a gap from ONE backup feed only (first feed in priority
   order that yields overlapping blocks wins), and never re-download
   overlapping windows across feeds. Where two feeds do overlap the same
   radio traffic (e.g. 45474 vs 40009 fire), the priority order above acts
   as the dedup rule; do not transcribe the same gap twice. Cross-feed
   time alignment: blocks are wall-clock aligned per feed but rollovers
   differ (14029 ~:23/:53, 47440 ~:17/:47, 45166 ~:08/:38), so clip
   transcripts to the missing window `[start_ts, end_ts)` before merging
   into the digest, and tag partial-overlap blocks with their true span.
5. Honest limits: a 47440 substitution yields police dispatch only; EMS
   traffic lost in a failed 14029 block is unrecoverable from any other
   county feed.

## 6. Terms of Service (actual lines)

Source: https://www.broadcastify.com/terms (last updated July 22, 2026;
Section 9 revised to cover programmatic/automated access, AI/ML, scraping,
bulk downloading).

- Section 8 (COMMERCIAL USE): "Any use of any of the materials on this site
  other than for private, personal, non-commercial viewing purposes is
  strictly prohibited unless a license is obtained from Broadcastify."
- Section 9: "A Broadcastify account, including a Premium subscription,
  grants a personal, individual right to listen to and view content through
  Broadcastify's own websites and applications. It does not grant any right
  to access, retrieve, capture, store, or use Broadcastify audio ... by
  programmatic, automated, or bulk means. Any such access requires a
  separate commercial license obtained from Broadcastify in advance."
- Section 9(a): requires a commercial license for "Any programmatic or
  automated access to Broadcastify feeds, live audio, recorded calls,
  archives, or metadata, including ... scripts, bots, ... and any
  scheduled, unattended, repeated, or automated downloading ... or polling."
- Section 9(c): requires a commercial license for "Any use of Broadcastify
  content for machine learning or artificial intelligence, including ...
  transcription, ... summarization ... or any other automated analysis."
- Section 9: "A use does not become permitted because it is limited in
  scale, unpaid, or characterized as personal, hobby, educational,
  academic, research, journalistic, non-commercial ... " and licenses are
  issued exclusively through the Broadcastify Developer Program at
  https://bcfy.io.

Reading: our nightly automated fetch + transcription pipeline is squarely
inside Section 9(a)/(c) as written; it is tolerated practice today, not a
licensed one. Republishing transcripts publicly is also restricted by
Section 8. Mitigation options: obtain a bcfy.io developer license, or keep
digests private/non-redistributive. Flag this to the site owner before
scaling anything up.

## 7. Blockers

- No feed is a superset or quality upgrade over 14029; failover is
  compositional (police from 47440, fire from 45474/40009/45166) and EMS
  gaps are unrecoverable.
- 05:20 fetch can never capture 05:53-06:23 blocks; the tail is missing by
  construction unless the job moves to ~06:55 or a second tail job runs
  then.
- ToS Section 9 explicitly forbids unlicensed automated archive download
  and AI transcription; our pipeline currently operates without that
  license.
