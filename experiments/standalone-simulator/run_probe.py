#!/usr/bin/env python3
"""Bounded Linux-only experiment. No collection queues, game processes or labels."""
import argparse
import concurrent.futures
import datetime
import json
import hashlib
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



def raw_completion_matches_execution(value, expected_initial, request):
    """Validate the API label against this execution, not a separately searched route."""
    observation = value.get('trainingObservation', {})
    execution = value.get('execution', {})
    hp, maximum = observation.get('finalHp'), observation.get('finalMaxHp')
    initial = observation.get('initialHp')
    try:
        utc = datetime.datetime.fromisoformat(value.get('finishedAtUtc', '')).utcoffset() == datetime.timedelta(0)
    except (ValueError, TypeError):
        return False
    return (value.get('status') == 'StandaloneCompleted' and value.get('combatEnded') is True
            and value.get('runId') == request['runId'] and value.get('collectionRequest') == request
            and observation.get('complete') is True
            and all(observation.get(key) == expected_initial.get(key)
                    for key in ('initialHp', 'initialMaxHp', 'initialBuild'))
            and type(hp) is int and type(maximum) is int and maximum > 0 and 0 <= hp <= maximum
            and type(initial) is int and type(observation.get('netHpLoss')) is int
            and observation['netHpLoss'] == initial - hp
            and observation.get('playerDied') is (hp <= 0)
            and execution.get('status') == 'teacher_battle_completed'
            and type(execution.get('finalHp')) is int and execution['finalHp'] == hp
            and execution.get('outcome') == ('loss' if hp <= 0 else 'win')
            and (hp <= 0 or execution.get('roomCompleted') is True)
            and type(value.get('finishedTurn')) is int and value['finishedTurn'] >= 1 and utc
            and value.get('provenance', {}).get('backend') == 'standalone-managed-native'
            and value.get('productionReady') is False and value.get('productionLabels') is False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--native-fixtures", type=Path, help="Additional recorded native fixtures; checked-in fixtures are always required")
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
              "productionLabels": False, "collectedBattles": 0,
              "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    source = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="sts2-simulator-probe-") as directory:
        work = Path(directory)
        for name in ("Program.cs", "HostAdapter.cs", "OfflinePlatformService.cs", "PackedLocalization.cs", "RoundProbe.cs", "OriginalEffectProbe.cs", "HostClock.cs", "NativeSetupProbe.cs", "NativeActionProbe.cs", "FullBattleReplay.cs", "RequestRestoreProbe.cs", "RequestStartupProbe.cs", "RequestBattleProbe.cs", "RequestExecution.cs", "TeacherDeploymentProbe.cs", "TeacherBattleProbe.cs", "NativeTraceReplay.cs", "TerminalCleanupObservation.cs", "OpeningChoiceSearch.cs", "NativeImplicitChoiceObserver.cs", "NativeCombatRewards.cs", "NativeDetourHost.cs", "NativePlayerTurnBarrier.cs", "SimulatorPrototype.csproj"):
            payload = (source / name).read_bytes()
            if not payload or b"\x00" in payload:
                raise ValueError("Invalid text source: " + name)
            report.setdefault("sourceSha256", {})[name] = hashlib.sha256(payload).hexdigest()
            (work / name).write_bytes(payload)
            if (work / name).read_bytes() != payload:
                raise IOError("Build source copy verification failed: " + name)
        report["build"] = run([dotnet, "build", "-c", "Release", "--nologo"], work, 60)
        if report["build"]["exitCode"] == 0:
            dll = str(work / "bin/Release/net9.0/SimulatorPrototype.dll")
            report["smoke"] = run([dotnet, dll, runtime, str(args.iterations)], work, 30)
            report["rootProbe"] = run([dotnet, dll, runtime, "--root-probe"], work, 30)
            report["roundProbe"] = run([dotnet, dll, runtime, "--round-probe"], work, 30)
            report["victoryProbe"] = run([dotnet, dll, runtime, "--victory-probe"], work, 30)
            report["oracleProbe"] = run([dotnet, dll, runtime, "--oracle-probe"], work, 30)
            report["setupProbe"] = run([dotnet, dll, runtime, "--setup-probe"], work, 30)
            report["openingProbe"] = run([dotnet, dll, runtime, "--opening-probe"], work, 30)
            report["teacherProbe"] = run([dotnet, dll, runtime, "--teacher-probe"], work, 30)
            report["teacherDeploymentProbe"] = run([dotnet, dll, runtime, "--teacher-deploy-probe"], work, 30)
            report["teacherBattleProbe"] = run([dotnet, dll, runtime, "--teacher-battle-probe"], work, 140)
            report["teacherWinProbe"] = run([dotnet, dll, runtime, "--teacher-win-probe"], work, 140)
            report["teacherContinuationProbe"] = run([dotnet, dll, runtime, "--teacher-continuation-probe"], work, 140)
            report["teacherContinuationWinProbe"] = run([dotnet, dll, runtime, "--teacher-continuation-win-probe"], work, 140)
            report["actionProbe"] = run([dotnet, dll, runtime, "--action-probe"], work, 30)
            report["encounterProbe"] = run([dotnet, dll, runtime, "--encounter-probe"], work, 30)
            report["nativeRoundProbe"] = run([dotnet, dll, runtime, "--native-round-probe"], work, 30)
            report["nativeBattleProbe"] = run([dotnet, dll, runtime, "--native-battle-probe"], work, 30)
            report["nativeWinProbe"] = run([dotnet, dll, runtime, "--native-win-probe"], work, 30)
            report["restorationProbes"] = []
            for fixture in sorted((source / "fixtures").glob("restore-*.json")):
                fixture_payload = fixture.read_bytes()
                report.setdefault("fixtureSha256", {})[fixture.name] = hashlib.sha256(fixture_payload).hexdigest()
                copied = work / fixture.name
                copied.write_bytes(fixture_payload)
                if copied.read_bytes() != fixture_payload:
                    raise IOError("Fixture copy verification failed")
                report["restorationProbes"].append(run([dotnet, dll, runtime, "--restore-request", str(copied)], work, 30))
            report["requestStartupProbes"] = [run([dotnet, dll, runtime, "--startup-request", str(work / fixture.name)], work, 40)
                for fixture in sorted((source / "fixtures").glob("restore-*.json"))]
            report["requestBattleProbes"] = [run([dotnet, dll, runtime, "--battle-request", str(work / fixture.name)], work, 140)
                for fixture in sorted((source / "fixtures").glob("restore-*.json"))]
            report["exhaustedPlanProbe"] = run([dotnet, dll, runtime, "--battle-replan-request", str(work / "restore-1.json")], work, 140)
            progress_fixture = source / "fixtures/pilot-progress-v24.json"
            report["progressSnapshotSha256"] = hashlib.sha256(progress_fixture.read_bytes()).hexdigest()
            # Fault injection requires a targeted action and a second card play.
            # A timed search on the broad historical deck can choose only one
            # non-targeted play, which never reaches those diagnostic branches.
            injection_fixture = source / "fixtures/fault-injection-multi-attack.json"
            report.setdefault("fixtureSha256", {})[injection_fixture.name] = hashlib.sha256(injection_fixture.read_bytes()).hexdigest()
            report["deploymentDriftProbe"] = run([dotnet, dll, runtime, "--battle-drift-request", str(injection_fixture), str(progress_fixture)], work, 140)
            report["missingCardProbe"] = run([dotnet, dll, runtime, "--battle-missing-card-request", str(injection_fixture), str(progress_fixture)], work, 140)
            report["unconsumedChoiceProbe"] = run([dotnet, dll, runtime, "--battle-choice-drift-request", str(work / "restore-1.json"), str(progress_fixture)], work, 140)
            replay_fixture = source / "fixtures/native-replay-2.json"
            report.setdefault("fixtureSha256", {})[replay_fixture.name] = hashlib.sha256(replay_fixture.read_bytes()).hexdigest()
            report["nativeFixedReplayProbe"] = run([dotnet, dll, runtime, "--replay-native-request", str(replay_fixture), str(progress_fixture)], work, 140)
            soul_fixture = source / "fixtures/native-replay-soul_nexus_victory.json"
            report.setdefault("fixtureSha256", {})[soul_fixture.name] = hashlib.sha256(soul_fixture.read_bytes()).hexdigest()
            report["nativeSoulNexusVictoryProbe"] = run([dotnet, dll, runtime, "--replay-native-request", str(soul_fixture), str(progress_fixture)], work, 140)
            cleanup_fixture = source / "fixtures/native-replay-devoted_sculptor_cleanup.json"
            report.setdefault("fixtureSha256", {})[cleanup_fixture.name] = hashlib.sha256(cleanup_fixture.read_bytes()).hexdigest()
            report["nativeTerminalCleanupProbe"] = run([dotnet, dll, runtime, "--replay-native-request", str(cleanup_fixture), str(progress_fixture)], work, 140)
            wrong_cleanup = json.loads(cleanup_fixture.read_text())
            last_completed = wrong_cleanup["nativeTrace"]["events"][-1]
            assert last_completed["kind"] == "action_completed" and ";block=1;" in last_completed["value"]["after"]
            last_completed["value"]["after"] = last_completed["value"]["after"].replace(";block=1;", ";block=2;", 1)
            wrong_cleanup_path = work / "native-replay-wrong-cleanup-block.json"
            wrong_cleanup_path.write_text(json.dumps(wrong_cleanup))
            report["nativeTerminalCleanupNegative"] = run([dotnet, dll, runtime, "--replay-native-request", str(wrong_cleanup_path), str(progress_fixture)], work, 140)
            negative_replay = json.loads(replay_fixture.read_text())
            first_completed = next(e for e in negative_replay["nativeTrace"]["events"] if e["kind"] == "action_completed")
            original_stamp = first_completed["value"]["after"]
            first_completed["value"]["after"] = original_stamp.replace(";hp=70;", ";hp=69;", 1)
            if first_completed["value"]["after"] == original_stamp:
                raise ValueError("Native replay negative control did not change HP")
            negative_path = work / "native-replay-negative.json"
            negative_path.write_text(json.dumps(negative_replay))
            report["nativeFixedReplayNegative"] = run([dotnet, dll, runtime, "--replay-native-request", str(negative_path), str(progress_fixture)], work, 140)
            wrong_turn = json.loads(replay_fixture.read_text())
            wrong_turn["nativeTrace"]["result"]["finishedTurn"] += 1
            wrong_turn_path = work / "native-wrong-terminal-turn.json"
            wrong_turn_path.write_text(json.dumps(wrong_turn))
            report["nativeWrongTerminalTurn"] = run([dotnet, dll, runtime, "--replay-native-request", str(wrong_turn_path), str(progress_fixture)], work, 140)
            def copy_identity():
                return [(p.name, p.stat().st_ino, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                        for p in sorted(Path(dll).parent.glob("sts2.host-experiment-*.dll"))]
            copies_before = copy_identity()
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                tasks = [pool.submit(run, [dotnet, dll, runtime, "--replay-native-request", str(replay_fixture), str(progress_fixture)], work, 140) for _ in range(3)]
                report["concurrentHostReplays"] = [task.result() for task in tasks]
            report["immutableHostCopyPreserved"] = len(copies_before) == 1 and copies_before == copy_identity()
            raw_fixture = json.loads((source / "fixtures/restore-1.json").read_text())
            raw_path = work / "raw-request.json"
            raw_path.write_text(json.dumps(raw_fixture["request"]))
            # User acceptance: equal state and labels for identical actions/choices.
            # Independently searched historical routes remain diagnostic below.
            from replay_evidence import validate_replay
            fixture_paths = sorted((source / "fixtures").glob("native-replay-*.json"))
            if args.native_fixtures:
                additional = sorted(args.native_fixtures.glob("native-replay-*.json"))
                if not additional:
                    raise ValueError("No additional native trace fixtures")
                fixture_paths += additional
            report["nativeTraceSuite"] = []
            for fixture in fixture_paths:
                fixture_source = json.loads(fixture.read_text())
                trial = run([dotnet, dll, runtime, "--replay-native-request", str(fixture.resolve()), str(progress_fixture)], work, 140)
                trial.update(fixture=str(fixture), fixtureSha256=hashlib.sha256(fixture.read_bytes()).hexdigest(), matched=False)
                terminals = [v for v in trial["records"] if v.get("status") == "request_battle_completed"]
                if trial["exitCode"] == 0 and len(terminals) == 1:
                    try:
                        trial["validation"] = validate_replay(fixture_source["nativeTrace"], terminals[0])
                        trial["matched"] = True
                    except (ValueError, KeyError, TypeError) as error:
                        trial["validationError"] = str(error)
                report["nativeTraceSuite"].append(trial)
            report["rawRequestProbe"] = run([dotnet, dll, runtime, "--execute-request", str(raw_path)], work, 140)
            report["rawRequestExpected"] = raw_fixture["expected"]
            report["rawRequestRunId"] = raw_fixture["request"]["runId"]
            report["rawRequestInput"] = raw_fixture["request"]
            invalid_policy = dict(raw_fixture["request"], shortSearchBudgetOverrideMilliseconds=9000)
            raw_path.write_text(json.dumps(invalid_policy))
            report["wrongRequestBudget"] = run([dotnet, dll, runtime, "--execute-request", str(raw_path)], work, 30)
            invalid_target = dict(raw_fixture["request"], encounterId="TEST_SUBJECT_BOSS")
            raw_path.write_text(json.dumps(invalid_target))
            report["wrongRequestAct"] = run([dotnet, dll, runtime, "--execute-request", str(raw_path)], work, 30)
            bad_fixture = json.loads((source / "fixtures/restore-2.json").read_text())
            guilty = next(c for c in bad_fixture["request"]["runCards"] if c["cardId"] == "GUILTY")
            guilty["savedIntegerMembers"]["CombatsSeen"] += 1
            bad_path = work / "wrong-persistent-state.json"
            bad_path.write_text(json.dumps(bad_fixture))
            report["wrongPersistentState"] = run([dotnet, dll, runtime, "--restore-request", str(bad_path)], work, 30)
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
    def passed(name, status):
        result = report.get(name, {})
        return result.get("exitCode") == 0 and any(x.get("status") == status for x in result.get("records", []))
    startups = report.get("requestStartupProbes", [])
    report["requestStartupPassed"] = len(startups) == 6 and all(x["exitCode"] == 0
        and all(any(v.get("status") == status for v in x["records"])
            for status in ("request_startup_prepared", "request_restoration_matched")) for x in startups)
    battles = report.get("requestBattleProbes", [])
    report["historicalRequestBattlesMatched"] = len(battles) == 6 and all(x["exitCode"] == 0
        and any(v.get("status") == "request_battle_completed" and v.get("historicalTerminalMatched")
            for v in x["records"]) for x in battles)
    report["requestBattlesCompleted"] = len(battles) == 6 and all(x["exitCode"] == 0
        and any(v.get("status") == "request_battle_completed" for v in x["records"]) for x in battles)
    traces = report.get("nativeTraceSuite", [])
    report["nativeTraceSuiteMatched"] = len(traces) >= 16 and all(x.get("matched") is True for x in traces)
    report["acceptanceCriterion"] = "Identical initial state, actions and choices must yield identical full states and terminal labels; independently searched historical routes are diagnostic."
    exhausted = report.get("exhaustedPlanProbe", {})
    report["exhaustedPlanReplanned"] = exhausted.get("exitCode") == 0 and any(
        v.get("status") == "request_battle_completed"
        and v.get("battle", {}).get("exhaustedPlanReplans") == 1
        and v.get("battle", {}).get("injectedExhaustedPlan") is True
        and v.get("battle", {}).get("searches", 0) >= 2 for v in exhausted.get("records", []))
    drift = report.get("deploymentDriftProbe", {})
    report["deploymentDriftReplanned"] = drift.get("exitCode") == 0 and any(
        v.get("status") == "request_battle_completed"
        and v.get("battle", {}).get("deploymentDriftReplans") == 1
        and v.get("battle", {}).get("injectedDeploymentDrift") is True
        and v.get("battle", {}).get("searches", 0) >= 2 for v in drift.get("records", []))
    missing = report.get("missingCardProbe", {})
    report["missingCardReplanned"] = missing.get("exitCode") == 0 and any(
        v.get("status") == "request_battle_completed"
        and v.get("battle", {}).get("injectedMissingCard") is True
        and v.get("battle", {}).get("deploymentDriftReplans") == 1
        for v in missing.get("records", [])) and any(
        v.get("status") == "teacher_deployment_drift_replan" and v.get("reason") == "card_missing"
        and v.get("executedActions") == 1 for v in missing.get("records", []))
    unused = report.get("unconsumedChoiceProbe", {})
    report["unconsumedChoiceReplanned"] = unused.get("exitCode") == 0 and any(
        v.get("status") == "request_battle_completed"
        and v.get("battle", {}).get("injectedUnconsumedChoice") is True
        for v in unused.get("records", [])) and any(
        v.get("status") == "teacher_deployment_drift_replan" and v.get("reason") == "choice_plan_unconsumed"
        and v.get("executedActions") == 1 for v in unused.get("records", []))
    replay = report.get("nativeFixedReplayProbe", {})
    report["nativeFixedReplayMatched"] = replay.get("exitCode") == 0 and any(
        v.get("status") == "request_battle_completed"
        and v.get("battle", {}).get("status") == "native_fixed_action_replay_matched"
        and v["battle"].get("plays") == 40 and v["battle"].get("boundaries") == 9
        and len(v["battle"].get("compared", [])) == 88
        and all(c.get("matches") is True for c in v["battle"]["compared"])
        for v in replay.get("records", []))
    soul = report.get("nativeSoulNexusVictoryProbe", {})
    report["nativeSoulNexusVictoryMatched"] = soul.get("exitCode") == 0 and any(
        v.get("battle", {}).get("status") == "native_fixed_action_replay_matched"
        and v.get("finalHp") == 20 and v.get("finishedTurn") == 5
        and v["battle"].get("plays") == 24 and len(v["battle"].get("compared", [])) == 51
        and all(c.get("matches") is True for c in v["battle"]["compared"])
        for v in soul.get("records", []))
    cleanup = report.get("nativeTerminalCleanupProbe", {})
    report["nativeTerminalCleanupMatched"] = cleanup.get("exitCode") == 0 and any(
        v.get("battle", {}).get("status") == "native_fixed_action_replay_matched"
        and v.get("finalHp") == 3 and v.get("finishedTurn") == 6
        and v["battle"].get("terminalCleanupBoundaryComparisons") == 1
        and all(c.get("matches") is True for c in v["battle"].get("compared", []))
        for v in cleanup.get("records", []))
    cleanup_negative = report.get("nativeTerminalCleanupNegative", {})
    report["nativeTerminalCleanupNegativeRejected"] = cleanup_negative.get("exitCode") not in (None, 0) and any(
        v.get("status") == "native_replay_mismatch" and v.get("point") == "after_play_17"
        for v in cleanup_negative.get("records", []))
    negative_replay = report.get("nativeFixedReplayNegative", {})
    report["nativeFixedReplayNegativeRejected"] = negative_replay.get("exitCode") not in (None, 0) and any(
        v.get("status") == "native_replay_mismatch" and v.get("point") == "after_play_0"
        for v in negative_replay.get("records", []))
    wrong_turn = report.get("nativeWrongTerminalTurn", {})
    report["nativeWrongTerminalTurnRejected"] = wrong_turn.get("exitCode") not in (None, 0) and any(
        "Native fixed-action terminal turn differs." in v.get("error", "") for v in wrong_turn.get("records", []))
    concurrent_replays = report.get("concurrentHostReplays", [])
    report["concurrentHostReplaysMatched"] = report.get("immutableHostCopyPreserved") is True and len(concurrent_replays) == 3 and all(
        replay.get("exitCode") == 0 and any(v.get("battle", {}).get("status") == "native_fixed_action_replay_matched"
            for v in replay.get("records", [])) for replay in concurrent_replays)
    raw = report.get("rawRequestProbe", {})
    report["historicalRawRequestMatched"] = any(
        x.get("trainingObservation") == report.get("rawRequestExpected")
        for x in raw.get("records", []) if x.get("status") == "StandaloneCompleted")
    report["rawRequestPassed"] = raw.get("exitCode") == 0 and any(
        raw_completion_matches_execution(x, report["rawRequestExpected"], report["rawRequestInput"])
        for x in raw.get("records", []))
    report["wrongRequestBudgetRejected"] = report.get("wrongRequestBudget", {}).get("exitCode") not in (None, 0) and any(
        "Unsupported request policy: shortSearchBudgetOverrideMilliseconds" in x.get("error", "")
        for x in report.get("wrongRequestBudget", {}).get("records", []))
    report["wrongRequestActRejected"] = report.get("wrongRequestAct", {}).get("exitCode") not in (None, 0) and any(
        "Encounter does not belong to requested act/index" in x.get("error", "")
        for x in report.get("wrongRequestAct", {}).get("records", []))
    report["nativeSetupPassed"] = passed("setupProbe", "native_setup_passed")
    report["nativeOpeningPassed"] = passed("openingProbe", "native_opening_passed")
    report["teacherSearchPassed"] = passed("teacherProbe", "teacher_search_passed")
    report["teacherDeploymentPassed"] = passed("teacherDeploymentProbe", "teacher_opening_deployed")
    report["teacherBattlesCompleted"] = all(
        passed(name, "teacher_battle_completed") and any(x.get("outcome") == outcome
            and (outcome != "win" or x.get("roomCompleted"))
            for x in report.get(name, {}).get("records", []))
        for name, outcome in (("teacherBattleProbe", "loss"), ("teacherWinProbe", "win")))
    report["teacherChoicesConsumed"] = any(x.get("choicesConsumed", 0) >= 2
        for x in report.get("teacherBattleProbe", {}).get("records", []))
    report["teacherContinuationsPassed"] = all(
        passed(name, "teacher_battle_completed") and any(x.get("outcome") == outcome
            and x.get("reusedTurns", 0) > 0 and x.get("negativeChecks") == x.get("reusedTurns")
            and (outcome != "win" or x.get("roomCompleted"))
            for x in report.get(name, {}).get("records", []))
        for name, outcome in (("teacherContinuationProbe", "loss"), ("teacherContinuationWinProbe", "win")))
    report["nativeActionsMatched"] = passed("actionProbe", "native_actions_matched")
    report["encounterActionsMatched"] = passed("encounterProbe", "native_actions_matched")
    report["nativeRoundMatched"] = passed("nativeRoundProbe", "native_round_matched")
    report["nativeBattleMatched"] = passed("nativeBattleProbe", "native_battle_matched")
    report["nativeWinMatched"] = passed("nativeWinProbe", "native_battle_matched")
    report["nativeOpeningPassed"] &= passed("openingProbe", "native_opening_root_captured")
    report["nativeWinMatched"] &= any(
        x.get("outcome") == "win" and x.get("roomCompleted") and x.get("progressWritten")
        for x in report.get("nativeWinProbe", {}).get("records", []))
    report["nativeBattleMatched"] &= any(
        x.get("outcome") == "loss" for x in report.get("nativeBattleProbe", {}).get("records", []))
    restorations = report.get("restorationProbes", [])
    report["requestRestorationMatched"] = len(restorations) == 6 and all(
        x["exitCode"] == 0 and any(v.get("status") == "request_restoration_matched" for v in x["records"])
        for x in restorations)
    wrong = report.get("wrongPersistentState", {})
    report["wrongPersistentStateRejected"] = wrong.get("exitCode") not in (None, 0) and any(
        x.get("status") == "restoration_mismatch" for x in wrong.get("records", []))
    report["rootForkPassed"] = passed("rootProbe", "root_smoke_passed")
    report["fullRootCaptured"] = passed("roundProbe", "search_root_captured") and passed("victoryProbe", "search_root_captured")
    report["originalEffectsMatched"] = passed("oracleProbe", "original_effects_matched")
    report["battleFixturesPassed"] = all(
        passed(name, "battle_pair_passed") and any(
            x.get("battle", {}).get("outcome") == expected
            for x in report.get(name, {}).get("records", []))
        for name, expected in (("roundProbe", "loss"), ("victoryProbe", "win")))
    report["syntheticBattles"] = sum(
        x.get("syntheticBattles", 0) for name in ("roundProbe", "victoryProbe")
        for x in report.get(name, {}).get("records", []))
    report["experimentPassed"] = all(report[k] for k in (
        "smokePassed", "versionGuardPassed", "rootForkPassed", "fullRootCaptured",
        "originalEffectsMatched", "battleFixturesPassed",
        "nativeSetupPassed", "nativeOpeningPassed", "teacherSearchPassed", "teacherDeploymentPassed", "teacherBattlesCompleted", "teacherChoicesConsumed", "teacherContinuationsPassed", "nativeActionsMatched", "encounterActionsMatched", "nativeRoundMatched", "nativeBattleMatched", "nativeWinMatched", "requestRestorationMatched", "wrongPersistentStateRejected", "requestStartupPassed", "requestBattlesCompleted", "nativeTraceSuiteMatched", "exhaustedPlanReplanned", "deploymentDriftReplanned", "missingCardReplanned", "unconsumedChoiceReplanned", "nativeFixedReplayMatched", "nativeSoulNexusVictoryMatched", "nativeTerminalCleanupMatched", "nativeTerminalCleanupNegativeRejected", "nativeFixedReplayNegativeRejected", "nativeWrongTerminalTurnRejected", "concurrentHostReplaysMatched", "rawRequestPassed", "wrongRequestBudgetRejected", "wrongRequestActRejected"))
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
    return 0 if report["experimentPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
