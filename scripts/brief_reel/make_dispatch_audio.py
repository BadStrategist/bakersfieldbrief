#!/usr/bin/env python
"""make_dispatch_audio.py — build the reel's soundtrack from the REAL overnight
dispatch audio, deterministically, with no LLM.

For each story in brief.json (which is already ordered most-interesting-first
by make_brief_json.pick_stories), this:

  1. finds the transcript segments for that incident (fuzzy keyword match on the
     place/headline tokens, so ASR spellings like "Brindage" or "Gooder" still
     hit, scored within a time window around the story's clock time),
  2. locates the raw audio block and, using a silence map, the speech run that
     contains that moment,
  3. transcribes that run and scores every 6 s window inside it against the
     story's keywords, taking the best window (ties -> earliest), so the clip
     lands on the transmission that MATCHES the story rather than on whatever
     segment happens to start first,
  4. verifies the chosen window by re-transcribing the actual cut, and
  5. assembles  1 s lead + N x 6 s + 4 s outro  with the house music bed always
     mixed underneath at -18 dB.

Output: an MP3 whose length matches the reel duration, plus a JSON audit log
recording every offset and every verified transcript line.

Usage:
    python make_dispatch_audio.py --date 2026-09-17 \
        --brief work/reel-2026-09-17/brief.json \
        --out work/reel-2026-09-17/soundtrack.mp3
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PT = ZoneInfo("America/Los_Angeles")

STORY_LEN = 6.0        # minimum seconds of dispatch audio per story
LEAD, TAIL = 1.0, 4.0  # reel intro and outro
SCORE_WIN = 6.0        # window used to score candidate beats
TARGET = 30.0          # reel length rule: about 30 s
MIN_TOTAL = 25.0       # never under 25 s
MIN_STORY, MAX_STORY = 6.0, 12.0


def plan_story_len(n: int) -> float:
    """Seconds per story so the reel lands near TARGET and never under MIN_TOTAL.

    The render takes the same intro/outro, so a longer per-story slice is the
    only honest way to grow the reel: padding the tail just holds a dead outro.
    """
    if n <= 0:
        return STORY_LEN
    if n == 1:
        # One clip: hold it long enough to clear the floor on its own.
        return MIN_TOTAL - LEAD - TAIL
    want = (TARGET - LEAD - TAIL) / n
    return min(MAX_STORY, max(MIN_STORY, want))
BED_DB = -18           # house rule: the bed is ALWAYS under the dispatch audio
WHISPER = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
CHAIN = ("highpass=f=200,acompressor=threshold=-20dB:ratio=3:attack=5:"
         "release=150,loudnorm=I=-16:TP=-1.5:LRA=11")

# words that carry no locating value
STOP = {"the", "a", "an", "of", "on", "in", "at", "to", "and", "for", "with",
        "block", "area", "incident", "reported", "near", "avenue", "street",
        "road", "drive", "lane", "avenue,", "bakersfield", "county", "kern"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def norm_tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in STOP and len(t) > 2]


def fuzzy_hit(token, vocab):
    """ASR spells the same thing several ways; match on close tokens."""
    if token in vocab:
        return token
    m = difflib.get_close_matches(token, vocab, n=1, cutoff=0.78)
    return m[0] if m else None


def story_time_seconds(s):
    """'12:52 AM' -> seconds since local midnight."""
    try:
        return (datetime.strptime(s["time"], "%I:%M %p")
                - datetime(1900, 1, 1)).total_seconds()
    except Exception:
        return None


def block_start(path):
    m = re.search(r"-(\d{9,})\.mp3$|_(\d{9,})\.mp3$", os.path.basename(path))
    if not m:
        return None
    ts = int(m.group(1) or m.group(2))
    return datetime.fromtimestamp(ts, PT)


def load_rows(date, root):
    p = os.path.join(root, "transcripts", f"{date}.jsonl")
    rows = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def pick_row(story, rows, block_starts):
    """Best transcript segment for this story: fuzzy token score, then time."""
    keys = norm_tokens(story.get("place", "")) + norm_tokens(story["headline"])
    nums = set(re.findall(r"\b\d{3,5}\b", story.get("place", "") + " " + story["headline"]))
    wanted = story_time_seconds(story)
    best, best_key = None, None
    for r in rows:
        txt = (r.get("text") or "").lower()
        toks = set(re.findall(r"[a-z0-9]+", txt))
        score = 0
        for k in keys:
            if fuzzy_hit(k, toks):
                score += 2
        for n in nums:
            if n in txt:
                score += 3
        for w in ("code 33", "medical aid", "assault", "pursuit", "car wash",
                  "prowler", "vandalism", "fire", "alarm", "yielding"):
            if w in txt:
                score += 1
        if score <= 0:
            continue
        # proximity: prefer segments close to the story's clock time
        ts = r.get("time_local")
        try:
            mins = abs((datetime.strptime(ts, "%H:%M")
                        - datetime(1900, 1, 1)).total_seconds() - wanted) / 60.0
            mins = min(mins, 1440 - mins)          # wrap midnight
        except Exception:
            mins = 600
        if mins > 25:
            continue
        key = (score, -mins)
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best


def speech_runs(path, a, b, noise="-32dB"):
    """Speech runs (start, end) inside [a, b] of the file."""
    r = run(["ffmpeg", "-hide_banner", "-ss", str(a), "-t", str(b - a), "-i", path,
             "-af", f"silencedetect=noise={noise}:d=0.6", "-f", "null", "-"])
    txt = r.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", txt)]
    runs = []
    if not starts:
        return []
    if starts[0] > 0.2:                     # speech before the first silence
        runs.append((a, a + starts[0]))
    for i in range(len(ends) - 1):           # speech between two silences
        if starts[i + 1] > ends[i] + 0.2:
            runs.append((a + ends[i], a + starts[i + 1]))
    if ends and (b - a) > ends[-1] + 0.2:    # speech after the last silence
        runs.append((a + ends[-1], b))
    return runs


_MODEL = None
def transcribe(path, offset=0.0, vad=False):
    """Probe transcription. condition_on_previous_text stays OFF: on narrowband
    scanner audio a repetition loop turns a whole probe into 'Thank you.' for
    30 s blocks, which silently produced a garbage clip."""
    global _MODEL
    from faster_whisper import WhisperModel
    if _MODEL is None:
        _MODEL = WhisperModel(WHISPER, device="cpu", compute_type="int8", cpu_threads=8)
    segs, _ = _MODEL.transcribe(path, language="en", vad_filter=vad,
                                beam_size=5, temperature=0.0,
                                condition_on_previous_text=False,
                                no_speech_threshold=0.6)
    out = []
    for s in segs:
        t = (s.text or "").strip()
        if t:
            out.append({"start": offset + s.start, "end": offset + s.end, "text": t})
    return out


def score_window(text, story):
    keys = norm_tokens(story.get("place", "")) + norm_tokens(story["headline"])
    nums = set(re.findall(r"\b\d{3,5}\b", story.get("place", "") + " " + story["headline"]))
    low = text.lower()
    toks = set(re.findall(r"[a-z0-9]+", low))
    sc = 0
    for k in keys:
        if fuzzy_hit(k, toks):
            sc += 2
    for n in nums:
        if n in low:
            sc += 3
    # Drama first: a chase start or an injury dispatch is the beat worth
    # hearing, so it outweighs a plain mention of the street name.
    for w in ("code 33", "pursuit", "assault", "car wash", "prowler", "fire",
              "shooting", "stab"):
        if w in low:
            sc += 3
    for w in ("victim", "medic", "welfare", "yielding", "injuries", "ambulance"):
        if w in low:
            sc += 1
    return sc


def cut(src, ss, t, dst, wav=False, chain=CHAIN):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(ss), "-t", str(t), "-i", src]
    if chain:
        cmd += ["-af", chain]
    cmd += ["-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", dst] if wav else ["-c:a", "libmp3lame", "-b:a", "128k", dst]
    r = run(cmd)
    return r.returncode == 0


def load_emulator_clips(date: str, root: str) -> list[dict]:
    """CrimeRadar clips exported by `crimeradar_monitor --reel`, if any.

    Strictly optional: when the manifest is absent the reel behaves exactly as
    it did before, which is what keeps this safe for the live publish.
    """
    p = os.path.join(root, "work", "crimeradar", f"reel_{date}", "manifest.json")
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8")).get("clips", []) or []
    except Exception:  # noqa: BLE001
        return []


# Words too common in dispatch headlines to tie a clip to a story.
_CLIP_STOP = {"reported", "report", "reports", "possible", "possibly", "person",
              "police", "county", "area", "near", "after", "with", "from", "that",
              "this", "into", "call", "units", "bakersfield", "kern", "street",
              "avenue", "road", "drive", "lane", "north", "south", "east", "west"}


def _clip_stems(text: str) -> set:
    return {w[:5] for w in re.findall(r"[a-z]{4,}", str(text or "").lower())
            if w not in _CLIP_STOP}


def _story_minutes(story: dict):
    """Story clock time as minutes since midnight: '12:52 AM' or 24h '00:52'."""
    secs = story_time_seconds(story)
    if secs is not None:
        return int(secs // 60)
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(story.get("time") or ""))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def match_emulator_clip(story: dict, clips: list[dict], used: set,
                        window_min: int = 25) -> dict | None:
    """Best emulator clip for a story: most shared words, then nearest in time.

    A clip must be inside `window_min` of the story's time AND share at least
    one distinctive word with the headline. Time alone is never enough: two
    unrelated calls minutes apart would put the wrong audio under a story.
    """
    want = _story_minutes(story)
    if want is None:
        return None
    head = _clip_stems(story.get("headline"))
    best, best_key = None, None
    for c in clips:
        if c.get("file") in used:
            continue
        tm = re.search(r"(\d{1,2}):(\d{2})", str(c.get("approx_time") or ""))
        if not tm:
            continue
        got = int(tm.group(1)) * 60 + int(tm.group(2))
        diff = abs(got - want)
        diff = min(diff, 1440 - diff)          # the night crosses midnight
        if diff > window_min:
            continue
        shared = _clip_stems(c.get("title")) & head
        if not shared:
            continue
        key = (len(shared), -diff)
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--brief", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--bed", default=None, help="music bed (default: brief.json 'music')")
    ap.add_argument("--no-bed", action="store_true", help="dispatch audio alone")
    ap.add_argument("--scratch", default=None)
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    brief = json.load(open(args.brief, encoding="utf-8"))
    stories = brief["stories"]
    # Emulator clips (optional). When the manifest is missing this is empty and
    # every story takes the Broadcastify path exactly as before.
    em_clips = load_emulator_clips(args.date, root)
    em_dir = os.path.join(root, "work", "crimeradar", f"reel_{args.date}")
    em_used: set = set()
    if em_clips:
        print(f"emulator clips available: {len(em_clips)}")
    bed = args.bed or brief.get("music") or "assets/audio/reel_bed_2.mp3"
    if not os.path.isabs(bed):
        cand = os.path.join(root, bed)
        bed = cand if os.path.exists(cand) else os.path.join(HERE, bed)
    scratch = args.scratch or os.path.join(os.path.dirname(os.path.abspath(args.out)), "scratch")
    os.makedirs(scratch, exist_ok=True)

    rows = load_rows(args.date, root)
    audir = os.path.join(root, "audio", args.date)
    blocks = {}
    for f in sorted(os.listdir(audir)):
        if f.endswith(".mp3"):
            blocks[f] = block_start(f) or None

    log = {"date": args.date, "bed": os.path.basename(bed), "bed_db": 0 if args.no_bed else BED_DB,
           "stories": []}
    picks = []
    failed = []
    for i, s in enumerate(stories, 1):
        rec = {"index": i, "headline": s["headline"], "time": s.get("time")}
        # Prefer the emulator's own dispatch clip when one matches this story.
        em = match_emulator_clip(s, em_clips, em_used)
        if em:
            clip_path = os.path.join(em_dir, em["file"])
            if os.path.exists(clip_path):
                em_used.add(em["file"])
                rec.update({"source": "crimeradar", "emulator_clip": em["file"],
                            "emulator_tier": em.get("tier"),
                            "chosen_offset": 0.0, "window_score": 99})
                picks.append((i, s, rec, clip_path, 0.0, 99, "crimeradar"))
                log["stories"].append(rec)
                print(f"[{i}] emulator clip {em['file']} ({em['seconds']}s) "
                      f"for {s['headline']!r}")
                continue
        r = pick_row(s, rows, blocks)
        if not r:
            print(f"[{i}] no transcript match for {s['headline']!r}", file=sys.stderr)
            rec["error"] = "no transcript match"
            log["stories"].append(rec)
            continue
        blk = r["source_file"]
        bp = os.path.join(audir, blk)
        bs = blocks.get(blk)
        # `offset_s` is the row's own seconds into its block, written by the
        # transcribe step, so the cut lands on the transmission itself. Only a
        # row from an older transcript falls back to the clock, which carries
        # minutes and can read a few seconds "before" the block start.
        off = r.get("offset_s")
        hint, hint_source = None, "offset_s"
        if isinstance(off, (int, float)) and off >= 0:
            hint = float(off)
        elif bs:
            hint_source = "clock"
            hm = datetime.strptime(r["time_local"], "%H:%M")
            hint = (hm.hour * 3600 + hm.minute * 60) - (bs.hour * 3600 + bs.minute * 60 + bs.second)
            if hint < -120:
                hint += 86400
            if hint < 0:
                hint = 0.0
        if hint is None or hint < 0:
            hint, hint_source = 0.0, "block-start"
        rec.update({"block": blk, "hint": round(hint, 1), "hint_source": hint_source,
                    "matched_text": (r.get("text") or "")[:180]})

        # One probe around the matched moment. Transmission boundaries ARE the
        # whisper segment starts, so no silence map is needed: score a 6 s
        # window from every segment start and keep the best beat. A 6 s clip is
        # allowed to run past its own transmission into the next one, which is
        # what consecutive dispatch traffic actually sounds like.
        lo = max(0.0, hint - 25)
        probe = os.path.join(scratch, f"s{i}_probe.wav")
        cut(bp, lo, (hint + 45) - lo, probe, wav=True, chain=None)
        segs = transcribe(probe, offset=lo)
        rec["probe"] = [round(lo, 1), round(hint + 45, 1)]
        # Score every 6 s window (all segments it covers, not just the one that
        # starts it) and take the best; ties go to the window nearest the hint.
        def window_text(st):
            return " ".join(x["text"] for x in segs
                            if x["start"] < st + SCORE_WIN and x["end"] > st)

        best, best_key = None, None
        for seg in segs:
            st = seg["start"]
            key = (score_window(window_text(st), s), -abs(st - hint))
            if best_key is None or key > best_key:
                best, best_key = st, key
        best_sc = best_key[0] if best_key else 0
        if best_sc == 0:
            # ASR failure, not a missing story: retry with VAD, then refuse.
            segs = transcribe(probe, offset=lo, vad=True)
            for seg in segs:
                st = seg["start"]
                key = (score_window(window_text(st), s), -abs(st - hint))
                if best_key is None or key > best_key:
                    best, best_key = st, key
            best_sc = best_key[0] if best_key else 0
        if best is None or best_sc < 3:
            rec["error"] = "no keyword-matched beat in the transcript (ASR failed?)"
            print(f"[{i}] FAILED: no matched beat for {s['headline']!r}", file=sys.stderr)
            log["stories"].append(rec)
            failed.append(i)
            continue
        rec.update({"chosen_offset": round(best, 2), "window_score": best_sc,
                    "beat_text": window_text(best)[:220]})

        picks.append((i, s, rec, bp, best, best_sc, blk))
        log["stories"].append(rec)

    if not picks:
        sys.exit("no pieces produced")

    # Pace the reel: one slice per story that has a beat, long enough that the
    # whole thing runs about TARGET (never under MIN_TOTAL). The render's
    # per-scene length is (duration - intro - outro) / stories, so keeping the
    # picture limited to these same stories keeps scenes glued to their clip.
    story_len = plan_story_len(len(picks))
    print(f"\npacing: {len(picks)} stories x {story_len:.1f}s + {LEAD:.0f}s + {TAIL:.0f}s "
          f"= {LEAD + story_len * len(picks) + TAIL:.1f}s")

    pieces = []
    for i, s, rec, bp, best, best_sc, blk in picks:
        piece = os.path.join(scratch, f"s{i}.wav")
        rec["cut_ok"] = cut(bp, best, story_len, piece, wav=True)
        # Verify the actual cut, not the probe, on the raw audio.
        raw = os.path.join(scratch, f"s{i}_raw.wav")
        cut(bp, best, story_len, raw, wav=True, chain=None)
        vt = transcribe(raw, vad=True)
        rec["verified_transcript"] = [x["text"] for x in vt]
        vt_text = " ".join(rec["verified_transcript"])
        toks = re.findall(r"[a-z]+", vt_text.lower())
        ratio = (len(set(toks)) / len(toks)) if toks else 0.0
        # A standalone cut of narrowband radio can send whisper into a digit
        # loop ("2-5-5-5-5...") even when the audio is correct, so accept either
        # readable text or a story keyword in whatever came back.
        rec["verify_ratio"] = round(ratio, 2)
        rec["verify_score"] = score_window(vt_text, s)
        rec["verify_ok"] = ratio > 0.25 or rec["verify_score"] >= 2
        rec["seconds"] = story_len
        print(f"[{i}] {s['headline']}")
        print(f"     {blk} @ {best:.1f}s  score={best_sc}  {story_len:.1f}s")
        for line in rec["verified_transcript"]:
            print(f"       > {line}")
        if not rec["verify_ok"]:
            print(f"       ! verification came back degenerate; beat text was: "
                  f"{rec['beat_text'][:90]}", file=sys.stderr)
        pieces.append(piece)

    if not pieces:
        sys.exit("no pieces produced")

    # timeline: lead + pieces + tail, bed under all of it
    lead = os.path.join(scratch, "lead.wav"); tail = os.path.join(scratch, "tail.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", str(LEAD),
         "-i", "anullsrc=r=44100:cl=mono", "-c:a", "pcm_s16le", lead])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", str(TAIL),
         "-i", "anullsrc=r=44100:cl=mono", "-c:a", "pcm_s16le", tail])
    ins = [lead] + pieces + [tail]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for f in ins:
        cmd += ["-i", f]
    n = len(ins)
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[voice];"
    if args.no_bed:
        fc += "[voice]anull[out]"
    else:
        cmd += ["-stream_loop", "-1", "-i", bed]
        fc += f"[{n}:a]volume={BED_DB}dB[bed];[voice][bed]amix=inputs=2:duration=first:normalize=0[out]"
    cmd += ["-filter_complex", fc, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", args.out]
    r = run(cmd)
    if r.returncode != 0:
        sys.exit("mux failed: " + r.stderr[:400])

    dur = LEAD + story_len * len(pieces) + TAIL
    log["duration"] = dur
    log["story_len"] = story_len
    # 0-based positions of the stories that carry audio, in brief.json order:
    # the renderer keeps only these so the scenes stay glued to their clip.
    log["reel_indices"] = [i - 1 for i, _s, _r, _bp, _b, _sc, _blk in picks]
    logp = os.path.splitext(args.out)[0] + ".json"
    json.dump(log, open(logp, "w", encoding="utf-8"), indent=2)
    print(f"\nsoundtrack: {args.out}  ({dur:.1f}s = {LEAD:.0f}s + "
          f"{len(pieces)}x{story_len:.1f}s + {TAIL:.0f}s)")
    if dur < MIN_TOTAL:
        print(f"WARNING: {dur:.1f}s is under the {MIN_TOTAL:.0f}s floor", file=sys.stderr)
    print(f"audit log : {logp}")
    print(f"render with: --duration {dur:.0f}")
    if failed:
        # A clip that nobody verified must never reach the reel.
        print(f"FAILED stories {failed}: the reel was built without them. "
              f"Fix the transcript match or pick the clip by hand.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
