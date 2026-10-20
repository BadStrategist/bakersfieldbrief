#!/usr/bin/env python
"""build_captions.py - read-along captions for the reel's scanner audio.

Transcribes the FINISHED soundtrack (so every caption is timed to what the
viewer actually hears), keeps the words that fall inside each story's slot,
blanks what the report's privacy rules forbid, fixes misheard place names
against the story's own words, and groups the words into short cues that
render_reel.caption_panel draws karaoke style.

It also answers the question the clip builder's own check cannot: does this
clip talk about THIS story? A clip whose words carry none of the story's
anchors (its street, or the thing that happened: shots, knife, machete...) is
reported as a MISMATCH and gets no captions, and --strict exits 3 so the
publisher can hold the reel instead of airing the wrong call (2026-10-20: the
Terrace Way assault played a seizure call on Buck Owens Blvd).

Usage:
    python build_captions.py --brief brief.json --soundtrack soundtrack.mp3 \
        --audit soundtrack.json --out brief_captioned.json [--strict]
"""
import argparse
import os
import difflib
import json
import re
import sys

LEAD_S = 1.0
GAP_BREAK = 0.55        # a pause this long starts a new cue
CUE_CHARS = 58          # about two lines in the caption panel

# Words that say what happened. A clip must share one with its story, or the
# story's street, to count as the right call.
EVENT_WORDS = {
    "shot", "shots", "shooting", "gunfire", "gun", "firearm", "bang", "bangs",
    "knife", "knives", "machete", "machetes", "taser", "stab", "stabbing",
    "assault", "fight", "robbery", "burglary", "fire", "smoke", "crash",
    "collision", "pursuit", "chase", "chasing", "copper", "wire",
}
STOP = {"the", "and", "with", "near", "from", "that", "this", "was", "were",
        "street", "avenue", "road", "drive", "lane", "way", "court", "east",
        "west", "north", "south", "bakersfield", "kern", "county", "reported",
        "caller", "people", "man", "woman", "two", "one", "into", "after"}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
STREET_WORDS = {"Street", "Avenue", "Road", "Drive", "Lane", "Court", "Way", "Boulevard", "Highway"}
NAME_CUES = re.compile(r"^(named|name|subject|rp|reporting|party)$", re.I)
_NUM = ("zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
        "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
        "sixty|seventy|eighty|ninety|hundred|thousand")
NUMBER_WORD = re.compile(rf"^(({_NUM})(-({_NUM}))?|\d+)$")


def redact(word: str) -> tuple[str, bool]:
    """Blank a token the report may not carry: house numbers and other long
    numbers, plates (letters mixed with digits), phone-number pieces."""
    core = re.sub(r"[^\w-]", "", word)
    if re.search(r"\d{3,}", core) or (re.search(r"\d", core) and re.search(r"[A-Za-z]", core)
                                      and len(core) >= 5):
        trail = word[len(word.rstrip(".,?!;:")):]
        return "•••" + trail, True
    return word, False


# ---- person names -------------------------------------------------------------
# The report never names anyone, and neither may the reel. Radio does ("...with
# Sam Robertson...", 2026-10-20), so a word is treated as a person's name when
# Whisper capitalized it, it is not a known Kern street, town, police phonetic unit
# or a word of the story itself, and it almost never appears in lowercase in the
# whole radio transcript archive (so "Possession" at the start of a phrase is a
# common word, "Robertson" is not). This errs toward blanking: a business name
# may go too, a person's name may not air.
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PHONETIC = {"adam", "boy", "charles", "david", "edward", "frank", "george", "henry", "ida",
            "john", "king", "lincoln", "mary", "nora", "ocean", "paul", "queen", "robert",
            "sam", "tom", "union", "victor", "william", "xray", "young", "zebra", "control",
            "medic", "engine", "truck", "battalion", "rescue", "squad", "unit", "units"}
TOWNS = {"bakersfield", "kern", "oildale", "delano", "shafter", "arvin", "lamont", "tehachapi",
         "wasco", "mcfarland", "taft", "ridgecrest", "frazier", "lebec", "rosedale", "california",
         "highway", "interstate", "caltrans", "chp", "kcso", "kcfd", "bpd", "hall", "sheriff",
         "police", "fire", "county", "city", "valley", "american", "spanish", "english"}
_LOWER_FREQ: dict | None = None
_STREET_WORDS_ALL: set | None = None


def _lower_freq() -> dict:
    """How often each word appears in lowercase across the radio transcripts."""
    global _LOWER_FREQ
    if _LOWER_FREQ is None:
        from collections import Counter
        c: Counter = Counter()
        tdir = os.path.join(ROOT, "transcripts")
        for name in os.listdir(tdir) if os.path.isdir(tdir) else []:
            if not name.endswith(".jsonl"):
                continue
            with open(os.path.join(tdir, name), encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        text = json.loads(line).get("text", "")
                    except ValueError:
                        continue
                    c.update(t for t in re.findall(r"\b[a-z][a-z']+\b", text))
        _LOWER_FREQ = dict(c)
    return _LOWER_FREQ


def _street_words() -> set:
    global _STREET_WORDS_ALL
    if _STREET_WORDS_ALL is None:
        p = os.path.join(ROOT, "kern_overnight", "streets.txt")
        words = set()
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    words.update(w.lower() for w in re.findall(r"[A-Za-z]+", line))
        except OSError:
            pass
        _STREET_WORDS_ALL = words
    return _STREET_WORDS_ALL


STREET_TYPES = {"street", "st", "avenue", "ave", "road", "rd", "drive", "dr", "lane", "ln",
                "court", "ct", "way", "boulevard", "blvd", "place", "pl", "circle", "parkway",
                "highway", "hwy", "park", "trail", "loop", "terrace"}


def _core(w: str) -> str:
    return re.sub(r"[^A-Za-z']", "", w)


def is_proper(word: str, story_words: set) -> bool:
    """A capitalized word that is not a common word, a town, a unit or the story's own."""
    core = _core(word)
    if not re.match(r"^[A-Z][a-z']{2,}$", core):
        return False
    low = core.lower().replace("'", "")
    if low in PHONETIC or low in TOWNS or low in STREET_TYPES:
        return False
    if low in {s.lower() for s in story_words}:
        return False
    return _lower_freq().get(core.lower(), 0) < 3


def redact_names(words: list, story_words: set) -> None:
    """Blank person names in place. A proper word is a STREET only when a street
    type follows it ("Robertson Road"); Kern names streets after people, so
    "Robertson" alone, or after a first name ("Sam Robertson"), is a person."""
    for i, w in enumerate(words):
        if w.get("redacted") or not is_proper(w["w"], story_words):
            continue
        nxt = _core(words[i + 1]["w"]).lower() if i + 1 < len(words) else ""
        nxt2 = _core(words[i + 2]["w"]).lower() if i + 2 < len(words) else ""
        if nxt in STREET_TYPES or (is_proper(words[i + 1]["w"], story_words) and nxt2 in STREET_TYPES
                                   if i + 1 < len(words) else False):
            continue                              # "Ellis Court", "Buck Owens Blvd"
        if _core(w["w"]).lower() in _street_words() and i > 0 and \
                _core(words[i - 1]["w"]).lower() in {"on", "at", "near", "of", "off", "from", "to"}:
            continue                              # "near Jefferson": a place, not a person
        trail = w["w"][len(w["w"].rstrip(".,?!;:")):]
        w.update(w="•••" + trail, redacted=True)
        prev = words[i - 1] if i > 0 else None
        # "Sam Robertson": a capitalized word right before a name is part of it,
        # unless it starts the phrase or is itself a street type.
        if prev and not prev.get("redacted") and re.match(r"^[A-Z][a-z]+$", _core(prev["w"])) \
                and _core(prev["w"]).lower() not in STREET_TYPES and i - 1 > 0 \
                and not words[i - 2]["w"].endswith((".", "?", "!")):
            prev.update(w="•••", redacted=True)


def anchors_of(story: dict) -> tuple[set, set]:
    text = " ".join(story.get(k, "") for k in ("headline", "label", "where", "subhead", "place"))
    toks = {t.lower() for t in re.findall(r"[A-Za-z]+", text)}
    places = {t for t in re.findall(r"\b[A-Z][a-z]{3,}\b", text)} - {"Bakersfield", "Kern"}
    events = toks & EVENT_WORDS
    return {p.lower() for p in places} - STOP - EVENT_WORDS, events


def fix_place(word: str, places: list[str]) -> str:
    """'Culpice' -> 'Copus' when the story names Copus. Only words that look like
    a misheard version of one of the story's own place names are touched."""
    core = re.sub(r"[^A-Za-z]", "", word)
    if len(core) < 4 or not places:
        return word
    best = max(places, key=lambda p: difflib.SequenceMatcher(None, core.lower(), p.lower()).ratio())
    r = difflib.SequenceMatcher(None, core.lower(), best.lower()).ratio()
    if r >= 0.72 and core != best:      # also fixes case: "grace" -> "Grace"
        return word.replace(core, best)
    return word


_MODEL = None


def transcribe(path: str, t0: float, t1: float) -> list[dict]:
    """Words of the soundtrack between t0 and t1, timed on the soundtrack's clock.
    Each story's slot is cut out and transcribed on its own, so a word can only
    ever land on its own story's card (the whole-mix pass let the last words of
    story 1 drift onto story 2, 2026-10-20)."""
    import subprocess
    import tempfile
    from faster_whisper import WhisperModel
    import make_dispatch_audio as MDA    # same model and settings as the clip checks
    global _MODEL
    if _MODEL is None:
        _MODEL = WhisperModel(MDA.WHISPER, device="cpu", compute_type="int8", cpu_threads=8)
    fd, wav = tempfile.mkstemp(suffix=".wav"); os.close(fd)
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
                        "-i", path, "-ac", "1", "-ar", "16000", wav], check=True)
        segs, _ = _MODEL.transcribe(wav, language="en", word_timestamps=True, vad_filter=True,
                                    beam_size=5, condition_on_previous_text=False)
        words = [{"w": w.word.strip(), "s": t0 + float(w.start), "e": min(t1, t0 + float(w.end))}
                 for seg in segs for w in (seg.words or [])]
    finally:
        os.remove(wav)
    return [w for w in words if w["w"]]


def from_audit(rec: dict, t0: float, t1: float) -> list[dict]:
    """Fallback words for one slot: the clip builder's own verified transcript,
    spread evenly over the clip's measured speech. Timing is approximate, the
    words are not: they passed the builder's two-pass check."""
    text = " ".join(rec.get("verified_transcript") or []).split()
    if not text:
        return []
    span = min(t1 - t0, float(rec.get("speech_s") or rec.get("cut_s") or (t1 - t0)))
    step = span / len(text)
    return [{"w": w, "s": t0 + k * step, "e": t0 + (k + 1) * step * 0.95}
            for k, w in enumerate(text)]


def cues_for(words: list[dict]) -> list[dict]:
    cues, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > GAP_BREAK
                    or len(" ".join(x["w"] for x in cur + [w])) > CUE_CHARS):
            cues.append(cur); cur = []
        cur.append(w)
        if w["w"].endswith((".", "?", "!")) and len(" ".join(x["w"] for x in cur)) > 18:
            cues.append(cur); cur = []
    if cur:
        cues.append(cur)
    prev_end = True                     # capital only where a sentence starts
    for c in cues:
        w0 = c[0]
        if prev_end and w0["w"][:1].isalpha() and not w0.get("redacted"):
            w0["w"] = w0["w"][:1].upper() + w0["w"][1:]
        prev_end = c[-1]["w"].endswith((".", "?", "!"))
    return [{"s": c[0]["s"], "e": c[-1]["e"], "words": c} for c in cues]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True)
    ap.add_argument("--soundtrack", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--muted-out", default=None,
                    help="write the soundtrack with every blanked word muted")
    ap.add_argument("--report", default=None,
                    help="write per-story match results as JSON (for the publisher)")
    a = ap.parse_args()

    brief = json.load(open(a.brief, encoding="utf-8"))
    audit = json.load(open(a.audit, encoding="utf-8"))
    slot = float(audit["story_len"])
    stories = brief["stories"]

    all_cues, report, bad = [], [], 0
    verified = [s for s in audit.get("stories", []) if s.get("verify_ok") and s.get("cut_ok")]
    for i, story in enumerate(stories):
        t0, t1 = LEAD_S + i * slot, LEAD_S + (i + 1) * slot
        try:
            mine = transcribe(a.soundtrack, t0, t1)
        except Exception as exc:  # noqa: BLE001  (captions must never stop the reel)
            mine = from_audit(verified[i] if i < len(verified) else {}, t0, t1)
            print(f"WARN story {i + 1}: word timing failed ({exc}); captions from the "
                  f"clip builder's verified transcript, timed approximately", file=sys.stderr)
        places, events = anchors_of(story)
        said = {re.sub(r"[^a-z]", "", w["w"].lower()) for w in mine}
        place_names = sorted({p.title() for p in places} | STREET_WORDS)
        fix_words = place_names + sorted(events)    # "shops heard" -> "shots heard"
        hits_place = {p for p in places if any(difflib.SequenceMatcher(None, p, s).ratio() >= 0.8
                                               for s in said if len(s) >= 4)}
        hits_event = events & said
        ok = bool(hits_place or hits_event)
        heard = " ".join(w["w"] for w in mine)
        report.append({"story": i + 1, "label": story.get("label") or story["headline"],
                       "match": ok, "place_hits": sorted(hits_place),
                       "event_hits": sorted(hits_event), "heard": heard})
        if not ok:
            bad += 1
            continue
        out_words, prev = [], ""
        for w in mine:
            text = fix_place(w["w"], fix_words)
            text, red = redact(text)
            if NAME_CUES.match(re.sub(r"[^\w]", "", prev)) and re.match(r"^[A-Z][a-z]+", text):
                text, red = "•••", True      # a name after "subject", "named", ...
            out_words.append({"w": text, "s": round(w["s"], 3), "e": round(w["e"], 3),
                              **({"redacted": True} if red else {})})
            prev = w["w"]
        redact_names(out_words, set(fix_words))
        # A number the transcriber split ("4 ,300") is one house number: a digit
        # token next to a blanked one goes with it.
        for k, x in enumerate(out_words):
            if not x.get("redacted") and re.fullmatch(r"[\d,.]+", x["w"].strip(",. ")) and any(
                    0 <= j < len(out_words) and out_words[j].get("redacted") for j in (k - 1, k + 1)):
                x.update(w="•••", redacted=True)
        # Numbers spoken as words ("seven twenty-four Grace") are a house number too.
        k = 0
        while k < len(out_words):
            j = k
            while j < len(out_words) and NUMBER_WORD.match(re.sub(r"[^\w-]", "", out_words[j]["w"]).lower()):
                j += 1
            if j - k >= 2:
                for x in out_words[k:j]:
                    trail = x["w"][len(x["w"].rstrip(".,?!;:")):]
                    x.update(w="•••" + trail, redacted=True)
            k = max(j, k + 1)
        for c in cues_for(out_words):
            c["e"] = min(c["e"], t1 - 0.05)
            all_cues.append(c)

    # The radio says house numbers out loud ("724 Grace Street"). Blanking them on
    # screen is not enough: mute the same spans in the audio the viewer hears.
    spans = [(max(0.0, w["s"] - 0.06), w["e"] + 0.06)
             for c in all_cues for w in c["words"] if w.get("redacted")]
    if a.muted_out:
        import subprocess
        if spans:
            cond = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in spans)
            flt = f"volume=enable='{cond}':volume=0"
        else:
            flt = "anull"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", a.soundtrack, "-af", flt,
                        "-c:a", "libmp3lame", "-b:a", "192k", a.muted_out], check=True)
        print(f"muted {len(spans)} span(s) -> {a.muted_out}")

    brief["captions"] = all_cues
    brief["style"] = "night"
    json.dump(brief, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for r in report:
        mark = "MATCH   " if r["match"] else "MISMATCH"
        print(f"{mark} story {r['story']} {r['label']!r}: place {r['place_hits']} "
              f"event {r['event_hits']} | heard: {r['heard']}")
    print(f"captions: {len(all_cues)} cues -> {a.out}")
    if a.report:
        json.dump({"stories": report}, open(a.report, "w", encoding="utf-8"), indent=1,
                  ensure_ascii=False)
    return 3 if (bad and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
