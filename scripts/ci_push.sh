#!/usr/bin/env bash
# Commit and push the generated artifacts (email/, drafts/, data/) from a CI run.
# Usage: bash scripts/ci_push.sh "build: 2026-09-22 artifacts [skip ci]"
#
# One copy, all five content workflows. The old inline loops had three faults:
#  - on a rebase conflict they ran `git checkout --ours`, which during a rebase is
#    the REMOTE side, so this run's data was thrown away and the push "succeeded";
#  - after three failed pushes the loop ended on `sleep`, exit 0: a green step
#    with nothing pushed;
#  - four of them re-staged with `git add -A`, sweeping stray runner files in.
#
# The conflict itself was the real defect: two writers on one branch. That is now
# resolved by OWNERSHIP, not by a merge strategy. This script stages everything
# under data/, email/ and drafts/ EXCEPT the box-owned paths listed below. It is an
# exclusion list because a whitelist of "paths CI writes" drops a path silently the
# day a new tracker starts writing it.
# CI and the box (kern_overnight) own disjoint paths, so a plain
# rebase cannot conflict. If it conflicts anyway that is an ownership violation:
# fail loudly with the paths instead of guessing a winner and dropping an edit.
set -u
msg="${1:?commit message required}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# BOX_PATHS: written by the local overnight pipeline (kern_overnight/geo.py writes
# data/geo_cache.json; transcribe.py commits transcripts/; ko_publish.py the reports).
# CI must never commit these, because that collision is what produced the rebase
# conflicts. Everything else under data/, plus email/ and drafts/, is CI's to commit.
# This is an EXCLUSION list on purpose: a whitelist of "paths CI writes" drifts and
# drops paths silently (it dropped data/fog_delays/log.json and data/last_guide.json
# within a day of being written), while a new tracker path is picked up for free.
BOX_PATHS=(
  data/overnight_reports
  data/geo_cache.json
  data/incidents_geo.json
)

# assets/img/*.jpg are build OUTPUT, not box input: build/weather_card.py and
# build/tracker_card.py rewrite the tracked cards on every run. Nothing else writes
# them, so they belong in this commit. Leaving them dirty is what forced every run to
# autostash (see the pull below), and a stash-pop conflict is silent.
trees=()
for t in data email drafts assets/img; do
  [ -e "$t" ] && trees+=("$t")
done
if [ "${#trees[@]}" -gt 0 ]; then
  git add -A -- "${trees[@]}"
fi
git reset -q -- "${BOX_PATHS[@]}" 2>/dev/null || true

# Invariant: no box-owned path may be staged. If one is, the reset above missed it.
leak=$(git diff --cached --name-only | grep -E '^(data/overnight_reports|data/geo_cache\.json|data/incidents_geo\.json)(/|$)' || true)
if [ -n "$leak" ]; then
  echo "::error title=Ownership leak::CI staged a box-owned path:$leak"
  exit 1
fi

if git diff --cached --quiet; then
  echo "no artifact changes"
  exit 0
fi
git commit -q -m "$msg"

# NO --autostash. With it, a stash-pop conflict returns 0, leaves UU files with conflict
# markers in the worktree and a stash entry behind, and the push then "succeeds"
# (reproduced on git 2.53): a silent half-merge pushed as data. A clean tree is a
# precondition, asserted loudly. The commit above is what makes it clean.
dirty=$(git status --porcelain | grep -vE 'data/(geo_cache\.json|incidents_geo\.json|overnight_reports)' | head -20 || true)
if [ -n "$dirty" ]; then
  echo "::error title=Dirty tree::the worktree is dirty after the commit; refusing to pull without a stash:"
  echo "$dirty"
  exit 1
fi

for attempt in 1 2 3; do
  if ! git pull --rebase origin main; then
    unmerged=$(git diff --name-only --diff-filter=U)
    git rebase --abort 2>/dev/null || true
    if [ -n "$unmerged" ]; then
      echo "::error title=Ownership violation::rebase conflict, not auto-resolving. Conflicting paths: $unmerged"
      exit 1
    fi
    echo "::warning title=Artifact push::git pull failed with no conflict (fetch or network), attempt $attempt"
    sleep $((attempt * 8))
    continue
  fi
  if git push; then
    echo "artifacts pushed (attempt $attempt)"
    exit 0
  fi
  echo "push retry $attempt"
  sleep $((attempt * 8))
done

echo "::error title=Artifacts not pushed::three push attempts failed; this run's data/ and email/ changes are not in the repo"
exit 1
