#!/usr/bin/env bash
# Install git hooks from scripts/hooks/ into this clone's .git/hooks/ directory.
# Uses symlinks so edits to the scripts propagate without re-running this script.
#
# Usage:  ./scripts/install-hooks.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "Not inside a git repository." >&2
  exit 1
fi

SRC_DIR="$REPO_ROOT/scripts/hooks"
DST_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$SRC_DIR" ]; then
  echo "Missing $SRC_DIR — nothing to install." >&2
  exit 1
fi

mkdir -p "$DST_DIR"

installed=0
for src in "$SRC_DIR"/*; do
  [ -f "$src" ] || continue
  name=$(basename "$src")
  # Skip this README / anything that looks like docs
  case "$name" in
    README*|*.md) continue ;;
  esac
  chmod +x "$src"
  target="$DST_DIR/$name"
  # Remove any existing hook (regular file, symlink, or dead link)
  rm -f "$target"
  ln -s "../../scripts/hooks/$name" "$target"
  printf '  ✓ %s → %s\n' "$name" "$(readlink "$target")"
  installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
  echo "No hooks found in $SRC_DIR."
  exit 0
fi

echo
echo "Installed $installed hook(s). Try 'git commit' — the pre-commit"
echo "check will run before each commit. Bypass once with --no-verify."
