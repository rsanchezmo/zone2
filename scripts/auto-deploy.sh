#!/usr/bin/env bash
# Auto-deploy: fetch the configured branch, rebuild Docker services when
# origin has commits newer than the last deployed SHA (.git/last-deployed-sha).
#
# Designed for systemd-timer driven use (see deploy/strava-deploy.timer) but
# safe to run manually too:
#
#     sudo systemctl start strava-deploy.service
#
# or directly:
#
#     ./scripts/auto-deploy.sh
#
# Environment variables:
#   DEPLOY_BRANCH   Branch to track. Default: prod
#   REPO_DIR        Repository root. Default: directory containing this script
#   COMPOSE         Compose command. Default: 'docker compose'

set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BRANCH="${DEPLOY_BRANCH:-prod}"
COMPOSE="${COMPOSE:-docker compose}"
LOCK_FILE="/tmp/strava-auto-deploy.lock"
# Tracks the last SHA that was actually built, so a manual `git pull` in the
# repo can't make a push look already-deployed. Lives in .git/ (untracked,
# survives reboots).
STATE_FILE="$REPO_DIR/.git/last-deployed-sha"

log() { printf '[%s] %s\n' "$(date -u +'%FT%TZ')" "$*"; }

# ── Single-run lock (avoid overlapping runs from manual + timer) ───────
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "Another deploy is already running; exiting."
  exit 0
fi

cd "$REPO_DIR"

# ── Fetch + diff against remote ────────────────────────────────────────
log "Checking origin/$BRANCH for new commits in $REPO_DIR"
git fetch --quiet origin "$BRANCH"

if ! git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  log "ERROR: origin/$BRANCH does not exist. Create the branch on GitHub first."
  exit 1
fi

# If the local branch doesn't exist yet, create it tracking origin.
if ! git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  log "Local $BRANCH branch missing; creating from origin/$BRANCH"
  git branch --track "$BRANCH" "origin/$BRANCH"
fi

REMOTE="$(git rev-parse "origin/$BRANCH")"
DEPLOYED="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ "$REMOTE" = "$DEPLOYED" ]; then
  log "Already deployed $DEPLOYED — no changes."
  exit 0
fi

log "Deploying $BRANCH: ${DEPLOYED:-<unknown>} → $REMOTE"
if [ -n "$DEPLOYED" ] && git cat-file -e "$DEPLOYED^{commit}" 2>/dev/null; then
  log "New commits:"
  git log --oneline --no-color "$DEPLOYED..$REMOTE" | sed 's/^/  /'
fi

# ── Pull + rebuild ─────────────────────────────────────────────────────
git checkout --quiet "$BRANCH"
git pull --ff-only --quiet origin "$BRANCH"

log "Rebuilding Docker services..."
$COMPOSE up -d --build

git rev-parse HEAD > "$STATE_FILE"
log "Deploy complete."
