#!/usr/bin/env bash
# Commit and push the generated artifacts (email/, drafts/, data/) from a CI run.
# Usage: bash scripts/ci_push.sh "build: 2026-09-22 artifacts [skip ci]"
#
# One copy, all six content workflows. The old inline loops had three faults:
#  - on a rebase conflict they ran `git checkout --ours`, which during a rebase is
#    the REMOTE side, so this run's data was thrown away and the push "succeeded";
#  - after three failed pushes the loop ended on `sleep`, exit 0: a green step
#    with nothing pushed;
#  - four of them re-staged with `git add -A`, sweeping stray runner files in.
#
# The conflict itself was the real defect: two writers on one branch. That is now
# resolved by OWNERSHIP, not by a merge strategy. This script stages exactly the
# paths CI has actually been committing (evidence: the `artifacts [skip ci]`
# commits over the last 40 runs) and shouts when CI leaves anything else dirty.
# CI and the box (kern_overnight / ko_publish.py) own disjoint paths, so a plain
# rebase cannot conflict. If it conflicts anyway that is an ownership violation:
# fail loudly with the paths instead of guessing a winner and dropping an edit.
set -u
msg="${1:?commit message required}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

CI_PATHS=(
  data/build_report.json
  data/snapshots
  data/change_logs
  data/briefs
  data/briefs_archive.json
  data/last_sunday_read.json
  email
  drafts
)

# A listed path may not exist on a given run (no Sunday Read yet, no drafts, a
# tracker's first build), and `git add` aborts the whole invocation when a
# pathspec matches nothing. Stage only what is actually there.
present=()
for c in "${CI_PATHS[@]}"; do
  [ -e "$c" ] && present+=("$c")
done
if [ "${#present[@]}" -gt 0 ]; then
  git add -A -- "${present[@]}"
fi

owned() {
  local p="$1" c
  for c in "${CI_PATHS[@]}"; do
    [ "$p" = "$c" ] && return 0
    case "$p" in "$c"/*) return 0 ;; esac
  done
  return 1
}

# Ownership alarm: a dirty path outside the list means a CI step wrote a file the
# box owns. Not fatal for this push, but never silent: that collision is what
# produced the rebase conflicts this script used to paper over.
stray=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  p="${line:3}"
  owned "$p" || stray="$stray $p"
done < <(git status --porcelain data email drafts)
if [ -n "$stray" ]; then
  echo "::warning title=Ownership violation::CI left box-owned paths dirty:$stray"
fi

if git diff --cached --quiet; then
  echo "no artifact changes"
  exit 0
fi
git commit -q -m "$msg"

for attempt in 1 2 3; do
  if ! git pull --rebase origin main --autostash; then
    echo "::error title=Ownership violation::rebase conflict, not auto-resolving. Conflicting paths:"
    git diff --name-only --diff-filter=U | head -20
    git rebase --abort 2>/dev/null || true
    exit 1
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
