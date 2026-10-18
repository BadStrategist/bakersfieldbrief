"""kern_overnight.boxpush against real git: a bare origin, a box clone, CI commits.

The box's checkout must never gain a commit (that is what made it drift on
2026-10-17), and a push that loses the race with CI must be retried.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kern_overnight import boxpush  # noqa: E402

MSG = "ko: transcript checkpoint (3/3 blocks) [skip ci]"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    ci = tmp_path / "ci"
    git(tmp_path, "clone", "-q", str(origin), str(ci))
    (ci / "data").mkdir()
    (ci / "data" / "a.json").write_text("{}\n")
    git(ci, "add", "-A")
    git(ci, "commit", "-qm", "seed")
    git(ci, "push", "-q", "origin", "HEAD:main")
    box = tmp_path / "box"
    git(tmp_path, "clone", "-q", str(origin), str(box))
    for name in ("user.name", "user.email"):
        git(box, "config", name, "t")
    (box / "transcripts").mkdir()
    return origin, ci, box, tmp_path / "wt"


def ci_commit(ci: Path, text: str) -> None:
    git(ci, "pull", "-q", "--rebase", "origin", "main")
    (ci / "data" / "a.json").write_text(text)
    git(ci, "commit", "-qam", "build: artifacts [skip ci]")
    git(ci, "push", "-q", "origin", "HEAD:main")


def test_push_lands_on_origin_and_box_head_never_moves(repos):
    origin, ci, box, wt = repos
    head = git(box, "rev-parse", "HEAD")
    ci_commit(ci, '{"ci": 1}\n')                      # box is now behind
    t = box / "transcripts" / "2026-10-17.jsonl"
    t.write_text('{"text": "one"}\n')
    assert boxpush.push_transcript(t, MSG, repo=box, wt=wt)
    assert git(box, "rev-parse", "HEAD") == head      # no local commit
    git(box, "fetch", "-q", "origin")
    assert git(box, "show", "origin/main:transcripts/2026-10-17.jsonl") == '{"text": "one"}'
    assert git(box, "show", "origin/main:data/a.json") == '{"ci": 1}'   # CI's work kept
    assert git(box, "log", "-1", "--format=%s", "origin/main") == MSG
    assert git(box, "rev-list", "--count", "origin/main..HEAD") == "0"


def test_second_checkpoint_updates_and_same_bytes_is_noop(repos):
    origin, ci, box, wt = repos
    t = box / "transcripts" / "2026-10-17.jsonl"
    t.write_text("a\n")
    assert boxpush.push_transcript(t, MSG, repo=box, wt=wt)
    t.write_text("a\nb\n")
    assert boxpush.push_transcript(t, MSG, repo=box, wt=wt)
    git(box, "fetch", "-q", "origin")
    n = git(box, "rev-list", "--count", "origin/main")
    assert boxpush.push_transcript(t, MSG, repo=box, wt=wt)   # nothing new
    git(box, "fetch", "-q", "origin")
    assert git(box, "rev-list", "--count", "origin/main") == n
    assert git(box, "show", "origin/main:transcripts/2026-10-17.jsonl") == "a\nb"


def test_rejected_push_is_retried_from_fresh_origin(repos, monkeypatch):
    origin, ci, box, wt = repos
    t = box / "transcripts" / "2026-10-17.jsonl"
    t.write_text("x\n")
    real = boxpush._git
    raced = []

    def racing_git(args, cwd, timeout=60):
        if args[:1] == ["push"] and not raced:        # CI lands between commit and push
            raced.append(1)
            ci_commit(ci, '{"raced": 1}\n')
        return real(args, cwd, timeout)

    monkeypatch.setattr(boxpush, "_git", racing_git)
    assert boxpush.push_transcript(t, MSG, repo=box, wt=wt)
    git(box, "fetch", "-q", "origin")
    assert git(box, "show", "origin/main:data/a.json") == '{"raced": 1}'
    assert git(box, "show", "origin/main:transcripts/2026-10-17.jsonl") == "x"


def test_one_attempt_gives_up_quietly_when_raced(repos, monkeypatch):
    origin, ci, box, wt = repos
    t = box / "transcripts" / "2026-10-17.jsonl"
    t.write_text("x\n")
    real = boxpush._git

    def racing_git(args, cwd, timeout=60):
        if args[:1] == ["push"]:
            ci_commit(ci, '{"raced": 2}\n')
        return real(args, cwd, timeout)

    monkeypatch.setattr(boxpush, "_git", racing_git)
    assert boxpush.push_transcript(t, MSG, attempts=1, repo=box, wt=wt) is False


def test_non_transcript_and_outside_paths_run_no_git(repos, tmp_path, monkeypatch):
    origin, ci, box, wt = repos
    monkeypatch.setattr(boxpush, "_git", lambda *a, **k: pytest.fail("git ran"))
    (box / "data" / "b.json").write_text("{}")
    assert boxpush.push_transcript(box / "data" / "b.json", MSG, repo=box, wt=wt) is False
    stray = tmp_path / "out.jsonl"
    stray.write_text("x")
    assert boxpush.push_transcript(stray, MSG, repo=box, wt=wt) is False
