#!/usr/bin/env bash
# Auto-deploy: fetch the configured branch, check it out and rebuild Docker
# services when origin's tip differs from the last deployed SHA
# (.git/last-deployed-sha).
#
# Designed for systemd-timer driven use (see deploy/z2-deploy.timer) but
# safe to run manually too:
#
#     sudo systemctl start z2-deploy.service
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
LOCK_FILE="/tmp/z2-auto-deploy.lock"
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

REMOTE="$(git rev-parse "origin/$BRANCH")"
DEPLOYED="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ "$REMOTE" = "$DEPLOYED" ]; then
  log "Already deployed $DEPLOYED — no changes."
  exit 0
fi

log "Deploying $BRANCH: ${DEPLOYED:-<unknown>} → $REMOTE"
if [ -n "$DEPLOYED" ] && git merge-base --is-ancestor "$DEPLOYED" "$REMOTE" 2>/dev/null; then
  log "New commits:"
  git log --oneline --no-color "$DEPLOYED..$REMOTE" | sed 's/^/  /'
elif [ -n "$DEPLOYED" ]; then
  log "origin/$BRANCH was rewritten since the last deploy."
fi

# ── Checkout + rebuild ─────────────────────────────────────────────────
# Follows the remote ref even after a force-push. Local edits to tracked files
# are discarded; untracked files (docker-compose.override.yml, .env) are kept.
git checkout --quiet --force -B "$BRANCH" "origin/$BRANCH"

log "Rebuilding Docker services..."
$COMPOSE up -d --build

git rev-parse HEAD > "$STATE_FILE"
log "Deploy complete."
