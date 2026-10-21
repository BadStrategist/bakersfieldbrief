"""The reel, the night card and the reel's post lead with the serious calls, every
clip is about its own story, and the captions never air what the report may not.

2026-10-20, all from one morning:
  * the reel led with "Vehicle fire in Bakersfield" (owner: "always lead with the
    serious events, not a stupid fire"), on a plain cream title card;
  * "Assault on Terrace Way" (an emulator-only call, no radio audio) aired a
    seizure call at "2627 Buck Owens Blvd";
  * the post under Tuesday night's video described Monday night's standoff.
No network, no whisper model, no ffmpeg: the transcription is stubbed.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "brief_reel"))

import make_brief_json as mbj  # noqa: E402
import build_captions as BC  # noqa: E402
from build.builders import night_counts, overnight  # noqa: E402
import scripts.brief_reel.publish_social as PS  # noqa: E402
from scripts import post_facebook as PF  # noqa: E402

# Shapes taken from incidents/2026-10-20.json.
NIGHT = [
    {"type": "vehicle fire", "time": "20:52", "notability": 4, "area": "",
     "summary": "A semi with a box trailer burned on northbound Interstate 5."},
    {"type": "weapons", "time": "21:07", "notability": 2, "area": "",
     "summary": "A caller reported two people with machetes taking copper wire from a property."},
    {"type": "shots fired", "time": "22:10", "notability": 2, "area": "Grace Street",
     "summary": "Two loud bangs were reported in the area of Grace Street."},
    {"type": "assault", "time": "04:30", "notability": 2, "area": "White Lane",
     "summary": "A woman was reported slapping a man at a White Lane apartment."},
    {"type": "weapons", "time": "23:57", "notability": 2, "area": "Lincoln Street",
     "summary": "A man carrying a large kitchen knife followed a resident through a gate."},
    {"type": "Assault", "time": "01:20", "notability": 3, "area": "Terrace Way",
     "summary": "Assault with injured man at Terrace Way apartment.", "source": "crimeradar"},
    {"type": "vegetation fire", "time": "03:08", "notability": 3, "area": "",
     "summary": "A large brush fire was reported in a field."},
]


# ------------------------------------------------------------------- ranking
def test_severity_puts_people_before_fires():
    tier = {i["time"]: night_counts.severity(i) for i in NIGHT}
    assert tier["22:10"] == 0                       # gunfire
    assert tier["21:07"] == tier["23:57"] == 1      # a weapon named
    assert tier["04:30"] == 2                       # a slap: an assault, no weapon
    assert tier["20:52"] == 4                       # a vehicle fire
    assert tier["03:08"] == 5                       # a brush fire
    assert max(tier["22:10"], tier["21:07"], tier["04:30"]) < tier["20:52"]


def test_a_standoff_is_a_weapons_call_not_other():
    assert night_counts.CHIP_OF["standoff"] == "Weapons and assaults"
    assert night_counts.severity({"type": "standoff", "summary": "Man armed with a knife."}) == 0


def test_the_night_card_never_lets_a_fire_crowd_out_a_violent_call():
    top = overnight._top_calls(NIGHT)
    types = [i["type"] for i in top]
    assert "vehicle fire" not in types and "vegetation fire" not in types
    assert [i["time"] for i in top][0] == "21:07"   # still printed in clock order
    assert len(top) == 4


def test_the_reel_leads_with_gunfire_and_skips_emulator_only_calls(monkeypatch):
    monkeypatch.setattr(mbj, "load_incidents", lambda _d: list(NIGHT))
    picked = mbj.pick_stories("2026-10-20", "", "")
    assert picked[0]["time"] == "22:10"
    assert all(p.get("source") != "crimeradar" for p in picked)
    assert {p["time"] for p in picked[:3]} == {"22:10", "21:07", "23:57"}
    # fires come last, as alternates only
    assert [p["time"] for p in picked][-2:] in (["20:52", "03:08"], ["03:08", "20:52"])


def test_a_weapons_call_is_labelled_by_its_weapon():
    s = mbj.story_json(NIGHT[1])
    assert s["label"] == "Machetes reported"
    assert mbj.story_json(NIGHT[4])["label"] == "Knife reported"
    assert mbj.story_json({"type": "weapons", "time": "01:00", "summary": "A weapons call."})["label"] \
        == "Weapons call"
    assert "Bakersfield" not in s["label"]


# ------------------------------------------------------------------ captions
def test_house_numbers_plates_and_call_signs_air():
    """Owner's rule, 2026-10-21: the dispatch radio is already public, and a caption
    full of bullets is irritating rather than informative."""
    assert BC.redact("724") == ("724", False)
    assert BC.redact("1313,") == ("1313,", False)
    assert BC.redact("7ABC123") == ("7ABC123", False)
    assert BC.redact("3-4-6") == ("3-4-6", False)


def test_misheard_story_words_are_corrected_but_others_are_left_alone():
    assert BC.fix_place("Jeferson", ["Jefferson"]) == "Jefferson"
    assert BC.fix_place("Lincon", ["Lincoln"]) == "Lincoln"
    assert BC.fix_place("shops", ["shots"]) == "shots"
    assert BC.fix_place("grace", ["Grace", "Street"]) == "Grace"
    assert BC.fix_place("hat", ["Grace"]) == "hat"


def _stub_transcription(monkeypatch, by_slot):
    def fake(path, t0, t1):
        words = by_slot[round(t0, 2)]
        step = (t1 - t0) / max(1, len(words))
        return [{"w": w, "s": t0 + k * step, "e": t0 + (k + 0.9) * step} for k, w in enumerate(words)]
    monkeypatch.setattr(BC, "transcribe", fake)


def _run_captions(tmp_path, monkeypatch, stories, by_slot, strict=True):
    brief, audit = tmp_path / "brief.json", tmp_path / "soundtrack.json"
    brief.write_text(json.dumps({"stories": stories}), encoding="utf-8")
    audit.write_text(json.dumps({"story_len": 8.0, "stories": []}), encoding="utf-8")
    out, report = tmp_path / "cap.json", tmp_path / "report.json"
    _stub_transcription(monkeypatch, by_slot)
    argv = ["build_captions.py", "--brief", str(brief), "--soundtrack", "x.mp3",
            "--audit", str(audit), "--out", str(out), "--report", str(report)]
    monkeypatch.setattr(sys, "argv", argv + (["--strict"] if strict else []))
    code = BC.main()
    return code, json.loads(out.read_text(encoding="utf-8")), \
        json.loads(report.read_text(encoding="utf-8"))["stories"]


def test_a_clip_about_another_call_is_a_mismatch_and_gets_no_captions(tmp_path, monkeypatch):
    stories = [{"headline": "Shots reported near Jefferson Park", "label": "Shots reported",
                "where": "near Jefferson Park", "subhead": "Loud bangs on Grace Street."},
               {"headline": "Assault on Terrace Way", "label": "Assault",
                "where": "on Terrace Way", "subhead": "Assault with injured man."}]
    by_slot = {1.0: "shots heard in the area of 724 Grace Street near Jefferson".split(),
               9.0: "2627 Buck Owens Blvd seizure patient going to Siena".split()}
    code, cap, report = _run_captions(tmp_path, monkeypatch, stories, by_slot)
    assert code == 3
    assert [r["match"] for r in report] == [True, False]
    shown = " ".join(w["w"] for c in cap["captions"] for w in c["words"])
    assert "Buck" not in shown and "2627" not in shown      # the other call never airs
    assert "724 Grace" in shown and "•••" not in shown      # the call's own number airs
    assert cap["style"] == "night"


def test_spoken_number_words_air(tmp_path, monkeypatch):
    stories = [{"headline": "Knife reported on Lincoln Street", "label": "Knife reported",
                "where": "on Lincoln Street", "subhead": "A man with a knife."}]
    by_slot = {1.0: "weapons possession thirteen thirteen Lincoln Street".split()}
    code, cap, _ = _run_captions(tmp_path, monkeypatch, stories, by_slot)
    assert code == 0
    words = [w for c in cap["captions"] for w in c["words"]]
    assert not [w for w in words if w.get("redacted")]
    assert "thirteen thirteen Lincoln Street" in " ".join(w["w"] for w in words)
    assert all(w["e"] <= 9.0 for w in words)          # never past its own slot


def test_captions_fall_back_to_the_verified_transcript(tmp_path, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("cublas64_12.dll is not found")
    monkeypatch.setattr(BC, "transcribe", broken)
    brief, audit = tmp_path / "brief.json", tmp_path / "soundtrack.json"
    brief.write_text(json.dumps({"stories": [{"headline": "Shots reported", "label": "Shots reported",
                                              "where": "on Grace Street", "subhead": "Bangs."}]}),
                     encoding="utf-8")
    audit.write_text(json.dumps({"story_len": 8.0, "stories": [
        {"verify_ok": True, "cut_ok": True, "speech_s": 6.0,
         "verified_transcript": ["Shots heard near Grace Street."]}]}), encoding="utf-8")
    out = tmp_path / "cap.json"
    monkeypatch.setattr(sys, "argv", ["b", "--brief", str(brief), "--soundtrack", "x",
                                      "--audit", str(audit), "--out", str(out), "--strict"])
    assert BC.main() == 0
    cues = json.loads(out.read_text(encoding="utf-8"))["captions"]
    assert " ".join(w["w"] for c in cues for w in c["words"]).startswith("Shots heard")


# ------------------------------------------------- publisher: swap, rebuild, hold
def _publisher(tmp_path, monkeypatch, exits):
    out = tmp_path / "out"
    out.mkdir()
    brief = out / "brief.json"
    brief.write_text(json.dumps({
        "stories": [{"headline": "A", "label": "Shots"}, {"headline": "B", "label": "Assault"}],
        "alternates": [{"headline": "C", "label": "Knife reported"}]}), encoding="utf-8")
    sound = out / "soundtrack.mp3"
    sound.write_bytes(b"x")
    calls = []

    def fake_run(cmd, timeout=900):
        calls.append("captions")
        code = exits.pop(0)
        if code in (0, 3):
            (out / "brief_captioned.json").write_text("{}", encoding="utf-8")
            (out / "soundtrack_muted.mp3").write_bytes(b"m")
            (out / "captions_report.json").write_text(json.dumps({"stories": [
                {"story": 1, "match": True}, {"story": 2, "match": code == 0}]}), encoding="utf-8")
        return type("R", (), {"returncode": code, "stdout": "", "stderr": ""})()

    def fake_build(date, o, b, s):
        calls.append("rebuild")
        s.write_bytes(b"y")

    monkeypatch.setattr(PS, "run", fake_run)
    monkeypatch.setattr(PS, "_build_soundtrack", fake_build)
    monkeypatch.setattr(PS, "_prune_brief_to_audio", lambda *a: None)
    return out, brief, sound, calls


def test_a_mismatched_story_is_swapped_for_the_next_and_the_audio_rebuilt(tmp_path, monkeypatch):
    out, brief, sound, calls = _publisher(tmp_path, monkeypatch, [3, 0])
    rb, ra = PS._caption_reel("2026-10-20", out, brief, sound)
    assert calls == ["captions", "rebuild", "captions"]
    assert [s["headline"] for s in json.loads(brief.read_text(encoding="utf-8"))["stories"]] == ["A", "C"]
    assert rb.name == "brief_captioned.json" and ra.name == "soundtrack_muted.mp3"


def test_the_wrong_call_never_airs_the_reel_is_held_instead(tmp_path, monkeypatch):
    out, brief, sound, calls = _publisher(tmp_path, monkeypatch, [3, 3, 3])
    brief.write_text(json.dumps({"stories": [{"headline": "B", "label": "Assault"},
                                             {"headline": "B2", "label": "Assault"}],
                                 "alternates": []}), encoding="utf-8")
    with pytest.raises(PS.ReelHeld):
        PS._caption_reel("2026-10-20", out, brief, sound)


def test_a_broken_caption_step_never_stops_the_reel(tmp_path, monkeypatch):
    out, brief, sound, calls = _publisher(tmp_path, monkeypatch, [1])
    rb, ra = PS._caption_reel("2026-10-20", out, brief, sound)
    assert (rb, ra) == (brief, sound)          # renders, uncaptioned, and says so


# -------------------------------------------------------------- the post text
def test_the_reel_post_describes_the_stories_in_the_video():
    stories = [mbj.story_json(NIGHT[2]), mbj.story_json(NIGHT[1])]
    text = PF.compose_reel_post(stories)
    assert text.startswith("\U0001f305 Overnight in Kern County: shots fired on Grace Street and machetes")
    assert "standoff" not in text.lower()
    assert "https://bakersfieldbrief.com/overnight/" in text
    assert "10:10 PM:" in text


# ----------------------------------------------------------------- the render
def test_the_caption_panel_draws_above_the_bottom_third_without_a_collision():
    import render_reel as RR
    cfg = {"brand": "B", "kicker": "K", "date_label": "D", "tagline": "T", "url": "u",
           "backgrounds": "auto", "hook": "cold", "style": "night",
           "stories": [{"headline": "Two people with machetes", "label": "Two people with machetes",
                        "where": "taking copper wire", "time": "9:07 PM", "scene": "police",
                        "subhead": "A caller reported them stripping wire from a property. "
                                   "Officers searched the area and found no one there at all."}],
           "captions": [{"s": 2.0, "e": 5.0, "words": [
               {"w": "in", "s": 2.0, "e": 2.3}, {"w": "possession", "s": 2.3, "e": 2.9},
               {"w": "of", "s": 2.9, "e": 3.0}, {"w": "machetes", "s": 3.0, "e": 3.6}]}]}
    im = RR.frame(3.2, cfg, 30.0)
    assert RR.CAP_Y + RR.CAP_H < RR.H * 0.65 + 1
    px = im.getpixel((RR.W - 110, RR.CAP_Y + RR.CAP_H - 14))
    assert sum(px) < 200                      # the dark panel is there (its empty corner)
    below = im.crop((0, int(RR.H * 0.66), RR.W, RR.H)).convert("L").getextrema()
    assert below[1] < 250                     # no white text in the bottom third


def test_person_names_are_blanked_but_streets_named_after_people_are_kept():
    """2026-10-20: the Taser clip said "...with Sam Robertson...". Kern names streets
    after people, so the gazetteer alone would wave "Robertson" through."""
    def run(text, story=()):
        ws = [{"w": t} for t in text.split()]
        BC.redact_names(ws, set(story))
        return " ".join(w["w"] for w in ws if w["w"])
    # a name is dropped, never drawn as a bullet: no "•••" in any caption
    assert "Sam" not in run("attempting further with Sam Robertson, Taser.")
    assert "Robertson" not in run("attempting further with Sam Robertson, Taser.")
    text = run("the RP is Maria Garcia, she is at Robertson Road")
    assert "Maria" not in text and "Garcia" not in text and "•••" not in text
    assert "Robertson Road" in text
    assert run("724 Grace Street, near Jefferson Park Court.", ("Grace", "Jefferson")) \
        == "724 Grace Street, near Jefferson Park Court."
    assert "Lincoln Street" in run("Weapons Possession, 1313 Lincoln Street", ("Lincoln",))
    assert "Adam" in run("Adam 12 copy, subject John Smith fled")


# 2026-10-21: the reel read "3 -4 -6 •••, ••• -4 -6 Prior 2 for a ••• ••• South Union"
# and "making ••• towards CRP, ••• •••." Words below are Whisper's, from that reel.
def _words(text):
    return [{"w": t, "s": float(k), "e": k + 0.9} for k, t in enumerate(text.split())]


def test_digits_read_one_at_a_time_join_and_air():
    ws = BC.join_spoken_digits(_words("3 -4 -6 Adams, 242 -2572 South Union"))
    assert [w["w"] for w in ws] == ["3-4-6", "Adams,", "242", "2572", "South", "Union"]
    assert ws[0]["e"] == 2.9
    assert BC.redact("3-4-6") == ("3-4-6", False)
    assert BC.redact("1-3-1-3,") == ("1-3-1-3,", False)


def test_a_street_after_a_number_or_a_compass_word_is_kept():
    def run(text):
        ws = [{"w": t} for t in text.split()]
        BC.redact_names(ws, set())
        return " ".join(w["w"] for w in ws if w["w"])
    assert run("3-4-6 Adams, there") == "3-4-6 Adams, there"
    assert run("towards CRP, East Edmonton.") == "towards CRP, East Edmonton."
    # a name before a street word is still a name: "Maria Garcia is at Robertson Road"
    assert "Robertson Road" in run("Maria Garcia is at Robertson Road")
    assert "Maria" not in run("Maria Garcia is at Robertson Road")


def test_a_run_of_blanks_is_one_bullet_and_cues_end_on_a_comma():
    ws = _words("for a ••• ••• South Union")
    ws[2]["redacted"] = ws[3]["redacted"] = True
    out = BC.collapse_blanks(ws)
    assert [w["w"] for w in out] == ["for", "a", "•••", "South", "Union"]
    assert (out[2]["s"], out[2]["e"]) == (2.0, 3.9)
    text = ("Multiple units, current two in route, second will be a ••• man, currently "
            "inside of the bar, there's a medicinal Hispanic male with dark hair,")
    ws = [{"w": t, "s": k * 0.2, "e": k * 0.2 + 0.18} for k, t in enumerate(text.split())]
    cues = [" ".join(w["w"] for w in c["words"]) for c in BC.cues_for(ws)]
    assert " ".join(cues) == text
    assert all(c.endswith(",") for c in cues[:-1]), cues


def test_the_panel_never_drops_the_end_of_a_long_cue():
    import render_reel as RR
    long = ("a cue that nobody cut for the panel runs on for three full lines of text "
            "and its final words must still be drawn").split()
    assert len(RR.caption_lines(long)) > RR.CAP_LINES
    cfg = {"captions": [{"s": 0.0, "e": 9.0, "words": [
        {"w": t, "s": 0.0, "e": 0.1} for t in long]}]}
    from PIL import Image
    im = Image.new("RGBA", (RR.W, RR.H), (0, 0, 0, 255))
    RR.caption_panel(im, cfg, 5.0)
    # the last line is inside the panel, not cut off or drawn below it
    band = im.crop((130, RR.CAP_Y + 82, RR.W - 130, RR.CAP_Y + RR.CAP_H - 4)).convert("L")
    rows = [y for y in range(band.height) if band.crop((0, y, band.width, y + 1)).getextrema()[1] > 200]
    bands = sum(1 for k, y in enumerate(rows) if k == 0 or y - rows[k - 1] > 1)
    assert bands == 3                           # three lines drawn (lines[:2] drew two)
    below = im.crop((0, RR.CAP_Y + RR.CAP_H + 2, RR.W, RR.CAP_Y + RR.CAP_H + 80)).convert("L")
    assert below.getextrema()[1] < 30
