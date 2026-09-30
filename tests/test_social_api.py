"""social_api: same-day guards and leg isolation (no network)."""
from pathlib import Path

import scripts.social_api as SA


def test_la_date_formats():
    # Graph returns +0000 offsets, IG ISO, FB stories unix seconds
    assert SA._la_date("2026-09-29T23:06:04+0000") == "2026-09-29"
    assert SA._la_date("2026-09-30T06:30:00+0000") == "2026-09-29"  # 23:30 PT
    assert SA._la_date("2026-09-30T08:00:00Z") == "2026-09-30"
    assert SA._la_date("1790722000") == "2026-09-29"
    assert SA._la_date("") == ""


def test_existing_leg_is_skipped_not_republished(monkeypatch):
    monkeypatch.setattr(SA, "ig_user_id", lambda tok: "ig1")
    monkeypatch.setattr(SA, "fb_reel_today", lambda tok, d: "https://fb/reel/1/")
    called = []
    monkeypatch.setattr(SA, "publish_fb_reel", lambda *a: called.append(1))
    out = SA.publish_all("t", "2026-09-29", Path("x.mp4"), "cap", ("fb_reel",))
    assert out["fb_reel"] == {"ok": True, "skipped": True, "url": "https://fb/reel/1/"}
    assert not called


def test_one_failing_leg_does_not_block_others(monkeypatch):
    monkeypatch.setattr(SA, "ig_user_id", lambda tok: "ig1")
    monkeypatch.setattr(SA, "fb_reel_today", lambda tok, d: None)
    monkeypatch.setattr(SA, "fb_story_today", lambda tok, d: None)

    def boom(*a):
        raise SA.LegError("upload failed: 500")

    monkeypatch.setattr(SA, "publish_fb_reel", boom)
    monkeypatch.setattr(SA, "publish_fb_story", lambda tok, v: "story123")
    out = SA.publish_all("t", "2026-09-29", Path("x.mp4"), "cap", ("fb_reel", "fb_story"))
    assert out["fb_reel"]["ok"] is False and "500" in out["fb_reel"]["error"]
    assert out["fb_story"] == {"ok": True, "url": "story123"}


def test_no_instagram_link_fails_only_ig_legs(monkeypatch):
    def no_ig(tok):
        raise SA.LegError("no Instagram account linked")

    monkeypatch.setattr(SA, "ig_user_id", no_ig)
    monkeypatch.setattr(SA, "fb_reel_today", lambda tok, d: "https://fb/reel/1/")
    out = SA.publish_all("t", "2026-09-29", Path("x.mp4"), "cap", ("fb_reel", "ig_reel"))
    assert out["fb_reel"]["ok"] is True
    assert out["ig_reel"]["ok"] is False
