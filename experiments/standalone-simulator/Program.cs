using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;

string stage = "host_setup";
try
{
    if (args.Length is < 1 or > 4) throw new ArgumentException("Usage: SimulatorPrototype <game-directory> [--native-win-probe|--native-battle-probe|--native-round-probe|--encounter-probe|--action-probe|--teacher-probe|--opening-probe|--setup-probe|--root-probe|--round-probe|--victory-probe|--oracle-probe|iterations(1..10000)]");
    bool progressProbe = args.Length == 3 && args[1] == "--progress-unlock-probe";
    bool rawRequest = args.Length >= 3 && args[1] == "--execute-request";
    bool replanProbe = args.Length >= 3 && args[1] == "--battle-replan-request";
    bool driftProbe = args.Length >= 3 && args[1] == "--battle-drift-request";
    bool choiceDriftProbe = args.Length >= 3 && args[1] == "--battle-choice-drift-request";
    bool missingCardProbe = args.Length >= 3 && args[1] == "--battle-missing-card-request";
    bool replayNative = args.Length >= 3 && args[1] == "--replay-native-request";
    bool requestBattleProbe = choiceDriftProbe || missingCardProbe || replayNative || rawRequest || driftProbe || replanProbe || args.Length >= 3 && args[1] == "--battle-request";
    bool startupProbe = requestBattleProbe || args.Length == 3 && args[1] == "--startup-request";
    bool restoreProbe = startupProbe || args.Length == 3 && args[1] == "--restore-request";
    if (args.Length == 3 && !restoreProbe && !progressProbe) throw new ArgumentException("Only --restore-request accepts a fixture path.");
    if (args.Length == 4 && !requestBattleProbe) throw new ArgumentException("Progress snapshots require a full battle request.");
    JsonElement? restoreFixture = restoreProbe ? JsonDocument.Parse(File.ReadAllText(args[2])).RootElement : null;
    if (rawRequest) restoreFixture = RequestExecution.Envelope(restoreFixture!.Value);
    string root = Path.GetFullPath(args[0]);
    bool continuationProbe = args.Length == 2 && (args[1] == "--teacher-continuation-probe" || args[1] == "--teacher-continuation-win-probe");
    bool teacherWinProbe = args.Length == 2 && (args[1] == "--teacher-win-probe" || args[1] == "--teacher-continuation-win-probe");
    bool teacherBattleProbe = continuationProbe || teacherWinProbe || args.Length == 2 && args[1] == "--teacher-battle-probe";
    bool nativeWinProbe = teacherWinProbe || args.Length == 2 && args[1] == "--native-win-probe";
    bool nativeBattleProbe = nativeWinProbe || args.Length == 2 && args[1] == "--native-battle-probe";
    bool nativeRoundProbe = nativeBattleProbe || args.Length == 2 && args[1] == "--native-round-probe";
    bool encounterProbe = teacherBattleProbe || nativeRoundProbe || args.Length == 2 && args[1] == "--encounter-probe";
    bool actionProbe = !teacherBattleProbe && encounterProbe || args.Length == 2 && args[1] == "--action-probe";
    bool teacherDeployProbe = args.Length == 2 && args[1] == "--teacher-deploy-probe";
    bool teacherProbe = teacherBattleProbe || teacherDeployProbe || args.Length == 2 && args[1] == "--teacher-probe";
    bool openingProbe = actionProbe || teacherProbe || args.Length == 2 && args[1] == "--opening-probe";
    bool setupProbe = args.Length == 2 && args[1] == "--setup-probe";
    bool oracleProbe = args.Length == 2 && args[1] == "--oracle-probe";
    bool victoryProbe = args.Length == 2 && args[1] == "--victory-probe";
    bool roundProbe = oracleProbe || victoryProbe || args.Length == 2 && args[1] == "--round-probe";
    bool rootProbe = roundProbe || args.Length == 2 && args[1] == "--root-probe";
    int iterations = args.Length == 2 && !rootProbe && !setupProbe && !openingProbe ? int.Parse(args[1]) : 1000;
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
    NativeDetourHost.Initialize();
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
    if (progressProbe)
    {
        object actualUnlock = HostAdapter.LoadProgressSnapshot(Get, args[2]);
        object SerializeUnlock(object state) => state.GetType().GetMethod("ToSerializable")!.Invoke(state, null)!;
        Console.WriteLine(JsonSerializer.Serialize(new { status = "progress_unlock_loaded", productionReady = false,
            snapshotSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(args[2]))).ToLowerInvariant(),
            actual = SerializeUnlock(actualUnlock), all = SerializeUnlock(unlock) }));
        return;
    }
    if (args.Length == 4) unlock = HostAdapter.LoadProgressSnapshot(Get, args[3]);
    Begin("player_factory");
    object player = playerType.GetMethods().Single(m => m.Name == "CreateForNewRun" && !m.IsGenericMethod && m.GetParameters().Length == 3).Invoke(null, [character, unlock, 1UL])!;
    Begin("test_mod_environment");
    Get("Modding.ModManager").GetProperty("State")!.SetValue(null, Enum.Parse(Get("Modding.ModManagerState"), "Skipped"));
    Get("Modding.AssemblyInfo").GetMethod("Init")!.Invoke(null, null);
    Get("Multiplayer.Serialization.ModelIdSerializationCache").GetMethod("Init")!.Invoke(null, null);
    Begin("run");
    Array players = Array.CreateInstance(playerType, 1); players.SetValue(player, 0);
    object run = startupProbe ? RequestStartupProbe.CreateRun(Get, players, restoreFixture!.Value) : Get("Runs.RunState").GetMethod("CreateForTest")!.Invoke(null, [players, null, null, Enum.Parse(Get("Runs.GameMode"), "Standard"), encounterProbe || restoreProbe ? 10 : 0, restoreFixture?.GetProperty("request").GetProperty("seed").GetString() ?? "SIMPROTO1"])!;
    Get("Context.LocalContext").GetProperty("NetId")!.SetValue(null, 1UL);
    Begin("offline_platform");
    object manager = Get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
    var netProperty = manager.GetType().GetProperty("NetService")!;
    netProperty.SetValue(manager, DispatchProxy.Create(netProperty.PropertyType, typeof(OfflinePlatformService)));
    if (openingProbe || restoreProbe) NativeSetupProbe.InitializeRun(Get, run);
    if (restoreProbe)
    {
        Begin("formal_request_restoration");
        HostClock.Configure(data);
        PackedLocalization.Configure(Get, Path.Combine(root, "SlayTheSpire2.pck"));
        if (startupProbe) RequestStartupProbe.Prepare(Get, run, restoreFixture!.Value);
        object restored = RequestRestoreProbe.Run(Get, AssemblyLoadContext.Default.LoadFromAssemblyPath(solverPath), run, player, restoreFixture!.Value, startupProbe, !rawRequest);
        Console.WriteLine(JsonSerializer.Serialize(restored));
        if (requestBattleProbe)
        {
            object completed = RequestBattleProbe.Run(Get, AssemblyLoadContext.Default.LoadFromAssemblyPath(solverPath), run, player, restoreFixture!.Value, !rawRequest && !replayNative, nativeReplay: replayNative, injectExhaustedPlanOnce: replanProbe, injectDeploymentDriftOnce: driftProbe, injectMissingCardOnce: missingCardProbe, injectUnconsumedChoiceOnce: choiceDriftProbe);
            Console.WriteLine(JsonSerializer.Serialize(rawRequest ? RequestExecution.Result(restoreFixture.Value.GetProperty("request"), restored, completed, args.Length == 4 ? args[3] : null) : completed));
        }
        return;
    }
    if (nativeWinProbe)
    {
        Begin("collector_deck_injection");
        Assembly collector = AssemblyLoadContext.Default.LoadFromAssemblyPath(solverPath);
        Type runner = collector.GetType("CombatSolver.UnattendedTestRunner", true)!;
        runner.GetMethod("ClearRunDeck", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [run, player]);
        object injection = Activator.CreateInstance(collector.GetType("CombatSolver.UnattendedCardInjection", true)!)!;
        injection.GetType().GetProperty("CardId")!.SetValue(injection, "SLICE");
        injection.GetType().GetProperty("UpgradeLevels")!.SetValue(injection, 1);
        injection.GetType().GetProperty("Count")!.SetValue(injection, 10);
        ((Task)runner.GetMethod("InjectRunCardAsync", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [run, player, injection])!).GetAwaiter().GetResult();
    }
    object? encounter = null;
    if (encounterProbe)
    {
        encounter = db.GetMethods().Single(m => m.Name == "Encounter" && m.IsGenericMethodDefinition).MakeGenericMethod(Get("Models.Encounters.ChompersNormal")).Invoke(null, null)!;
        encounter = encounter.GetType().GetMethod("ToMutable")!.Invoke(encounter, null)!;
        encounter.GetType().GetMethod("GenerateMonstersWithSlots")!.Invoke(encounter, [run]);
        object hero = playerType.GetProperty("Creature")!.GetValue(player)!;
        ((Task)Get("Commands.CreatureCmd").GetMethod("SetCurrentHp")!.Invoke(null, [hero, Convert.ToDecimal(hero.GetType().GetProperty("MaxHp")!.GetValue(hero))])!).GetAwaiter().GetResult();
    }
    Begin("combat");
    object combat = Activator.CreateInstance(Get("Combat.CombatState"), [encounter, run, null, null, null])!;
    combat.GetType().GetMethod("AddPlayer")!.Invoke(combat, [player]);
    if (encounterProbe)
    {
        object room = Activator.CreateInstance(Get("Rooms.CombatRoom"), [combat])!;
        run.GetType().GetMethod("PushRoom")!.Invoke(run, [room]);
    }
    object pcs = Activator.CreateInstance(Get("Entities.Players.PlayerCombatState"), [player])!;
    playerType.GetProperty("PlayerCombatState")!.SetValue(player, pcs);
    Begin("monster");
    object monster, enemy;
    if (encounter != null)
    {
        foreach (object pair in (System.Collections.IEnumerable)encounter.GetType().GetProperty("MonstersWithSlots")!.GetValue(encounter)!)
        {
            object m = pair.GetType().GetField("Item1")!.GetValue(pair)!;
            object? slot = pair.GetType().GetField("Item2")!.GetValue(pair);
            object e = combat.GetType().GetMethod("CreateCreature")!.Invoke(combat, [m, Enum.Parse(Get("Combat.CombatSide"), "Enemy"), slot])!;
            combat.GetType().GetMethod("AddCreature")!.Invoke(combat, [e]);
        }
        enemy = ((System.Collections.IEnumerable)combat.GetType().GetProperty("Enemies")!.GetValue(combat)!).Cast<object>().First();
        monster = enemy.GetType().GetProperty("Monster")!.GetValue(enemy)!;
    }
    else
    {
        monster = db.GetMethods().Single(m => m.Name == "Monster" && m.IsGenericMethodDefinition).MakeGenericMethod(Get("Models.Monsters.Chomper")).Invoke(null, null)!;
        monster = monster.GetType().GetMethod("ToMutable")!.Invoke(monster, null)!;
        enemy = combat.GetType().GetMethod("CreateCreature")!.Invoke(combat, [monster, Enum.Parse(Get("Combat.CombatSide"), "Enemy"), null])!;
        combat.GetType().GetMethod("AddCreature")!.Invoke(combat, [enemy]);
    }
    if (setupProbe || openingProbe)
    {
        Begin("native_combat_setup");
        Console.WriteLine(JsonSerializer.Serialize(NativeSetupProbe.Run(Get, combat, player, enemy, openingProbe)));
        if (openingProbe)
        {
            Begin("native_opening_root_capture");
            PackedLocalization.Configure(Get, Path.Combine(root, "SlayTheSpire2.pck"));
            Assembly openingSolver = AssemblyLoadContext.Default.LoadFromAssemblyPath(solverPath);
            openingSolver.GetType("CombatSolver.Entry", true)!.GetProperty("Logger")!.SetValue(null,
                Activator.CreateInstance(Get("Logging.Logger"), ["StandaloneProbe", Enum.Parse(Get("Logging.LogType"), "Generic")]));
            object openingRoot = openingSolver.GetType("CombatSolver.CombatRootSnapshot", true)!.GetMethod("Capture")!.Invoke(null, [combat])!;
            openingRoot.GetType().GetMethod("ForkSimulator")!.Invoke(openingRoot, null);
            Console.WriteLine(JsonSerializer.Serialize(new { status = "native_opening_root_captured", productionReady = false }));
            if (actionProbe)
            {
                Begin("managed_host_clock");
                HostClock.Configure(data);
                Begin("native_action_comparison");
                Console.WriteLine(JsonSerializer.Serialize(NativeActionProbe.Run(Get, openingSolver, openingRoot, combat, player, enemy,
                    encounterProbe ? ["STRIKE_SILENT", "DEFEND_SILENT", "STRIKE_SILENT"] : ["STRIKE_SILENT", "DEFEND_SILENT", "NEUTRALIZE"], nativeRoundProbe, nativeBattleProbe, nativeWinProbe)));
            }
            if (teacherBattleProbe)
            {
                HostClock.Configure(data);
                Console.WriteLine(JsonSerializer.Serialize(TeacherBattleProbe.Run(Get, openingSolver, combat, player, continuationProbe)));
            }
            if (teacherProbe && !teacherBattleProbe)
            {
                Begin("teacher_search");
                object beam = RoundProbe.CreateBeam(openingSolver, openingRoot);
                var watch = System.Diagnostics.Stopwatch.StartNew();
                object result = beam.GetType().GetMethod("Solve")!.Invoke(beam, null)!;
                watch.Stop();
                object Field(string name) => result.GetType().GetProperty(name)!.GetValue(result)!;
                if (Field("SearchPhase").ToString() != "Short" || (bool)Field("DeepSearchTriggered") || Convert.ToInt32(Field("ExpandedNodes")) <= 0)
                    throw new InvalidOperationException("Teacher search did not complete a nonempty short-only search.");
                Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_search_passed", productionReady = false,
                    productionLabels = false, scope = "one search on starter A0 opening; no plan deployment or terminal label",
                    elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, phase = Field("SearchPhase").ToString(),
                    expandedNodes = Field("ExpandedNodes"), transitions = Field("TransitionCount"),
                    policy = new { softBudgetMilliseconds = 8000, beamWidth = 24, maxExpandedNodes = 2400, maxCardBranchesPerNode = 20, dop = 1, potions = "Disabled", shortOnly = true },
                    predictedSnapshot = JsonSerializer.SerializeToElement(Field("Snapshot")) }));
                if (teacherDeployProbe)
                {
                    HostClock.Configure(data);
                    Console.WriteLine(JsonSerializer.Serialize(TeacherDeploymentProbe.Run(Get, openingSolver, result, combat, player)));
                }
            }
        }
        return;
    }
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
