using System.Reflection;
using System.Text.Json;

internal static class RequestBattleProbe
{
    private static object Read(object o, string n) => o.GetType().GetProperty(n)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    public static void WaitForPlayerTurn(object cm, object player, int previousTurn, NativePlayerTurnBarrier barrier)
    {
        var watch = System.Diagnostics.Stopwatch.StartNew();
        while (true)
        {
            Task? loop = (Task?)cm.GetType().GetField("_turnLoopTask", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(cm);
            if (loop is { IsFaulted: true }) loop.GetAwaiter().GetResult();
            bool starting = (bool)Read(cm, "IsStarting"), active = (bool)Read(cm, "IsInProgress");
            if (!starting && !active) return;
            object pcs = Read(player, "PlayerCombatState");
            if (!starting && Convert.ToInt32(Read(pcs, "TurnNumber")) > previousTurn && Read(pcs, "Phase").ToString() == "Play" && barrier.IsSignaled)
            {
                object manager = cm.GetType().Assembly.GetType("MegaCrit.Sts2.Core.Runs.RunManager", true)!
                    .GetProperty("Instance")!.GetValue(null)!;
                object executor = Read(manager, "ActionExecutor");
                ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!)
                    .WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
                return;
            }
            if (watch.Elapsed.TotalSeconds > 10) throw new TimeoutException("Native combat loop did not reach playable turn.");
            Thread.Sleep(1);
        }
    }
    public static int AdvanceTurn(Func<string, Type> get, Assembly solver, object cm, object player, object result, int turn, bool requireAllRecordedChoices = true, Task? nativeTerminal = null)
    {
        object? boundary = Items(Read(Read(result, "BestNode"), "Actions")).FirstOrDefault(a =>
            Convert.ToInt32(Read(a, "Turn")) == turn && Read(a, "Kind").ToString() == "EndTurn");
        if (boundary == null) throw new InvalidOperationException("Teacher plan has no EndTurn boundary; must replan before ending turn.");
        object? choices = boundary.GetType().GetProperty("TurnStartChoices")!.GetValue(boundary);
        choices ??= Array.CreateInstance(solver.GetType("CombatSolver.PlanCardChoice", true)!, 0);
        Type selectorType = solver.GetType("CombatSolver.PlannedCardSelector", true)!;
        object selector = Activator.CreateInstance(selectorType, [choices])!;
        selectorType.GetMethod("CaptureBefore")!.Invoke(selector, [player]);
        using var implicitChoices = new NativeImplicitChoiceObserver(get, solver, selector, player);
        MethodInfo push = get("Commands.CardSelectCmd").GetMethod("PushSelector")!;
        object?[] args = push.GetParameters().Select((parameter, index) => index == 0 ? selector : parameter.Name == "localOnly" ? true : parameter.HasDefaultValue ? parameter.DefaultValue : throw new InvalidOperationException("Unknown selector parameter.")).ToArray();
        using IDisposable scope = (IDisposable)push.Invoke(null, args)!;
        using var barrier = new NativePlayerTurnBarrier(cm);
        cm.GetType().GetMethod("SetReadyToEndTurn")!.Invoke(cm, [player, false, null]);
        WaitForPlayerTurn(cm, player, turn, barrier);
        if (!(bool)Read(cm, "IsInProgress"))
            nativeTerminal?.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        implicitChoices.AssertValid();
        selectorType.GetMethod("ReconcileImplicitChoices")!.Invoke(selector, [player]);
        bool terminalPlanCancelled = !requireAllRecordedChoices && !(bool)Read(cm, "IsInProgress");
        if (!terminalPlanCancelled) selectorType.GetMethod("AssertConsumed")!.Invoke(selector, null);
        int count = Items(choices).Length;
        int consumed = (int)selectorType.GetField("_index", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(selector)!;
        Console.WriteLine(JsonSerializer.Serialize(new { status = "native_boundary_choices_consumed", turn, count,
            consumed, cancelledAfterTerminal = terminalPlanCancelled ? count - consumed : 0,
            choices = JsonSerializer.SerializeToElement(choices) }));
        return consumed;
    }
    public static object Run(Func<string, Type> get, Assembly solver, object run, object player, JsonElement fixture, bool compareHistorical = true, bool nativeReplay = false, bool injectExhaustedPlanOnce = false, bool injectDeploymentDriftOnce = false, bool injectMissingCardOnce = false, bool injectUnconsumedChoiceOnce = false)
    {
        object manager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        object encounter = Items(get("Models.ModelDb").GetProperty("AllEncounters")!.GetValue(null)!).Single(e => Read(Read(e, "Id"), "Entry").ToString() == fixture.GetProperty("request").GetProperty("encounterId").GetString());
        encounter = encounter.GetType().GetMethod("ToMutable")!.Invoke(encounter, null)!;
        solver.GetType("CombatSolver.Entry", true)!.GetProperty("Logger")!.SetValue(null,
            Activator.CreateInstance(get("Logging.Logger"), ["StandaloneRequest", Enum.Parse(get("Logging.LogType"), "Generic") ]));
        object cm = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        using var rewards = new NativeCombatRewards(get, solver, cm);
        var ended = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        EventInfo endedEvent = cm.GetType().GetEvent("CombatEnded")!;
        Type handlerType = endedEvent.EventHandlerType!;
        var parameters = handlerType.GetMethod("Invoke")!.GetParameters().Select(p => System.Linq.Expressions.Expression.Parameter(p.ParameterType)).ToArray();
        object? endedCombat = null;
        Action<object> complete = room => { endedCombat = Read(room, "CombatState"); ended.TrySetResult(); };
        Delegate handler = System.Linq.Expressions.Expression.Lambda(handlerType,
            System.Linq.Expressions.Expression.Call(System.Linq.Expressions.Expression.Constant(complete), typeof(Action<object>).GetMethod("Invoke")!,
                System.Linq.Expressions.Expression.Convert(parameters.Single(), typeof(object))), parameters).Compile();
        endedEvent.AddEventHandler(cm, handler);
        Console.WriteLine("{\"stage\":\"request_enter_combat_room\"}");
        // Toolbox and similar opening hooks choose before the first playable turn.
        // Install the recorded selector before entering the room, so the original
        // hook generates its options and applies exactly the native selection.
        object? openingSelector = null;
        IDisposable? openingScope = null;
        NativeImplicitChoiceObserver? openingImplicitChoices = null;
        OpeningChoiceSearch? openingSearch = nativeReplay ? null : new OpeningChoiceSearch(get, solver, player);
        object? openingResult = null;
        try
        {
            if (nativeReplay)
            {
                JsonElement[] openingChoices = fixture.GetProperty("nativeTrace").GetProperty("events")
                    .EnumerateArray().TakeWhile(e => e.GetProperty("kind").GetString() is not ("play" or "end_turn"))
                    .Where(e => e.GetProperty("kind").GetString() == "choice_plan"
                        && e.GetProperty("value").GetProperty("owner").GetString() == "turn_setup:1")
                    .SelectMany(e => e.GetProperty("value").GetProperty("choices").EnumerateArray()).ToArray();
                if (openingChoices.Length > 0)
                {
                    Type choiceType = solver.GetType("CombatSolver.PlanCardChoice", true)!;
                    Array choices = Array.CreateInstance(choiceType, openingChoices.Length);
                    for (int i = 0; i < choices.Length; i++)
                        choices.SetValue(JsonSerializer.Deserialize(openingChoices[i], choiceType), i);
                    openingSelector = Activator.CreateInstance(solver.GetType("CombatSolver.PlannedCardSelector", true)!, [choices])!;
                    openingImplicitChoices = new NativeImplicitChoiceObserver(get, solver, openingSelector, player);
                    MethodInfo push = get("Commands.CardSelectCmd").GetMethod("PushSelector")!;
                    object?[] selectorArgs = push.GetParameters().Select((parameter, index) => index == 0 ? openingSelector
                        : parameter.Name == "localOnly" ? true : parameter.HasDefaultValue ? parameter.DefaultValue : throw new InvalidOperationException("Unknown selector parameter.")).ToArray();
                    openingScope = (IDisposable)push.Invoke(null, selectorArgs)!;
                }
            }
            using var barrier = new NativePlayerTurnBarrier(cm);
            Task entering = (Task)manager.GetType().GetMethod("EnterRoomDebug")!.Invoke(manager,
                [Read(encounter, "RoomType"), Enum.Parse(get("Map.MapPointType"), "Unassigned"), encounter, false])!;
            entering.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
            WaitForPlayerTurn(cm, player, 0, barrier);
            openingSearch?.AssertConsumed();
            openingResult = openingSearch?.Result;
            if (openingSelector != null)
            {
                openingImplicitChoices!.AssertValid();
                openingSelector.GetType().GetMethod("ReconcileImplicitChoices")!.Invoke(openingSelector, [player]);
                openingSelector.GetType().GetMethod("AssertConsumed")!.Invoke(openingSelector, null);
                Console.WriteLine("{\"status\":\"native_opening_choices_consumed\"}");
            }
        }
        finally { openingScope?.Dispose(); openingImplicitChoices?.Dispose(); openingSearch?.Dispose(); }
        bool openingTerminal = !(bool)Read(cm, "IsInProgress");
        if (openingTerminal) ended.Task.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        object combat = openingTerminal ? endedCombat ?? throw new InvalidOperationException("Opening terminal has no native combat state.")
            : cm.GetType().GetMethod("DebugOnlyGetState")!.Invoke(cm, null)!;
        // Retain the actual combat state: room cleanup may detach it from player.
        object playerCombatState = Read(player, "PlayerCombatState");
        Console.WriteLine(JsonSerializer.Serialize(new { status = "request_native_opening", productionReady = false,
            stamp = Read(solver.GetType("CombatSolver.ContinuationStamp", true)!.GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText") }));
        object battle = nativeReplay ? NativeTraceReplay.Run(get, solver, combat, player, ended.Task, fixture.GetProperty("nativeTrace"), rewards, openingTerminal)
            : openingTerminal ? new { status = "native_opening_terminal", openingTerminal = true }
            : TeacherBattleProbe.Run(get, solver, combat, player, reuseContinuations: true, nativeTurnLoop: true, nativeTerminal: ended.Task, injectExhaustedPlanOnce: injectExhaustedPlanOnce, injectDeploymentDriftOnce: injectDeploymentDriftOnce, injectMissingCardOnce: injectMissingCardOnce, injectUnconsumedChoiceOnce: injectUnconsumedChoiceOnce, openingResult: openingResult, nativeRewards: rewards);
        rewards.Wait();
        endedEvent.RemoveEventHandler(cm, handler);
        object hero = Read(player, "Creature");
        int hp = Convert.ToInt32(Read(hero, "CurrentHp")), maxHp = Convert.ToInt32(Read(hero, "MaxHp"));
        if (!ReferenceEquals(endedCombat, combat))
            throw new InvalidOperationException("Missing native completion event for this combat.");
        if (hp > 0) rewards.AssertVictory(combat);
        int finishedTurn = Convert.ToInt32(Read(playerCombatState, "TurnNumber"));
        string finalCombatState = (string)Read(solver.GetType("CombatSolver.ContinuationStamp", true)!
            .GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText");
        DateTimeOffset finishedAtUtc = DateTimeOffset.UtcNow;
        bool? historicalTerminalMatched = null;
        if (compareHistorical)
        {
        JsonElement expected = fixture.GetProperty("expected");
        historicalTerminalMatched = hp == expected.GetProperty("finalHp").GetInt32()
            && maxHp == expected.GetProperty("finalMaxHp").GetInt32()
            && (hp <= 0) == expected.GetProperty("playerDied").GetBoolean()
            && expected.GetProperty("initialHp").GetInt32() - hp == expected.GetProperty("netHpLoss").GetInt32();
        }
        return new { status = "request_battle_completed", productionReady = false, productionLabels = false,
            attemptId = fixture.GetProperty("attemptId").GetInt32(), historicalTerminalMatched,
            finalHp = hp, finalMaxHp = maxHp, finishedTurn, finishedAtUtc, finalCombatState, openingTerminal, battle };
    }
}
