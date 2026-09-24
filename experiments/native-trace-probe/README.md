# Native action trace for standalone validation

This diagnostic mod runs only in an isolated Wine game copy. It is inert without
`STS2_NATIVE_TRACE_PATH` and rejects a collector DLL other than the pinned hash.
It records accepted native TryManualPlay enqueue operations with the original PlanAction, before/after continuation stamps,
choice plans, and actual EndPlayerTurnAction execution. It does not replace the
original teacher, card effects, choice driver, or RNG. Its task wrapper awaits the
original native choice/action completion before recording the after-state.
Logging can change timing, so these runs are not performance measurements.

Build with the fixed game's data directory:

```sh
dotnet build experiments/native-trace-probe/NativeTraceProbe.csproj -c Release   -p:GameDataDir=/path/to/isolated/game/data_sts2_windows_x86_64   -p:BaseIntermediateOutputPath=/tmp/native-trace/obj/   -p:OutputPath=/tmp/native-trace/bin/
```

`run_capture.py` requires `--experiment-directory`, `--native-runtime`, `--fixture`,
`--progress-snapshot`, `--trace-dll`, and `--report`. Use an otherwise idle isolated
runtime. All mutable runtime paths must be below the experiment directory. The
runner refuses to replace an installed trace mod and removes its own mod after
stopping the owned game process, including on failure. It uses a unique run ID and
records native completion separately from diagnostic readiness.

`persistent_capture.py` is the batch form used by
`../standalone-simulator/run_build_panel.py`: it reuses one isolated game process
through the original ready/result protocol, writes a separate trace per request,
and restores the pinned progress snapshot before each scenario. `startup_slots.py`
bounds simultaneous cold starts across workers (`STS2_NATIVE_STARTUP_SLOTS`).

For replay, start from the restoration fixture and add `nativeTrace` containing
the capture report; set `request` to that report's actual request. Run:

```sh
dotnet SimulatorPrototype.dll /path/to/game --replay-native-request   fixture-with-native-trace.json pilot-progress-v24.json
```

A recorded example is `../standalone-simulator/fixtures/native-replay-2.json`.
The replay executes original native game commands in the standalone host without
searching for a new route. It consumes recorded next-turn choices, compares the
full continuation text at each recorded action boundary, and checks actual final
HP/max HP. Missing intermediate completion events are errors. Native deployment
can be cancelled by the final killing action, leaving no post-action stamp; only
this final pending action may use the terminal observation, after the standalone
CombatEnded event and a matching final HP/max HP.

Known bounds: this is a diagnostic entry, not a collection backend. Unsupported
nonempty choice-session owners, trace errors, missing sequence entries and
unplayable actions fail closed. Rejected FindCardForDeployment/CanPlayTargeting attempts are not executed actions and are not recorded as plays. When the producer task completed successfully but the native choice plan failed, the observer records the resulting state and rethrows the original exception. Such drift-bearing traces still require explicit replay validation. Recorded traces remain experimental.
