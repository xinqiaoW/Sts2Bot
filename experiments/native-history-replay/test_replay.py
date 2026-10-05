"""Checks for historical route reconstruction and crash-safe source cursors."""
import json
from pathlib import Path
import tempfile
import unittest
import replay as r


def case(trace):
    return {"runId": "source", "combatEnded": True, "finishedTurn": 2,
            "provenance": {"solverSha256": r.SOLVER_SHA, "gameSha256": r.GAME_SHA, "progressSnapshotSha256": r.PROGRESS_SHA},
            "trainingObservation": {"complete": True, "finalCombatState": "terminal"}, "execution": {"trace": trace}}


def segment(turn, state, reason=None):
    deploy = {"actionCount": 1, "trace": [{"action": {"Kind": 0, "Turn": turn}, "live": state}]}
    if reason:
        deploy["reason"] = reason
    return {"turn": turn, "deployment": deploy}


class ReplayTests(unittest.TestCase):
    def test_replans_do_not_insert_extra_end_turns(self):
        row = case([segment(1, "first", "choice_plan_unconsumed"), segment(1, "second"), segment(2, "third")])
        plan = r.make_plan(row, "opening", [], {1: {"choices": [], "cancelledAfterTerminal": 0}}, "job", "new", Path("checks"))
        self.assertEqual([s["kind"] for s in plan["steps"]], ["play", "play", "end_turn", "play"])
        self.assertEqual([s["allowUnconsumedPlan"] for s in plan["steps"] if s["kind"] == "play"], [True, False, False])

    def test_incomplete_historical_routes_fail_closed(self):
        row = case([segment(1, "first")])
        row["execution"]["trace"][0]["deployment"]["actionCount"] = 2
        with self.assertRaisesRegex(ValueError, "incomplete"):
            r.make_plan(row, "opening", [], {}, "job", "new", Path("checks"))
        with self.assertRaisesRegex(ValueError, "not represented"):
            r.make_plan(case([]), "opening", [], {1: {}}, "job", "new", Path("checks"))

    def test_opening_terminal_only_accepts_explicit_native_terminal_record(self):
        row = case([])
        row["execution"] = {"status": "native_opening_terminal", "openingTerminal": True}
        row["trainingObservation"]["openingTerminal"] = True
        plan = r.make_plan(row, "opening", [], {}, "job", "new", Path("checks"))
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["plays"], 0)
        row["trainingObservation"]["openingTerminal"] = False
        with self.assertRaisesRegex(ValueError, "missing"):
            r.make_plan(row, "opening", [], {}, "job", "new", Path("checks"))

    def test_recorded_terminal_cancellation_retains_source_ledger(self):
        step = {"kind": "end_turn", "turn": 4, "choices": [{}, {}], "cancelledAfterTerminal": 1}
        r.annotate_terminal_cancellation([step], 5)
        self.assertEqual(step["terminalChoiceCancellation"], {"mode": "recorded", "count": 1})
        self.assertEqual(step["cancelledAfterTerminal"], 1)
        with self.assertRaisesRegex(ValueError, "count"):
            r.annotate_terminal_cancellation([{**step, "cancelledAfterTerminal": 3}], 5)

    def test_legacy_entropy_repair_is_restricted_to_final_terminal_boundary(self):
        choice = {"SourceId": "ENTROPY_POWER", "Effect": 5, "Cards": [{"CardId": "SNAKEBITE"}]}
        step = {"kind": "end_turn", "turn": 6, "choices": [choice], "cancelledAfterTerminal": 0}
        r.annotate_terminal_cancellation([step], 6)
        self.assertEqual(step["terminalChoiceCancellation"], {"mode": "legacy_entropy_cleanup", "count": 1})
        self.assertEqual(step["cancelledAfterTerminal"], 0)
        for steps, finished in (([{**step}, {"kind": "play"}], 7), ([{**step}], 7),
                                ([{**step, "choices": [{**choice, "SourceId": "OTHER"}]}], 6),
                                ([{**step, "choices": [{**choice, "Effect": 2}]}], 6)):
            for item in steps:
                item.pop("terminalChoiceCancellation", None)
            r.annotate_terminal_cancellation(steps, finished)
            self.assertNotIn("terminalChoiceCancellation", steps[0])

    def test_interrupted_attempt_never_advances_committed_cursor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = r.Store(root)
            first = root / "first"
            first.mkdir()
            store.begin("first", "job1", first)
            result = {"sourceJobId": "job1", "sourceRunId": "run1", "status": "matched", "attempt": "first", "attemptPath": str(first)}
            store.finish(result, {"worker": 0, "offset": 512})
            second = root / "second"
            second.mkdir()
            store.begin("second", "job2", second)
            r.event(second / "checkpoints.jsonl", {"kind": "checkpoint", "value": {"matches": True}})
            store.db.close()
            recovered = r.Store(root)
            self.assertEqual(recovered.cursor(), {"worker": 0, "offset": 512})
            self.assertEqual(recovered.db.execute("SELECT status FROM attempts WHERE id='second'").fetchone()[0], "interrupted")
            self.assertEqual(dict(recovered.counts), {"matched": 1})
            self.assertTrue((first / "result.json").exists())
            self.assertEqual(len(r.checkpoints(second / "checkpoints.jsonl")), 1)
            recovered.db.close()

    def test_truncated_tail_does_not_destroy_completed_results(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.jsonl"
            path.write_bytes(b'{"complete":true}\n{"partial"')
            r.repair_jsonl(path)
            self.assertEqual(path.read_bytes(), b'{"complete":true}\n')


if __name__ == "__main__":
    unittest.main()
