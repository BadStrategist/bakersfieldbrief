# Handover: CrimeRadar emulator as a second source for Kern Overnight

Author: Hermes Agent. Date: 2026-10-04. Repo: `C:\Users\tscac\Projects\BakersfieldBrief.com`

Purpose of this document: a reviewer can audit every claim here against a command and an
observed result. Claims are split into **confirmed**, **built but unconfirmed**, and **known
broken**. Nothing in this file should be taken as evidence of a full end-to-end run, because
there has never been one.

---

## 1. What this is

`com.newsbreak.crimeradar` runs in a local Android emulator (AVD `CrimeRadar`). It aggregates
Bakersfield Police/Fire/EMS dispatch, shows each incident as a card with a location, and caches
the scanner audio clip for high-severity items as raw MP3 on world-readable external storage.

The goal: use it as a **first-class second source** for the `/overnight/` report and the morning
reels. Not a fallback. Specifically:

1. Verify incidents our own transcription missed.
2. Add the app's missed incidents to `incidents/<date>.json` so they reach the published report.
3. Feed the app's own dispatch clips into the morning reel.

## 2. Architecture: two bridges

### 2.1 Report bridge (this is the non-obvious part)

The 07:30 publish job runs `kern_overnight/digest.py`, which **rewrites** `incidents/<date>.json`
from the transcript. Anything written to that file earlier is destroyed. So the emulator rows are
staged first and merged after the digest:

```
07:15  crimeradar_emit.sh
         -> crimeradar_monitor.py --emit <date>
         -> sweeps the app's History, keeps in-window rows our incidents never matched
         -> writes work/crimeradar/emulator_incidents_<date>.json   (staging, whole window)

07:30  Kern Overnight publish (LLM job c25ccbac11ee)
         step 2   digest.py        -> REWRITES incidents/<date>.json
         step 2b  merge_crimeradar.py <date>   -> appends the staged rows
         step 4   writes the report markdown from incidents/<date>.json
```

The staging file always carries the **whole window**, not just what was new, so the merge is
idempotent and a second run cannot empty it.

`--dry` writes the staging file but never touches `incidents/`.

### 2.2 Reel bridge

`scripts/brief_reel/make_dispatch_audio.py` now prefers the app's own clip for a story:
match by clock time within 25 minutes, then by word overlap between the clip title and the
headline. One clip per story, never reused. **Strictly additive**: with no manifest present the
reel behaves exactly as before.

## 3. CONFIRMED working (command + observed result)

| Item | Evidence |
|---|---|
| Monitor compiles | `.venv/Scripts/python.exe -m py_compile scripts/crimeradar_monitor.py` -> exit 0 |
| Feed poll, live | `crimeradar_night.sh` -> exit 0; 4 cards parsed, tiers assigned |
| Clip capture, live | 17.04 s CRITICAL pepper-spray clip, duration matched the player's `-00:17` |
| Audio is real | `ffmpeg volumedetect` on captured clips: -23.8 / -35.9 dB |
| History sweep | 121 rows on first sweep; header later read 184 incidents |
| `--verify` window filter | 46 rows in window / 72 out; found the 05:00 Marriott fight our log missed |
| `--reel` export | 3 clips + manifest, CRITICAL first, partials excluded |
| Overlay detector | `work/crimeradar/test_overlays.py` -> 6/6, incl. the real "History" control not misread as an overlay |
| **Canary (new)** | forced 0 cards -> `poll rc: 4` + explicit alarm; healthy feed -> exit 0, no false alarm |
| **`--emit` dry-run** | 10-15 rows staged for 2026-10-03; `incidents/2026-10-03.json` md5 **unchanged** |
| **Merge idempotency** | 3 consecutive runs -> 1 staged, 1 added then 0 then 0; file stayed at 1 row |
| **Merge never crashes the publish** | malformed staging -> rc 0; malformed incidents file -> rc 0; missing staging -> rc 0 |
| **Area recovery** | `pain at Bank St` -> `Bank St`; `Burger King on White Lane` -> `White Ln`; streetless titles -> `""` |
| **Reel clip matcher** | Oakley fire story -> the CRITICAL Oakley clip; missing-juvenile story -> its own clip; a 21:30 story -> **no match** (correct); reuse guard held |
| Emulator self-heal | killed the emulator, preflight restarted the AVD and re-foregrounded the app in 14.5 s |
| Wrappers | `bash -n` OK on emit / morning / night / preflight |
| Cron retime | 9 jobs moved; `next_run_at` read back from the scheduler for each |

## 4. BUILT BUT UNCONFIRMED (a reviewer should treat these as unproven)

1. **The full chain has never run end to end.** emit -> digest -> merge -> write -> publish has
   not executed as one piece even once. Every piece is individually verified; the composition is not.
2. **No cron job has ever fired.** Both emulator jobs were created during this work. First real
   run is the night of 2026-10-04.
3. **Overlay dismissal has never met a live ad.** The detector passes 6/6 offline and is wired at
   four call sites, but no real interstitial appeared during a poll to test against.
4. **The reel bridge has never produced a reel.** It is code-verified against the real manifest
   only. The first actual reel is the 07:50 run.
5. **Area yield is unmeasured over a real night.** On an 8-title sample, 2 recovered.
6. **No emulator-only build exists.** Deliberately not built (user decision).

## 5. Bugs found and fixed during this work

Found in the app/emulator integration:
- Wrong AVD name: `CrimeRadar5554` is only the window title; the real AVD is `CrimeRadar`. The
  wrong name made the emulator refuse to start and burned the full preflight wait.
- A feed card clipped by the bottom nav produced a junk title `"1"`. Fixed with a word-required filter.
- `goto_history()` failed because the History control only renders after the Replay screen is
  scrolled. Rewrote the navigation.
- The play button moves with title length. Replaced fixed x/y taps with resource-id
  `transcript_play_button_container`.
- No retry in the device check: a concurrent kill produced exit 2 "device not online". Added a
  6 x 10 s retry, verified to wait 60 s then exit 2.

Bugs **I introduced and caught myself**:
- **Merge fingerprint mismatch.** `have` was computed with the area included while staged rows were
  fingerprinted without it, so a populated area could re-add the same incident forever. Fixed:
  identity is time + summary, area deliberately excluded. Verified by a short-summary case
  (`"Fire at Bank St."` with area `"Bank St"`) across 3 runs.
- **Silent-break gap.** The poll treated zero parsed cards as a normal quiet night, so a Play Store
  update would have produced a silent short report with exit 0 forever. Added a canary: retry once,
  then exit 4 with an alarm.

## 6. Known limitations (honest)

- **Same upstream.** The app credits "Bakersfield Police, Fire and EMS" = Broadcastify feed 14029,
  the feed our own pipeline already pulls. This is a second **path**, not an independent source.
  If Broadcastify goes down, both die together.
- **Aggregation lag.** The History header read `184 incidents · Updated 47 min ago`. At the 07:15
  emit the app may only hold data to ~06:28, so the report's real coverage ends nearer 06:30 than
  07:00. This varies; it needs measuring for a few nights before any cutoff is trusted.
- **Thinner data.** A History row carries only a time and a one-line headline. `type` is inferred
  from the wording (many land as generic "Incident"), `area` is recovered (see below), and there is
  no disposition or notability signal. These rows are marked `source: "crimeradar"`.
- **Where the area actually lives** (all four checked):
  - per-incident: the feed card's `address_tv` renders `2.9 mi · Mount Vernon Ave`. The monitor
    already parses this into `place`, so **live polls carry the street**.
  - feed-wide: `top_feeds_hero_location` = `Kern, California` in the History header. This is the
    notification area, identical on every row, unusable per incident.
  - the History row itself: no location.
  - the Map tab: exists, tile cache on disk (`map_cache.db`, 44 tiles), but pins carry no readable text.
  `_area_for()` recovers the area from the poll card first, then the project's 6,275-street
  gazetteer, then gives up. Titles like "Fight at Marriott" carry no street and correctly stay empty.
- **Third-party UI automation.** Every read is coupled to resource-ids, label text and scroll
  positions. An app update can break it; the canary now makes that loud rather than silent, but it
  cannot be prevented.
- **One process, one machine.** The host must not sleep. A reboot costs one poll.

## 7. Schedule (retimed this session)

| Time | Job | ID |
|---|---|---|
| 03:00 | Kern Overnight phase 1 (early transcribe) | `fb5deffa99bc` |
| 05:20 | KO tail capture | `a5932c17bacb` |
| 22:00-06:45 | CrimeRadar night monitor (`*/15 22-23,0-6`) | `f76fbfbb3977` |
| **07:15** | CrimeRadar emit (stage before publish) | `ffab0caa36d2` |
| **07:30** | Kern Overnight publish (LLM) | `c25ccbac11ee` |
| **07:40** | KO publish (no_agent backstop) | `54d7c836a9b2` |
| **07:50** | CrimeRadar morning pass (verify + reel clips) | `2df4a4eb9688` |
| **08:00** | KO report monitor (live-page watchdog) | `b5ad54871cea` |
| **08:15** | KO completion watchdog | `38e96586dc62` |
| **08:30** | KO manual posting kit | `de7a6ccd504c` |
| **09:15** | KO social publish | `6c48d2ddc168` |
| **09:30** | KO social publish retry | `42c2a117c45b` |

The 07:30 publish needs the 08:00 monitor: the monitor probes the **live page**, so it must run
after commit + push + deploy. Moving the publish without moving the monitor would fire a false
`MISSING/STALE` alarm every morning.

## 8. Files

New:
- `kern_overnight/merge_crimeradar.py` - deterministic, no-emulator, idempotent merge
- `$LOCALAPPDATA/hermes/scripts/crimeradar_emit.sh` - 07:15 staging job
- `$LOCALAPPDATA/hermes/scripts/crimeradar_preflight.sh` - restarts a dead emulator
- `work/crimeradar/test_overlays.py` - 6/6 offline overlay checks

Modified:
- `scripts/crimeradar_monitor.py` - `--emit`, `--dry`, `_poll_places`, `_area_for`, canary,
  `report_window` end 07:00, `TITLE_OK` filter
- `scripts/brief_reel/make_dispatch_audio.py` - `load_emulator_clips`, `match_emulator_clip`
- cron job `c25ccbac11ee` - new publish step 2b
- `$LOCALAPPDATA/hermes/scripts/crimeradar_morning.sh` - `--emit` **removed** (it runs after the
  publish has committed; emitting there would leave the tree dirty with changes the report never saw)

## 9. How to verify independently

```bash
cd C:/Users/tscac/Projects/BakersfieldBrief.com
ADB="C:/Users/tscac/Android/Sdk/platform-tools/adb.exe"

# emulator alive, app foregrounded
"$ADB" devices

# compile
.venv/Scripts/python.exe -m py_compile scripts/crimeradar_monitor.py kern_overnight/merge_crimeradar.py

# emit in dry mode: stages rows, must NOT touch incidents/
md5sum incidents/2026-10-03.json
.venv/Scripts/python.exe scripts/crimeradar_monitor.py --emit 2026-10-03 --dry
md5sum incidents/2026-10-03.json      # must be identical

# canary: with the app UI intact this exits 0; break the UI and it must exit 4
.venv/Scripts/python.exe scripts/crimeradar_monitor.py --once

# overlay detector
.venv/Scripts/python.exe work/crimeradar/test_overlays.py
```

Highest-value things for a reviewer to attack, in order:
1. Run the chain end to end and see whether the emulator rows actually reach the published log.
2. Check whether the LLM publish job actually performs step 2b. This is the weakest link: the merge
   depends on an LLM following a prompt instruction. A deterministic backstop would be better and
   does not exist yet.
3. Measure the aggregation lag across several nights; the 47-minute figure may make the 07:00 window
   end unachievable.
4. Confirm the area yield over a full night.
---

## 10. Audit corrections (2026-10-04) - this section supersedes the text above where they differ

Faults found by an independent audit and fixed. Regression tests: `tests/test_crimeradar.py`.

- **Every scheduled run was failing.** The Hermes cron runner starts scripts with an invalid
  stdin; on Windows each child process then died with WinError 6, which `device_online()`
  reported as "device not online". All subprocess calls now use `stdin=DEVNULL` and the wrappers
  redirect `</dev/null`. (Section 4 item 2, "no cron job has ever fired", was wrong: the night
  job had fired and failed 5 of 5.)
- **The 07:15 emit could not run.** It required `incidents/<date>.json`, which the 07:30 publish
  creates. The emit is now **staging only**: it stages every in-window History row and never
  writes `incidents/`. `--dry` is accepted and changes nothing.
- **Coverage is decided at merge time**, per incident (near in time + shared distinctive words),
  not against the whole night's vocabulary. `merge_crimeradar.py` rebuilds the emulator section
  on every run (transcript rows + surviving staged rows), so it is idempotent and survives a
  re-extraction. It refuses to merge into a file with no transcript incidents.
- **Privacy and rank.** Rows that are patient / hospital / self-harm traffic are withheld, house
  numbers are stripped, and an emulator row's notability is capped at 3 so a one-line app
  headline can never be "The big one". `CR_MERGE_MIN_NOTABILITY=3` merges only serious rows.
- **Backstop and watchdog now merge too** (`ko_publish.py`, watchdog prompt step 2b).
- **Stale UI dumps** are impossible now: both copies are deleted before each dump and a failed
  dump raises. A broken read path exits 4 or 5, never 0.
- **Night spans two calendar days.** The reel export and street lookup read both days' poll files.
- **Reel matcher** needs a shared word as well as a time match, and reads `11:30 PM` correctly.
- **Clip capture is retried** (up to 3 polls); seen-keys expire after 36 h; the card is re-located
  before each tap and the opened page is checked against the headline.
- **One run at a time**: `work/crimeradar/emulator.lock` with a heartbeat (stale after 10 min).
- **cp1252 crash** in the morning job's output fixed (stdout forced to UTF-8).
- Schedule: live-page monitor `b5ad54871cea` moved 08:00 -> 08:15 (publishes take 19-33 min);
  the emit job's failures now go to Discord.

Exit codes for `crimeradar_monitor.py`: 0 ok / skipped (emulator busy, poll only), 2 device
offline, 4 feed or History window empty, 5 the app's UI could not be read, 6 emulator busy
(emit / morning).

Still unproven: a real 07:30 LLM publish performing step 2b, and overlay dismissal against a
live ad.
