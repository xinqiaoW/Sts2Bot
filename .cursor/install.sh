#!/usr/bin/env bash
# Idempotent Cloud Agent setup for the Sts2 damage model repository.
#
# Creates the two Python environments the project documents:
#   .venv        collection / model code (numpy + torch)   -> `python -m damage_model.cli ...`, pytest
#   .venv-train  training / comparison / inference extras   -> `python -m train.* ...`
#
# CPU torch wheels are used because Cloud Agent VMs have no GPU; the training
# code still accepts --device cuda:* where a GPU is available.
#
# Not provisioned here: the Slay the Spire 2 game assets, Wine, and the
# generated `catalogs/game-0.111.0.raw.json` catalog dump. Those are proprietary
# and required only for live data collection and the catalog-backed tests.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"

# System packages required to build Python virtual environments. Guarded so the
# step is a no-op once the base image or snapshot already provides them.
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip
fi

# Collection / model environment.
python3 -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet --index-url "$TORCH_CPU_INDEX" torch
.venv/bin/python -m pip install --quiet "numpy>=1.24" pytest
.venv/bin/python -m pip install --quiet -e .

# Training / comparison / inference environment (README: adds ML extras on top
# of the collection dependencies without touching the collection env).
python3 -m venv .venv-train
.venv-train/bin/python -m pip install --quiet --upgrade pip
.venv-train/bin/python -m pip install --quiet --index-url "$TORCH_CPU_INDEX" torch
.venv-train/bin/python -m pip install --quiet \
  "numpy>=1.24" pytest scipy pandas pyarrow scikit-learn lightgbm rtdl_revisiting_models tabm
.venv-train/bin/python -m pip install --quiet -e .

echo "Environment ready: .venv (collection) and .venv-train (training)."
