using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;

string stage = "host_setup";
try
{
    if (args.Length is < 1 or > 2) throw new ArgumentException("Usage: SimulatorPrototype <game-directory> [--root-probe|--round-probe|--victory-probe|--oracle-probe|iterations(1..10000)]");
    string root = Path.GetFullPath(args[0]);
    bool oracleProbe = args.Length == 2 && args[1] == "--oracle-probe";
    bool victoryProbe = args.Length == 2 && args[1] == "--victory-probe";
    bool roundProbe = oracleProbe || victoryProbe || args.Length == 2 && args[1] == "--round-probe";
    bool rootProbe = roundProbe || args.Length == 2 && args[1] == "--root-probe";
    int iterations = args.Length == 2 && !rootProbe ? int.Parse(args[1]) : 1000;
    if (iterations is < 1 or > 10000) throw new ArgumentOutOfRangeException(nameof(iterations));
    string data = Path.Combine(root, "data_sts2_windows_x86_64");
    string solverPath = Path.Combine(root, "mods", "CombatSolver", "CombatSolver.dll");
    HostAdapter.Verify(solverPath, HostAdapter.SolverHash);
    string hostGame = HostAdapter.CreateGameCopy(Path.Combine(data, "sts2.dll"), AppContext.BaseDirectory);
    string[] directories = [data, Path.Combine(root, "mods", "CombatSolver"), Path.Combine(root, "mods", "STS2-RitsuLib")];
    AssemblyLoadContext.Default.Resolving += (context, name) =>
    {
        string? path = directories.Select(d => Path.Combine(d, name.Name + ".dll")).FirstOrDefault(File.Exists);
        return path == null ? null : context.LoadFromAssemblyPath(path);
    };
    Assembly game = AssemblyLoadContext.Default.LoadFromAssemblyPath(hostGame);
    Type Get(string name) => game.GetType("MegaCrit.Sts2.Core." + name, throwOnError: true)!;
    void Begin(string name) { stage = name; Console.WriteLine(JsonSerializer.Serialize(new { stage })); }
    Begin("native_test_host");
    Get("TestSupport.TestMode").GetProperty("IsOn")!.SetValue(null, true);
    var logEvent = Get("Logging.Log").GetEvent("LogCallback")!;
    var logArgs = logEvent.EventHandlerType!.GetMethod("Invoke")!.GetParameters().Select(p => System.Linq.Expressions.Expression.Parameter(p.ParameterType, p.Name)).ToArray();
    var logBody = System.Linq.Expressions.Expression.Call(System.Linq.Expressions.Expression.Constant(Console.Error), typeof(TextWriter).GetMethod("WriteLine", [typeof(string)])!, logArgs[1]);
    logEvent.AddEventHandler(null, System.Linq.Expressions.Expression.Lambda(logEvent.EventHandlerType, logBody, logArgs).Compile());
    Begin("model_catalog");
    Type db = Get("Models.ModelDb"), model = Get("Models.AbstractModel");
    MethodInfo init = db.GetMethods().Single(m => m.Name == "Init");
    object?[] initArgs = init.GetParameters().Length switch
    {
        0 => [],
        1 when init.GetParameters()[0].ParameterType == typeof(Type[]) => [game.GetTypes().Where(t => !t.IsAbstract && model.IsAssignableFrom(t)).ToArray()],
        _ => throw new NotSupportedException("Unrecognized ModelDb.Init signature: " + init),
    };
    init.Invoke(null, initArgs);
    Begin("player");
    object character = db.GetMethods().Single(m => m.Name == "Character" && m.IsGenericMethodDefinition).MakeGenericMethod(Get("Models.Characters.Silent")).Invoke(null, null)!;
    Begin("unlock_state");
    Type unlockType = Get("Unlocks.UnlockState");
    object unlock = unlockType.GetField("all", BindingFlags.Public | BindingFlags.Static)!.GetValue(null)!;
    Begin("create_player");
    Type playerType = Get("Entities.Players.Player");
    HostAdapter.ConfigureTestSave(Get);
    Begin("player_factory");
    object player = playerType.GetMethods().Single(m => m.Name == "CreateForNewRun" && !m.IsGenericMethod && m.GetParameters().Length == 3).Invoke(null, [character, unlock, 1UL])!;
    Begin("test_mod_environment");
    Get("Modding.ModManager").GetProperty("State")!.SetValue(null, Enum.Parse(Get("Modding.ModManagerState"), "Skipped"));
    Begin("run");
    Array players = Array.CreateInstance(playerType, 1); players.SetValue(player, 0);
    object run = Get("Runs.RunState").GetMethod("CreateForTest")!.Invoke(null, [players, null, null, Enum.Parse(Get("Runs.GameMode"), "Standard"), 0, "SIMPROTO1"])!;
    Get("Context.LocalContext").GetProperty("NetId")!.SetValue(null, 1UL);
    Begin("offline_platform");
    object manager = Get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
    var netProperty = manager.GetType().GetProperty("NetService")!;
    netProperty.SetValue(manager, DispatchProxy.Create(netProperty.PropertyType, typeof(OfflinePlatformService)));
    Begin("combat");
    object combat = Activator.CreateInstance(Get("Combat.CombatState"), [null, run, null, null, null])!;
    combat.GetType().GetMethod("AddPlayer")!.Invoke(combat, [player]);
    object pcs = Activator.CreateInstance(Get("Entities.Players.PlayerCombatState"), [player])!;
    playerType.GetProperty("PlayerCombatState")!.SetValue(player, pcs);
    Begin("monster");
    object monster = db.GetMethods().Single(m => m.Name == "Monster" && m.IsGenericMethodDefinition).MakeGenericMethod(Get("Models.Monsters.Chomper")).Invoke(null, null)!;
    monster = monster.GetType().GetMethod("ToMutable")!.Invoke(monster, null)!;
    object enemy = combat.GetType().GetMethod("CreateCreature")!.Invoke(combat, [monster, Enum.Parse(Get("Combat.CombatSide"), "Enemy"), null])!;
    combat.GetType().GetMethod("AddCreature")!.Invoke(combat, [enemy]);
    if (victoryProbe) enemy.GetType().GetProperty("CurrentHp")!.SetValue(enemy, 12);
    Begin("monster_state_machine");
    monster.GetType().GetMethod("SetUpForCombat")!.Invoke(monster, null);
    monster.GetType().GetMethod("RollMove")!.Invoke(monster, [combat.GetType().GetProperty("PlayerCreatures")!.GetValue(combat)]);
    Begin("cards");
    object hand = pcs.GetType().GetProperty("Hand")!.GetValue(pcs)!;
    foreach (string name in new[] { "StrikeSilent", "DefendSilent" })
    {
        object card = combat.GetType().GetMethods().Single(m => m.Name == "CreateCard" && m.IsGenericMethodDefinition).MakeGenericMethod(Get("Models.Cards." + name)).Invoke(combat, [player])!;
        hand.GetType().GetMethod("AddInternal")!.Invoke(hand, [card, -1, true]);
    }
    pcs.GetType().GetProperty("Energy")!.SetValue(pcs, 3);
    Begin("solver");
    Assembly solver = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(root, "mods", "CombatSolver", "CombatSolver.dll"));
    Type simulatorType = solver.GetType("CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator", true)!;
    Begin("simulator");
    object simulationRoot = rootProbe
        ? Activator.CreateInstance(solver.GetType("CombatSolver.SimulatedCombatState", true)!, [combat, null])!
        : combat;
    object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    object[] Cards(object pile) => Items(Read(pile, "Cards"));
    string CardId(object card) => Read(Read(card, "Id"), "Entry").ToString()!;
    string[] Ids(object pile, bool predicted) => Cards(pile).Select(c => CardId(predicted ? Read(c, "Preview") : c)).ToArray();
    object creature = Read(player, "Creature");
    string Baseline() => JsonSerializer.Serialize(new
    {
        playerHp = Read(creature, "CurrentHp"),
        playerBlock = Read(creature, "Block"),
        enemyHp = Read(enemy, "CurrentHp"),
        enemyBlock = Read(enemy, "Block"),
        energy = Read(pcs, "Energy"),
        piles = new[] { "Hand", "DrawPile", "DiscardPile", "ExhaustPile", "PlayPile" }.Select(p => Ids(Read(pcs, p), false)).ToArray(),
        playerPowers = Items(Read(creature, "Powers")).Select(p => new { id = CardId(p), amount = Read(p, "Amount") }).ToArray(),
        enemyPowers = Items(Read(enemy, "Powers")).Select(p => new { id = CardId(p), amount = Read(p, "Amount") }).ToArray(),
        rng = Read(run, "Rng").GetType().GetMethod("ToSerializable")!.Invoke(Read(run, "Rng"), null)
    });
    string baseline = Baseline();
    if (roundProbe)
    {
        Begin("localization");
        PackedLocalization.Configure(Get, Path.Combine(root, "SlayTheSpire2.pck"));
        Begin("search_root_capture");
        object searchRoot = solver.GetType("CombatSolver.CombatRootSnapshot", true)!.GetMethod("Capture")!.Invoke(null, [combat])!;
        Console.WriteLine(JsonSerializer.Serialize(new { status = "search_root_captured" }));
        Begin(oracleProbe ? "original_effect_comparison" : "battle_replay");
        Console.WriteLine(JsonSerializer.Serialize(oracleProbe
            ? OriginalEffectProbe.Run(Get, searchRoot, player, enemy, monster)
            : RoundProbe.Run(solver, searchRoot, combat, player, enemy)));
        return;
    }
    object? capturedSimulator = rootProbe ? Activator.CreateInstance(simulatorType, [simulationRoot])! : null;
    object RunPair()
    {
        object sim = capturedSimulator is null
            ? Activator.CreateInstance(simulatorType, [combat])!
            : simulatorType.GetMethod("Fork")!.Invoke(capturedSimulator, null)!;
        object state = Read(sim, "State");
        object ps = state.GetType().GetMethod("GetPlayerCombatState")!.Invoke(state, [player])!;
        object ph = Read(ps, "Hand");
        simulatorType.GetMethod("ManualPlay")!.Invoke(sim, [Cards(ph)[0], enemy, null]);
        simulatorType.GetMethod("ManualPlay")!.Invoke(sim, [Cards(ph)[0], null, null]);
        object pe = state.GetType().GetMethod("GetCreature")!.Invoke(state, [enemy])!;
        object pp = state.GetType().GetMethod("GetCreature")!.Invoke(state, [creature])!;
        string[] discard = Ids(Read(ps, "DiscardPile"), true);
        if ((int)Read(pe, "CurrentHp") != (int)Read(enemy, "CurrentHp") - 6 || (int)Read(pp, "Block") != 5
            || (int)Read(ps, "Energy") != 1 || Cards(ph).Length != 0
            || !discard.SequenceEqual(new[] { "STRIKE_SILENT", "DEFEND_SILENT" })
            || (bool)Read(sim, "HasRisk") || Baseline() != baseline)
            throw new InvalidOperationException("Fixed smoke fixture or source-state isolation check failed.");
        return new { enemyHp = Read(pe, "CurrentHp"), playerBlock = Read(pp, "Block"), energy = Read(ps, "Energy"), discard, checkedSourceStateUnchanged = true };
    }
    Begin("fixed_card_smoke");
    object outcome = RunPair(); // JIT warmup excluded from the timing below.
    var sw = System.Diagnostics.Stopwatch.StartNew();
    for (int i = 0; i < iterations; i++) RunPair();
    sw.Stop();
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        status = rootProbe ? "root_smoke_passed" : "smoke_passed",
        productionReady = false,
        productionLabels = false,
        completeBattles = 0,
        gameSha256 = HostAdapter.GameHash,
        solverSha256 = HostAdapter.SolverHash,
        fixture = "Silent: StrikeSilent + DefendSilent vs Chomper; manually prepared hand; no enemy turn",
        outcome,
        iterations,
        actions = iterations * 2,
        elapsedMilliseconds = sw.Elapsed.TotalMilliseconds,
        measurement = rootProbe ? "fork captured simulator + two card plays + assertions + source-state snapshot" : "fresh simulator + two card plays + assertions + source-state snapshot",
        peakWorkingSetBytes = System.Diagnostics.Process.GetCurrentProcess().PeakWorkingSet64
    }));
}
catch (Exception error)
{
    while (error is TargetInvocationException { InnerException: not null }) error = error.InnerException;
    Console.Error.WriteLine(JsonSerializer.Serialize(new { status = "blocked", stage, error = error.ToString(), productionReady = false, productionLabels = false }));
    Environment.ExitCode = 1;
}
