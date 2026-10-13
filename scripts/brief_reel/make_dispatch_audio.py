#!/usr/bin/env python
"""make_dispatch_audio.py — build the reel's soundtrack from the REAL overnight
dispatch audio, deterministically, with no LLM.

For each story in brief.json (which is already ordered most-interesting-first
by make_brief_json.pick_stories), this:

  1. finds the transcript row for that incident (fuzzy keyword match on the
     place/headline tokens, so ASR spellings like "Brindage" or "Gooder" still
     hit, scored within a time window around the story's clock time),
  2. transcribes a 70 s probe around that row with the voice detector on and
     word timestamps, so every candidate start is the start of real speech,
  3. scores the window that begins at each utterance and keeps the best one
     that carries an ANCHOR: the story's street or number, or the words of the
     matched row itself. No anchor, no clip. A dramatic word on its own never
     picks a window,
  4. cuts it, then checks the cut three ways: it holds audible speech (measured,
     not transcribed), it re-transcribes to readable text, and that text is the
     beat that was picked. A clip that fails any of them is DROPPED, never
     mixed, and the reel is re-paced over the clips that are left,
  5. assembles  1 s lead + N clips + 4 s outro  with the house music bed mixed
     underneath, and normalises the finished mix to a measured loudness (the
     numbers are in reel_audio_gate.py).

Output: an MP3 whose length matches the reel duration, plus a JSON audit log
recording every offset, every verified transcript line and the `outcome`.

Exit: 0 = every brief story carries a verified clip
      2 = degraded: built, but at least one story was dropped (named on stderr)
      4 = held: no clip verified. NO soundtrack is written; the audit log is.
      5 = the mix failed its loudness check. NO soundtrack is written.
The publisher treats 4 and 5 as "hold the reel" and 2 as "publish and alert".

Usage:
    python make_dispatch_audio.py --date 2026-09-17 \
        --brief work/reel-2026-09-17/brief.json \
        --out work/reel-2026-09-17/soundtrack.mp3
"""
import argparse
import difflib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PT = ZoneInfo("America/Los_Angeles")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import reel_audio_gate as RAG  # noqa: E402

STORY_LEN = 6.0        # minimum seconds of dispatch audio per story
LEAD, TAIL = 1.0, 4.0  # reel intro and outro
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
UTTER_GAP = 0.6        # a pause this long between words starts a new utterance
PRE_ROLL = 0.15        # start the cut this far ahead of the first word
EXIT_DEGRADED, EXIT_HELD, EXIT_MIX = 2, 4, 5
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
def transcribe(path, offset=0.0, vad=False, words=False, fallback=False):
    """Probe transcription. condition_on_previous_text stays OFF: on narrowband
    scanner audio a repetition loop turns a whole probe into 'Thank you.' for
    30 s blocks, which silently produced a garbage clip.

    A segment's own start/end are NOT where the speech is. Whisper works in
    30 s chunks, and a chunk that opens on dead air comes back as one segment
    stamped 0.00 to 29.98 with the words spoken in its last five seconds
    (2026-10-12, both clips). Anything that places a cut asks for `words` and
    reads the word times, with the voice detector on.

    `fallback` lets whisper retry a looping decode at a higher temperature,
    which is what the temperature ladder is for. Only the last verification
    attempt uses it: its text is not repeatable run to run, so it never places
    a cut, and it still has to match the picked beat to count."""
    global _MODEL
    from faster_whisper import WhisperModel
    if _MODEL is None:
        _MODEL = WhisperModel(WHISPER, device="cpu", compute_type="int8", cpu_threads=8)
    segs, _ = _MODEL.transcribe(path, language="en", vad_filter=vad,
                                beam_size=5,
                                temperature=(0.0, 0.2, 0.4, 0.6) if fallback else 0.0,
                                condition_on_previous_text=False,
                                no_speech_threshold=0.6,
                                word_timestamps=words)
    out = []
    for s in segs:
        t = (s.text or "").strip()
        if not t:
            continue
        rec = {"start": offset + s.start, "end": offset + s.end, "text": t}
        if words:
            rec["words"] = [{"start": offset + w.start, "end": offset + w.end,
                             "word": (w.word or "").strip()}
                            for w in (s.words or []) if (w.word or "").strip()]
        out.append(rec)
    return out


def flatten_words(segs):
    """Every timed word of a probe, in order."""
    out = []
    for s in segs:
        out.extend(s.get("words") or [])
    out.sort(key=lambda w: w["start"])
    return out


def utterance_starts(words, gap=UTTER_GAP):
    """Where a clip may begin: the first word, a word after a pause, or a word
    after the end of a sentence. Always a word's own start, so always speech."""
    starts = []
    prev = None
    for w in words:
        if (prev is None or w["start"] - prev["end"] >= gap
                or prev["word"][-1:] in ".?!"):
            starts.append(w["start"])
        prev = w
    return starts


def window_text(words, st, length):
    """The words that begin inside [st, st + length): what the cut will hold."""
    text = " ".join(w["word"] for w in words
                    if st - 0.05 <= w["start"] < st + length)
    return re.sub(r"\s+-", "-", text)        # whisper times "I", "-5" apart


# Words of a place that are true of half the county and locate nothing.
_PLACE_GENERIC = {"north", "south", "east", "west", "northbound", "southbound",
                  "eastbound", "westbound", "highway", "interstate", "route",
                  "freeway", "exit", "ramp", "city", "town", "apartment",
                  "apartments", "complex", "about", "just", "off", "mile",
                  "miles", "rest", "intersection", "between", "from", "two",
                  "three", "store", "parking", "lot", "residence", "home"}


# Words every transmission holds. Sharing them ties two texts to nothing.
_FUNCTION = {"they", "them", "their", "there", "were", "with", "that", "this",
             "from", "have", "will", "been", "then", "when", "what", "your",
             "going", "about", "just", "one", "two", "last", "seen", "copy",
             "okay", "units", "unit", "advised", "advise", "advising", "but",
             "now", "are", "was", "has", "his", "her", "she", "not", "you"}


def _distinct(text):
    """A text's own words, in order, once each, without the filler."""
    return [t for t in dict.fromkeys(norm_tokens(text)) if t not in _FUNCTION]


def _same_word(token, toks):
    """The anchor's match, stricter than fuzzy_hit on purpose: fuzzy_hit calls
    "northbound" and "southbound" the same word (0.80) and "they" and "the"
    (0.86). Short words and numbers match exactly; a longer word may differ by
    an ASR letter ("Niles" / "Nile")."""
    if token in toks:
        return True
    if len(token) < 5 or not token.isalpha():
        return False
    return bool(difflib.get_close_matches(token, [t for t in toks if len(t) >= 4],
                                          n=1, cutoff=0.85))


def place_tokens(story):
    """The words that name where the story is: its street, not its type."""
    src = story.get("place") or story.get("headline") or ""
    return [t for t in norm_tokens(src)
            if t.isalpha() and len(t) >= 4 and t not in _PLACE_GENERIC]


def number_hit(text, story):
    """True when the text carries the story's house or block number.

    A "5400 block" is said on the air as the address itself ("5420"), and the
    ASR writes digits apart ("64-65 Niles"), so digit groups are joined and a
    block number matches any address inside that block."""
    src = (story.get("place") or "") + " " + (story.get("headline") or "")
    nums = set(re.findall(r"\b\d{3,5}\b", src))
    if not nums:
        return False
    is_block = "block" in src.lower()
    joined = re.sub(r"(?<=\d)[\s-]+(?=\d)", "", text or "")
    said = set(re.findall(r"\d+", joined)) | set(re.findall(r"\d+", text or ""))
    for n in nums:
        if n in said:
            return True
        if is_block and n.endswith("00"):
            if any(len(d) == len(n) and d.startswith(n[:-2]) for d in said):
                return True
    return False


def anchor(text, story, row_text=None):
    """What ties this text to THIS story. `ok` is the rule a window must pass.

    Three ways to be anchored, any one is enough:
      place   a word of the story's street name is in the text,
      number  the story's house or block number is in the text,
      row     the text holds the words of the transcript row the story was
              matched to (most of a short row, four or more of a long one).
    A word like "fire" or "medic" is none of these. On 2026-10-09 the card read
    "Shots fired on the 5400 block of Pembroke Avenue" and played a brake fire:
    the probe never heard "Pembroke", and "fire" alone scored 5 (3 as a drama
    word, 2 because it is one letter from "fired")."""
    toks = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    place = [t for t in place_tokens(story) if _same_word(t, toks)]
    row = _distinct(row_text or "")
    hits = [t for t in row if _same_word(t, toks)]
    need = 4 if len(row) > 6 else max(3, math.ceil(0.6 * len(row)))
    row_ok = len(row) >= 3 and len(hits) >= need
    num = number_hit(text, story)
    return {"place": place, "number": num, "row_hits": len(hits),
            "row_tokens": len(row), "ok": bool(place) or num or row_ok}


def agreement(a, b):
    """Share of b's distinct words that a also holds (fuzzy). Two ASR passes
    over the same seconds of radio agree on most words; two passes over
    different seconds agree on almost none."""
    want = _distinct(b)
    if not want:
        return 0.0
    have = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    return sum(1 for t in want if _same_word(t, have)) / len(want)


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


def _limiter():
    return f"alimiter=limit={10 ** (RAG.LIMIT_DB / 20):.4f}:level=0"


def level_to(src, dst, target):
    """Write src to dst at `target` LUFS, by one measured gain and a limiter.

    The chain's single-pass loudnorm undershoots on sparse speech (clips shipped
    at -25 and -28 LUFS next to clips at -16), so the level is measured and
    trimmed. The lift is capped: dead air is not turned up, it is dropped by the
    speech check. Returns the measured loudness of dst, or None."""
    lv = RAG.loudness(src)
    if lv is None:
        return None
    gain = max(-RAG.MAX_VOICE_GAIN, min(RAG.MAX_VOICE_GAIN, target - lv["lufs"]))
    r = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
             "-af", f"volume={gain:.2f}dB,{_limiter()}",
             "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", dst])
    if r.returncode != 0:
        return None
    return RAG.loudness(dst)


def find_beat(story, row_text, probe, lo, hint, length):
    """The start of the best anchored window in the probe, or None.

    Returns {"start", "score", "text", "anchor", "asr"}. The voice detector goes
    first because its word times sit on real speech; the plain pass is the
    fallback for a transmission the detector threw away, and whatever it finds
    still has to pass the speech check and the re-transcription."""
    for asr, vad in (("vad", True), ("plain", False)):
        words = flatten_words(transcribe(probe, offset=lo, vad=vad, words=True))
        best, best_key = None, None
        for st in utterance_starts(words):
            text = window_text(words, st, length)
            anc = anchor(text, story, row_text)
            if not anc["ok"]:
                continue
            sc = score_window(text, story)
            key = (sc, -abs(st - hint))
            if best_key is None or key > best_key:
                best_key = key
                best = {"start": st, "score": sc, "text": text, "anchor": anc,
                        "asr": asr}
        if best:
            return best
    return None


def check_clip(pick, story_len, scratch):
    """Cut one clip at this length and decide whether it may be mixed.

    Returns the path of the levelled piece, or None. Fills pick["rec"] with what
    was measured and, on a refusal, `verify_reason`. Three checks, all must pass:
    audible speech in the cut, a readable re-transcription of the cut, and that
    re-transcription being the beat that was picked."""
    i, s, rec = pick["i"], pick["story"], pick["rec"]
    start = max(0.0, pick["start"] - PRE_ROLL)
    proc = os.path.join(scratch, f"s{i}_proc.wav")
    raw = os.path.join(scratch, f"s{i}_raw.wav")
    piece = os.path.join(scratch, f"s{i}.wav")
    rec["seconds"] = story_len
    rec["cut_ok"] = cut(pick["src"], start, story_len, proc, wav=True)
    cut(pick["src"], start, story_len, raw, wav=True, chain=None)
    rec["verify_ok"] = False
    for k in ("verify_reason", "dropped"):
        rec.pop(k, None)

    def refuse(why):
        rec["verify_reason"] = why
        return None

    if not rec["cut_ok"]:
        return refuse("ffmpeg could not cut the clip")
    speech = RAG.speech_seconds(proc)
    rec["speech_s"] = None if speech is None else round(speech, 2)
    if speech is None:
        return refuse("the speech in the cut could not be measured")
    if speech < RAG.MIN_SPEECH_S:
        return refuse(f"{rec['speech_s']} s of audible speech in a {story_len:.1f} s cut "
                      f"(floor {RAG.MIN_SPEECH_S} s)")

    # Verify the actual cut, not the probe, on the raw audio. Two ASR passes
    # over the same seconds of narrowband radio do not always agree, and a
    # standalone cut can send whisper into a digit loop when the audio is right,
    # so the clip gets more than one hearing before it is refused: the raw cut,
    # the processed cut, then the raw cut with the temperature ladder (and first
    # of all the pass that picked the beat, when that was the plain one). A
    # hearing counts only when it reads as speech AND is the picked beat.
    hearings = [(raw, True, False), (proc, True, False), (raw, True, True)]
    if rec.get("asr") == "plain":
        hearings.insert(0, (raw, False, False))
    problem = "not transcribed"
    for n, (src, vad, ladder) in enumerate(hearings):
        lines = [x["text"] for x in transcribe(src, vad=vad, fallback=ladder)]
        vt_text = " ".join(lines)
        got = RAG.transcript_problem(lines)
        agree = None
        if not got and pick.get("source") != "crimeradar":
            agree = agreement(vt_text, rec.get("beat_text", ""))
            if not (anchor(vt_text, s, pick.get("row_text"))["ok"] or agree >= 0.5):
                got = ("the cut re-transcribes to something other than the "
                       "beat that was picked")
        if n == 0 or not got:
            toks = re.findall(r"[a-z0-9]+", vt_text.lower())
            rec["verified_transcript"] = lines
            rec["verify_ratio"] = round(len(set(toks)) / len(toks), 2) if toks else 0.0
            rec["verify_score"] = score_window(vt_text, s)
            rec["verify_hearing"] = n + 1
            rec.pop("verify_agreement", None)
            if agree is not None:
                rec["verify_agreement"] = round(agree, 2)
            problem = got
        if not got:
            break
    if problem:
        return refuse(problem)

    lv = level_to(proc, piece, RAG.VOICE_LUFS)
    if lv is None:
        return refuse("the clip's loudness could not be measured")
    rec["piece_lufs"] = lv["lufs"]
    rec["verify_ok"] = True
    return piece


def pace_and_verify(picks, check):
    """Pace the reel over the clips that verify, and only those.

    The per-clip length depends on how many clips there are, and whether a clip
    verifies depends on its length, so: cut every clip at the length the current
    count gives, drop the ones that fail, and go again until a round drops
    nothing. Returns (kept, story_len, dropped) with kept = [(pick, piece)]."""
    kept, dropped = list(picks), []
    while kept:
        story_len = plan_story_len(len(kept))
        good, bad = [], []
        for p in kept:
            piece = check(p, story_len)
            if piece:
                good.append((p, piece))
            else:
                bad.append(p)
        if not bad:
            return good, story_len, dropped
        dropped += bad
        kept = [p for p in kept if p not in bad]
    return [], plan_story_len(0), dropped


class MixError(Exception):
    """The finished mix is not fit to publish. No soundtrack is left on disk."""


def mix_soundtrack(pieces, bed, out, scratch, no_bed=False):
    """lead + pieces + tail with the bed under it, normalised and MEASURED.

    The old mix set the bed with `volume=-18dB` and trusted the voice to carry
    the level. With no voice in the clips the result was the bed alone at
    -35.6 LUFS, published. Now the bed is placed at RAG.BED_LUFS from its own
    measured loudness, the mix is brought to RAG.MIX_LUFS by one measured gain
    under a limiter, and the file that was written is measured again. A mix that
    would need more than RAG.MAX_MIX_GAIN has no voice in it and is refused, not
    turned up. Returns the measurements; raises MixError and removes `out`."""
    lead = os.path.join(scratch, "lead.wav")
    tail = os.path.join(scratch, "tail.wav")
    voice = os.path.join(scratch, "voice.wav")
    premix = os.path.join(scratch, "premix.wav")
    if os.path.exists(out):
        os.remove(out)
    if not pieces:
        raise MixError("no clips to mix")
    for path, secs in ((lead, LEAD), (tail, TAIL)):
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", str(secs),
             "-i", "anullsrc=r=44100:cl=mono", "-c:a", "pcm_s16le", path])
    ins = [lead] + list(pieces) + [tail]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for f in ins:
        cmd += ["-i", f]
    n = len(ins)
    fc = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
    r = run(cmd + ["-filter_complex", fc, "-map", "[out]", "-c:a", "pcm_s16le",
                   "-ar", "44100", voice])
    if r.returncode != 0:
        raise MixError("concat failed: " + r.stderr[:300])

    info = {"bed_lufs": None, "bed_gain_db": None}
    if no_bed:
        premix = voice
    else:
        bed_lv = RAG.loudness(bed)
        if bed_lv is None:
            raise MixError(f"the bed's loudness could not be measured: {bed}")
        bed_gain = RAG.BED_LUFS - bed_lv["lufs"]
        info.update({"bed_lufs": bed_lv["lufs"], "bed_gain_db": round(bed_gain, 2)})
        r = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice,
                 "-stream_loop", "-1", "-i", bed, "-filter_complex",
                 f"[1:a]volume={bed_gain:.2f}dB[bed];"
                 "[0:a][bed]amix=inputs=2:duration=first:normalize=0[out]",
                 "-map", "[out]", "-c:a", "pcm_s16le", "-ar", "44100", premix])
        if r.returncode != 0:
            raise MixError("mux failed: " + r.stderr[:300])

    pre = RAG.loudness(premix)
    if pre is None:
        raise MixError("the mix's loudness could not be measured")
    gain = RAG.MIX_LUFS - pre["lufs"]
    info.update({"premix_lufs": pre["lufs"], "mix_gain_db": round(gain, 2)})
    if gain > RAG.MAX_MIX_GAIN:
        raise MixError(f"the mix measures {pre['lufs']:.1f} LUFS before normalising: "
                       f"there is no voice track in it (it would need +{gain:.1f} dB, "
                       f"cap +{RAG.MAX_MIX_GAIN:.0f})")
    r = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", premix,
             "-af", f"volume={gain:.2f}dB,{_limiter()}",
             "-c:a", "libmp3lame", "-b:a", "192k", out])
    if r.returncode != 0:
        raise MixError("normalise failed: " + r.stderr[:300])

    final = RAG.loudness(out)
    problem = None
    if final is None:
        problem = "the finished soundtrack could not be measured"
    elif abs(final["lufs"] - RAG.MIX_LUFS) > RAG.MIX_TOLERANCE:
        problem = (f"the finished soundtrack measures {final['lufs']:.1f} LUFS, "
                   f"outside {RAG.MIX_LUFS:.0f} +/- {RAG.MIX_TOLERANCE:.0f}")
    elif final["peak"] > RAG.MAX_PEAK_DB:
        problem = (f"the finished soundtrack peaks at {final['peak']:.1f} dBTP, "
                   f"over {RAG.MAX_PEAK_DB:.1f}")
    if problem:
        if os.path.exists(out):
            os.remove(out)
        raise MixError(problem)
    info.update({"mix_lufs": final["lufs"], "mix_peak_db": final["peak"]})
    return info


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

    # A soundtrack left over from an earlier build must not outlive this one:
    # the publisher takes whatever soundtrack.mp3 is on disk.
    for stale in (args.out, os.path.splitext(args.out)[0] + ".json"):
        if os.path.exists(stale):
            os.remove(stale)

    log = {"date": args.date, "bed": os.path.basename(bed),
           "levels": {"voice_lufs": RAG.VOICE_LUFS, "mix_lufs": RAG.MIX_LUFS,
                      "bed_lufs": None if args.no_bed else RAG.BED_LUFS},
           "stories": []}
    picks = []
    score_len = plan_story_len(len(stories))
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
                picks.append({"i": i, "story": s, "rec": rec, "src": clip_path,
                              "start": 0.0, "source": "crimeradar",
                              "label": "crimeradar"})
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

        # One probe around the matched moment, scored at the shortest length a
        # clip can end up with, so the words that pick a window are words the
        # cut will hold. A clip is allowed to run past its own transmission into
        # the next one, which is what consecutive dispatch traffic sounds like.
        # A clock hint is a minute, so the row can sit up to 60 s after it.
        lo = max(0.0, hint - 25)
        hi = hint + (45 if hint_source == "offset_s" else 90)
        probe = os.path.join(scratch, f"s{i}_probe.wav")
        cut(bp, lo, hi - lo, probe, wav=True, chain=None)
        rec["probe"] = [round(lo, 1), round(hi, 1)]
        beat = find_beat(s, r.get("text") or "", probe, lo, hint, score_len)
        if beat is None:
            rec["error"] = ("no anchored beat in the probe: nothing in it names "
                            "the story's place or repeats the matched row")
            print(f"[{i}] FAILED: no anchored beat for {s['headline']!r}", file=sys.stderr)
            log["stories"].append(rec)
            continue
        rec.update({"chosen_offset": round(beat["start"], 2),
                    "window_score": beat["score"], "beat_text": beat["text"][:220],
                    "anchor": beat["anchor"], "asr": beat["asr"]})
        picks.append({"i": i, "story": s, "rec": rec, "src": bp,
                      "start": beat["start"], "row_text": r.get("text") or "",
                      "label": blk})
        log["stories"].append(rec)

    # Pace the reel: one slice per story whose clip VERIFIES, long enough that
    # the whole thing runs about TARGET (never under MIN_TOTAL). The render's
    # per-scene length is (duration - intro - outro) / stories, so keeping the
    # picture limited to these same stories keeps scenes glued to their clip.
    kept, story_len, dropped = pace_and_verify(
        picks, lambda p, n: check_clip(p, n, scratch))
    for p in dropped:
        p["rec"]["dropped"] = True
        p["rec"]["verify_ok"] = False
        print(f"[{p['i']}] DROPPED, not mixed: {p['story']['headline']}\n"
              f"     {p['rec'].get('verify_reason')}\n"
              f"     beat text was: {p['rec'].get('beat_text', '')[:90]}", file=sys.stderr)
    for p, _piece in kept:
        rec = p["rec"]
        print(f"[{p['i']}] {p['story']['headline']}")
        print(f"     {p['label']} @ {p['start']:.1f}s  score={rec.get('window_score')}  "
              f"{story_len:.1f}s  speech={rec.get('speech_s')}s  {rec.get('piece_lufs')} LUFS")
        for line in rec.get("verified_transcript", []):
            print(f"       > {line}")

    # 0-based positions of the stories that carry audio, in brief.json order:
    # the renderer keeps only these so the scenes stay glued to their clip.
    log["reel_indices"] = [p["i"] - 1 for p, _piece in kept]
    log["story_len"] = story_len
    logp = os.path.splitext(args.out)[0] + ".json"
    missing = [rec["index"] for rec in log["stories"]
               if rec["index"] - 1 not in log["reel_indices"]]

    def finish(outcome, reason=None):
        log["outcome"] = outcome
        if reason:
            log["held_reason"] = reason
        json.dump(log, open(logp, "w", encoding="utf-8"), indent=2)

    if not kept:
        finish("held", "no dispatch clip verified")
        print(f"HELD: no dispatch clip verified for {args.date}. No soundtrack was "
              f"written. Audit log: {logp}", file=sys.stderr)
        sys.exit(EXIT_HELD)

    try:
        log["mix"] = mix_soundtrack([piece for _p, piece in kept], bed, args.out,
                                    scratch, no_bed=args.no_bed)
    except MixError as exc:
        finish("held", f"mix refused: {exc}")
        print(f"HELD: {exc}. No soundtrack was written. Audit log: {logp}",
              file=sys.stderr)
        sys.exit(EXIT_MIX)

    dur = LEAD + story_len * len(kept) + TAIL
    log["duration"] = dur
    finish("degraded" if missing else "ok")
    print(f"\nsoundtrack: {args.out}  ({dur:.1f}s = {LEAD:.0f}s + "
          f"{len(kept)}x{story_len:.1f}s + {TAIL:.0f}s)  "
          f"{log['mix']['mix_lufs']} LUFS, peak {log['mix']['mix_peak_db']} dBTP")
    if dur < MIN_TOTAL:
        print(f"WARNING: {dur:.1f}s is under the {MIN_TOTAL:.0f}s floor", file=sys.stderr)
    print(f"audit log : {logp}")
    print(f"render with: --duration {dur:.0f}")
    if missing:
        # Loud on purpose: the reel is fit to publish, the run is not clean.
        print(f"DEGRADED: stories {missing} have no verified clip and are not in "
              f"the reel. Fix the transcript match or pick the clip by hand.",
              file=sys.stderr)
        sys.exit(EXIT_DEGRADED)


if __name__ == "__main__":
    main()
