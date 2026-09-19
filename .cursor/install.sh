#!/usr/bin/env bash
# Idempotent Cloud Agent setup for the Sts2 damage model repository.
#
# Creates the two Python environments the project documents:
#   .venv        collection / model code (numpy + torch)   -> `python -m damage_model.cli ...`, pytest
#   .venv-train  training / comparison / inference extras   -> `python -m train.* ...`
#
# The virtualenvs live under $HOME (VENV_ROOT), NOT inside /workspace, so they
# survive the fresh /workspace checkout that happens on every boot and are
# captured in environment-build snapshots. `.cursor/start.sh` links them back
# into /workspace as .venv / .venv-train on each boot for the documented paths.
#
# CPU torch wheels are used because Cloud Agent VMs have no GPU; the training
# code still accepts --device cuda:* where a GPU is available.
#
# Not provisioned here: the Slay the Spire 2 game assets, Wine, and the
# generated `catalogs/game-0.111.0.raw.json` catalog dump. Those are proprietary
# and required only for live data collection and the catalog-backed tests.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV_ROOT="${STS2_VENV_ROOT:-$HOME/sts2-venvs}"
TORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"

# System packages required to build Python virtual environments. Guarded so the
# step is a no-op once the base image or snapshot already provides them.
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip
fi

mkdir -p "$VENV_ROOT"

# Collection / model environment.
python3 -m venv "$VENV_ROOT/collection"
"$VENV_ROOT/collection/bin/python" -m pip install --quiet --upgrade pip
"$VENV_ROOT/collection/bin/python" -m pip install --quiet --index-url "$TORCH_CPU_INDEX" torch
"$VENV_ROOT/collection/bin/python" -m pip install --quiet "numpy>=1.24" pytest
"$VENV_ROOT/collection/bin/python" -m pip install --quiet -e .

# Training / comparison / inference environment (README: adds ML extras on top
# of the collection dependencies without touching the collection env).
python3 -m venv "$VENV_ROOT/train"
"$VENV_ROOT/train/bin/python" -m pip install --quiet --upgrade pip
"$VENV_ROOT/train/bin/python" -m pip install --quiet --index-url "$TORCH_CPU_INDEX" torch
"$VENV_ROOT/train/bin/python" -m pip install --quiet \
  "numpy>=1.24" pytest scipy pandas pyarrow scikit-learn lightgbm rtdl_revisiting_models tabm
"$VENV_ROOT/train/bin/python" -m pip install --quiet -e .

# Link the environments into /workspace for the documented .venv paths.
bash "$(dirname "${BASH_SOURCE[0]}")/start.sh"

echo "Environment ready: .venv (collection) and .venv-train (training) -> $VENV_ROOT."
