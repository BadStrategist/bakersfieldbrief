"""Push a box-owned transcript to origin/main without committing in the box's checkout.

Why: the transcript checkpoint used to commit in the working copy and push once
at the end. CI commits artifacts to main every few hours, so that push was a
non-fast-forward whenever CI had landed since the last pull, and it failed
silently. The commits stayed local: on 2026-10-17 the box was 12 ahead / 24
behind, every one a "transcript checkpoint", and the drift guard (which only
fast-forwards a box with no local commits) refused to update the box.

So the checkpoint now works like ko_publish's push: reset a worktree that only
this module writes to (WT) to origin/main, copy the one transcript in with plain
file I/O, commit there, push HEAD:main. A rejection (CI pushed in between) is
retried from a fresh origin/main. The box's own HEAD never moves; once the push
lands, its copy of the transcript is byte-identical to origin's, which the drift
guard treats as safe to fast-forward over.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WT = Path(os.environ.get("KO_TRANSCRIPT_WT") or REPO.parent / ".bb_transcript_wt")


def _git(args: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def _worktree_at_origin(repo: Path, wt: Path) -> str | None:
    """Reset WT to origin/main (create it if missing). Returns an error or None."""
    if (wt / ".git").exists() and _git(["rev-parse", "--git-dir"], wt).returncode == 0:
        if _git(["reset", "-q", "--hard", "origin/main"], wt, 120).returncode == 0:
            _git(["clean", "-fdq"], wt)
            return None
    _git(["worktree", "remove", "--force", str(wt)], repo)
    _git(["worktree", "prune"], repo)
    r = _git(["worktree", "add", "-q", "--detach", str(wt), "origin/main"], repo, 300)
    return None if r.returncode == 0 else f"worktree add failed: {r.stderr.strip()[-90:]}"


def _rel(path: Path, repo: Path) -> str | None:
    """transcripts/<name> for a file under the repo's transcripts/, else None."""
    try:
        rel = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
    return rel if rel.startswith("transcripts/") else None


def in_repo_transcripts(path: Path, repo: Path | None = None) -> bool:
    return _rel(path, repo or REPO) is not None


def push_transcript(path: Path, message: str, attempts: int = 3,
                    repo: Path | None = None, wt: Path | None = None) -> bool:
    """Push one transcripts/*.jsonl to origin/main. True if origin now holds these bytes.

    Never raises for git trouble (transcription must not break for it). A path
    outside the repo's transcripts/ (pytest temp dirs) runs no git and returns False.
    """
    repo = repo or REPO
    wt = wt or WT
    rel = _rel(path, repo)
    if rel is None or not path.exists():
        return False
    for attempt in range(1, attempts + 1):
        if _git(["fetch", "-q", "origin", "main"], repo, 60).returncode != 0:
            print(f"    [ko-stt] transcript push: fetch failed (attempt {attempt})", flush=True)
            continue
        err = _worktree_at_origin(repo, wt)
        if err:
            print(f"    [ko-stt] transcript push: {err}", flush=True)
            return False
        dst = wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(path.read_bytes())
        _git(["add", "--", rel], wt)
        staged = [p for p in _git(["diff", "--cached", "--name-only"], wt).stdout.splitlines()
                  if p.strip()]
        if staged and staged != [rel]:
            _git(["reset", "-q", "--hard", "origin/main"], wt)
            print(f"    [ko-stt] transcript push refused: stray paths {staged[:3]}", flush=True)
            return False
        if not staged:
            return True                    # origin already holds these bytes
        if _git(["commit", "-q", "-m", message], wt).returncode != 0:
            print("    [ko-stt] transcript push: commit failed", flush=True)
            return False
        if _git(["push", "-q", "origin", "HEAD:main"], wt, 60).returncode == 0:
            return True
        print(f"    [ko-stt] transcript push rejected (attempt {attempt})", flush=True)
    return False
