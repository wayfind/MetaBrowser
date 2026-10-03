#!/usr/bin/env bash
# Merge the latest CloakHQ/CloakBrowser into the current branch.
#   metabrowser/scripts/sync-upstream.sh            # merge upstream/main
#   metabrowser/scripts/sync-upstream.sh v0.5.12    # merge a release tag
set -euo pipefail

UPSTREAM_URL="${UPSTREAM_URL:-https://github.com/CloakHQ/CloakBrowser.git}"
target="${1:-upstream/main}"

git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
# Replay recorded conflict resolutions automatically; honour merge=ours for fork-owned files.
git config rerere.enabled true
git config rerere.autoupdate true
git config merge.ours.driver true
git fetch upstream --tags --prune

if [[ -n "$(git status --porcelain)" ]]; then
  echo "working tree not clean; commit or set work aside first" >&2
  exit 1
fi

before="$(git rev-parse --short HEAD)"
git merge --no-edit -m "chore(upstream): merge CloakBrowser ${target}" "$target"
echo "merged ${target} into $(git branch --show-current) (was ${before})"

python3 "$(dirname "$0")/fork_guard.py" upstream/main
echo "next: cd metabrowser && pytest   # overlay still works against the new cloakbrowser"
