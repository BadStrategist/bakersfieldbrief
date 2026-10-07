#!/usr/bin/env bash
# Commit and push the generated artifacts (email/, drafts/, data/) from a CI run.
# Usage: bash scripts/ci_push.sh "build: 2026-09-22 artifacts [skip ci]"
#
# One copy for all five workflows. The old inline loops had three faults:
#  - on a rebase conflict they ran `git checkout --ours`, which during a rebase is the REMOTE
#    side, so this run's data was thrown away and the push still "succeeded";
#  - after three failed pushes the loop ended on `sleep`, exit 0: a green step, nothing pushed;
#  - four of them re-staged with `git add -A`, sweeping stray runner files into the commit.
set -u
msg="${1:?commit message required}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add email drafts data
if git diff --cached --quiet; then
  echo "no artifact changes"
  exit 0
fi
git commit -q -m "$msg"

for attempt in 1 2 3; do
  # -X theirs during a REBASE keeps the commit being replayed, which is THIS
  # run's artifacts. Deterministic, so no interactive rebase and no guessing
  # which side `--ours` means. This script stages only email/drafts/data, so the
  # strategy option cannot touch a source file.
  if git pull --rebase -X theirs origin main --autostash && git push; then
    echo "artifacts pushed (attempt $attempt)"
    exit 0
  fi
  git rebase --abort 2>/dev/null || true
  echo "push retry $attempt"
  sleep $((attempt * 8))
done

echo "::error title=Artifacts not pushed::three push attempts failed; this run's data/ and email/ changes are not in the repo"
exit 1
