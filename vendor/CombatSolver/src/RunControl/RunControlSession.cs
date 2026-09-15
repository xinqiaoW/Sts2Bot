using System.Diagnostics;
using Environment = System.Environment;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Screens.GameOverScreen;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Random;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Settings;
using MegaCrit.Sts2.Core.Timeline;

namespace CombatSolver;

// Owns one real run. No synthetic combat state, HP injection, reward generation,
// teacher-label insertion, or AutoSlayer.Start lifecycle is used here.
internal sealed partial class RunControlSession(NGame host, RunControlRequest request, RunControlFiles files)
{
    private readonly Stopwatch _elapsed = Stopwatch.StartNew();
    private readonly Rng _random = new(unchecked((uint)request.PolicySeed));
    private readonly HashSet<object> _handledRooms = [];
    private int _decisionSequence;
    private int _combatCount;
    private RunState? _run;
    private string _stage = "startup";
    private long _lastProgress;
    public string Stage => _stage;

    private RunState Run => _run ?? throw new InvalidOperationException("No active run.");
    private Player Me => LocalContext.GetMe(Run) ?? throw new InvalidOperationException("No local player.");

    private object State() => new
    {
        act = Run.CurrentActIndex + 1, actId = Run.Act.Id.Entry, floor = Run.TotalFloor,
        ascension = Run.AscensionLevel, startedWithNeow = Run.ExtraFields.StartedWithNeow,
        actFloor = Run.ActFloor, room = Run.CurrentRoom?.RoomType.ToString(),
        hp = Me.Creature.CurrentHp, maxHp = Me.Creature.MaxHp, gold = Me.Gold,
        deck = Me.Deck.Cards.Select(c => new { id = c.Id.Entry, upgrade = c.CurrentUpgradeLevel, native = c.ToSerializable() }).ToArray(),
        relics = Me.Relics.Select(r => new { id = r.Id.Entry, native = r.ToSerializable() }).ToArray(),
        potions = Me.PotionSlots.Select((p, slot) => new { slot, id = p?.Id.Entry }).ToArray(),
    };

    private void Record(string kind, object details)
    {
        files.Record(kind, new { state = _run == null ? null : State(), details });
        _lastProgress = Environment.TickCount64;
    }

    public async Task<object> RunAsync()
    {
        using CancellationTokenSource deadline = new(TimeSpan.FromSeconds(request.TimeoutSeconds));
        CancellationToken ct = deadline.Token;
        SolverSettingsData original = SolverSettings.Current;
        await host.GameStartupComplete.WaitAsync(ct);
        FastModeType originalFast = SaveManager.Instance.PrefsSave.FastMode;
        if (RunManager.Instance.IsInProgress)
            throw new InvalidOperationException("Run control requires an idle, dedicated process.");
        SolverSettings.ApplyForTesting(SolverSettings.ApplyPerformancePreset(original, SolverPerformancePreset.Medium) with
        {
            SolverDisabled = false, AutomaticCalculationEnabled = true, EnableNoGcRegion = false,
            PotionPolicy = SolverPotionPolicy.Disabled, PotionDirectives = [],
            DeploymentFastMode = SolverDeploymentFastMode.Instant, DeploymentInterActionDelaySeconds = 0,
            StopFullAutoOnCombatEnd = false, StopFullAutoOnDeathTurn = false,
            StopFullAutoOnWorseRecalculation = false, EnableDetailedDiagnosticLogs = false,
        });
        SolverController.ApplyPersistentSettings(SolverSettings.Capture());
        SaveManager.Instance.PrefsSave.FastMode = FastModeType.Fast;
        SaveManager.Instance.SetFtuesEnabled(false);
        // A fresh collector profile has no Neow/content unlocks. Whole-run
        // experiments use the complete native card/relic/event pools in memory.
        foreach (string epoch in EpochModel.AllEpochIds)
            SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
        try
        {
            CharacterModel character = ModelDb.AllCharacters.Single(c => c.Id.Entry == request.CharacterId);
            _stage = "start_run";
            await host.StartNewSingleplayerRun(character, false, ActModel.GetDefaultList().ToList(),
                [], request.Seed, GameMode.Standard, request.Ascension).WaitAsync(ct);
            _run = RunManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("Run was not created.");
            if (Run.AscensionLevel != 10 || !Run.ExtraFields.StartedWithNeow)
                throw new InvalidOperationException("Whole-run startup must preserve A10 and the native Neow start.");
            Record("run_started", new { request.Seed, request.PolicySeed, request.CombatMode });
            while (true)
            {
                ct.ThrowIfCancellationRequested();
                if (Environment.TickCount64 - _lastProgress > 60_000)
                    throw new TimeoutException($"No progress at {_stage}, floor {Run.TotalFloor}.");
                if (NOverlayStack.Instance?.Peek() is NGameOverScreen)
                {
                    _stage = "game_over";
                    bool win = Run.CurrentRoom?.IsVictoryRoom == true;
                    if (!win && !Me.Creature.IsDead)
                        throw new InvalidOperationException("Game-over screen without victory or death.");
                    object final = State();
                    // ToSave reads native history without replaying OnEnded or rewards.
                    RunControlFiles.AtomicWrite(Path.Combine(files.DirectoryPath, "native-run.json"), RunManager.Instance.ToSave(null));
                    Record("run_ended", new { outcome = win ? "victory" : "death" });
                    await host.ReturnToMainMenu().WaitAsync(ct);
                    SolverController.ReleaseUnattendedResultReferencesForTesting();
                    return new { schemaVersion = 1, kind = "run", request.RunId, status = "complete",
                        outcome = win ? "victory" : "death", decisionCount = _decisionSequence,
                        combatCount = _combatCount, elapsedSeconds = _elapsed.Elapsed.TotalSeconds, state = final };
                }
                if (CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting)
                {
                    await CombatAsync(ct);
                    continue;
                }
                if (NMapScreen.Instance?.IsOpen == true)
                {
                    await MapAsync(ct);
                    continue;
                }
                if (NOverlayStack.Instance?.Peek() is { } overlay)
                {
                    await OverlayAsync(overlay, ct);
                    continue;
                }
                await RoomStepAsync(ct);
                await Task.Delay(100, ct);
            }
        }
        finally
        {
            SolverSettings.ApplyForTesting(original);
            SolverController.ApplyPersistentSettings(SolverSettings.Capture());
            SaveManager.Instance.PrefsSave.FastMode = originalFast;
        }
    }

    private async Task CombatAsync(CancellationToken parent)
    {
        _stage = "combat";
        using CancellationTokenSource deadline = CancellationTokenSource.CreateLinkedTokenSource(parent);
        deadline.CancelAfter(TimeSpan.FromSeconds(request.CombatTimeoutSeconds));
        CancellationToken ct = deadline.Token;
        await WaitHelper.Until(() => CombatManager.Instance.DebugOnlyGetState() != null,
            ct, TimeSpan.FromSeconds(30), "Combat state did not appear.");
        CombatState state = CombatManager.Instance.DebugOnlyGetState()!;
        int number = ++_combatCount;
        Record("combat_started", new { number, enemies = state.Enemies.Select(e => e.Monster?.Id.Entry).ToArray() });
        bool engaged = false;
        while (CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting)
        {
            ct.ThrowIfCancellationRequested();
            if (!engaged && !CombatManager.Instance.IsOverOrEnding
                && (Me.PlayerCombatState?.Phase == PlayerTurnPhase.Play || PlayerTurnSetupCoordinator.CanTakeOverTurnSetup(state)))
            {
                SolverController.SetFullAuto(host, state, true);
                engaged = SolverController.FullAutoEnabled;
            }
            if (SolverController.AutomaticSearchPaused)
                throw new InvalidOperationException("CombatSolver paused; this run is not a completed combat.");
            await Task.Delay(50, ct);
        }
        await RunManager.Instance.ActionExecutor.FinishedExecutingActions().WaitAsync(ct);
        Record("combat_ended", new { number, alive = Me.Creature.IsAlive });
        SolverController.ReleaseUnattendedResultReferencesForTesting();
    }

    private async Task MapAsync(CancellationToken ct)
    {
        _stage = "map";
        NMapScreen map = NMapScreen.Instance!;
        NMapPoint[] points = UiHelper.FindAll<NMapPoint>(map)
            .Where(p => p.IsEnabled && p.IsTravelable).OrderBy(p => p.Point.coord.row).ThenBy(p => p.Point.coord.col).ToArray();
        if (points.Length == 0) { await Task.Delay(100, ct); return; }
        int seq = ++_decisionSequence;
        object decision = new { schemaVersion = 1, request.RunId, decisionSeq = seq, screen = "MAP", state = State(),
            options = points.Select((p, index) => new { index, row = p.Point.coord.row, col = p.Point.coord.col, type = p.Point.PointType.ToString() }).ToArray() };
        files.Record("decision", decision);
        RunControlFiles.AtomicWrite(files.DecisionPath, decision);
        using CancellationTokenSource waiting = CancellationTokenSource.CreateLinkedTokenSource(ct);
        waiting.CancelAfter(TimeSpan.FromSeconds(request.ActionTimeoutSeconds));
        while (!File.Exists(files.ActionPath)) await Task.Delay(50, waiting.Token);
        RunControlAction action = System.Text.Json.JsonSerializer.Deserialize<RunControlAction>(File.ReadAllText(files.ActionPath), RunControlFiles.Json)
            ?? throw new InvalidDataException("Empty action.");
        if (action.SchemaVersion != 1 || action.RunId != request.RunId || action.DecisionSeq != seq
            || action.Choice < 0 || action.Choice >= points.Length)
            throw new InvalidDataException("Stale, duplicate, foreign, or invalid action.");
        File.Move(files.ActionPath, Path.Combine(files.DirectoryPath, $"action-{seq:D5}.json"));
        NMapPoint point = points[action.Choice];
        if (!point.IsTravelable || !point.IsEnabled) throw new InvalidOperationException("Map option is no longer legal.");
        Record("action", action);
        int floor = Run.TotalFloor;
        await UiHelper.Click(point);
        await WaitHelper.Until(() => Run.TotalFloor != floor, ct, TimeSpan.FromSeconds(30), "Map action did not enter a floor.");
        Record("floor_entered", new { point.Point.coord.row, point.Point.coord.col });
    }
}
