import json
import threading
import time
from pathlib import Path

import pytest

import runctl.env as module
from runctl.env import RealRunEnv, RunControlError, atomic_json


@pytest.fixture
def native(tmp_path, monkeypatch):
    class FakeGame:
        behavior = "complete"
        starts = 0
        requests = []
        actions = []
        screen = 'MAP'

        def __init__(self, **kwargs):
            self.process = None
            self.log_path = tmp_path / "native.log"
            self.stopped = threading.Event()
            self.thread = None
            self.errors = []

        def start(self):
            FakeGame.starts += 1
            self.process = self
            self.thread = threading.Thread(target=self.serve, daemon=True)
            self.thread.start()

        def poll(self):
            return 1 if self.stopped.is_set() else None

        def stop(self):
            self.stopped.set()
            if self.thread:
                self.thread.join(timeout=2)
            assert not self.errors

        def serve(self):
            try:
                while not self.stopped.wait(.005):
                    request_file = tmp_path / "combat_solver_test_request.json"
                    if not request_file.exists():
                        continue
                    request = json.loads(request_file.read_text())
                    request_file.unlink()
                    FakeGame.requests.append(request)
                    folder = tmp_path / "combat_solver_runs" / request["runId"]
                    folder.mkdir(parents=True)
                    identity = dict(schemaVersion=1, runId=request["runId"])
                    if self.behavior == "exit":
                        self.stopped.set()
                        return
                    if self.behavior == "failed":
                        atomic_json(folder / "result.json", dict(**identity, status="failed", stage="combat", error="native crash"))
                        continue
                    decision = dict(**identity, decisionSeq=1, screen=self.screen, state={}, options=[{"index": 0}, {"index": 1}])
                    if self.behavior == "foreign":
                        decision["runId"] = "old-run"
                    if self.behavior == "sequence":
                        decision["decisionSeq"] = 3
                    atomic_json(folder / "decision.json", decision)
                    action_file = folder / "action.json"
                    while not action_file.exists():
                        if self.stopped.wait(.005):
                            return
                    action = json.loads(action_file.read_text())
                    action_file.unlink()
                    FakeGame.actions.append(action)
                    assert action["runId"] == request["runId"] and action["decisionSeq"] == 1
                    atomic_json(folder / "result.json", dict(**identity, status="complete", outcome="death", state={"hp": 0}))
            except BaseException as exc:
                self.errors.append(exc)
                self.stopped.set()

    monkeypatch.setattr(module, "GameProcess", FakeGame)
    runtime = dict(kind="run_control", data_dir=str(tmp_path), game_dir=str(tmp_path), command=["fake"],
                   env={"COMBATSOLVER_RUN_CONTROL": "1"})
    return runtime, FakeGame


def test_reuse_isolates_results_and_restarts_decision_sequence(native):
    runtime, game = native
    with RealRunEnv(runtime) as env:
        ids = []
        for seed in ["FIRST", "SECOND"]:
            decision = env.reset(seed)
            ids.append(decision["runId"])
            assert decision["decisionSeq"] == 1
            with pytest.raises(RunControlError):
                env.reset("OVERLAP")
            assert env.step(1)["outcome"] == "death"
        assert len(set(ids)) == 2
        assert game.starts == 1
        assert [a["runId"] for a in game.actions] == ids


@pytest.mark.parametrize('screen', ['EVENT', 'SHOP', 'REST', 'TREASURE', 'REWARDS', 'CARD_REWARD',
                                    'CHOOSE_CARD', 'RELIC', 'BUNDLE', 'CARD_GRID', 'CRYSTAL'])
def test_all_mode_accepts_explicit_noncombat_screens(native, screen):
    runtime, game = native
    game.screen = screen
    with RealRunEnv(runtime) as env:
        assert env.reset('ALL', decision_mode='all')['screen'] == screen
        assert game.requests[-1]['decisionMode'] == 'all'
        assert env.step(0)['status'] == 'complete'


def test_map_mode_rejects_nonmap_screen(native):
    runtime, game = native
    game.screen = 'EVENT'
    with RealRunEnv(runtime) as env, pytest.raises(RunControlError, match='Invalid v1 decision'):
        env.reset('MAP-ONLY')


@pytest.mark.parametrize("behavior", ["foreign", "sequence", "failed", "exit"])
def test_rejects_invalid_native_lifecycle(native, behavior):
    runtime, game = native
    game.behavior = behavior
    with RealRunEnv(runtime) as env:
        with pytest.raises(RunControlError):
            env.reset("BAD")
        with pytest.raises(RunControlError, match="failed/closed"):
            env.reset("REUSE-FAILED")


def test_bad_actions_do_not_reach_game(native):
    runtime, game = native
    with RealRunEnv(runtime) as env:
        env.reset("ACTIONS")
        for choice in [-1, 2, True, 0.0, "0"]:
            with pytest.raises(ValueError):
                env.step(choice)
            assert not (env.run_dir / "action.json").exists()
        assert env.step(0)["status"] == "complete"
        with pytest.raises(RunControlError):
            env.step(0)
        assert len(game.actions) == 1


def test_exclusive_directory_and_explicit_runtime(native):
    runtime, _ = native
    with pytest.raises(ValueError):
        RealRunEnv({**runtime, "kind": "collection"})
    with RealRunEnv(runtime):
        with pytest.raises(RunControlError, match="already owned"):
            RealRunEnv(runtime)
    with RealRunEnv(runtime):
        pass


def test_existing_request_is_not_overwritten(native):
    runtime, _ = native
    path = Path(runtime["data_dir"]) / "combat_solver_test_request.json"
    original = {"runId": "another-owner"}
    atomic_json(path, original)
    with RealRunEnv(runtime) as env:
        with pytest.raises(RunControlError, match="unaccepted"):
            env.reset("COLLISION")
    assert json.loads(path.read_text()) == original


def test_deadline_retains_partial_artifacts(native):
    runtime, _ = native
    with RealRunEnv(runtime) as env:
        env.reset("DEADLINE")
        decision = env.run_dir / "decision.json"
        env._deadline = time.monotonic() - 1
        with pytest.raises(RunControlError, match="deadline"):
            env._wait()
        assert decision.exists()


@pytest.mark.parametrize("parameter,value", [("timeout_seconds", 0), ("combat_timeout_seconds", 121),
                                               ("action_timeout_seconds", True), ("policy_seed", 2**32)])
def test_invalid_request_rejected_before_launch(native, parameter, value):
    runtime, game = native
    with RealRunEnv(runtime) as env:
        with pytest.raises(ValueError):
            env.reset("INVALID", **{parameter: value})
        assert game.starts == 0


def test_constructor_failure_releases_directory(native, monkeypatch):
    runtime, game = native
    def fail_constructor(**kwargs):
        raise OSError("Cannot create game")
    monkeypatch.setattr(module, "GameProcess", fail_constructor)
    with pytest.raises(OSError, match="Cannot create game"):
        RealRunEnv(runtime)
    monkeypatch.setattr(module, "GameProcess", game)
    with RealRunEnv(runtime):
        pass


def test_start_failure_retains_request_and_blocks_reuse(native, monkeypatch):
    runtime, game = native
    def fail_start(self):
        raise OSError("Cannot launch executable")
    monkeypatch.setattr(game, "start", fail_start)
    with RealRunEnv(runtime) as env:
        with pytest.raises(OSError, match="Cannot launch"):
            env.reset("START-FAILURE")
        with pytest.raises(RunControlError, match="failed/closed"):
            env.reset("AGAIN")
        request = Path(runtime["data_dir"]) / "combat_solver_test_request.json"
        assert json.loads(request.read_text())["runId"] == env.run_id


def test_stop_failure_retains_ownership_until_cleanup_succeeds(native, monkeypatch):
    runtime, game = native
    original_stop = game.stop
    def fail_stop(self):
        raise OSError("Termination failed")
    env = RealRunEnv(runtime)
    try:
        env.reset("STOP-FAILURE")
        monkeypatch.setattr(game, "stop", fail_stop)
        with pytest.raises(OSError, match="Termination failed"):
            env.close()
        with pytest.raises(RunControlError, match="already owned"):
            RealRunEnv(runtime)
    finally:
        monkeypatch.setattr(game, "stop", original_stop)
        env.close()
    with RealRunEnv(runtime):
        pass


def test_windows_snapshot_locks_do_not_duplicate_actions(native, monkeypatch):
    runtime, game = native
    original = module._read_shared_text
    denied = {"decision.json": 3, "result.json": 2}

    def transient_lock(path):
        if denied.get(path.name, 0):
            denied[path.name] -= 1
            error = PermissionError(13, "Snapshot is being replaced", str(path))
            error.winerror = 5
            raise error
        return original(path)

    monkeypatch.setattr(module, "_read_shared_text", transient_lock)
    with RealRunEnv(runtime) as env:
        assert env.reset("WINDOWS-LOCK")["decisionSeq"] == 1
        assert env.step(1)["outcome"] == "death"
        assert len(game.actions) == 1
        assert game.actions[0]["choice"] == 1
        assert denied == {"decision.json": 0, "result.json": 0}


def test_permanent_windows_access_denial_is_bounded(tmp_path, monkeypatch):
    calls = []
    error = PermissionError(13, "Access denied", str(tmp_path / "decision.json"))
    error.winerror = 5

    def denied(path):
        calls.append(path)
        raise error

    monkeypatch.setattr(module, "_read_shared_text", denied)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError) as caught:
        module.read_protocol_json(tmp_path / "decision.json")
    assert caught.value is error
    assert len(calls) == 21


def test_corrupt_snapshot_is_not_treated_as_file_contention(tmp_path, monkeypatch):
    path = tmp_path / "decision.json"
    path.write_text('{"partial":', encoding="utf-8")

    def unexpected_retry(_):
        pytest.fail("Malformed JSON must fail immediately")

    monkeypatch.setattr(module.time, "sleep", unexpected_retry)
    with pytest.raises(json.JSONDecodeError):
        module.read_protocol_json(path)


def test_player_search_settings_are_explicit_and_keep_long_search_deadline(native):
    runtime, game = native
    with RealRunEnv({**runtime, 'combat_search_mode': 'settings'}) as env:
        env.reset('PLAYER-SETTINGS')
        assert game.requests[-1]['combatSearchMode'] == 'settings'
        assert game.requests[-1]['combatTimeoutSeconds'] == 1800
        assert env.step(0)['status'] == 'complete'
    with RealRunEnv(runtime) as env:
        env.reset('LEGACY-EVALUATION')
        assert 'combatSearchMode' not in game.requests[-1]
        assert game.requests[-1]['combatTimeoutSeconds'] == 120
        assert env.step(0)['status'] == 'complete'


def test_search_configuration_rejects_unknown_mode_and_unbounded_deadline(native):
    runtime, game = native
    with pytest.raises(ValueError, match='combat_search_mode'):
        RealRunEnv({**runtime, 'combat_search_mode': 'typo'})
    with RealRunEnv({**runtime, 'combat_search_mode': 'settings'}) as env:
        with pytest.raises(ValueError, match='deadline'):
            env.reset('BAD-DEADLINE', combat_timeout_seconds=3601)
    assert game.starts == 0
