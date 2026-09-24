#!/usr/bin/env python3
"""Capture native deployed actions in an explicitly isolated Wine installation."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from damage_model.worker import GameProcess
from damage_model.provenance import sha256, verify_runtime


def write_report(path, report):
    data = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if temporary.read_bytes() != data:
        raise IOError("Trace report copy verification failed")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("experiment-directory", "native-runtime", "fixture", "progress-snapshot", "trace-dll", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    isolated = args.experiment_directory.resolve(strict=True)
    runtime = json.loads(args.native_runtime.read_text())
    for path in (runtime["game_dir"], runtime["data_dir"], runtime["env"]["WINEPREFIX"]):
        if not Path(path).resolve(strict=True).is_relative_to(isolated):
            parser.error("Every mutable runtime path must be inside the isolated experiment directory")
    teacher = json.loads((ROOT / "configs/teacher.json").read_text())
    verify_runtime(runtime, teacher)
    folder = Path(tempfile.mkdtemp(prefix="native-trace-", dir=isolated))
    trace = folder / "trace.jsonl"
    runtime["env"]["STS2_NATIVE_TRACE_PATH"] = "Z:" + str(trace).replace("/", "\\")
    runtime["log_path"] = str(folder / "native.log")
    fixture = json.loads(args.fixture.read_text())
    request = fixture["request"]
    request["runId"] = uuid.uuid4().hex
    progress = Path(runtime["data_dir"]) / "default/1/modded/profile1/saves/progress.save"
    if not progress.resolve().is_relative_to(isolated):
        raise ValueError("Progress file escapes isolated runtime")
    mod = Path(runtime["game_dir"]) / "mods/NativeTraceProbe"
    mod.mkdir()  # Refuse to replace another installed probe.
    game = GameProcess(**runtime)
    started = time.monotonic()
    try:
        progress.write_bytes(args.progress_snapshot.read_bytes())
        shutil.copyfile(args.trace_dll, mod / "NativeTraceProbe.dll")
        shutil.copyfile(Path(__file__).with_name("NativeTraceProbe.json"), mod / "NativeTraceProbe.json")
        result = game.run(request)
        time.sleep(1)  # Give final action observers time to finish before shutting down.
    finally:
        game.stop()
        shutil.rmtree(mod)
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    complete = (result.get("status") == "Passed" and result.get("combatEnded") is True
                and bool(events) and events[0]["kind"] == "initialized"
                and not any(e["kind"] == "trace_error" for e in events)
                and [e["sequence"] for e in events] == list(range(1, len(events) + 1)))
    report = dict(schema="native-fixed-action-trace/v1", complete=complete,
                  productionReady=False, productionLabels=False, directory=str(folder),
                  request=request, result=result, events=events, wallSeconds=time.monotonic()-started,
                  teacher=teacher, traceModSha256=sha256(args.trace_dll),
                  captureScriptSha256=sha256(__file__), fixtureSha256=sha256(args.fixture),
                  progressSnapshotSha256=sha256(args.progress_snapshot),
                  scope="Instrumented native trace for semantic replay; not a performance benchmark or production label.")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.report, report)
    print(json.dumps({"report": str(args.report), "complete": complete, "events": len(events)}), flush=True)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
