# Retained 24-hour routes → original native game

This diagnostic mod drives the **original recorded actions**, without another
teacher search. It uses the frozen native game's scenario builder, effects, RNG,
action executor and visible choice surfaces. The teacher search entry is replaced
with a throwing body, and automatic search/setup interception is disabled.
An incomplete mod initialization rejects every request.

The source is `standalone-rollout-readiness-20260929/rollout-v5b/soak`. The frozen
report has 202,527 successful cases and 11 quarantined execution failures. Those
11 failures are not evidence that they were the only rules differences.

All 202,527 successes retain enough inputs for this comparison:

* Original collection request, exact progress snapshot and pinned game/collector.
* Opening choice plan and complete opening state.
* All 5,104,714 played actions, including their nested choices and post-play states.
* Recorded end-turn choice plans, full stable terminal state and finished turn.

There were no complete intermediate end-turn states recorded. This job executes
those boundaries natively and compares the next recorded action state or terminal;
it cannot retrospectively compare unrecorded checkpoints. State equality means
exact equality of the retained continuation stamp, including RNG and private
fields represented by that format; it is not an assertion about unrecorded data.
One explicitly marked opening-terminal success has no action trace.

## Build and prepare

Use the .NET 9 tool and `GameDataDir` from the frozen native template. Put both
`BaseIntermediateOutputPath` and `OutputPath` in the external experiment directory.
The build output must include `NativeHistoryReplay.dll`. Then:

```bash
PYTHONDONTWRITEBYTECODE=1 python experiments/native-history-replay/replay.py \
  --prepare --root /absolute/unique/experiment/full --binary-dir /absolute/build/bin
```

Preparation hardlinks immutable game assets, copies the Wine prefix (never
hardlinking saves), installs the diagnostic mod in the clone and binds all inputs
in `manifest.json`. It refuses to overwrite an existing runtime. Original native
and standalone assets are never modified. Run pilots in separate output directories;
`--only-run`, `--pilot-runs` and `--corrupt-opening` bind a distinct persisted scope
that cannot be combined with the full campaign.

Before launching, freeze this directory and the original collector's `worker.py`,
`schema.py`, and `__init__.py` under `code/collector/damage_model/`. The controller
uses that local copy when available. Preserve the source hashes and git branch/HEAD
in the experiment manifest. Terminate any previous Wine server for this **cloned
prefix only**, so the system service owns all Wine processes.

## Durable results and resume

The controller holds an exclusive lease. Each attempt has its own request, plan,
native result, checkpoint JSONL and final summary under `attempts/`. Every native
checkpoint uses `Flush(true)`. Every per-case JSON, event and SQLite commit is
flushed to disk; SQLite uses WAL and `synchronous=FULL`.

`results.sqlite` is the authoritative per-case outcome index. `results.jsonl`
provides a convenient live stream and `state.json` is atomically updated progress.
A crash between the SQLite commit and JSONL append may omit that JSONL line; the
committed database row and individual attempt result remain intact. An incomplete
JSONL tail is trimmed on restart. The committed source cursor advances only with a
durable outcome. An interrupted attempt is preserved and marked `interrupted` on
restart; that case is retried with a new attempt ID. Already committed cases are
skipped. Failures and mismatches are recorded separately and the native process is
restarted after either. Five consecutive cases without any native comparison stop
the controller for diagnosis.

Run as a user systemd service with `Linger=yes`, `KillMode=mixed`,
`TimeoutStopSec=180`, `Restart=on-abnormal`, and `WorkingDirectory` in the experiment.
The controller MainPID is stable during the run; the native PID may change after
failures. The service survives the launching conversation and SSH session closing.
SIGTERM requests a stop after the active case; a `STOP` file also stops between
cases. Remove `STOP` before restarting the service to resume.

```bash
cat /absolute/experiment/full/state.json
tail -f /absolute/experiment/full/results.jsonl
sqlite3 /absolute/experiment/full/results.sqlite \
  'SELECT status,count(*) FROM outcomes GROUP BY status;'
systemctl --user status sts2-native-history-replay-20261004.service
systemctl --user stop sts2-native-history-replay-20261004.service
systemctl --user start sts2-native-history-replay-20261004.service
```

The statuses are `matched`, `mismatch`, `execution_failure`, and `unreplayable`.
`comparisonCompleted` retains the distinction between a successful state comparison
and a later native request/menu cleanup failure. A recorded failure is never
reported as a passing comparison just because no difference was captured.

Validation includes native pilots for long routes, death, opening choices,
terminal choice cancellation, historical choice drift, terminal rewards and the
opening-terminal case, plus a deliberately corrupted checkpoint. Controller tests
exercise turn reconstruction, missing routes, partial JSONL recovery and interrupted
attempts without advancing the committed cursor:

```bash
cd experiments/native-history-replay
PYTHONDONTWRITEBYTECODE=1 python -m unittest -v test_replay.py
```

The opening session now spans setup and native auto pre-play. Terminal boundary
cancellations require the final historical boundary, the observed native terminal
turn, the exact unused plan count and the complete terminal stamp. A separately
marked compatibility policy repairs the retained ENTROPY cleanup ledger without
rewriting it. See [FIXES.md](FIXES.md) for representative native evidence and the
corrupt-terminal negative control; the running full campaign retains its frozen mod.
