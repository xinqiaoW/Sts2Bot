using System.Reflection;
using System.Text.Json;

internal static class RoundProbe
{
    private static object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    public static object CreateBeam(Assembly solver, object root, object? observedDamage = null, bool includeTurnSetup = false)
    {
        Type Get(string name) => solver.GetType("CombatSolver." + name, true)!;
        object potionPolicy = Enum.Parse(Get("SolverPotionPolicy"), "Disabled");
        object potionStrategy = Activator.CreateInstance(Get("PotionStrategySnapshot"), [potionPolicy, Array.CreateInstance(Get("PotionSlotDirective"), 0)])!;
        object shortProfile = Get("SolverSearchProfile").GetProperty("Short")!.GetValue(null)!;
        foreach (var (name, expected) in new[] { ("BeamWidth", 24), ("MaxExpandedNodes", 2400), ("MaxCardBranchesPerNode", 20), ("SoftTimeBudgetMilliseconds", 8000) })
            if (Convert.ToInt32(Read(shortProfile, name)) != expected)
                throw new InvalidOperationException("Unexpected pinned teacher profile: " + name);
        object deepProfile = Get("SolverSearchProfile").GetProperty("Deep")!.GetValue(null)!;
        // Presentation uses the solver's existing ID fallback, without enumerating localized mock powers.
        var namesCtor = Get("SolverDisplayNames").GetConstructors(BindingFlags.NonPublic | BindingFlags.Instance).Single();
        object names = namesCtor.Invoke(namesCtor.GetParameters().Select(p => Activator.CreateInstance(p.ParameterType)).ToArray());
        object diagnostics = Activator.CreateInstance(Get("SearchDiagnosticsSink"), [(Action<string>)Console.Error.WriteLine, (Action<string>)Console.Error.WriteLine])!;
        var policyType = Get("SearchPolicySnapshot");
        var constructor = policyType.GetConstructors().Single(c => c.GetParameters().Length > 1);
        object policy = constructor.Invoke([
            shortProfile,deepProfile,potionPolicy,potionStrategy,false,false,true,false,1,null,null,includeTurnSetup,null,
            Enum.Parse(Get("BossHpStrategy"),"ProgressionFirst"),Enum.Parse(Get("BossHpStrategy"),"ProgressionFirst"),0,
            diagnostics,Activator.CreateInstance(Get("SearchFramePressureSignal")),Activator.CreateInstance(Get("SearchMemoryPressureSignal"))]);
        object damage = observedDamage ?? Activator.CreateInstance(Get("BattleDamageSnapshot"), [0, 0, 0])!;
        var ctor = Get("CombatBeamSolver").GetConstructors().Single();
        object?[] arguments = ctor.GetParameters().Select((p, i) => i < 4 ? null : p.HasDefaultValue ? p.DefaultValue : throw new NotSupportedException("Required solver argument: " + p.Name)).ToArray();
        arguments[0] = root; arguments[1] = names; arguments[2] = damage; arguments[3] = policy;
        return ctor.Invoke(arguments);
    }
    public static object Run(Assembly solver, object root, object combat, object player, object enemy)
    {
        Type Get(string name) => solver.GetType("CombatSolver." + name, true)!;
        object beam = CreateBeam(solver, root);
        object MakeSimulator() => root.GetType().GetMethod("ForkSimulator")!.Invoke(root, null)!;
        object Stamp(object sim)
        {
            object shadow = Read(Read(sim, "State"), "CombatState");
            int turn = (int)shadow.GetType().GetMethod("GetPlayerTurnNumber")!.Invoke(shadow, [player])!;
            object stamp = Get("ContinuationStamp").GetMethod("CapturePredicted")!.Invoke(null, [player, sim, turn, Read(root, "Forecast"), Read(root, "StartTurnNumber")])!;
            return Read(stamp, "StateText");
        }
        string rootBefore = Stamp(MakeSimulator()).ToString()!;
        object Battle()
        {
            object sim = MakeSimulator(), state = Read(sim, "State"), shadow = Read(state, "CombatState");
            object ps = state.GetType().GetMethod("GetPlayerCombatState")!.Invoke(state, [player])!;
            object[] Hand() => Items(Read(Read(ps, "Hand"), "Cards"));
            object me = state.GetType().GetMethod("GetCreature")!.Invoke(state, [Read(player, "Creature")])!;
            object foe = state.GetType().GetMethod("GetCreature")!.Invoke(state, [enemy])!;
            string CardId(object c) => Read(Read(Read(c, "Preview"), "Id"), "Entry").ToString()!;
            var trace = new List<object>();
            void Record(string action)
            {
                if ((bool)Read(sim, "HasRisk") || (bool)Read(shadow, "HasPendingChoice"))
                    throw new NotSupportedException("Unresolved prediction risk/choice in fixture: " + action);
                trace.Add(new { action, round = Read(shadow, "RoundNumber"), playerHp = Read(me, "CurrentHp"), enemyHp = Read(foe, "CurrentHp"), energy = Read(ps, "Energy"), hand = Hand().Select(CardId).ToArray(), state = Stamp(sim) });
            }
            Record("start");
            var dead = new HashSet<uint>();
            for (int round = 0; round < 40; round++)
            {
                int plays = 0;
                while (Hand().FirstOrDefault(c => (bool)sim.GetType().GetMethod("CanPlay")!.Invoke(sim, [c])!) is { } card)
                {
                    if (++plays > 20) throw new InvalidOperationException("Fixture action bound exceeded.");
                    string id = CardId(card);
                    if (id is not ("STRIKE_SILENT" or "DEFEND_SILENT")) throw new NotSupportedException("Fixture policy does not support " + id);
                    sim.GetType().GetMethod("ManualPlay")!.Invoke(sim, [card, id == "STRIKE_SILENT" ? enemy : null, null]);
                    Record(id);
                    if ((int)Read(me, "CurrentHp") <= 0 || (int)Read(foe, "CurrentHp") <= 0) break;
                }
                if ((int)Read(me, "CurrentHp") <= 0 || (int)Read(foe, "CurrentHp") <= 0)
                    return new { outcome = (int)Read(me, "CurrentHp") <= 0 ? "loss" : "win", trace };
                object?[] roundArgs = [sim, shadow, round, dead, 0, null];
                object boundary = beam.GetType().GetMethod("AdvanceRound", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(beam, roundArgs)!;
                if (boundary.ToString() != "None") throw new NotSupportedException("Round stopped at " + boundary);
                Record("end_turn");
                if ((int)Read(me, "CurrentHp") <= 0 || (int)Read(foe, "CurrentHp") <= 0)
                    return new { outcome = (int)Read(me, "CurrentHp") <= 0 ? "loss" : "win", trace };
            }
            throw new InvalidOperationException("Fixture did not terminate within 40 rounds.");
        }
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        object first = Battle(), second = Battle();
        stopwatch.Stop();
        if (JsonSerializer.Serialize(first) != JsonSerializer.Serialize(second) || Stamp(MakeSimulator()).ToString() != rootBefore)
            throw new InvalidOperationException("Replay determinism or root fork isolation failed.");
        return new { status = "battle_pair_passed", productionReady = false, productionLabels = false, policy = "play legal fixture cards in hand order; no teacher search", syntheticBattles = 2, elapsedMilliseconds = stopwatch.Elapsed.TotalMilliseconds, deterministic = true, rootUnchanged = true, battle = first };
    }
}
