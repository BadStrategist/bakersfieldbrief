"""publish_social: the API-failure branch. No network, no browser, no posting.

The Playwright fallback is retired. These two tests pin the contract: a failed API leg
must exit non-zero (so the retry slot re-runs the API, which skips legs already live),
and a clean API run must not touch the browser engine at all.
"""
from pathlib import Path

import scripts.brief_reel.publish_social as PS


def _no_browser(*a, **k):
    raise AssertionError("the browser fallback ran; it is retired (API only)")


def test_api_failure_exits_nonzero_and_never_touches_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "STATE_DIR", tmp_path)
    monkeypatch.setattr(PS, "log", lambda *a, **k: None)
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish",
                        lambda d, r, c: {"fb_reel": {"ok": False, "error": "401 token expired"}})
    monkeypatch.setattr(PS, "ensure_session", _no_browser)
    assert PS.main(["publish_social.py", "--date", "2026-10-06"]) == 5


def test_all_legs_ok_returns_zero_without_the_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "STATE_DIR", tmp_path)
    monkeypatch.setattr(PS, "log", lambda *a, **k: None)
    monkeypatch.setattr(PS, "build_assets", lambda d: (Path("reel.mp4"), {}, "caption"))
    monkeypatch.setattr(PS, "api_publish",
                        lambda d, r, c: {"fb_reel": {"ok": True, "url": "u"},
                                         "ig_reel": {"ok": True, "url": "v"}})
    monkeypatch.setattr(PS, "ensure_session", _no_browser)
    assert PS.main(["publish_social.py", "--date", "2026-10-06"]) == 0
