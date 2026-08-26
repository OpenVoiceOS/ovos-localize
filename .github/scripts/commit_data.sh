#!/usr/bin/env bash
# Commit regenerated data to dev.
#
# The job takes minutes and the release automation commits to dev whenever a
# pull request merges, so dev has usually moved by the time this runs and a
# plain push is rejected. Everything here is generated output, so replaying
# the commit on top of whatever arrived is always the right answer.
set -euo pipefail

MESSAGE="$1"
PATTERN="$2"

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

git add -- ${PATTERN}
if git diff --cached --quiet; then
  echo "nothing to commit for ${PATTERN}"
  exit 0
fi
git commit -m "${MESSAGE}"

for attempt in 1 2 3 4 5; do
  if git push origin HEAD:dev; then
    echo "pushed on attempt ${attempt}"
    exit 0
  fi
  echo "push rejected; rebasing onto dev (attempt ${attempt})"
  git fetch origin dev
  git rebase origin/dev
  sleep $(( attempt * 5 ))
done

echo "::error::could not push ${PATTERN} after 5 attempts"
exit 1
