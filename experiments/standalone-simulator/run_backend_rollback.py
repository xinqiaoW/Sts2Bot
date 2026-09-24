#!/usr/bin/env python3
"""Exercise native -> standalone drain -> native using isolated frozen collector code."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from replay_evidence import write


def snapshot(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return dict(counts=dict(db.execute("SELECT status,count(*) FROM jobs GROUP BY status")),
                    attempts=[list(r) for r in db.execute("SELECT * FROM attempts ORDER BY id")])


def unlocked(path):
    with path.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "benchmark", "native-runtime", "isolated-native-directory", "output-root", "report"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.report.exists(): p.error("Report already exists")
    bundle = a.bundle.resolve(strict=True)
    subprocess.run([sys.executable, str(bundle / "release_tool.py"), "verify", "--bundle", str(bundle)], check=True)
    sys.path.insert(0, str(bundle))
    from damage_model.catalog import Catalog
    from damage_model.provenance import teacher_for, verify_runtime
    from damage_model.schema import Build
    from damage_model.store import Store
    native = json.loads(a.native_runtime.read_text())
    isolated = a.isolated_native_directory.resolve(strict=True)
    for path in (native["game_dir"], native["data_dir"], native["env"]["WINEPREFIX"]):
        if not Path(path).resolve(strict=True).is_relative_to(isolated):
            raise ValueError("Mutable native path outside isolated directory")
    unlocked(Path(native["data_dir"]) / "collector.lock")
    folder = Path(tempfile.mkdtemp(prefix="standalone-rollback-", dir=a.output_root.resolve()))
    native["log_path"] = str(folder / "native-game.log")
    standalone = json.loads((bundle / "runtime-template.json").read_text())
    standalone["data_dir"] = str(folder / "standalone-data")
    Path(standalone["data_dir"]).mkdir()
    catalog = Catalog.load(bundle / "catalogs/game-0.111.0.raw.json", bundle / "configs/real-runs-8s.json")
    nt = teacher_for(catalog, bundle / "configs/teacher.json")
    st = json.loads((bundle / "teacher.json").read_text())
    verify_runtime(native, nt); verify_runtime(standalone, st)
    comparison = json.loads(a.benchmark.read_text())
    assert comparison["complete"]
    stores = {k: Store(folder / (k + ".sqlite")) for k in ("native", "standalone")}
    for fixture in ("restore-3.json", "restore-5.json"):
        trial = next(t for t in comparison["trials"] if t["fixture"] == fixture and t["backend"] == "native-wine" and t["validatedStatus"] == "complete")
        source = Path(trial["resultFile"]).with_suffix(".sqlite")
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
            body, target, seed, teacher = db.execute("SELECT b.body,j.target,j.seed,j.teacher FROM jobs j JOIN builds b ON b.id=j.build_id").fetchone()
        assert all(nt.get(k) == v for k, v in json.loads(teacher).items())
        for name, teacher in (("native", nt), ("standalone", st)):
            stores[name].schedule(Build.from_dict(json.loads(body)), [json.loads(target)], [seed], teacher)
    for store in stores.values(): store.db.close()
    for name, runtime in (("native", native), ("standalone", standalone)):
        write(folder / (name + "-runtime.json"), runtime)
    report = dict(schema="standalone-native-rollback/v1", productionReady=False, productionLabels=False,
                  directory=str(folder), bundle=str(bundle), complete=False, passed=False, phases=[],
                  scope="Isolated single-queue pool handoff; experiment pointer only, no production session switched.",
                  scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    write(a.report, report)
    env = {**os.environ, "PYTHONPATH": str(bundle), "PYTHONSAFEPATH": "1", "TMPDIR": "/tmp"}
    def run(name, phase, drain=False):
        runtime = native if name == "native" else standalone
        dbpath = folder / (name + ".sqlite")
        unlocked(dbpath.with_suffix(".pool.lock"))
        unlocked(Path(runtime["data_dir"]) / "collector.lock")
        write(folder / "active.json", dict(backend=name, database=str(dbpath), runtime=str(folder / (name + "-runtime.json"))))
        if name == "native":
            progress = Path(native["data_dir"]) / "default/1/modded/profile1/saves/progress.save"
            data = (bundle / "progress-snapshot.json").read_bytes()
            temp = progress.with_name(progress.name + "." + uuid.uuid4().hex)
            with temp.open("xb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            assert temp.read_bytes() == data
            os.replace(temp, progress)
            assert progress.read_bytes() == data
        command = [sys.executable, "-P", "-u", "-m", "tools.collect_parallel", "--db", str(dbpath),
                   "--config", str(bundle / "configs/real-runs-8s.json"), "--catalog", str(bundle / "catalogs/game-0.111.0.raw.json"),
                   "--teacher", str(bundle / ("configs/teacher.json" if name == "native" else "teacher.json")),
                   "--runtimes", str(folder / (name + "-runtime.json")), "--reserve-gib", "4", "--worker-start-gib", "2",
                   "--limit-per-worker", "2" if drain else "1"]
        entry = dict(phase=phase, command=command, before=snapshot(dbpath), stopRequestedDuringLease=False)
        with (folder / (phase + ".log")).open("w") as log:
            proc = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
            entry["pid"] = proc.pid
            deadline = time.monotonic() + 60
            if drain:
                while proc.poll() is None:
                    if snapshot(dbpath)["counts"].get("running", 0):
                        (Path(runtime["data_dir"]) / "collector.stop").touch()
                        entry["stopRequestedDuringLease"] = True
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("No active lease observed; collector left intact for diagnosis")
                    time.sleep(.1)
            entry["exitCode"] = proc.wait()
        entry["after"] = snapshot(dbpath)
        unlocked(dbpath.with_suffix(".pool.lock")); unlocked(Path(runtime["data_dir"]) / "collector.lock")
        entry["locksReleased"] = True
        assert entry["exitCode"] == 0 and entry["after"]["counts"].get("running", 0) == 0
        assert entry["after"]["counts"].get("complete", 0) == entry["before"]["counts"].get("complete", 0) + 1
        if drain: assert entry["stopRequestedDuringLease"] and entry["after"]["counts"].get("pending") == 1
        report["phases"].append(entry); write(a.report, report)
        print(json.dumps(dict(phase=phase, counts=entry["after"]["counts"])), flush=True)
        return entry["after"]
    before = run("native", "native-before")
    standalone_state = run("standalone", "standalone-stop-drain", True)
    assert snapshot(folder / "native.sqlite") == before
    for name in stores:
        with sqlite3.connect(folder / (name + ".sqlite")) as src, sqlite3.connect(folder / (name + ".handoff-backup.sqlite")) as dest:
            src.backup(dest)
        assert snapshot(folder / (name + ".sqlite")) == snapshot(folder / (name + ".handoff-backup.sqlite"))
    after = run("native", "native-after-rollback")
    assert after["attempts"][:len(before["attempts"])] == before["attempts"]
    assert snapshot(folder / "standalone.sqlite") == standalone_state
    assert after["counts"] == {"complete": 2}
    subprocess.run([sys.executable, str(bundle / "release_tool.py"), "verify", "--bundle", str(bundle)], check=True)
    report.update(complete=True, passed=True, nativeHistoryPreserved=True, standaloneHistoryPreserved=True,
                  handoffBackupsVerified=True, finalActive=json.loads((folder / "active.json").read_text()))
    write(a.report, report)

if __name__ == "__main__":
    main()
