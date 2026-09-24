using System.Reflection;
using System.Text.Json;

internal static class NativeActionProbe
{
    private static object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    private static string Id(object o) => Read(Read(o, "Id"), "Entry").ToString()!;

    public static object Run(Func<string, Type> get, Assembly solver, object root, object combat, object player, object enemy, string[] actions, bool advanceRound = false, bool fullBattle = false, bool expectWin = false)
    {
        if (fullBattle) return FullBattleReplay.Run(get, solver, root, combat, player, expectWin);
        object sim = root.GetType().GetMethod("ForkSimulator")!.Invoke(root, null)!;
        object state = Read(sim, "State");
        object ps = state.GetType().GetMethod("GetPlayerCombatState")!.Invoke(state, [player])!;
        object pcs = Read(player, "PlayerCombatState");
        Type stamp = solver.GetType("CombatSolver.ContinuationStamp", true)!;
        string Live() => Read(stamp.GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText").ToString()!;
        string Predicted() => Read(stamp.GetMethod("CapturePredicted")!.Invoke(null,
            [player, sim, Read(pcs, "TurnNumber"), Read(root, "Forecast"), Read(root, "StartTurnNumber")])!, "StateText").ToString()!;
        var trace = new List<object>();
        void Compare(string action)
        {
            string live = Live(), predicted = Predicted();
            trace.Add(new { action, live, predicted });
            if (live != predicted)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { status = "native_action_mismatch", action, live, predicted }));
                throw new InvalidOperationException("Full continuation differs after " + action);
            }
        }
        Compare("opening");
        void Play(object card)
        {
            string id = Id(card);
            object predictedCard = Items(Read(Read(ps, "Hand"), "Cards")).First(c => ReferenceEquals(Read(c, "Original"), card));
            object? target = id == "DEFEND_SILENT" ? null : Items(Read(combat, "Enemies")).First(e => Convert.ToInt32(Read(e, "CurrentHp")) > 0);
            sim.GetType().GetMethod("ManualPlay")!.Invoke(sim, [predictedCard, target, null]);
            if (!(bool)card.GetType().GetMethod("TryManualPlay")!.Invoke(card, [target])!)
                throw new InvalidOperationException("Native play rejected: " + id);
            object manager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
            object executor = Read(manager, "ActionExecutor");
            ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!)
                .WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            Compare(id);
        }
        foreach (string id in actions) Play(Items(Read(Read(pcs, "Hand"), "Cards")).First(c => Id(c) == id));
        if (advanceRound)
        {
            object beam = RoundProbe.CreateBeam(solver, root);
            object shadow = Read(state, "CombatState");
            object?[] roundArgs = [sim, shadow, 0, new HashSet<uint>(), 0, null];
            object boundary = beam.GetType().GetMethod("AdvanceRound", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(beam, roundArgs)!;
            if (boundary.ToString() != "None") throw new InvalidOperationException("Predicted round boundary: " + boundary);
            object cm = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
            object turn = cm.GetType().GetField("_turnState", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(cm)!;
            Task End() => (Task)cm.GetType().GetMethod("AwaitTurnEndAndSwitchSides", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn])!;
            Task Start() => (Task)cm.GetType().GetMethod("StartTurn", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn, null])!;
            Task end = End();
            cm.GetType().GetMethod("SetReadyToEndTurn")!.Invoke(cm, [player, false, null]);
            end.WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if (Read(combat, "CurrentSide").ToString() != "Enemy") throw new InvalidOperationException("Native turn did not switch to enemy.");
            Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if (Read(combat, "CurrentSide").ToString() != "Player") throw new InvalidOperationException("Native enemy turn did not return to player.");
            Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if (Convert.ToInt32(Read(pcs, "TurnNumber")) != 2) throw new InvalidOperationException("Native round did not advance.");
            Compare("end_turn_and_enemy_round");
        }
        return new { status = advanceRound ? "native_round_matched" : "native_actions_matched", productionReady = false, productionLabels = false,
            scope = "three queued native card plays from starter opening; full continuation compared after each",
            ascension = Read(Read(combat, "RunState"), "AscensionLevel"), trace };
    }
}
