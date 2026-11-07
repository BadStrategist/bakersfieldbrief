"""Two newsletter senders, one email.

CI (any build at 8 AM PT or later) and the PC's bb_email_watchdog (08:10-08:40) both
check for today's campaign, create one, then schedule it. On a morning the 08:00
deadline release pushes, both run within minutes. The old rule deleted any draft as
"left by an earlier failed send", which could delete the other sender's campaign mid
send, and two creates could both send. Now a young draft is the other sender's, and
after creating, only the oldest claim goes ahead.

Run: .venv/Scripts/python.exe -m pytest tests/test_newsletter_claim.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import send_newsletter_ml as sn  # noqa: E402
from build import common  # noqa: E402

NAME = sn._campaign_name(common.today_pacific())


def ml_time(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


class FakeML:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def __call__(self, method, path, payload=None, token=""):
        self.calls.append((method, path))
        if method == "GET":
            return {"data": list(self.rows)} if "page=1" in path else {"data": []}
        if method == "DELETE":
            cid = path.rsplit("/", 1)[-1]
            self.rows = [r for r in self.rows if r["id"] != cid]
        return {}


def test_a_young_draft_belongs_to_the_other_sender(monkeypatch):
    ml = FakeML([{"id": "d1", "name": NAME, "status": "draft", "created_at": ml_time(2)}])
    monkeypatch.setattr(sn, "_req", ml)
    with pytest.raises(sn.SendInFlight):
        sn._today_campaign_exists("t")
    assert not any(m == "DELETE" for m, _ in ml.calls)


def test_an_old_draft_is_still_cleaned_up(monkeypatch):
    ml = FakeML([{"id": "d1", "name": NAME, "status": "draft", "created_at": ml_time(90)}])
    monkeypatch.setattr(sn, "_req", ml)
    assert sn._today_campaign_exists("t") is None
    assert ("DELETE", "/campaigns/d1") in ml.calls


def test_the_oldest_claim_wins_whoever_asks():
    a = {"id": "200", "created_at": "2026-11-07 16:10:01"}
    b = {"id": "201", "created_at": "2026-11-07 16:10:03"}
    tie = {"id": "199", "created_at": "2026-11-07 16:10:03"}
    assert sn._first_claim([b, a])["id"] == "200"
    assert sn._first_claim([b, tie])["id"] == "199"


def _ready_to_send(monkeypatch, tmp_path, ml):
    html = tmp_path / "brief.html"
    html.write_text("<html>ok</html>", encoding="utf-8")
    monkeypatch.setattr(sn, "HTML", html)
    monkeypatch.setattr(sn, "TXT", tmp_path / "none.txt")
    monkeypatch.setattr(sn, "SUBJECT", tmp_path / "none-subject.txt")
    monkeypatch.setattr(sn, "_token", lambda: "t")
    monkeypatch.setattr(sn, "_group", lambda: "g")
    monkeypatch.setattr(sn, "_content_is_degraded", lambda: [])
    monkeypatch.setattr(sn, "source_mismatch", lambda html, root: "")
    monkeypatch.setattr(sn, "format_stamp", lambda **k: "stamp")
    monkeypatch.setattr(sn, "read_stamp", lambda html: {})
    monkeypatch.setattr(sn, "_req", ml)


def test_a_sender_that_created_second_deletes_its_own_draft_and_stands_down(monkeypatch, tmp_path):
    class Racing(FakeML):
        def __call__(self, method, path, payload=None, token=""):
            if method == "POST" and path == "/campaigns":
                self.calls.append((method, path))
                # The other sender created one a moment before ours.
                self.rows += [{"id": "100", "name": NAME, "status": "draft", "created_at": ml_time(0.1)},
                              {"id": "101", "name": NAME, "status": "draft", "created_at": ml_time(0)}]
                return {"data": {"id": "101", "missing_data": []}}
            return super().__call__(method, path, payload, token)
    ml = Racing([])
    _ready_to_send(monkeypatch, tmp_path, ml)
    assert sn.main() == 0
    assert ("DELETE", "/campaigns/101") in ml.calls
    assert not any(p.endswith("/schedule") for _, p in ml.calls)


def test_the_first_claim_sends(monkeypatch, tmp_path):
    class Alone(FakeML):
        def __call__(self, method, path, payload=None, token=""):
            if method == "POST" and path == "/campaigns":
                self.calls.append((method, path))
                self.rows.append({"id": "100", "name": NAME, "status": "draft", "created_at": ml_time(0)})
                return {"data": {"id": "100", "missing_data": []}}
            return super().__call__(method, path, payload, token)
    ml = Alone([])
    _ready_to_send(monkeypatch, tmp_path, ml)
    assert sn.main() == 0
    assert ("POST", "/campaigns/100/schedule") in ml.calls
