#!/usr/bin/env bash
# CI-equivalent frontend check on a fresh clone: only committed files count, so an
# uncommitted fix in the working tree can't hide a broken build.
# Usage: scripts/clean-clone-check.sh [repo-path-or-url] [ref]
set -euo pipefail

REPO="${1:-$(git rev-parse --show-toplevel)}"
REF="${2:-HEAD}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --quiet "$REPO" "$WORK/repo"
git -C "$WORK/repo" checkout --quiet "$REF"
echo "clean clone of $REPO at $(git -C "$WORK/repo" rev-parse --short HEAD)"

cd "$WORK/repo/frontend"
npm ci --no-audit --no-fund --loglevel=error
npm run typecheck
npm run build
echo "CLEAN-CLONE CHECK PASSED"
