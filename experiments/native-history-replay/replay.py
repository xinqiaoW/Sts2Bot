#!/usr/bin/env python3
"""Replay retained successful soak routes in the original, pinned native game.

No teacher search is allowed. Every native checkpoint and attempt is retained;
SQLite FULL commits advance the source cursor only after an outcome is durable.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

try:
    import ujson as fastjson
except ImportError:
    fastjson = json

REPORT_SHA = "82289783503adb713978c13f05d1fe6ee7c9c78c498547db91a0b32ad7fee9e3"
SOLVER_SHA = "f55809c52e58ba3bcbc01bbc9ad89eb59de6d468143fa9260a58c0f68d8a8d0b"
GAME_SHA = "0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9"
PROGRESS_SHA = "7e85da8d9e937869e8aaf3a8b559e343683231b5cc05dab2815b91e144365d9f"
BASE = Path("/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929")
SOAK = BASE / "rollout-v5b/soak"
TEMPLATE = BASE / "native-terminal-diagnostic-0001/native-template"
COLLECTOR = Path(__file__).resolve().parent / "collector"
if not COLLECTOR.exists():
    COLLECTOR = Path("/data1/pl/ImageTask/wxq/Projects/standalone-boulder-validation-20261001/source")
STOP_REQUESTED = False


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)
    sync_dir(path.parent)


def event(path, value):
    with Path(path).open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def repair_jsonl(path):
    """Discard only a crash-truncated final line; individual results remain intact."""
    if not path.exists():
        return
    with path.open("r+b") as f:
        f.seek(0, 2)
        size = f.tell()
        if not size:
            return
        f.seek(size - 1)
        if f.read(1) == b"\n":
            return
        pos = size
        while pos:
            start = max(0, pos - 65536)
            f.seek(start)
            chunk = f.read(pos - start)
            end = chunk.rfind(b"\n")
            if end >= 0:
                f.truncate(start + end + 1)
                break
            pos = start
        else:
            f.truncate(0)
        f.flush()
        os.fsync(f.fileno())


def successful_cases():
    report = SOAK / "report.json"
    if sha(report) != REPORT_SHA:
        raise ValueError("Frozen 24h report identity changed")
    data = fastjson.loads(report.read_bytes())
    cases = {value["runId"]: (job, value) for job, value in data["cases"].items()
             if value.get("status") == "complete"}
    if len(cases) != 202527:
        raise ValueError("Expected all 202527 successful historical cases")
    return cases


def source_cases(worker, offset=0):
    """One completion and its opening/boundary records, with exact byte cursor."""
    path = SOAK / "workers" / f"{worker:02d}" / "host.log"
    opening = None
    opening_choices = []
    boundaries = {}
    start = offset
    with path.open("rb") as f:
        f.seek(offset)
        while line := f.readline():
            before, after = f.tell() - len(line), f.tell()
            if not line.startswith(b"{"):
                continue
            try:
                row = fastjson.loads(line)
            except ValueError:
                continue
            status = row.get("status")
            if row.get("stage") == "native_test_host":
                opening, opening_choices, boundaries = None, [], {}
                start = before
            elif status == "teacher_opening_choice_plan":
                if opening_choices:
                    raise ValueError("Duplicate opening choice plan")
                opening_choices = row["choices"]
            elif status == "request_native_opening":
                if opening is not None:
                    raise ValueError("Duplicate historical opening checkpoint")
                opening = row["stamp"]
            elif status == "native_boundary_choices_consumed":
                turn = row["turn"]
                if turn in boundaries:
                    raise ValueError("Duplicate historical boundary")
                if row["count"] != len(row["choices"]) or row["consumed"] + row.get("cancelledAfterTerminal", 0) != row["count"]:
                    raise ValueError("Historical boundary choice list is incomplete")
                boundaries[turn] = row
            elif status == "StandaloneCompleted":
                yield row, opening, opening_choices, boundaries, {
                    "worker": worker, "startOffset": start, "offset": after,
                    "completionOffset": before, "completionSha256": hashlib.sha256(line).hexdigest(),
                }
                opening, opening_choices, boundaries = None, [], {}
                start = after
            elif status in ("StandaloneFailed", "Failed", "Timeout"):
                opening, opening_choices, boundaries = None, [], {}
                start = after


def make_plan(row, opening, choices, boundaries, job, native_id, output):
    if not opening or not row["trainingObservation"]["complete"] or not row["combatEnded"]:
        raise ValueError("Historical case lacks opening or stable terminal state")
    provenance = row["provenance"]
    for key, expected in (("solverSha256", SOLVER_SHA), ("gameSha256", GAME_SHA), ("progressSnapshotSha256", PROGRESS_SHA)):
        if provenance[key] != expected:
            raise ValueError("Historical dependency identity differs: " + key)
    execution = row["execution"]
    if "trace" not in execution:
        if execution.get("status") != "native_opening_terminal" or execution.get("openingTerminal") is not True or row["trainingObservation"].get("openingTerminal") is not True:
            raise ValueError("Historical action trace is missing")
        segments = []
    else:
        segments = execution["trace"]
    steps, used_boundaries = [], set()
    previous_turn = 1
    for i, segment in enumerate(segments):
        turn = segment["turn"]
        if turn < previous_turn:
            raise ValueError("Historical turn order is invalid")
        previous_turn = turn
        deployment = segment["deployment"]
        trace = deployment["trace"]
        if len(trace) != deployment["actionCount"]:
            raise ValueError("Historical deployment actions are incomplete")
        for a, entry in enumerate(trace):
            action = entry["action"]
            if action["Kind"] != 0 or action["Turn"] != turn or not entry["live"]:
                raise ValueError("Historical action is unsupported or lacks a state checkpoint")
            steps.append({"kind": "play", "turn": turn, "action": action, "expected": entry["live"],
                          "allowUnconsumedPlan": a == len(trace) - 1 and deployment.get("reason") == "choice_plan_unconsumed"})
        if i == len(segments) - 1 or segments[i + 1]["turn"] != turn:
            if turn in boundaries:
                boundary = boundaries[turn]
                steps.append({"kind": "end_turn", "turn": turn, "choices": boundary["choices"],
                              "cancelledAfterTerminal": boundary.get("cancelledAfterTerminal", 0)})
                used_boundaries.add(turn)
    # Opening-terminal cases have no deployment segments. A missing segment for
    # a zero-play turn would be ambiguous and must never silently be guessed.
    if set(boundaries) != used_boundaries:
        raise ValueError("Historical boundary is not represented in the action route")
    terminal = row["trainingObservation"]["finalCombatState"]
    if not isinstance(terminal, str) or not terminal:
        raise ValueError("Historical stable terminal checkpoint is missing")
    annotate_terminal_cancellation(steps, row["finishedTurn"])
    return {"nativeRunId": native_id, "sourceRunId": row["runId"], "sourceJobId": job,
            "checkpointPath": str(output), "progressSnapshotSha256": PROGRESS_SHA,
            "openingChoices": choices, "openingState": opening, "steps": steps,
            "terminalState": terminal, "finishedTurn": row["finishedTurn"],
            "plays": sum(s["kind"] == "play" for s in steps)}


def annotate_terminal_cancellation(steps, finished_turn):
    """Authorize only a retained terminal boundary; never discard a mid-battle plan.

    The old selector could count ENTROPY's missing transform as applied after
    combat cleared every pile. Retain that source ledger and mark the repair;
    the native consumer still checks the actual terminal turn, unused count,
    every post-play checkpoint and the complete terminal stamp.
    """
    if not steps or steps[-1]["kind"] != "end_turn":
        return
    step = steps[-1]
    if finished_turn not in (step["turn"], step["turn"] + 1):
        return
    count = step["cancelledAfterTerminal"]
    if count:
        if not 0 < count <= len(step["choices"]):
            raise ValueError("Historical terminal cancellation count is invalid")
        step["terminalChoiceCancellation"] = {"mode": "recorded", "count": count}
    elif (finished_turn == step["turn"] and step["choices"]
          and step["choices"][-1].get("SourceId") == "ENTROPY_POWER"
          and step["choices"][-1].get("Effect") == 5
          and step["choices"][-1].get("Cards")):
        step["terminalChoiceCancellation"] = {"mode": "legacy_entropy_cleanup", "count": 1}


def prepare(root, binary_dir):
    root.mkdir(parents=True, exist_ok=True)
    runtime_dir = root / "runtime"
    if runtime_dir.exists():
        raise ValueError("Runtime already exists; refusing to overwrite an experiment")
    runtime_dir.mkdir()
    # Hardlink immutable game assets, copy every mutable prefix/save file.
    shutil.copytree(TEMPLATE / "game", runtime_dir / "game", copy_function=os.link)
    subprocess.run(["cp", "-a", "--reflink=auto", str(TEMPLATE / "prefix"), str(runtime_dir / "prefix")], check=True)
    mod_dir = runtime_dir / "game/mods/NativeHistoryReplay"
    mod_dir.mkdir()
    shutil.copy2(binary_dir / "NativeHistoryReplay.dll", mod_dir)
    shutil.copy2(Path(__file__).with_name("NativeHistoryReplay.json"), mod_dir)
    progress = root / "progress-snapshot.json"
    shutil.copy2(BASE / "candidate-release-v5/progress-snapshot.json", progress)
    runtime = json.loads((TEMPLATE / "native-runtime.json").read_text())
    runtime["game_dir"] = str(runtime_dir / "game")
    runtime["data_dir"] = str(runtime_dir / "prefix/drive_c/users/pl/AppData/Roaming/SlayTheSpire2")
    runtime["log_path"] = str(root / "native.log")
    runtime["env"].update({"WINEPREFIX": str(runtime_dir / "prefix"), "PYTHONDONTWRITEBYTECODE": "1",
                            "STS2_HISTORY_REPLAY_PLAN": str(root / "active-plan.json"),
                            "STS2_HISTORY_REPLAY_PROGRESS": str(progress),
                            "STS2_HISTORY_REPLAY_SOLVER_SHA256": SOLVER_SHA})
    data = Path(runtime["data_dir"])
    for name in ("combat_solver_test_request.json", "combat_solver_test_ready.json", "combat_solver_test_result.json"):
        (data / name).unlink(missing_ok=True)
    atomic_json(root / "native-runtime.json", runtime)
    source_files = []
    for worker in range(24):
        path = SOAK / "workers" / f"{worker:02d}" / "host.log"
        st = path.stat()
        source_files.append({"path": str(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns})
    manifest = {"createdAt": time.time(), "report": str(SOAK / "report.json"), "reportSha256": REPORT_SHA,
                "sourceFiles": source_files, "nativeSolverSha256": SOLVER_SHA, "nativeGameSha256": GAME_SHA,
                "progressSnapshotSha256": PROGRESS_SHA, "modSha256": sha(mod_dir / "NativeHistoryReplay.dll"),
                "expectedCases": 202527, "comparison": "exact opening, every recorded post-play state, stable terminal and turn; native end-turn choices",
                "missingHistoricalCheckpoints": "No full intermediate end-turn states were saved; compare next recorded action and terminal instead."}
    atomic_json(root / "manifest.json", manifest)


def verify_inputs(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for relative, expected in manifest.get("frozenCode", {}).items():
        if sha(root / relative) != expected:
            raise ValueError("Frozen replay code changed: " + relative)
    for item in manifest["sourceFiles"]:
        st = Path(item["path"]).stat()
        if (st.st_size, st.st_mtime_ns) != (item["size"], item["mtime_ns"]):
            raise ValueError("Historical source log changed: " + item["path"])
    game = root / "runtime/game"
    for path, expected in ((game / "data_sts2_windows_x86_64/sts2.dll", GAME_SHA),
                           (game / "mods/CombatSolver/CombatSolver.dll", SOLVER_SHA),
                           (root / "progress-snapshot.json", PROGRESS_SHA),
                           (game / "mods/NativeHistoryReplay/NativeHistoryReplay.dll", manifest["modSha256"])):
        if sha(path) != expected:
            raise ValueError("Pinned native dependency changed: " + str(path))


class Store:
    def __init__(self, root):
        self.root = root
        self.db = sqlite3.connect(root / "results.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS outcomes(job TEXT PRIMARY KEY, run TEXT UNIQUE, status TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job TEXT, status TEXT, path TEXT);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        self.db.commit()
        for attempt, path in self.db.execute("SELECT id,path FROM attempts WHERE status='running'").fetchall():
            event(root / "events.jsonl", {"event": "attempt_interrupted", "attempt": attempt, "path": path, "at": time.time()})
        self.db.execute("UPDATE attempts SET status='interrupted' WHERE status='running'")
        self.db.commit()
        self.counts = Counter(dict(self.db.execute("SELECT status,count(*) FROM outcomes GROUP BY status")))

    def cursor(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()
        return json.loads(row[0]) if row else {"worker": 0, "offset": 0}

    def begin(self, attempt, job, path):
        self.db.execute("INSERT INTO attempts VALUES (?,?,?,?)", (attempt, job, "running", str(path)))
        self.db.commit()

    def finish(self, result, cursor):
        job = result["sourceJobId"]
        path = Path(result["attemptPath"])
        atomic_json(path / "result.json", result)
        with self.db:
            self.db.execute("INSERT INTO outcomes VALUES (?,?,?,?)", (job, result["sourceRunId"], result["status"], json.dumps(result)))
            self.db.execute("UPDATE attempts SET status=? WHERE id=?", (result["status"], result["attempt"]))
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('cursor',?)", (json.dumps(cursor),))
        self.counts[result["status"]] += 1
        event(self.root / "results.jsonl", result)


def checkpoints(path):
    # A native crash may leave the final write partial; keep it on disk and use
    # only complete checkpoint records in classification.
    rows = []
    if path.exists():
        with path.open("rb") as f:
            for line in f:
                if not line.endswith(b"\n"):
                    continue
                rows.append(json.loads(line))
    return rows


def write_state(root, store, **extra):
    atomic_json(root / "state.json", {"pid": os.getpid(), "updatedAt": time.time(),
                "expectedCases": 202527, "completedCases": sum(store.counts.values()),
                "counts": dict(store.counts), "cursor": store.cursor(), **extra})


def run(root, limit=None, only_run=None, corrupt_opening=False, pilot_runs=None):
    root = root.resolve()
    lease = (root / "controller.lock").open("a+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    repair_jsonl(root / "results.jsonl")
    repair_jsonl(root / "events.jsonl")
    verify_inputs(root)
    cases = successful_cases()
    sys.path.insert(0, str(COLLECTOR))
    from damage_model.worker import GameProcess
    runtime = json.loads((root / "native-runtime.json").read_text())
    store = Store(root)
    scope = json.dumps({"selectedRuns": sorted(pilot_runs or ([only_run] if only_run else [])), "corruptOpening": corrupt_opening}, sort_keys=True)
    previous_scope = store.db.execute("SELECT value FROM meta WHERE key='scope'").fetchone()
    if previous_scope and previous_scope[0] != scope:
        raise ValueError("Cannot mix pilot/negative controls with the full campaign in one result directory")
    store.db.execute("INSERT OR REPLACE INTO meta VALUES ('scope',?)", (scope,))
    store.db.commit()
    selected = set(pilot_runs or ([only_run] if only_run else []))
    class ReplayGame(GameProcess):
        def start(self):
            super().start()
            state_path = root / "state.json"
            state = json.loads(state_path.read_text())
            state.update({"nativePid": self.process.pid, "updatedAt": time.time()})
            atomic_json(state_path, state)
            atomic_json(root / "native-process.json", {"pid": self.process.pid, "startedAt": time.time(),
                        "command": self.command, "log": str(self.log_path)})
    game = ReplayGame(**runtime)
    initial = store.cursor()
    attempted = 0
    early_failures = 0
    global STOP_REQUESTED

    def stop(signum, frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True  # Save the active battle, then stop between cases.

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    event(root / "events.jsonl", {"event": "controller_started", "pid": os.getpid(), "at": time.time(), "cursor": initial})
    write_state(root, store, phase="starting")
    try:
        for worker in range(initial["worker"], 24):
            offset = initial["offset"] if worker == initial["worker"] else 0
            for row, opening, choices, boundaries, cursor in source_cases(worker, offset):
                run_id = row["runId"]
                if run_id not in cases:
                    raise ValueError("Successful host route absent from frozen report: " + run_id)
                job, reported = cases[run_id]
                if selected and run_id not in selected:
                    continue
                if STOP_REQUESTED or (root / "STOP").exists() or (limit is not None and attempted >= limit):
                    write_state(root, store, phase="stopped", nativePid=None)
                    return
                if store.db.execute("SELECT 1 FROM outcomes WHERE job=?", (job,)).fetchone():
                    continue
                attempt = uuid.uuid4().hex
                directory = root / "attempts" / job[:2] / job / attempt
                directory.mkdir(parents=True)
                sync_dir(directory.parent)
                native_id = "history-" + attempt
                started = time.time()
                result = {"sourceJobId": job, "sourceRunId": run_id, "attempt": attempt,
                          "attemptPath": str(directory), "source": cursor, "startedAt": started}
                store.begin(attempt, job, directory)
                log_start = game.log_path.stat().st_size if game.log_path.exists() else 0
                try:
                    plan = make_plan(row, opening, choices, boundaries, job, native_id, directory / "checkpoints.jsonl")
                    if corrupt_opening:
                        plan["openingState"] += ";deliberate_negative_control"
                    request = dict(row["collectionRequest"])
                    request.update({"runId": native_id, "scenarioId": "HISTORY-" + job[:16], "timeoutSeconds": 120,
                                    "exitOnComplete": False})
                    atomic_json(directory / "request.json", request)
                    atomic_json(directory / "plan.json", plan)
                    atomic_json(root / "active-plan.json", plan)
                    write_state(root, store, phase="replaying", activeJob=job, activeRun=run_id,
                                activeAttempt=attempt, activePath=str(directory), nativePid=game.process.pid if game.process else None)
                    native = game.run(request)
                    atomic_json(directory / "native-result.json", native)
                    observations = checkpoints(directory / "checkpoints.jsonl")
                    compared = [v["value"] for v in observations if v["kind"] == "checkpoint"]
                    mismatches = [v for v in compared if not v["matches"]]
                    completed = [v["value"] for v in observations if v["kind"] == "replay_completed"]
                    if mismatches:
                        status = "mismatch"
                    elif native.get("status") == "Passed" and len(completed) == 1 and completed[0]["checkpoints"] == plan["plays"] + 2:
                        status = "matched"
                    else:
                        status = "execution_failure"
                    result.update({"status": status, "nativeStatus": native.get("status"),
                                   "nativeError": native.get("error"), "nativeRunId": native_id,
                                   "checkpoints": len(compared), "matchedCheckpoints": sum(v["matches"] for v in compared),
                                   "comparisonCompleted": bool(completed), "plays": plan["plays"],
                                   "mismatchPoints": [v["point"] for v in mismatches],
                                   "nativeReplay": completed[0] if completed else None})
                    early_failures = early_failures + 1 if not compared else 0
                    if status != "matched":
                        game.stop()
                except (ValueError, KeyError, TypeError) as error:
                    result.update({"status": "unreplayable", "error": str(error)})
                    early_failures += 1
                    game.stop()
                result.update({"finishedAt": time.time(), "elapsedSeconds": time.time() - started,
                               "nativeLogStart": log_start, "nativeLogEnd": game.log_path.stat().st_size if game.log_path.exists() else log_start})
                store.finish(result, cursor)
                attempted += 1
                summary = {"event": "case_completed", "sourceJobId": job, "status": result["status"],
                           "completedCases": sum(store.counts.values()), "counts": dict(store.counts),
                           "elapsedSeconds": result["elapsedSeconds"], "nativePid": game.process.pid if game.process else None}
                print(json.dumps(summary), flush=True)
                write_state(root, store, phase="running", nativePid=game.process.pid if game.process else None)
                if early_failures >= 5:
                    raise RuntimeError("Five consecutive routes produced no native comparison; inspect saved attempts before resuming")
                if selected and sum(store.counts.values()) == len(selected):
                    write_state(root, store, phase="stopped", nativePid=None)
                    return
        total = sum(store.counts.values())
        expected = len(selected) if selected else 202527
        if total != expected:
            raise ValueError(f"End of source logs reached but only {total}/{expected} unique cases have outcomes")
        write_state(root, store, phase="complete" if not selected else "stopped", nativePid=None)
    except BaseException as error:
        event(root / "events.jsonl", {"event": "controller_error", "at": time.time(), "error": repr(error)})
        write_state(root, store, phase="error", error=repr(error), nativePid=None)
        raise
    finally:
        game.stop()
        store.db.execute("PRAGMA wal_checkpoint(FULL)")
        store.db.close()
        lease.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--binary-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-run")
    parser.add_argument("--pilot-runs", nargs="+")
    parser.add_argument("--corrupt-opening", action="store_true", help="Pilot negative control only")
    args = parser.parse_args()
    if args.prepare:
        if args.binary_dir is None:
            parser.error("--prepare requires --binary-dir")
        prepare(args.root.resolve(), args.binary_dir.resolve())
    else:
        run(args.root, args.limit, args.only_run, args.corrupt_opening, args.pilot_runs)


if __name__ == "__main__":
    main()
