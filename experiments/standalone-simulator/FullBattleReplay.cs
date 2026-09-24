using System.Reflection;
using System.Text.Json;

// Finish prediction while the live source is frozen, then replay in the native engine.
// The solver's original-model fallback reads are not valid against an advancing source.
internal static class FullBattleReplay
{
    private static object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    private static string Id(object o) => Read(Read(o, "Id"), "Entry").ToString()!;
    private sealed record Step(string Action, object? Card, object? Target, string State, int Hp, bool Terminal);

    public static object Run(Func<string, Type> get, Assembly solver, object root, object combat, object player, bool expectWin)
    {
        object sim = root.GetType().GetMethod("ForkSimulator")!.Invoke(root, null)!;
        object state = Read(sim, "State"), shadow = Read(state, "CombatState");
        object ps = state.GetType().GetMethod("GetPlayerCombatState")!.Invoke(state, [player])!;
        object hero = Read(player, "Creature");
        object simulatedHero = state.GetType().GetMethod("GetCreature")!.Invoke(state, [hero])!;
        Type stamp = solver.GetType("CombatSolver.ContinuationStamp", true)!;
        string Live() => Read(stamp.GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText").ToString()!;
        string Predicted() => Read(stamp.GetMethod("CapturePredicted")!.Invoke(null,
            [player, sim, shadow.GetType().GetMethod("GetPlayerTurnNumber")!.Invoke(shadow, [player]), Read(root, "Forecast"), Read(root, "StartTurnNumber")])!, "StateText").ToString()!;
        string initial = Live();
        if (initial != Predicted()) throw new InvalidOperationException("Initial frozen root differs.");
        var steps = new List<Step>();
        object beam = RoundProbe.CreateBeam(solver, root);
        var deaths = new HashSet<uint>();
        int shuffles = 0;
        bool Dead() => Convert.ToInt32(Read(simulatedHero, "CurrentHp")) <= 0;
        bool Won() => Items(Read(combat, "Enemies")).All(e => Convert.ToInt32(Read(state.GetType().GetMethod("GetCreature")!.Invoke(state, [e])!, "CurrentHp")) <= 0);
        bool Terminal() => Dead() || Won();
        var predictionWatch = System.Diagnostics.Stopwatch.StartNew();
        for (int round = 0; round < 40 && !Terminal(); round++)
        {
            int plays = 0;
            while (!Terminal() && Items(Read(Read(ps, "Hand"), "Cards")).FirstOrDefault(c =>
                (Id(Read(c, "Preview")) is "STRIKE_SILENT" or "DEFEND_SILENT" or "NEUTRALIZE" or "SLICE")
                && (bool)sim.GetType().GetMethod("CanPlay")!.Invoke(sim, [c])!) is { } card)
            {
                if (++plays > 20) throw new InvalidOperationException("Fixture action limit.");
                string id = Id(Read(card, "Preview"));
                object? target = id == "DEFEND_SILENT" ? null : Items(Read(combat, "Enemies")).First(e =>
                    Convert.ToInt32(Read(state.GetType().GetMethod("GetCreature")!.Invoke(state, [e])!, "CurrentHp")) > 0);
                sim.GetType().GetMethod("ManualPlay")!.Invoke(sim, [card, target, null]);
                steps.Add(new(id, Read(card, "Original"), target, Predicted(), Convert.ToInt32(Read(simulatedHero, "CurrentHp")), Terminal()));
            }
            if (Terminal()) break;
            object?[] args = [sim, shadow, round, deaths, shuffles, null];
            object boundary = beam.GetType().GetMethod("AdvanceRound", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(beam, args)!;
            shuffles = (int)args[4]!;
            if (boundary.ToString() != "None") throw new InvalidOperationException("Fixture boundary: " + boundary);
            steps.Add(new("end_turn", null, null, Predicted(), Convert.ToInt32(Read(simulatedHero, "CurrentHp")), Terminal()));
        }
        if (!Terminal() || Won() != expectWin) throw new InvalidOperationException("Fixture did not reach expected predicted outcome.");
        if (Live() != initial) throw new InvalidOperationException("Prediction modified the frozen native root.");
        predictionWatch.Stop();
        object manager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        object cm = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        object turn = cm.GetType().GetField("_turnState", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(cm)!;
        var trace = new List<object>();
        var nativeWatch = System.Diagnostics.Stopwatch.StartNew();
        foreach (Step step in steps)
        {
            if (step.Card is { } card)
            {
                if (!(bool)card.GetType().GetMethod("TryManualPlay")!.Invoke(card, [step.Target])!)
                    throw new InvalidOperationException("Native rejected planned " + step.Action);
                object executor = Read(manager, "ActionExecutor");
                ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            }
            else
            {
                Task end = (Task)cm.GetType().GetMethod("AwaitTurnEndAndSwitchSides", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn])!;
                cm.GetType().GetMethod("SetReadyToEndTurn")!.Invoke(cm, [player, false, null]);
                end.WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
                Task Start() => (Task)cm.GetType().GetMethod("StartTurn", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn, null])!;
                if ((bool)Read(cm, "IsInProgress")) Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
                if ((bool)Read(cm, "IsInProgress")) Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            }
            if (step.Terminal && expectWin)
                ((Task)cm.GetType().GetMethod("CheckWinCondition", Type.EmptyTypes)!.Invoke(cm, null)!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if (step.Terminal)
            {
                if ((bool)Read(cm, "IsInProgress") || Convert.ToInt32(Read(hero, "CurrentHp")) != step.Hp)
                    throw new InvalidOperationException("Native terminal status or HP differs.");
                trace.Add(new { action = step.Action, terminal = true, hp = Read(hero, "CurrentHp"), predictedHp = step.Hp });
            }
            else
            {
                string live = Live();
                if (live != step.State)
                {
                    Console.WriteLine(JsonSerializer.Serialize(new { status = "native_action_mismatch", action = step.Action, live, predicted = step.State }));
                    throw new InvalidOperationException("Frozen-source replay differs after " + step.Action);
                }
                trace.Add(new { action = step.Action, live, predicted = step.State });
            }
        }
        nativeWatch.Stop();
        bool roomCompleted = false, progressWritten = false;
        if (expectWin)
        {
            object room = Read(Read(combat, "RunState"), "CurrentRoom");
            roomCompleted = (bool)Read(room, "IsPreFinished");
            object save = get("Saves.SaveManager").GetProperty("Instance")!.GetValue(null)!;
            object progress = Read(save, "Progress");
            object stats = progress.GetType().GetMethod("GetOrCreateEncounterStats")!.Invoke(progress, [Read(Read(combat, "Encounter"), "Id")])!;
            int wins = Items(Read(stats, "FightStats")).Sum(s => Convert.ToInt32(Read(s, "Wins")));
            object store = save.GetType().GetField("_saveStore", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(save)!;
            progressWritten = Items(Read(store, "Calls")).Any(call =>
                call.GetType().GetField("Item1")!.GetValue(call)?.ToString() == "WriteFile"
                && ((object[])call.GetType().GetField("Item2")!.GetValue(call)!)[0].ToString()!.EndsWith("/progress.save", StringComparison.Ordinal));
            if (!roomCompleted || wins != 1 || !progressWritten)
                throw new InvalidOperationException("Native victory did not finalize room, record win and save in-memory progress.");
        }
        return new { status = "native_battle_matched", productionReady = false, productionLabels = false,
            scope = "A10 fixture; full continuation before terminal, HP and ended flag at terminal; victory also checks room completion and in-memory progress; no reward/exit lifecycle",
            policy = "play legal StrikeSilent, DefendSilent, Neutralize and Slice in hand order; no teacher search",
            outcome = expectWin ? "win" : "loss", completedEnemyRounds = steps.Count(s => s.Action == "end_turn"),
            roomCompleted, progressWritten, rootUnchangedBeforeNativeReplay = true,
            predictionMilliseconds = predictionWatch.Elapsed.TotalMilliseconds,
            nativeReplayMilliseconds = nativeWatch.Elapsed.TotalMilliseconds,
            measurement = "first execution including JIT and trace/assertions; excludes process startup and initialization; native is managed TestMode, not Wine baseline",
            trace };
    }
}
