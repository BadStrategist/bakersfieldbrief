"""The reel soundtrack: a clip with no usable voice is never mixed, and the mix
cannot ship quiet.

2026-10-12: both clips were cut from dead air (whisper had stamped the matched
line 0.00 to 29.98 s of a probe whose first 24 s were silence), both
re-transcribed to nothing, both were mixed anyway, and the reel was published at
-35.6 LUFS: the music bed alone. 2026-10-09: the card read "Shots fired on the
5400 block of Pembroke Avenue" and played a brake fire, because the word "fire"
on its own was worth 5 points.

No whisper and no network here. The tests that need real audio make it with
ffmpeg. Without ffmpeg and ffprobe they skip on a dev machine and FAIL in CI:
CI installs a pinned build (.github/actions/setup-ffmpeg), so a missing binary
there is a broken run, never a quiet skip.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "brief_reel"))
import make_dispatch_audio as mda  # noqa: E402

RAG = mda.RAG
_NO_FFMPEG = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]


@pytest.fixture
def _ffmpeg():
    if not _NO_FFMPEG:
        return
    missing = " and ".join(_NO_FFMPEG) + " not on PATH"
    if os.environ.get("CI"):
        pytest.fail(f"{missing}: CI installs a pinned build, so this run is broken", pytrace=False)
    pytest.skip(missing)


needs_ffmpeg = pytest.mark.usefixtures("_ffmpeg")

ROBBERY = {"headline": "Incident reported on the 2600 block of Mount Vernon Avenue",
           "time": "8:19 PM",
           "place": "THE 2600 BLOCK OF MOUNT VERNON AVENUE, AT THE DOLLAR TREE"}
ROBBERY_ROW = ("211 at the Dollar Tree, with Machete, 2682 Mount Vernon Avenue, the "
               "two subjects, they were last seen toward the Taco Bell")
SHOTS = {"headline": "Shots fired on the 5400 block of Pembroke Avenue",
         "time": "1:22 AM", "place": "THE 5400 BLOCK OF PEMBROKE AVENUE"}
SHOTS_ROW = ("apartment 161, break Medic Squad 63, medical aid to station 61's "
             "area, 5420 Pembroke Avenue,")
BRAKE_FIRE = ("He advised there's flames that are coming from the front brakes. "
              "He extinguished a fire, but now he's 1126 and needs to get to the "
              "TA Center.")


def timed(text, t0, step=0.3):
    """Word dicts for `text`, the first one starting at t0."""
    return [{"start": t0 + n * step, "end": t0 + n * step + 0.25, "word": w}
            for n, w in enumerate(text.split())]


def one_segment(words, start=0.0, end=29.98):
    """A whisper segment as the 30 s chunker stamps it: the chunk, not the speech."""
    return [{"start": start, "end": end, "text": " ".join(w["word"] for w in words),
             "words": words}]


# --------------------------------------------------------------------------- #
# where the cut starts
# --------------------------------------------------------------------------- #
def test_the_cut_starts_on_the_first_word_not_on_the_segment_stamp(monkeypatch):
    """The 2026-10-12 probe: one segment stamped 0.00 to 29.98, speech at 24.7."""
    words = timed("211 at the Dollar Tree, with Machete, 2682 Mt. Vernon Avenue.", 24.74)
    monkeypatch.setattr(mda, "transcribe", lambda *a, **k: one_segment(words))
    beat = mda.find_beat(ROBBERY, ROBBERY_ROW, "probe.wav", 0.0, 25.0, 12.0)
    assert beat is not None
    assert beat["start"] == pytest.approx(24.74)
    assert beat["start"] > 20, "a cut at the segment stamp is 12 s of dead air"


def test_a_clip_may_start_after_a_pause_or_a_full_stop_and_nowhere_else():
    words = (timed("Copy that. Units responding", 1.0)
             + timed("to Pembroke Avenue", 9.0))
    starts = mda.utterance_starts(words)
    assert starts == [pytest.approx(1.0), pytest.approx(1.6), pytest.approx(9.0)]


# --------------------------------------------------------------------------- #
# which window is the story's
# --------------------------------------------------------------------------- #
def test_a_drama_word_alone_never_picks_a_window(monkeypatch):
    """2026-10-09: nothing in the probe named Pembroke, so there is no clip.
    The brake fire still scores (that was the defect) and is still refused."""
    words = timed(BRAKE_FIRE, 30.0)
    monkeypatch.setattr(mda, "transcribe", lambda *a, **k: one_segment(words))
    assert mda.score_window(BRAKE_FIRE, SHOTS) >= 3
    assert mda.anchor(BRAKE_FIRE, SHOTS, SHOTS_ROW)["ok"] is False
    assert mda.find_beat(SHOTS, SHOTS_ROW, "probe.wav", 0.0, 25.0, 8.3) is None


def test_the_window_that_names_the_street_beats_the_dramatic_one(monkeypatch):
    words = (timed("Medic Squad 63, medical aid, 5420 Pembroke Avenue.", 5.0)
             + timed(BRAKE_FIRE, 30.0))
    monkeypatch.setattr(mda, "transcribe", lambda *a, **k: one_segment(words))
    beat = mda.find_beat(SHOTS, SHOTS_ROW, "probe.wav", 0.0, 25.0, 8.3)
    assert beat["start"] == pytest.approx(5.0)
    assert "Pembroke" in beat["text"]


@pytest.mark.parametrize("text,story,hit", [
    ("food max, 64-65 Nile Street", {"place": "THE 6400 BLOCK OF NILES STREET"}, True),
    ("5420 Pembroke Avenue", SHOTS, True),
    ("6520 Pembroke Avenue", SHOTS, False),
    ("54 units on scene", SHOTS, False),
    ("1801, University Avenue", {"place": "1801 UNIVERSITY AVENUE"}, True),
    ("1811, University Avenue", {"place": "1801 UNIVERSITY AVENUE"}, False),
])
def test_a_block_number_matches_an_address_inside_that_block(text, story, hit):
    assert mda.number_hit(text, story) is hit


def test_a_place_with_no_street_is_anchored_by_the_matched_row():
    story = {"headline": "Incident reported on southbound Interstate 5 north of the rest area",
             "place": "SOUTHBOUND INTERSTATE 5 NORTH OF THE REST AREA"}
    row = "Start of break, southbound I-5, north of the rest area."
    assert mda.place_tokens(story) == []
    assert mda.anchor("Start a break, southbound I-5, north of the rest area.",
                      story, row)["ok"] is True
    assert mda.anchor("Engine 53 is on scene northbound, north of the exit.",
                      story, row)["ok"] is False


# --------------------------------------------------------------------------- #
# a clip that does not verify is dropped, never mixed
# --------------------------------------------------------------------------- #
GOOD = ["211 at the Dollar Tree with machete, 2682 Mount Vernon Avenue."]
LOOP = ["2 5 " + "5 " * 60]


def _pick(i, story=ROBBERY, row=ROBBERY_ROW):
    return {"i": i, "story": story, "src": "block.mp3", "start": 100.0,
            "row_text": row, "label": "block.mp3",
            "rec": {"index": i, "headline": story["headline"],
                    "beat_text": "211 at the Dollar Tree, with Machete, 2682 Mt. Vernon Avenue."}}


@pytest.fixture
def studio(monkeypatch, tmp_path):
    """check_clip with every ffmpeg and whisper call replaced. `cuts[i]` is what
    clip i re-transcribes to, `speech[i]` the audible speech in it, `length[i]`
    how long the cut came back (default: as long as was asked for) and `lufs[i]`
    where the trim left it (default: on the target)."""
    box = {"cuts": {}, "ladder": {}, "speech": {}, "length": {}, "lufs": {},
           "asked": {}, "levelled": []}

    def clip_no(path):
        return int(re.match(r"s(\d+)", os.path.basename(path)).group(1))

    def fake_transcribe(path, offset=0.0, **kw):
        i = clip_no(path)
        lines = box["cuts"].get(i, [])
        if kw.get("fallback") and i in box["ladder"]:
            lines = box["ladder"][i]
        return [{"start": 0.0, "end": 1.0, "text": t} for t in lines]

    def fake_cut(src, ss, t, dst, **kw):
        box["asked"][clip_no(dst)] = t
        return True

    def fake_length(path):
        i = clip_no(path)
        return box["length"].get(i, box["asked"][i])

    def fake_speech(path, noise=None):
        return box["speech"].get(clip_no(path), 8.0)

    def fake_level(src, dst, target):
        box["levelled"].append(os.path.basename(dst))
        return {"lufs": box["lufs"].get(clip_no(dst), target), "peak": -2.0,
                "gain_db": 1.0, "from_lufs": target - 1.0}

    monkeypatch.setattr(mda, "transcribe", fake_transcribe)
    monkeypatch.setattr(mda, "cut", fake_cut)
    monkeypatch.setattr(mda, "level_to", fake_level)
    monkeypatch.setattr(RAG, "speech_seconds", fake_speech)
    monkeypatch.setattr(RAG, "duration", fake_length)
    box["check"] = lambda p, n: mda.check_clip(p, n, str(tmp_path))
    return box


@pytest.mark.parametrize("cut_text,speech,says", [
    ([], 8.0, "empty"),                                   # 2026-10-12, both clips
    (LOOP, 8.0, "loop"),                                  # 2026-10-08
    (["Okay."], 8.0, "1 word"),
    (GOOD, 0.5, "audible speech"),                        # text, but dead air
    (GOOD, None, "could not be measured"),                # no measurement, no pass
    (["He extinguished a fire but now he needs to get to the TA Center."], 8.0,
     "other than the beat"),                              # the wrong seconds
])
def test_a_degenerate_clip_is_refused_and_says_why(studio, cut_text, speech, says):
    studio["cuts"][1], studio["speech"][1] = cut_text, speech
    p = _pick(1)
    assert studio["check"](p, 12.0) is None
    assert p["rec"]["verify_ok"] is False
    assert says in p["rec"]["verify_reason"]
    assert studio["levelled"] == [], "a refused clip must not reach the mix chain"


def test_a_clip_that_verifies_is_levelled_and_kept(studio):
    studio["cuts"][1] = GOOD
    p = _pick(1)
    assert studio["check"](p, 12.0).endswith("s1.wav")
    assert p["rec"]["verify_ok"] is True and "verify_reason" not in p["rec"]
    assert p["rec"]["piece_lufs"] == RAG.VOICE_LUFS


def test_a_whisper_loop_gets_the_temperature_ladder_before_the_clip_is_refused(studio):
    """A loop is the ASR failing, not always the audio. The ladder's text still
    has to be the picked beat: a readable wrong answer is refused like any other."""
    studio["cuts"][1], studio["ladder"][1] = LOOP, GOOD
    p = _pick(1)
    assert studio["check"](p, 12.0) is not None
    assert p["rec"]["verified_transcript"] == GOOD

    studio["cuts"][2], studio["ladder"][2] = LOOP, ["Thank you for watching, see you next time."]
    q = _pick(2)
    assert studio["check"](q, 12.0) is None
    assert q["rec"]["verify_ok"] is False
    assert "loop" in q["rec"]["verify_reason"], "the first hearing is the one on record"


def test_a_right_sentence_with_a_looping_tail_is_still_the_right_clip(studio):
    """2026-10-10, north Chester: whisper read the transmission, then looped."""
    story = {"headline": "Incident reported on north Chester Avenue",
             "place": "NORTH CHESTER AVENUE"}
    studio["cuts"][1] = ["10-4, start to back via north and north Chester, our current "
                         "time to go, start P-6-5-1" + "-2-4-5-0-1" * 40]
    p = _pick(1, story, "RP's left the area, north and north Chester")
    p["rec"]["beat_text"] = "start to back via north and north Chester. Occurred 10 ago"
    assert RAG.transcript_problem(studio["cuts"][1]) is None
    assert studio["check"](p, 8.3) is not None
    assert RAG.collapse_loops("a b c b c b c d".split()) == ["a", "b", "c", "d"]
    assert RAG.collapse_loops(["5"] * 40) == ["5"]


def test_the_reel_is_repaced_over_the_clips_that_verified(studio):
    studio["cuts"] = {1: [], 2: GOOD, 3: GOOD}
    picks = [_pick(1), _pick(2), _pick(3)]
    kept, story_len, dropped = mda.pace_and_verify(picks, studio["check"])
    assert [p["i"] for p, _piece in kept] == [2, 3]
    assert [p["i"] for p in dropped] == [1]
    assert story_len == mda.plan_story_len(2) == 12.0
    assert all(p["rec"]["seconds"] == 12.0 for p, _piece in kept)


def test_no_verified_clip_means_nothing_is_kept(studio):
    studio["cuts"] = {1: [], 2: LOOP}
    kept, _len, dropped = mda.pace_and_verify([_pick(1), _pick(2)], studio["check"])
    assert kept == [] and len(dropped) == 2


# --------------------------------------------------------------------------- #
# the three numbers that were logged and compared with nothing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("speech,slot,kept,says", [
    (2.0, 20.0, False, "mostly dead air"),      # 10 percent of the cut: it passed
    (4.9, 20.0, False, "mostly dead air"),
    (5.0, 20.0, True, None),                    # a quarter of the slot
    (2.9, 12.0, False, "mostly dead air"),
    (3.0, 12.0, True, None),
    (2.0, 6.0, True, None),                     # the same 2 s fills a 6 s slot
    (1.4, 6.0, False, "no usable audio"),       # under the floor at any length
    (0.5, 20.0, False, "no usable audio"),
])
def test_the_speech_a_clip_needs_grows_with_its_slot(studio, speech, slot, kept, says):
    studio["cuts"][1], studio["speech"][1] = GOOD, speech
    p = _pick(1)
    assert (studio["check"](p, slot) is not None) is kept
    assert p["rec"]["verify_ok"] is kept
    assert p["rec"]["speech_share"] == pytest.approx(speech / slot, abs=0.01)
    if says:
        assert says in p["rec"]["verify_reason"]
        assert studio["levelled"] == []


def test_the_speech_floor_is_a_share_of_the_slot_and_never_under_the_absolute_one():
    assert RAG.speech_floor(4.0) == RAG.MIN_SPEECH_S == 1.5
    assert RAG.speech_floor(8.0) == pytest.approx(2.0)
    assert RAG.speech_floor(20.0) == pytest.approx(5.0)


def test_a_clip_that_fills_a_short_slot_can_fail_the_long_one_it_is_repaced_to(studio):
    """Clip 2 drops, the slots grow from 8.3 s to 12 s, and clip 1's 2.5 s of
    speech is no longer a quarter of its slot. It is dropped, not stretched."""
    studio["cuts"] = {1: GOOD, 2: [], 3: GOOD}
    studio["speech"] = {1: 2.5, 3: 9.0}
    kept, story_len, dropped = mda.pace_and_verify(
        [_pick(1), _pick(2), _pick(3)], studio["check"])
    assert [p["i"] for p, _piece in kept] == [3]
    assert story_len == mda.plan_story_len(1) == 20.0
    assert [p["i"] for p in dropped] == [2, 1]
    assert "mostly dead air" in dropped[1]["rec"]["verify_reason"]


@pytest.mark.parametrize("lufs,kept", [(-16.0, True), (-16.9, True), (-15.1, True),
                                       (-17.1, False), (-14.9, False),
                                       (-24.0, False), (-32.4, False)])
def test_a_clip_that_does_not_measure_at_the_voice_level_is_not_mixed(studio, lufs, kept):
    """The level was written to the audit log and nothing read it."""
    studio["cuts"][1], studio["lufs"][1] = GOOD, lufs
    p = _pick(1)
    assert (studio["check"](p, 12.0) is not None) is kept
    assert p["rec"]["verify_ok"] is kept
    assert p["rec"]["piece_lufs"] == lufs
    if not kept:
        assert f"{lufs:.1f} LUFS" in p["rec"]["verify_reason"]


def test_a_short_cut_is_judged_against_its_slot_and_its_padding_is_on_record(studio):
    """The 2026-10-12 dispatch 6.2 s before the end of its block."""
    studio["cuts"][1], studio["length"][1], studio["speech"][1] = GOOD, 6.16, 4.45
    p = _pick(1)
    assert studio["check"](p, 25 / 3) is not None
    assert p["rec"]["cut_s"] == 6.16 and p["rec"]["pad_s"] == 2.17
    assert p["rec"]["speech_share"] == 0.53

    studio["cuts"][2], studio["length"][2], studio["speech"][2] = GOOD, 3.0, 2.0
    q = _pick(2)
    assert studio["check"](q, 25 / 3) is None, "2 s of speech and 6.3 s of padding"
    assert "mostly dead air" in q["rec"]["verify_reason"]


def test_a_cut_whose_length_cannot_be_measured_is_refused(studio):
    studio["cuts"][1], studio["length"][1] = GOOD, None
    p = _pick(1)
    assert studio["check"](p, 12.0) is None
    assert "could not be measured" in p["rec"]["verify_reason"]


@pytest.mark.parametrize("scenes,reel_s,says", [
    (3, 30.0, None),
    (3, 30.05, None),                            # an encoder's padding
    (3, 27.82, "the reel runs 27.82 s"),         # the short cut, unpadded
    (2, 30.0, "2 scenes"),                       # a story with no clip got a scene
    (4, 30.0, "4 scenes"),
    (None, 30.0, "brief.json"),
    (3, None, "could not be measured"),
])
def test_the_picture_is_on_the_clip_plan_or_it_is_a_problem(scenes, reel_s, says):
    audit = {"reel_indices": [0, 1, 2], "story_len": 25 / 3}
    problems = RAG.timeline_problems(audit, scenes, reel_s)
    if says is None:
        assert problems == []
    else:
        assert len(problems) == 1 and says in problems[0]


@pytest.mark.parametrize("audit", [None, {}, {"reel_indices": [0]},
                                   {"reel_indices": [], "story_len": 12.0},
                                   {"reel_indices": [0], "story_len": 0}])
def test_an_audit_with_no_clip_plan_cannot_vouch_for_the_timeline(audit):
    assert RAG.timeline_problems(audit, 1, 25.0) != []


# --------------------------------------------------------------------------- #
# the builder end to end: what reaches the mixer, what it exits with
# --------------------------------------------------------------------------- #
DATE = "2026-10-12"
CRASH = {"headline": "Vehicle vs. pedestrian on Panama Lane and Pebble Point",
         "time": "8:06 PM", "place": "PANAMA LANE AND PEBBLE POINT"}
CRASH_ROW = "Local Traffic Unit 4901P, Panama and Pebble Point for vehicle versus pedestrian."


@pytest.fixture
def night(studio, monkeypatch, tmp_path):
    """A one-block night with two stories, and a mixer that only records."""
    root = tmp_path / "root"
    (root / "transcripts").mkdir(parents=True)
    (root / "audio" / DATE).mkdir(parents=True)
    blk = "14029-1791773560.mp3"
    (root / "audio" / DATE / blk).write_bytes(b"")
    rows = [{"text": ROBBERY_ROW, "time_local": "20:19", "source_file": blk, "offset_s": 1634.6},
            {"text": CRASH_ROW, "time_local": "20:06", "source_file": blk, "offset_s": 855.6}]
    (root / "transcripts" / f"{DATE}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"stories": [ROBBERY, CRASH], "music": "bed.mp3"}),
                     encoding="utf-8")
    out = tmp_path / "soundtrack.mp3"
    probes = {1: timed(ROBBERY_ROW, 1634.6), 2: timed(CRASH_ROW, 855.6)}
    cuts = studio["transcribe_cut"] = mda.transcribe
    mixed, slots = [], []

    def fake_transcribe(path, offset=0.0, **kw):
        name = os.path.basename(path)
        if name.endswith("_probe.wav"):
            return one_segment(probes[int(name[1])], start=offset, end=offset + 29.98)
        return cuts(path, offset=offset, **kw)

    def fake_mix(pieces, slot, bed, outp, scratch, no_bed=False):
        mixed.append([os.path.basename(p) for p in pieces])
        slots.append(slot)
        Path(outp).write_bytes(b"mp3")
        return {"mix_lufs": -16.0, "mix_peak_db": -2.0}

    monkeypatch.setattr(mda, "transcribe", fake_transcribe)
    monkeypatch.setattr(mda, "mix_soundtrack", fake_mix)
    monkeypatch.setattr(sys, "argv", ["make_dispatch_audio.py", "--date", DATE,
                                      "--brief", str(brief), "--out", str(out),
                                      "--root", str(root)])

    def build():
        with pytest.raises(SystemExit) as exc:
            mda.main()
            raise SystemExit(0)
        audit = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        return exc.value.code, audit

    return {"build": build, "mixed": mixed, "slots": slots, "out": out, "studio": studio}


def test_when_no_clip_verifies_nothing_is_mixed_and_the_build_is_held(night):
    """2026-10-12, as it should have gone."""
    night["studio"]["cuts"] = {1: [], 2: []}
    night["out"].write_bytes(b"yesterday's soundtrack")
    code, audit = night["build"]()
    assert code == mda.EXIT_HELD == 4
    assert night["mixed"] == [], "a degenerate clip reached the mixer"
    assert not night["out"].exists(), "a held build must leave no soundtrack to publish"
    assert audit["outcome"] == "held" and audit["reel_indices"] == []
    assert all(s["verify_ok"] is False and s["dropped"] for s in audit["stories"])


def test_a_degenerate_clip_is_left_out_of_the_mix_and_the_build_says_so(night):
    night["studio"]["cuts"] = {1: [], 2: [CRASH_ROW]}
    code, audit = night["build"]()
    assert code == mda.EXIT_DEGRADED == 2
    assert night["mixed"] == [["s2.wav"]], "only the verified clip may be mixed"
    assert audit["outcome"] == "degraded" and audit["reel_indices"] == [1]
    assert audit["stories"][0]["verify_reason"] == "re-transcription came back empty"
    assert audit["duration"] == mda.LEAD + mda.plan_story_len(1) + mda.TAIL
    assert night["slots"] == [audit["story_len"]], "the mix lays each clip into its slot"


def test_a_quiet_clip_and_a_sparse_clip_are_dropped_by_the_build(night):
    """The two refusals this file added, through main: exit, audit and mixer."""
    night["studio"]["cuts"] = {1: GOOD, 2: [CRASH_ROW]}
    night["studio"]["lufs"][1] = -24.0
    code, audit = night["build"]()
    assert code == mda.EXIT_DEGRADED and night["mixed"] == [["s2.wav"]]
    assert "-24.0 LUFS" in audit["stories"][0]["verify_reason"]

    night["mixed"].clear()
    night["studio"]["lufs"].clear()
    night["studio"]["speech"] = {1: 2.0, 2: 2.0}     # 2 s in a 12 s, then a 20 s, slot
    code, audit = night["build"]()
    assert code == mda.EXIT_HELD and night["mixed"] == []
    assert all("mostly dead air" in s["verify_reason"] for s in audit["stories"])


def test_every_clip_verified_is_a_clean_build(night):
    night["studio"]["cuts"] = {1: GOOD, 2: [CRASH_ROW]}
    code, audit = night["build"]()
    assert code == 0
    assert night["mixed"] == [["s1.wav", "s2.wav"]]
    assert audit["outcome"] == "ok" and audit["reel_indices"] == [0, 1]
    assert RAG.audit_problems(audit) == []


def test_a_refused_mix_is_held_too(night, monkeypatch):
    def refuse(*a, **k):
        raise mda.MixError("the mix measures -35.6 LUFS before normalising")
    night["studio"]["cuts"] = {1: GOOD, 2: [CRASH_ROW]}
    monkeypatch.setattr(mda, "mix_soundtrack", refuse)
    code, audit = night["build"]()
    assert code == mda.EXIT_MIX == 5
    assert audit["outcome"] == "held" and "-35.6" in audit["held_reason"]
    assert RAG.audit_problems(audit) != []


# --------------------------------------------------------------------------- #
# the audit log, as the publisher reads it
# --------------------------------------------------------------------------- #
# The log the builder wrote on 2026-10-12, trimmed to the fields that matter.
AUDIT_1012 = {
    "date": "2026-10-12", "bed": "reel_bed_3.mp3", "bed_db": -18,
    "stories": [
        {"index": 1, "headline": "Incident reported on the 2600 block of Mount Vernon Avenue",
         "cut_ok": True, "verified_transcript": [], "verify_ratio": 0.0,
         "verify_score": 0, "verify_ok": False, "seconds": 12.0},
        {"index": 2, "headline": "Incident reported on southbound Interstate 5 north of the rest area",
         "cut_ok": True, "verified_transcript": [], "verify_ratio": 0.0,
         "verify_score": 0, "verify_ok": False, "seconds": 12.0},
        {"index": 3, "headline": "Vehicle vs. pedestrian on Panama Lane and Pebble Point",
         "error": "no keyword-matched beat in the transcript (ASR failed?)"}],
    "duration": 29.0, "story_len": 12.0, "reel_indices": [0, 1]}


def test_the_2026_10_12_audit_log_vouches_for_nothing():
    problems = RAG.audit_problems(AUDIT_1012)
    assert any("story 1 is in the reel without a verified clip" in p for p in problems)
    assert any("story 2 is in the reel without a verified clip" in p for p in problems)
    assert any("outcome" in p for p in problems), "an audit with no outcome predates the gate"


@pytest.mark.parametrize("audit", [None, {}, {"outcome": "ok"}, {"outcome": "ok", "reel_indices": []},
                                   {"outcome": "held", "reel_indices": [0],
                                    "stories": [{"index": 1, "verify_ok": True}]},
                                   {"outcome": "ok", "reel_indices": [0],
                                    "stories": [{"index": 1, "verify_ok": None}]},
                                   {"outcome": "ok", "reel_indices": [1],
                                    "stories": [{"index": 1, "verify_ok": True}]}])
def test_an_audit_log_that_does_not_vouch_is_a_problem(audit):
    assert RAG.audit_problems(audit) != []


@pytest.mark.parametrize("lines,bad", [
    ([], True), ([""], True), (["Okay."], True), (LOOP, True),
    (["2-5-5-5-5-5-5-5-5-5-5-5-5-5-5-5-5-5-5-5"], True),
    (GOOD, False),
    (["One vehicle is described as a newer model, red Hyundai, fled northbound Union."], False),
])
def test_what_counts_as_a_usable_re_transcription(lines, bad):
    assert (RAG.transcript_problem(lines) is not None) is bad


# --------------------------------------------------------------------------- #
# real audio: the mix cannot ship quiet
# --------------------------------------------------------------------------- #
def _make(path, source, seconds):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t",
                    str(seconds), "-i", source, "-c:a", "pcm_s16le", "-ar", "16000",
                    "-ac", "1", str(path)], check=True)
    return str(path)


@pytest.fixture
def tracks(tmp_path):
    """A 'voice' at radio level, 12 s of dead air, and a music bed at -18 LUFS."""
    return {
        "voice": _make(tmp_path / "voice_piece.wav", "anoisesrc=color=pink:amplitude=0.8", 12),
        "dead": _make(tmp_path / "dead_piece.wav", "anullsrc=r=16000:cl=mono", 12),
        "bed": _make(tmp_path / "bed.wav", "sine=frequency=220:sample_rate=44100,volume=4dB", 30),
        "out": str(tmp_path / "soundtrack.mp3"),
        "scratch": str(tmp_path),
    }


@needs_ffmpeg
def test_dead_air_holds_no_speech_and_a_voice_does(tracks):
    assert RAG.speech_seconds(tracks["dead"]) < RAG.MIN_SPEECH_S
    assert RAG.speech_seconds(tracks["voice"]) > 10
    assert RAG.loudness(tracks["dead"])["lufs"] <= -60
    assert RAG.loudness(tracks["bed"])["lufs"] == pytest.approx(-18.0, abs=2.5)
    assert RAG.loudness("no-such-file.wav") is None


@needs_ffmpeg
def test_a_mix_with_no_voice_is_refused_not_published_at_minus_35(tracks):
    """The 2026-10-12 mix: two clips of dead air and the bed under them."""
    Path(tracks["out"]).write_bytes(b"stale")
    with pytest.raises(mda.MixError) as exc:
        mda.mix_soundtrack([tracks["dead"], tracks["dead"]], 12.0, tracks["bed"],
                           tracks["out"], tracks["scratch"])
    assert "no voice track" in str(exc.value)
    assert not os.path.exists(tracks["out"]), "a refused mix must leave nothing to publish"


@needs_ffmpeg
def test_a_mix_with_a_voice_lands_on_the_stated_loudness(tracks):
    levelled = os.path.join(tracks["scratch"], "s1.wav")
    lv = mda.level_to(tracks["voice"], levelled, RAG.VOICE_LUFS)
    assert lv["lufs"] == pytest.approx(RAG.VOICE_LUFS, abs=1.5)
    info = mda.mix_soundtrack([levelled, levelled], 12.0, tracks["bed"], tracks["out"],
                              tracks["scratch"])
    assert info["plan_s"] == 29.0
    assert info["measured_s"] == pytest.approx(29.0, abs=RAG.PLAN_TOLERANCE)
    assert info["mix_lufs"] == pytest.approx(RAG.MIX_LUFS, abs=RAG.MIX_TOLERANCE)
    assert info["mix_lufs"] >= RAG.MIN_MIX_LUFS
    assert info["mix_peak_db"] <= RAG.MAX_PEAK_DB
    assert info["bed_lufs"] + info["bed_gain_db"] == pytest.approx(RAG.BED_LUFS, abs=0.1)
    measured = RAG.loudness(tracks["out"])
    assert measured["lufs"] == pytest.approx(RAG.MIX_LUFS, abs=RAG.MIX_TOLERANCE)


@needs_ffmpeg
def test_a_quiet_clip_is_brought_up_to_the_voice_level(tracks, tmp_path):
    quiet = _make(tmp_path / "quiet.wav", "anoisesrc=color=pink:amplitude=0.3", 8)
    assert RAG.loudness(quiet)["lufs"] < -24
    lv = mda.level_to(quiet, str(tmp_path / "s9.wav"), RAG.VOICE_LUFS)
    assert lv["lufs"] == pytest.approx(RAG.VOICE_LUFS, abs=RAG.CLIP_TOLERANCE)
    assert 0 < lv["gain_db"] <= RAG.MAX_VOICE_GAIN


@needs_ffmpeg
def test_near_silence_is_not_turned_up_to_the_voice_level(tracks, tmp_path):
    """The trim stops at its cap, and what it leaves is under the line a clip
    has to measure at, so check_clip refuses it."""
    hiss = _make(tmp_path / "hiss.wav", "anoisesrc=color=pink:amplitude=0.01", 8)
    lv = mda.level_to(hiss, str(tmp_path / "s8.wav"), RAG.VOICE_LUFS)
    assert lv["gain_db"] == RAG.MAX_VOICE_GAIN
    assert lv["lufs"] < RAG.VOICE_LUFS - RAG.CLIP_TOLERANCE


def _first_sound_after(path, t):
    """Where the first silence that starts after `t` ends, in seconds."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        "silencedetect=noise=-50dB:d=0.3", "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return next(e for s, e in zip(starts, ends) if s >= t)


@needs_ffmpeg
def test_a_short_clip_does_not_pull_the_next_clip_ahead_of_its_scene(tracks, tmp_path):
    """A 6 s cut in a 12 s slot. Concatenated at its own length it left the
    track 6 s short and started clip 2 at 7 s, under scene 1."""
    short = _make(tmp_path / "short_piece.wav", "anoisesrc=color=pink:amplitude=0.8", 6)
    info = mda.mix_soundtrack([short, tracks["voice"]], 12.0, tracks["bed"],
                              tracks["out"], tracks["scratch"])
    assert info["plan_s"] == 29.0
    assert RAG.duration(tracks["out"]) == pytest.approx(29.0, abs=RAG.PLAN_TOLERANCE)
    voice = os.path.join(tracks["scratch"], "voice.wav")
    assert RAG.duration(voice) == pytest.approx(29.0, abs=0.01)
    assert _first_sound_after(voice, 6.5) == pytest.approx(mda.LEAD + 12.0, abs=0.05)


@needs_ffmpeg
def test_a_long_clip_is_trimmed_to_its_slot(tracks):
    info = mda.mix_soundtrack([tracks["voice"], tracks["voice"]], 8.0, tracks["bed"],
                              tracks["out"], tracks["scratch"])
    assert info["plan_s"] == 21.0
    assert info["measured_s"] == pytest.approx(21.0, abs=RAG.PLAN_TOLERANCE)
