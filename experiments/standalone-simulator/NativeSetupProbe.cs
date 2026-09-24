using System.Reflection;

// Calls the reviewed game's real setup methods. Does not substitute mirrored setup rules.
internal static class NativeSetupProbe
{
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;
    private static object[] Items(object value) => ((System.Collections.IEnumerable)value).Cast<object>().ToArray();
    private static string Id(object value) => Read(Read(value, "Id"), "Entry").ToString()!;

    public static void InitializeRun(Func<string, Type> get, object run)
    {
        object runManager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        Console.WriteLine("{\"stage\":\"singleplayer_service\"}");
        // The native constructor only sets LocalVersion through NGame/Godot project metadata.
        // Supply pinned offline handshake metadata while retaining all original service methods.
        Type serviceType = get("Multiplayer.NetSingleplayerGameService");
        object service = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(serviceType);
        object version = Activator.CreateInstance(get("Multiplayer.PeerVersionInfo"))!;
        version.GetType().GetField("version")!.SetValue(version, "0.111.0");
        version.GetType().GetField("idDatabaseHash")!.SetValue(version, get("Multiplayer.Serialization.ModelIdSerializationCache").GetProperty("Hash")!.GetValue(null));
        serviceType.GetField("<LocalVersion>k__BackingField", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(service, version);
        Console.WriteLine("{\"stage\":\"run_manager_setup\"}");
        runManager.GetType().GetMethod("SetUpTest")!.Invoke(runManager, [run, service, true, false]);
    }

    public static object Run(Func<string, Type> get, object combat, object player, object enemy, bool opening = false)
    {
        object manager = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        var watch = System.Diagnostics.Stopwatch.StartNew();
        manager.GetType().GetMethod("SetUpCombat")!.Invoke(manager, [combat]);
        foreach (object creature in Items(Read(combat, "Creatures")))
            ((Task)manager.GetType().GetMethod("AfterCreatureAdded", [creature.GetType()])!
                .Invoke(manager, [creature])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        watch.Stop();
        object pcs = Read(player, "PlayerCombatState");
        string[] deck = Items(Read(Read(player, "Deck"), "Cards")).Select(Id).ToArray();
        string[] draw = Items(Read(Read(pcs, "DrawPile"), "Cards")).Select(Id).ToArray();
        var powers = Items(Read(enemy, "Powers"));
        if (deck.Length == 0 || !deck.Order().SequenceEqual(draw.Order()))
            throw new InvalidOperationException("Native setup did not copy the complete starting deck.");
        if (!powers.Any(p => Id(p) == "ARTIFACT_POWER" && Convert.ToInt32(Read(p, "Amount")) == 2))
            throw new InvalidOperationException("Native Chomper spawn did not apply Artifact 2: " + string.Join(",", powers.Select(p => $"{Id(p)}={Read(p, "Amount")}")));
        if (opening)
        {
            object turn = manager.GetType().GetField("_turnState", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(manager)!;
            turn.GetType().GetProperty("IsInProgress")!.SetValue(turn, true);
            turn.GetType().GetProperty("IsStarting")!.SetValue(turn, false);
            ((Task)get("Hooks.Hook").GetMethod("BeforeCombatStart")!.Invoke(null, [Read(combat, "RunState"), combat])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            ((Task)manager.GetType().GetMethod("StartTurn", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(manager, [turn, null])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            string[] hand = Items(Read(Read(pcs, "Hand"), "Cards")).Select(Id).ToArray();
            string[] remainingDraw = Items(Read(Read(pcs, "DrawPile"), "Cards")).Select(Id).ToArray();
            if (hand.Length != 7 || !hand.SequenceEqual(draw.Take(7)) || !remainingDraw.SequenceEqual(draw.Skip(7))
                || Convert.ToInt32(Read(pcs, "Energy")) != 3 || Convert.ToInt32(Read(pcs, "TurnNumber")) != 1
                || Read(pcs, "Phase").ToString() != "Play")
                throw new InvalidOperationException("Native starter opening order, draw count, energy, turn or phase differs.");
            return new { status = "native_opening_passed", productionReady = false, productionLabels = false,
                scope = "native starter opening hooks and StartTurn; no room lifecycle",
                ascension = Read(Read(combat, "RunState"), "AscensionLevel"),
                enemies = Items(Read(combat, "Enemies")).Select(e => new { monster = Id(Read(e, "Monster")), hp = Read(e, "CurrentHp"), maxHp = Read(e, "MaxHp"), slot = e.GetType().GetProperty("SlotName")!.GetValue(e) }).ToArray(),
                hand, remainingDraw, energy = Read(pcs, "Energy"), turn = Read(pcs, "TurnNumber"), phase = Read(pcs, "Phase").ToString() };
        }
        return new {
            status = "native_setup_passed", productionReady = false, productionLabels = false,
            scope = "native SetUpCombat and AfterCreatureAdded; before BeforeCombatStart and first draw; starter deck A0 fixture",
            deck, draw, enemyPowers = powers.Select(p => new { id = Id(p), amount = Read(p, "Amount") }).ToArray(),
            elapsedMilliseconds = watch.Elapsed.TotalMilliseconds
        };
    }
}
