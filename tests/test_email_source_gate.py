#!/usr/bin/env python3
"""The email's overnight numbers must be origin/main's (build/email_gate.source_mismatch).

On 2026-10-15 the watchdog rebuilt the email in the box's working copy, read an unpushed
28-incident report, and sent it while the site showed 37. The emailer now stamps the
report and call file it read (date + git blob sha1); the send holds unless the stamp is
origin/main's newest report and its exact blobs. These tests use a throwaway local git
remote, so they stay offline.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from build import common, email_gate, emailer  # noqa: E402
from build.builders import overnight  # noqa: E402
from build.email_gate import (blob_sha, content_is_degraded, format_stamp,  # noqa: E402
                              source_mismatch)

D = "2026-10-15"
REPORT = f"data/overnight_reports/{D}.md"
INCS = f"incidents/{D}.json"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                           "core.autocrlf=false", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone whose origin/main holds the night's report and a 37-row call file."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    (seed / "data" / "overnight_reports").mkdir(parents=True)
    (seed / "incidents").mkdir()
    (seed / "data" / "overnight_reports" / "2026-10-14.md").write_bytes(b"# old night\n")
    (seed / REPORT).write_bytes(b"# The Kern Overnight\n\n37 calls.\n")
    (seed / INCS).write_bytes(b"[" + b",".join([b"{}"] * 37) + b"]\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "night")
    _git(seed, "push", "-q", str(origin), "main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    return work


def _stamped(tmp_path: Path, stamp: str) -> Path:
    p = tmp_path / "brief.html"
    p.write_text(f"<html><head><title>b</title>\n<!-- {stamp} --></head><body></body></html>",
                 encoding="utf-8")
    return p


def _origin_stamp(repo: Path) -> str:
    return format_stamp(D, _git(repo, "rev-parse", f"origin/main:{REPORT}"),
                        _git(repo, "rev-parse", f"origin/main:{INCS}"))


def test_blob_sha_is_gits_and_ignores_crlf(tmp_path):
    p = tmp_path / "f.json"
    p.write_bytes(b'[{"a": 1}]\n')
    assert blob_sha(p) == _git(tmp_path, "hash-object", "--no-filters", str(p))
    lf = blob_sha(p)
    p.write_bytes(b'[{"a": 1}]\r\n')       # the box checks out with core.autocrlf=true
    assert blob_sha(p) == lf
    assert blob_sha(tmp_path / "missing.json") == "none"


def test_agrees_with_origin_is_none(repo, tmp_path):
    html = _stamped(tmp_path, format_stamp(D, blob_sha(repo / REPORT), blob_sha(repo / INCS)))
    assert source_mismatch(html, repo) is None
    assert format_stamp(D, blob_sha(repo / REPORT), blob_sha(repo / INCS)) == _origin_stamp(repo)


def test_an_unpushed_call_file_is_a_mismatch(repo, tmp_path):
    (repo / INCS).write_bytes(b"[" + b",".join([b"{}"] * 28) + b"]\n")   # the 08:12 file
    html = _stamped(tmp_path, format_stamp(D, blob_sha(repo / REPORT), blob_sha(repo / INCS)))
    why = source_mismatch(html, repo)
    assert why and why.startswith("built from bb-overnight-src date=2026-10-15")
    assert f"origin/main has {_origin_stamp(repo)}" in why


def test_an_older_night_while_origin_has_a_newer_one_is_a_mismatch(repo, tmp_path):
    old = repo / "data" / "overnight_reports" / "2026-10-14.md"
    html = _stamped(tmp_path, format_stamp("2026-10-14", blob_sha(old), "none"))
    why = source_mismatch(html, repo)
    assert why and "origin/main has bb-overnight-src date=2026-10-15" in why


def test_no_stamp_is_a_mismatch(repo, tmp_path):
    p = tmp_path / "brief.html"
    p.write_text("<html><body>no stamp</body></html>", encoding="utf-8")
    assert "no bb-overnight-src stamp" in source_mismatch(p, repo)


def test_a_push_after_the_build_is_caught_by_the_fetch(repo, tmp_path):
    html = _stamped(tmp_path, _origin_stamp(repo))
    assert source_mismatch(html, repo) is None
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    (other / INCS).write_bytes(b"[{}]\n")
    _git(other, "commit", "-q", "-am", "revise the night")
    _git(other, "push", "-q", "origin", "main")
    assert source_mismatch(html, repo, fetch=False) is None     # the last fetch
    assert source_mismatch(html, repo) is not None              # fetched: origin moved


def test_the_stamp_does_not_satisfy_the_date_check(tmp_path):
    html = _stamped(tmp_path, format_stamp(date.today().isoformat(), "none", "none"))
    assert "date" in content_is_degraded(html)


def test_the_emailer_stamps_the_cards_night_and_warns_on_a_split(tmp_path, monkeypatch, capsys):
    (tmp_path / "data" / "overnight_reports").mkdir(parents=True)
    (tmp_path / "incidents").mkdir()
    (tmp_path / REPORT).write_bytes(b"# r\n")
    (tmp_path / INCS).write_bytes(b"[]\r\n")
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(overnight, "REPORTS_DIR", tmp_path / "data" / "overnight_reports")
    today = date(2026, 10, 15)
    stamp = emailer._overnight_src(today, {"date": D}, keyless=True)
    assert stamp == format_stamp(D, blob_sha(tmp_path / REPORT), blob_sha(tmp_path / INCS))
    assert "disagree" not in capsys.readouterr().out
    split = emailer._overnight_src(date(2026, 10, 16), {"date": D}, keyless=True)
    assert split.startswith(f"bb-overnight-src date={D} ")
    assert "WARNING overnight sources disagree on the night: card=2026-10-15, " \
           "header=2026-10-15, prose=2026-10-16" in capsys.readouterr().out
    monkeypatch.setattr(overnight, "REPORTS_DIR", tmp_path / "nothing")
    assert emailer._overnight_src(today, None, keyless=False) == format_stamp(None, None, None)


def test_the_gate_module_stays_stdlib():
    src = Path(email_gate.__file__).read_text(encoding="utf-8")
    assert "from build" not in src and "from ." not in src
