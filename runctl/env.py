from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid

from damage_model.worker import GameProcess


class RunControlError(RuntimeError):
    """The episode failed; it must not be counted as a game loss or training label."""


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class RealRunEnv:
    """One exclusive native process, with reset/step at real map decisions.

    v1 returns an observation or terminal result dictionary. Other room and
    selection choices use the recorded native baseline. This is not yet a Gym
    environment or a standardized F-label producer.
    """

    def __init__(self, runtime: dict):
        if runtime.get("kind") != "run_control" or runtime.get("env", {}).get("COMBATSOLVER_RUN_CONTROL") != "1":
            raise ValueError("Use an explicitly isolated run_control runtime configuration")
        self.data_dir = Path(runtime["data_dir"]).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = (self.data_dir / "runctl.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lock.write(b"\0")
                self._lock.flush()
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise RunControlError("This run-control directory is already owned") from None
        try:
            self.game = GameProcess(**{k: v for k, v in runtime.items() if k in {"game_dir", "data_dir", "command", "env", "log_path"}})
        except Exception:
            self._lock.close()
            raise
        self.run_id: str | None = None
        self.run_dir: Path | None = None
        self.observation: dict | None = None
        self._seq = 0
        self._deadline = 0.0
        self._closed = False
        self._failed = False

    def reset(self, seed: str, *, policy_seed: int = 0, timeout_seconds: int = 3600,
              action_timeout_seconds: int = 60, combat_timeout_seconds: int = 120) -> dict:
        if self._closed or self._failed:
            raise RunControlError("A failed/closed environment cannot be reused")
        if self.observation is not None and self.observation.get("status") != "complete":
            raise RunControlError("The previous episode has not completed")
        if not isinstance(seed, str) or not seed.strip() or len(seed) > 100:
            raise ValueError("Invalid game seed")
        for value, maximum in [(timeout_seconds, 14400), (action_timeout_seconds, 300), (combat_timeout_seconds, 120)]:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid deadline")
        if type(policy_seed) is not int or not -(2**31) <= policy_seed < 2**31:
            raise ValueError("policy_seed must be an int32")
        self.run_id = uuid.uuid4().hex
        self.run_dir = self.data_dir / "combat_solver_runs" / self.run_id
        self._seq = 0
        self.observation = None
        request_path = self.data_dir / "combat_solver_test_request.json"
        if request_path.exists():
            raise RunControlError("An unaccepted native request already exists; inspect its owning run")
        request = dict(schemaVersion=1, kind="run", runId=self.run_id, seed=seed,
                       characterId="SILENT", ascension=10, combatMode="solver", policySeed=policy_seed,
                       timeoutSeconds=timeout_seconds, actionTimeoutSeconds=action_timeout_seconds,
                       combatTimeoutSeconds=combat_timeout_seconds)
        self._deadline = time.monotonic() + timeout_seconds + 120
        try:
            atomic_json(request_path, request)
            if self.game.process is None:
                self.game.start()
        except Exception:
            self._failed = True
            raise
        return self._wait()

    def step(self, choice: int) -> dict:
        if self._closed or self._failed or self.observation is None or self.observation.get("status") == "complete":
            raise RunControlError("step requires an active decision")
        options = self.observation["options"]
        if type(choice) is not int or not 0 <= choice < len(options):
            raise ValueError("Choice must be a legal option index")
        assert self.run_dir is not None
        action = self.run_dir / "action.json"
        if action.exists():
            raise RunControlError("Previous action has not been consumed")
        atomic_json(action, dict(schemaVersion=1, runId=self.run_id, decisionSeq=self._seq, choice=choice))
        return self._wait()

    def _wait(self) -> dict:
        try:
            return self._wait_native()
        except (RunControlError, OSError, ValueError):
            self._failed = True
            raise

    def _wait_native(self) -> dict:
        assert self.run_dir is not None
        while time.monotonic() < self._deadline:
            result_path = self.run_dir / "result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self._identity(result)
                if result.get("status") != "complete":
                    raise RunControlError(f"{result.get('stage')}: {result.get('error', result)}")
                if result.get("outcome") not in {"victory", "death"}:
                    raise RunControlError("Native result has no valid terminal outcome")
                self.observation = result
                return result
            decision_path = self.run_dir / "decision.json"
            if decision_path.exists():
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
                self._identity(decision)
                seq = decision.get("decisionSeq")
                if type(seq) is not int:
                    raise RunControlError("Missing decision sequence")
                if seq == self._seq:
                    pass  # The last atomic snapshot remains until the next decision.
                elif seq != self._seq + 1:
                    raise RunControlError("Out-of-order decision")
                else:
                    options = decision.get("options")
                    if decision.get("screen") != "MAP" or not isinstance(options, list) or not options:
                        raise RunControlError("Invalid v1 decision")
                    if [o.get("index") for o in options] != list(range(len(options))):
                        raise RunControlError("Invalid option indices")
                    self._seq = seq
                    self.observation = decision
                    return decision
            if self.game.process is None or self.game.process.poll() is not None:
                raise RunControlError(f"Native process exited before completion; inspect {self.game.log_path}")
            time.sleep(0.05)
        raise RunControlError("Native run deadline exceeded; partial artifacts were retained")

    def _identity(self, value: dict) -> None:
        if value.get("schemaVersion") != 1 or value.get("runId") != self.run_id:
            raise RunControlError("Foreign run ID or unsupported schema")

    def close(self) -> None:
        if not self._closed:
            # If termination fails, retain ownership and allow close() to be
            # retried. Another client must not acquire a still-live game.
            self.game.stop()
            self._lock.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
