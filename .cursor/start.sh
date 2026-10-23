#!/usr/bin/env bash
# Per-boot linking of the Python environments into /workspace.
#
# The virtualenvs are created under $HOME by .cursor/install.sh so they persist
# across the fresh /workspace checkout that happens on every boot (and inside
# environment-build snapshots). This script re-creates the documented
# /workspace/.venv and /workspace/.venv-train symlinks on each start. It is
# idempotent, fast, and never clobbers a real (non-symlink) directory a
# developer may have created by hand.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV_ROOT="${STS2_VENV_ROOT:-$HOME/sts2-venvs}"

link_venv() {
  local link="$1" target="$2"
  if [ -L "$link" ] || [ ! -e "$link" ]; then
    ln -sfn "$target" "$link"
  fi
}

if [ -d "$VENV_ROOT/collection" ]; then link_venv .venv "$VENV_ROOT/collection"; fi
if [ -d "$VENV_ROOT/train" ]; then link_venv .venv-train "$VENV_ROOT/train"; fi
