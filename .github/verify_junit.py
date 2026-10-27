"""Temporary (ffmpeg-verify.yml): per-file JUnit counts for tests/test_reel_audio.py.
Exits 1 unless every listed XML holds all 80 of that file's tests with none skipped,
failed or errored, and names the 7 ffmpeg tests by their outcome."""
import sys
import xml.etree.ElementTree as ET

FFMPEG_TESTS = {
    "test_dead_air_holds_no_speech_and_a_voice_does",
    "test_a_mix_with_no_voice_is_refused_not_published_at_minus_35",
    "test_a_mix_with_a_voice_lands_on_the_stated_loudness",
    "test_a_quiet_clip_is_brought_up_to_the_voice_level",
    "test_near_silence_is_not_turned_up_to_the_voice_level",
    "test_a_short_clip_does_not_pull_the_next_clip_ahead_of_its_scene",
    "test_a_long_clip_is_trimmed_to_its_slot",
}

bad = False
for path in sys.argv[1:]:
    root = ET.parse(path).getroot()
    suite_totals = {k: sum(int(s.get(k, 0)) for s in root.iter("testsuite"))
                    for k in ("tests", "skipped", "failures", "errors")}
    cases = [c for c in root.iter("testcase") if c.get("classname") == "tests.test_reel_audio"]
    counts = {"tests": len(cases), "skipped": 0, "failures": 0, "errors": 0}
    for c in cases:
        outcome = "passed"
        for tag, key in (("skipped", "skipped"), ("failure", "failures"), ("error", "errors")):
            if c.find(tag) is not None:
                counts[key] += 1
                outcome = tag
        if c.get("name") in FFMPEG_TESTS:
            print(f"  {path}: {c.get('name')}: {outcome} ({c.get('time')} s)")
    ran = {c.get("name") for c in cases} & FFMPEG_TESTS
    print(f"{path}: whole run {suite_totals}; tests/test_reel_audio.py {counts}; "
          f"ffmpeg tests present {len(ran)}/7")
    if counts["tests"] != 80 or len(ran) != 7 or counts["skipped"] or counts["failures"] or counts["errors"]:
        bad = True
sys.exit(1 if bad else 0)
