"""publish_social: the API-failure branch and the audio gate. No network, no
browser, no posting.

The Playwright fallback is retired. The first two tests pin that contract: a failed
API leg must exit non-zero (so the retry slot re-runs the API, which skips legs
already live), and a clean API run must not touch the browser engine at all.

The rest pin the audio gate (2026-10-12: a reel whose two clips had both failed
verification was published at -35.6 LUFS, the run exited 0 and reported
verify=ok). A reel whose audio is not vouched for is never handed to the API,
and the run that holds it or publishes it short is never a quiet green.
"""
import json
from pathlib import Path

import pytest

import scripts.brief_reel.publish_social as PS

DATE = "2026-10-06"
AUDIO_OK = {"ok": True, "outcome": "ok", "problems": [], "dropped": [], "lufs": -16.2}
LEGS_OK = {"fb_reel": {"ok": True, "url": "u"}, "ig_reel": {"ok": True, "url": "v"}}


def _no_browser(*a, **k):
    raise AssertionError("the browser fallback ran; it is retired (API only)")


def _no_post(*a, **k):
    raise AssertionError("a held reel was handed to the publisher")


def test_api_failure_exits_nonzero_and_never_touches_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "STATE_DIR", tmp_path)
    monkeypatch.setattr(PS, "log", lambda *a, **k: None)
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "audio_gate", lambda d, r: dict(AUDIO_OK))
    monkeypatch.setattr(PS, "api_publish",
                        lambda d, r, c: {"fb_reel": {"ok": False, "error": "401 token expired"}})
    monkeypatch.setattr(PS, "ensure_session", _no_browser)
    assert PS.main(["publish_social.py", "--date", "2026-10-06"]) == 5


def test_all_legs_ok_returns_zero_without_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "STATE_DIR", tmp_path)
    monkeypatch.setattr(PS, "log", lambda *a, **k: None)
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "audio_gate", lambda d, r: dict(AUDIO_OK))
    monkeypatch.setattr(PS, "api_publish",
                        lambda d, r, c: {"fb_reel": {"ok": True, "url": "u"},
                                         "ig_reel": {"ok": True, "url": "v"}})
    monkeypatch.setattr(PS, "ensure_session", _no_browser)
    assert PS.main(["publish_social.py", "--date", "2026-10-06"]) == 0


# --------------------------------------------------------------------------- #
# the audio gate
# --------------------------------------------------------------------------- #
def _audit(**over):
    """A clean two-story audit log, as make_dispatch_audio writes it."""
    a = {"date": DATE, "outcome": "ok", "reel_indices": [0, 1],
         "stories": [{"index": 1, "headline": "Robbery on Mount Vernon Avenue",
                      "verify_ok": True},
                     {"index": 2, "headline": "Crash on Interstate 5", "verify_ok": True}]}
    a.update(over)
    return a


# What the builder wrote on 2026-10-12: verify_ok false twice, and both mixed.
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


@pytest.fixture
def day(tmp_path, monkeypatch):
    """A date directory with an audit log, and a reel whose loudness is `lufs`."""
    box = {"lufs": -16.2, "dir": tmp_path / DATE}
    box["dir"].mkdir()
    monkeypatch.setattr(PS, "STATE_DIR", tmp_path)
    monkeypatch.setattr(PS, "log", lambda *a, **k: None)
    monkeypatch.setattr(PS.RAG, "loudness",
                        lambda p: None if box["lufs"] is None
                        else {"lufs": box["lufs"], "peak": -1.5})

    def write(audit):
        (box["dir"] / "soundtrack.json").write_text(json.dumps(audit), encoding="utf-8")
    box["write"] = write
    box["state"] = lambda: json.loads((tmp_path / f"{DATE}.json").read_text(encoding="utf-8"))
    return box


def test_the_gate_passes_a_verified_reel_at_a_listening_level(day):
    day["write"](_audit())
    g = PS.audio_gate(DATE, Path("reel.mp4"))
    assert g["ok"] is True and g["outcome"] == "ok" and g["lufs"] == -16.2


def test_the_gate_holds_the_2026_10_12_reel_on_the_audit_alone(day):
    """Even if the reel somehow measured loud, an unverified clip holds it."""
    day["write"](AUDIT_1012)
    g = PS.audio_gate(DATE, Path("reel.mp4"))
    assert g["ok"] is False and g["outcome"] == "held"
    assert any("story 1 is in the reel without a verified clip" in p for p in g["problems"])


def test_the_gate_holds_the_2026_10_12_reel_on_the_loudness_alone(day):
    """Even if the audit log were clean, a reel at -35.6 LUFS is held."""
    day["write"](_audit())
    day["lufs"] = -35.6
    g = PS.audio_gate(DATE, Path("reel.mp4"))
    assert g["ok"] is False and g["outcome"] == "held"
    assert "-35.6 LUFS" in g["problems"][0]


@pytest.mark.parametrize("case", ["no audit", "unreadable audit", "unmeasurable reel",
                                  "builder held", "no outcome", "no clips"])
def test_the_gate_never_passes_what_it_cannot_vouch_for(day, case):
    if case == "unreadable audit":
        (day["dir"] / "soundtrack.json").write_text("{not json", encoding="utf-8")
    elif case == "unmeasurable reel":
        day["write"](_audit())
        day["lufs"] = None
    elif case == "builder held":
        day["write"](_audit(outcome="held", held_reason="no dispatch clip verified"))
    elif case == "no outcome":
        a = _audit()
        del a["outcome"]
        day["write"](a)
    elif case == "no clips":
        day["write"](_audit(reel_indices=[]))
    g = PS.audio_gate(DATE, Path("reel.mp4"))
    assert g["ok"] is False and g["outcome"] == "held" and g["problems"]


def test_a_dropped_story_is_degraded_not_ok(day):
    a = _audit(outcome="degraded", reel_indices=[0])
    a["stories"][1] = {"index": 2, "headline": "Crash on Interstate 5", "verify_ok": False,
                       "dropped": True, "verify_reason": "re-transcription came back empty"}
    day["write"](a)
    g = PS.audio_gate(DATE, Path("reel.mp4"))
    assert g["ok"] is True and g["outcome"] == "degraded"
    assert g["dropped"] == ["story 2 (Crash on Interstate 5): re-transcription came back empty"]


# --------------------------------------------------------------------------- #
# what the run does with the gate's answer
# --------------------------------------------------------------------------- #
def test_a_reel_that_fails_the_gate_is_never_published_and_the_run_is_loud(
        day, monkeypatch, capsys):
    """2026-10-12 replayed: the reel exists, the API is up, and nothing is posted."""
    day["write"](AUDIT_1012)
    day["lufs"] = -35.6
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish", _no_post)
    monkeypatch.setattr(PS, "ensure_session", _no_post)
    rc = PS.main(["publish_social.py", "--date", DATE])
    out = capsys.readouterr().out
    assert rc == PS.EXIT_HELD == 6
    assert rc not in (0, 3), "a held reel must not read as published or as gate-skipped"
    assert "audio=HELD" in out and "verify=held" in out
    assert "audio_problem=reel.mp4 measures -35.6 LUFS" in out
    assert "verify=ok" not in out
    st = day["state"]()
    assert st["held"] is True and st["done"] is False and st["held_reasons"]
    assert "api" not in st


def test_a_build_with_no_verified_clip_is_held_before_any_render(day, monkeypatch, capsys):
    def held(d):
        raise PS.ReelHeld("no dispatch clip verified")
    monkeypatch.setattr(PS, "build_assets", held)
    monkeypatch.setattr(PS, "audio_gate", _no_post)
    monkeypatch.setattr(PS, "api_publish", _no_post)
    assert PS.main(["publish_social.py", "--date", DATE]) == PS.EXIT_HELD
    assert "audio_problem=no dispatch clip verified" in capsys.readouterr().out
    assert day["state"]()["done"] is False


def test_a_dry_run_is_gated_too(day, monkeypatch):
    day["write"](AUDIT_1012)
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish", _no_post)
    monkeypatch.setattr(PS, "ensure_session", _no_post)
    assert PS.main(["publish_social.py", "--date", DATE, "--dry-run"]) == PS.EXIT_HELD


def test_a_degraded_reel_is_published_and_the_run_still_fails_loudly(
        day, monkeypatch, capsys):
    a = _audit(outcome="degraded", reel_indices=[0])
    a["stories"][1] = {"index": 2, "headline": "Crash on Interstate 5", "verify_ok": False,
                       "dropped": True, "verify_reason": "re-transcription came back empty"}
    day["write"](a)
    posted = []
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish",
                        lambda d, r, c: posted.append(r) or dict(LEGS_OK))
    monkeypatch.setattr(PS, "ensure_session", _no_browser)
    rc = PS.main(["publish_social.py", "--date", DATE])
    out = capsys.readouterr().out
    assert posted == [Path("reel.mp4")]
    assert rc == PS.EXIT_DEGRADED == 7, "a dropped clip must not exit 0"
    assert "audio=DEGRADED" in out
    assert "audio_dropped=story 2 (Crash on Interstate 5): re-transcription came back empty" in out
    assert day["state"]()["done"] is True, "it is live: the retry slot must not post again"


def test_a_clean_reel_reports_its_measured_loudness(day, monkeypatch, capsys):
    day["write"](_audit())
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish", lambda d, r, c: dict(LEGS_OK))
    assert PS.main(["publish_social.py", "--date", DATE]) == 0
    assert "audio=ok -16.2 LUFS" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# build_assets: the builder's answer reaches the publisher
# --------------------------------------------------------------------------- #
class _Done:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def builder(day, monkeypatch):
    """build_assets with the gate open and every subprocess replaced. The fake
    builder exits `rc` and leaves `audit` behind, and a soundtrack only when
    `writes_mp3` is set."""
    box = {"rc": 4, "audit": {"outcome": "held", "held_reason": "no dispatch clip verified",
                              "reel_indices": [], "stories": []},
           "writes_mp3": False, "calls": []}

    def fake_run(cmd, timeout=900):
        name = Path(str(cmd[1])).name
        box["calls"].append(name)
        if name == "make_brief_json.py":
            Path(str(cmd[cmd.index("--out") + 1])).write_text('{"stories": []}', encoding="utf-8")
            return _Done()
        if name == "make_dispatch_audio.py":
            out = Path(str(cmd[cmd.index("--out") + 1]))
            if box["audit"] is not None:
                out.with_suffix(".json").write_text(json.dumps(box["audit"]), encoding="utf-8")
            if box["writes_mp3"]:
                out.write_bytes(b"mp3")
            return _Done(box["rc"], "pacing", "HELD: no dispatch clip verified")
        raise AssertionError(f"{name} ran after the soundtrack was refused")

    monkeypatch.setattr(PS.PF, "_git_pull_latest", lambda: None)
    monkeypatch.setattr(PS.PF, "gate_check", lambda d: ("brief", "overnight"))
    monkeypatch.setattr(PS, "run", fake_run)
    return box


def test_a_held_soundtrack_stops_the_build_before_the_render(builder):
    with pytest.raises(PS.ReelHeld) as exc:
        PS.build_assets(DATE)
    assert "no dispatch clip verified" in str(exc.value)
    assert "render_reel.py" not in builder["calls"]


def test_a_builder_that_dies_without_a_soundtrack_is_held_with_its_exit_code(builder):
    builder.update({"rc": 1, "audit": None})
    with pytest.raises(PS.ReelHeld) as exc:
        PS.build_assets(DATE)
    assert "exit 1" in str(exc.value)


def test_a_day_already_held_is_not_rebuilt_by_the_retry_slot(builder):
    with pytest.raises(PS.ReelHeld):
        PS.build_assets(DATE)
    builder["calls"].clear()
    with pytest.raises(PS.ReelHeld) as exc:
        PS.build_assets(DATE)
    assert "make_dispatch_audio.py" not in builder["calls"]
    assert "held by an earlier run" in str(exc.value)
