#!/usr/bin/env python3
"""The Kern Overnight push goes out from a worktree of origin/main (ko_publish.py).

ko_publish used to commit and rebase in the box's working copy. That copy is
usually behind origin and often dirty (a staged email/latest, a checked-out
data/briefs file), so the rebase refused: on 2026-10-14 and 2026-10-15 the
report only reached origin because an agent pushed from a worktree by hand.
It now copies the box-owned files into its own worktree of origin/main, commits
and pushes, and holds (exit 3) when the box data fails its own privacy tests.

ko_publish.py is a box script (hermes/scripts, no git), so these tests skip
where it is not installed. They use a throwaway bare remote and stay offline.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

KO_PATH = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "scripts" / "ko_publish.py"
if not KO_PATH.is_file():
    pytest.skip("ko_publish.py is a box script and is not installed here",
                allow_module_level=True)

D = "2026-10-15"
REPORT = f"data/overnight_reports/{D}.md"
INCS = f"incidents/{D}.json"
BOX = {REPORT, INCS, "data/incidents_geo.json", "data/geo_cache.json"}

PASSING = '''
def test_feed_shape_and_privacy():
    assert True

def test_incidents_schema_and_privacy():
    assert True
'''
FAILING = '''
def test_feed_shape_and_privacy():
    assert "25 Union Avenue" == "the 2500 block of Union Avenue"

def test_incidents_schema_and_privacy():
    assert True
'''


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                           "core.autocrlf=false", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


@pytest.fixture
def ko(tmp_path: Path, monkeypatch):
    """ko_publish pointed at a dirty clone that is one CI commit behind origin."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    _write(seed, "tests/test_kern_overnight.py", PASSING)
    _write(seed, "data/overnight_reports/2026-10-14.md", "# old night\n")
    _write(seed, "incidents/2026-10-14.json", "[]\n")
    _write(seed, "data/incidents_geo.json", "[]\n")
    _write(seed, "data/geo_cache.json", json.dumps({"Chester Avenue": [35.3, -119.0]}))
    _write(seed, "email/latest/brief.html", "<p>ci</p>\n")
    _write(seed, "data/briefs/2026-10-14.json", "{}\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", str(origin), "main")

    box = tmp_path / "box"
    _git(tmp_path, "clone", "-q", "-c", "core.autocrlf=false", "-c", "user.name=box",
         "-c", "user.email=box@t", str(origin), str(box))

    # CI commits artifacts after the box's last pull: the box is now behind.
    ci = tmp_path / "ci"
    _git(tmp_path, "clone", "-q", str(origin), str(ci))
    _write(ci, "email/latest/brief.html", "<p>ci 08:53</p>\n")
    _write(ci, f"data/briefs/{D}.json", '{"date": "2026-10-15"}\n')
    _git(ci, "add", "-A")
    _git(ci, "commit", "-q", "-m", "build: artifacts [skip ci]")
    _git(ci, "push", "-q", "origin", "main")

    # The box's working copy is dirty the way it was on 10-14: a staged
    # email/latest, a modified CI-owned brief, an untracked artifact.
    _write(box, "email/latest/brief.html", "<p>box rebuild</p>\n")
    _git(box, "add", "email/latest/brief.html")
    _write(box, "data/briefs/2026-10-14.json", '{"overlay": true}\n')
    _write(box, "data/ad_kit/stray.png", "png")
    # The night's box data.
    _write(box, REPORT, "# The Kern Overnight\n\n37 calls.\n")
    _write(box, INCS, '[{"type": "fire", "area": "Union Avenue"}]\n')
    _write(box, "data/incidents_geo.json", '[{"area": "Union Avenue"}]\n')
    _write(box, "data/geo_cache.json",
           json.dumps({"Chester Avenue": [35.3, -119.0], "Union Avenue": [35.36, -118.99]}))

    spec = importlib.util.spec_from_file_location("ko_publish_under_test", KO_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO", box)
    monkeypatch.setattr(mod, "REPORTS", box / "data" / "overnight_reports")
    monkeypatch.setattr(mod, "INCIDENTS", box / "incidents")
    monkeypatch.setattr(mod, "WT", tmp_path / "state" / "ko_publish_wt")
    monkeypatch.setattr(mod, "PY", Path(sys.executable))
    # The second-source gate, the emulator merge and the part-of-town fix run box
    # tools this temp repo does not have; they are not what is tested here.
    monkeypatch.setattr(mod, "_second_source_ok", lambda iso: True)
    monkeypatch.setattr(mod, "_merge_and_rewrite_if_changed", lambda iso, report: None)
    monkeypatch.setattr(mod, "_fix_parts_of_town", lambda iso: None)
    mod.test_origin, mod.test_box, mod.test_ci = origin, box, ci
    return mod


def _origin_files(ko, ref="main") -> dict[str, str]:
    names = _git(ko.test_origin, "ls-tree", "-r", "--name-only", ref).splitlines()
    return {n: _git(ko.test_origin, "show", f"{ref}:{n}") for n in names}


def _last_commit_paths(ko) -> set[str]:
    out = _git(ko.test_origin, "show", "--name-only", "--format=", "main")
    return {p for p in out.splitlines() if p.strip()}


def test_push_lands_with_the_tree_dirty_and_behind(ko):
    head_before = _git(ko.test_box, "rev-parse", "HEAD")
    assert ko.main(["ko_publish.py", D]) == 0
    files = _origin_files(ko)
    assert files[REPORT] == "# The Kern Overnight\n\n37 calls."
    assert "Union Avenue" in files[INCS]
    assert "Union Avenue" in files["data/geo_cache.json"]
    # CI's commit is kept, not reverted by the push.
    assert files["email/latest/brief.html"] == "<p>ci 08:53</p>"
    assert f"data/briefs/{D}.json" in files
    assert _git(ko.test_origin, "log", "-1", "--format=%s", "main") == f"ko: publish {D}"
    # The working copy is left exactly as it was: same HEAD, same dirt.
    assert _git(ko.test_box, "rev-parse", "HEAD") == head_before
    assert "M  email/latest/brief.html" in _git(ko.test_box, "status", "--porcelain")
    # A second run is a no-op: origin already holds these bytes.
    assert ko.main(["ko_publish.py", D]) == 0
    assert _git(ko.test_origin, "log", "-1", "--format=%s", "main") == f"ko: publish {D}"
    assert _git(ko.test_origin, "rev-list", "--count", "main") == "3"


def test_no_ci_owned_path_is_ever_committed(ko):
    assert ko.main(["ko_publish.py", D]) == 0
    assert _last_commit_paths(ko) <= BOX
    assert _last_commit_paths(ko) == BOX
    files = _origin_files(ko)
    assert "data/ad_kit/stray.png" not in files
    assert files["data/briefs/2026-10-14.json"] == "{}"
    assert all(not f.startswith(("email/", "data/briefs/", "build/", "snapshots/"))
               for f in ko._box_files(D))


def test_a_cache_missing_origins_keys_is_not_pushed(ko):
    _write(ko.test_box, "data/geo_cache.json", json.dumps({"Union Avenue": [35.36, -118.99]}))
    assert ko.main(["ko_publish.py", D]) == 0
    assert "data/geo_cache.json" not in _last_commit_paths(ko)
    assert "Chester Avenue" in _origin_files(ko)["data/geo_cache.json"]
    assert REPORT in _last_commit_paths(ko)


def test_a_non_fast_forward_is_retried_once(ko, monkeypatch):
    real = ko._commit_in_worktree
    calls = []

    def racing(iso):
        out = real(iso)
        if not calls:                       # CI pushes between commit and push
            _write(ko.test_ci, "email/latest/brief.html", "<p>ci 09:00</p>\n")
            _git(ko.test_ci, "commit", "-q", "-am", "build: later [skip ci]")
            _git(ko.test_ci, "push", "-q", "origin", "main")
        calls.append(iso)
        return out

    monkeypatch.setattr(ko, "_commit_in_worktree", racing)
    assert ko.main(["ko_publish.py", D]) == 0
    assert len(calls) == 2
    files = _origin_files(ko)
    assert files["email/latest/brief.html"] == "<p>ci 09:00</p>"
    assert REPORT in files


def test_a_push_that_still_fails_is_exit_1_with_a_short_reason(ko, monkeypatch, capsys):
    _git(ko.test_box, "remote", "set-url", "--push", "origin",
         str(ko.test_origin.parent / "no-such-remote.git"))
    assert ko.main(["ko_publish.py", D]) == 1
    err = capsys.readouterr().err
    verdict = [ln for ln in err.splitlines() if ln.startswith("[ko] PUSH FAILED")]
    assert verdict and len(verdict[-1]) < 150
    assert REPORT not in _origin_files(ko)


def test_a_failing_privacy_test_holds_the_push(ko, capsys):
    before = _git(ko.test_origin, "rev-parse", "main")
    _write(ko.test_box, "tests/test_kern_overnight.py", FAILING)
    assert ko.main(["ko_publish.py", D]) == ko.HELD == 3
    err = capsys.readouterr().err
    held = [ln for ln in err.splitlines() if ln.startswith("[ko] HELD")]
    assert held and "test_feed_shape_and_privacy" in held[0] and len(held[0]) < 150
    assert _git(ko.test_origin, "rev-parse", "main") == before
    assert (ko.test_box / REPORT).exists()          # the report stays on disk
