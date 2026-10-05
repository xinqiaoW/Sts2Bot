#!/usr/bin/env python3
"""Freeze this diagnostic and start a durable user systemd replay service."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--unit", default="sts2-native-history-replay-20261004")
    args = parser.parse_args()
    root = args.root.resolve()
    source = Path(__file__).resolve().parent
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=source, text=True).strip()
    if branch != "codex/standalone-combat-prototype":
        raise RuntimeError("Launch must originate from the requested prototype branch")
    if subprocess.check_output(["loginctl", "show-user", "pl", "-p", "Linger", "--value"], text=True).strip() != "yes":
        raise RuntimeError("User manager must already have Linger=yes to survive SSH logout")
    replay.verify_inputs(root)
    if (root / "code").exists():
        raise RuntimeError("Frozen code already exists; resume the existing service instead of overwriting it")
    code = root / "code"
    code.mkdir()
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, code / path.name)
    collector = code / "collector/damage_model"
    collector.mkdir(parents=True)
    for name in ("__init__.py", "worker.py", "schema.py"):
        shutil.copy2(replay.COLLECTOR / "damage_model" / name, collector / name)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest.update({"sourceWorktree": str(source.parent.parent), "sourceBranch": branch,
                     "sourceHead": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip(),
                     "frozenCode": {str(path.relative_to(root)): replay.sha(path) for path in code.rglob("*") if path.is_file()}})
    replay.atomic_json(root / "manifest.json", manifest)
    unit = args.unit + ".service"
    unit_text = f"""[Unit]
Description=Native replay of all 202527 retained standalone combat routes
StartLimitIntervalSec=600
StartLimitBurst=3

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={sys.executable} {code / 'replay.py'} --root {root}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
Environment=OPENBLAS_NUM_THREADS=1
StandardInput=null
StandardOutput=append:{root / 'controller.log'}
StandardError=append:{root / 'controller.log'}
KillMode=mixed
TimeoutStopSec=180
Restart=on-abnormal
RestartSec=15
MemoryMax=8G
CPUQuota=200%
TasksMax=512
Nice=10
"""
    unit_path = Path.home() / ".config/systemd/user" / unit
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    if unit_path.exists():
        raise RuntimeError("Refusing to overwrite another systemd service")
    (root / unit).write_text(unit_text)
    unit_path.write_text(unit_text)
    # Previous pilots used this isolated prefix. End only its Wine server so
    # every process in the final runtime belongs to the new service cgroup.
    runtime = json.loads((root / "native-runtime.json").read_text())
    wineserver = Path(runtime["command"][0]).with_name("wineserver")
    stopped = subprocess.run([str(wineserver), "-k"], env={**__import__("os").environ, "WINEPREFIX": runtime["env"]["WINEPREFIX"]})
    if stopped.returncode not in (0, 1):  # Wine returns 1 when no server is running.
        raise RuntimeError("Could not stop the isolated pilot Wine server")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "start", unit], check=True)
    info = subprocess.check_output(["systemctl", "--user", "show", unit,
                                   "-p", "MainPID", "-p", "ActiveState", "-p", "ControlGroup"], text=True)
    print(info.strip())
    replay.atomic_json(root / "service.json", {"unit": unit, "unitPath": str(unit_path), "launchInfo": info})


if __name__ == "__main__":
    main()
