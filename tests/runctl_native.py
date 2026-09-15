"""Explicit native protocol checks; never collected by pytest.

Run from the repo: PYTHONPATH=. python tests/runctl_native.py --runtime ... --output ...
Use a dedicated run_control runtime, not a collection worker or player save.
This validates rejection at the C# boundary and the legacy combat protocol.
Whole episodes are exercised separately with python -m runctl.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import uuid

from runctl.env import RealRunEnv, RunControlError, atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in ["foreign", "sequence", "range", "missing", "timeout"]:
        with RealRunEnv(runtime) as env:
            observation = env.reset("RUNCTLP" + case.upper(), action_timeout_seconds=3)
            assert observation["state"]["ascension"] == 10
            assert observation["state"]["startedWithNeow"] is True
            action = dict(schemaVersion=1, runId=env.run_id,
                          decisionSeq=observation["decisionSeq"], choice=0)
            if case == "foreign":
                action["runId"] = "FOREIGN"
            elif case == "sequence":
                action["decisionSeq"] -= 1
            elif case == "range":
                action["choice"] = len(observation["options"])
            elif case == "missing":
                del action["choice"]
            if case != "timeout":
                atomic_json(env.run_dir / "action.json", action)
            try:
                env._wait()
            except RunControlError as exc:
                result = json.loads((env.run_dir / "result.json").read_text())
                assert result["status"] == "failed" and result["stage"] == "map"
                assert result["runId"] == env.run_id
                expected = {"missing": "missing required properties", "timeout": "canceled"}.get(case, "invalid action")
                assert expected in result["error"].lower(), result
                row = dict(case=case, passed=True, runId=env.run_id, error=str(exc))
            else:
                raise AssertionError(f"Native boundary accepted {case}")
            results.append(row)
            atomic_json(args.output / "protocol.json", dict(cases=results))
            print(json.dumps(row), flush=True)
    # Existing requests omit kind. Each fixture is a one-attack smoke combat,
    # not an episode and not a source of standardized damage labels.
    with RealRunEnv(runtime) as env:
        pid = None
        for index in range(2):
            request = dict(schemaVersion=1, runId=uuid.uuid4().hex, scenarioId="SMOKE-001",
                           exitOnComplete=False, timeoutSeconds=120,
                           forceShortSearchOnly=True, shortSearchBudgetOverrideMilliseconds=2000,
                           searchMaxDegreeOfParallelismForTest=1, enableNoGcRegionForTest=False)
            result = env.game.run(request)
            assert result["status"] == "Passed", result
            current_pid = env.game.process.pid
            if pid is not None:
                assert current_pid == pid, "Legacy reuse silently restarted"
            pid = current_pid
            row = dict(case=f"legacy-{index}", passed=True, runId=request["runId"], pid=pid)
            results.append(row)
            atomic_json(args.output / "protocol.json", dict(cases=results))
            print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
