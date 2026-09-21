#!/usr/bin/env python3
"""Bounded Linux-only experiment. No collection queues, game processes or labels."""
import argparse
import datetime
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import tempfile
import time


def run(command, cwd, timeout):
    env = dict(os.environ, DOTNET_PROCESSOR_COUNT="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    records = []
    for line in (stdout + "\n" + stderr).splitlines():
        if line.startswith("{"):
            records.append(json.loads(line))
    return {"exitCode": process.returncode, "timedOut": timed_out,
            "wallSeconds": time.monotonic() - started,
            "records": records, "stdout": stdout, "stderr": stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 10000:
        parser.error("iterations must be 1..10000")
    runtime = str(args.runtime.resolve(strict=True))
    dotnet = shutil.which(args.dotnet)
    if dotnet is None:
        parser.error("dotnet executable not found")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    report = {"schema": "standalone-simulator-probe/v1", "productionReady": False,
              "productionLabels": False, "completeBattles": 0,
              "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="sts2-simulator-probe-") as directory:
        work = Path(directory)
        for name in ("Program.cs", "HostAdapter.cs", "SimulatorPrototype.csproj"):
            shutil.copyfile(source / name, work / name)
        report["build"] = run([dotnet, "build", "-c", "Release", "--nologo"], work, 60)
        if report["build"]["exitCode"] == 0:
            dll = str(work / "bin/Release/net9.0/SimulatorPrototype.dll")
            report["smoke"] = run([dotnet, dll, runtime, str(args.iterations)], work, 30)
            report["rootProbe"] = run([dotnet, dll, runtime, "--root-probe"], work, 30)
            # Prove the adapter refuses an unreviewed assembly before attempting game bootstrap.
            bad = work / "unreviewed/mods/CombatSolver"
            bad.mkdir(parents=True)
            (bad / "CombatSolver.dll").write_bytes(b"not a reviewed runtime")
            report["unreviewedRuntime"] = run([dotnet, dll, str(work / "unreviewed"), "1"], work, 10)
    smoke = report.get("smoke", {})
    guard = report.get("unreviewedRuntime", {})
    report["smokePassed"] = smoke.get("exitCode") == 0 and any(
        x.get("status") == "smoke_passed" for x in smoke.get("records", []))
    report["versionGuardPassed"] = guard.get("exitCode") not in (None, 0) and "Unreviewed runtime assembly" in guard.get("stderr", "")
    report["fullRootCaptured"] = False  # The diagnostic mode never certifies a usable full root.
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        target = args.report.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_text(encoding="utf-8") != payload:
            raise IOError("Report verification failed")
        temporary.replace(target)
    print(payload)
    return 0 if report["smokePassed"] and report["versionGuardPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
