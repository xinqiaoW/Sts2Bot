using System.Reflection;
using System.Text.Json;

internal static class TeacherBattleProbe
{
    private static object Read(object o, string n) => o.GetType().GetProperty(n)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    public static object Run(Func<string, Type> get, Assembly solver, object combat, object player, bool reuseContinuations = false, bool nativeTurnLoop = false, Task? nativeTerminal = null, bool injectExhaustedPlanOnce = false, bool injectDeploymentDriftOnce = false, bool injectMissingCardOnce = false, bool injectUnconsumedChoiceOnce = false, object? openingResult = null)
    {
        object cm = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        object pcs = Read(player, "PlayerCombatState"), hero = Read(player, "Creature");
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var trace = new List<object>();
        int choices = 0, boundaryChoices = 0, searches = 0, reusedTurns = 0, rejectedContinuations = 0, negativeChecks = 0;
        object? source = null;
        bool sourceOpeningSetupConsumed = openingResult != null;
        Type tracker = solver.GetType("CombatSolver.BattleDamageTracker", true)!;
        Type stampType = solver.GetType("CombatSolver.ContinuationStamp", true)!;
        if (openingResult == null) tracker.GetMethod("Begin")!.Invoke(null, [combat]);
        double searchMs = openingResult == null ? 0 : ((TimeSpan)Read(openingResult, "Elapsed")).TotalMilliseconds, deploymentMs = 0;
        if (openingResult != null) searches++;
        int exhaustedPlanReplans = 0, deploymentDriftReplans = 0;
        bool injectedDeploymentDrift = false, injectedMissingCard = false, injectedUnconsumedChoice = false;
        bool injectedExhaustedPlan = false;
        while ((bool)Read(cm, "IsInProgress"))
        {
            if (watch.Elapsed.TotalSeconds > 120) throw new TimeoutException("Battle exceeded 120 seconds.");
            int turnNumber = Convert.ToInt32(Read(pcs, "TurnNumber"));
            object damage = tracker.GetMethod("Observe")!.Invoke(null, [combat])!;
            bool openingSetupAlreadyConsumed = openingResult != null;
            object? result = openingResult;
            if (result != null)
            {
                source = Read(result, "ResultScope").ToString() == "CurrentTurnAdoption" ? null : result;
                openingResult = null;
            }
            bool reused = false;
            if (result == null && reuseContinuations && source != null)
            {
                object actual = stampType.GetMethod("CaptureLive")!.Invoke(null, [combat])!;
                MethodInfo continuation = source.GetType().GetMethod("TryCreateContinuation")!;
                object?[] args = [actual, Read(hero, "CurrentHp"), damage, null];
                reused = (bool)continuation.Invoke(source, args)!;
                if (reused)
                {
                    result = args[3]!;
                    // Original SolverResult continuations retain the root's
                    // TurnSetupChoices even after those choices were consumed.
                    openingSetupAlreadyConsumed = sourceOpeningSetupConsumed;
                    reusedTurns++;
                    object wrong = Activator.CreateInstance(stampType, [Read(actual, "StateText") + ";deliberate_invalid_state=1"])!;
                    object?[] bad = [wrong, Read(hero, "CurrentHp"), damage, null];
                    if ((bool)continuation.Invoke(source, bad)! || bad[3] != null)
                        throw new InvalidOperationException("Continuation accepted altered state.");
                    negativeChecks++;
                }
                else rejectedContinuations++;
            }
            var search = System.Diagnostics.Stopwatch.StartNew();
            if (result == null)
            {
                object root = solver.GetType("CombatSolver.CombatRootSnapshot", true)!.GetMethod("Capture")!.Invoke(null, [combat])!;
                object beam = RoundProbe.CreateBeam(solver, root, damage);
                result = beam.GetType().GetMethod("Solve")!.Invoke(beam, null)!;
                searches++;
                if (Read(result, "SearchPhase").ToString() != "Short" || (bool)Read(result, "DeepSearchTriggered"))
                    throw new InvalidOperationException("Unexpected teacher policy.");
                source = Read(result, "ResultScope").ToString() == "CurrentTurnAdoption" ? null : result;
                sourceOpeningSetupConsumed = false;
            }
            search.Stop();
            searchMs += search.Elapsed.TotalMilliseconds;
            Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_search_metrics", turn = turnNumber, reused,
                expandedNodes = Read(result, "ExpandedNodes"), transitions = Read(result, "TransitionCount"),
                boundary = Read(result, "BoundaryReason").ToString(), elapsedMilliseconds = ((TimeSpan)Read(result, "Elapsed")).TotalMilliseconds,
                predictedHp = Read(Read(result, "Snapshot"), "PlayerHp") }));
            // Diagnostic-only injection: discard one searched route without changing live game state.
            if (injectExhaustedPlanOnce && !injectedExhaustedPlan)
            {
                object selected = Read(result, "BestNode");
                object empty = Array.CreateInstance(solver.GetType("CombatSolver.PlanAction", true)!, 0);
                object replacement = Activator.CreateInstance(selected.GetType(), [empty, 0, Read(selected, "Score")])!;
                result.GetType().GetProperty("BestNode")!.SetValue(result, replacement);
                injectedExhaustedPlan = true;
            }
            if (injectDeploymentDriftOnce && !injectedDeploymentDrift)
            {
                object action = Items(Read(Read(result, "BestNode"), "Actions")).First(a =>
                    Convert.ToInt32(Read(a, "Turn")) == turnNumber && Read(a, "Kind").ToString() == "PlayCard"
                    && a.GetType().GetProperty("TargetCombatId")!.GetValue(a) != null);
                action.GetType().GetProperty("TargetCombatId")!.SetValue(action, Read(hero, "CombatId"));
                injectedDeploymentDrift = true;
            }
            if (injectMissingCardOnce && !injectedMissingCard)
            {
                object action = Items(Read(Read(result, "BestNode"), "Actions")).Where(a =>
                    Convert.ToInt32(Read(a, "Turn")) == turnNumber && Read(a, "Kind").ToString() == "PlayCard").Skip(1).First();
                action.GetType().GetProperty("CardStateKey")!.SetValue(action, "deliberate_missing_card_state");
                injectedMissingCard = true;
            }
            if (injectUnconsumedChoiceOnce && !injectedUnconsumedChoice)
            {
                object action = Items(Read(Read(result, "BestNode"), "Actions")).First(a =>
                    Convert.ToInt32(Read(a, "Turn")) == turnNumber && Read(a, "Kind").ToString() == "PlayCard"
                    && Items(a.GetType().GetMethod("GetActionChoicesInExecutionOrder")!.Invoke(a, null)!).Length == 0);
                Type choiceType = solver.GetType("CombatSolver.PlanCardChoice", true)!;
                object choice = JsonSerializer.Deserialize(JsonSerializer.Serialize(new {
                    Effect = Convert.ToInt32(Enum.Parse(choiceType.GetProperty("Effect")!.PropertyType, "Discard")),
                    SourcePile = Convert.ToInt32(Enum.Parse(choiceType.GetProperty("SourcePile")!.PropertyType, "Hand")),
                    Cards = new[] { new { CardId = "DIAGNOSTIC_MISSING_CARD", UpgradeLevel = 0, StateKey = "",
                        SourceOccurrence = 0, OptionOccurrence = 0, Title = "diagnostic" } }
                }), choiceType)!;
                Array extra = Array.CreateInstance(choiceType, 1); extra.SetValue(choice, 0);
                action.GetType().GetProperty("NestedChoices")!.SetValue(action, extra);
                injectedUnconsumedChoice = true;
            }
            tracker.GetMethod("RegisterPlan")!.Invoke(null, [combat, result]);
            object deployed = TeacherDeploymentProbe.Run(get, solver, result, combat, player, allowEmpty: true,
                openingSetupAlreadyConsumed: openingSetupAlreadyConsumed);
            JsonElement deployment = JsonSerializer.SerializeToElement(deployed);
            deploymentMs += deployment.GetProperty("elapsedMilliseconds").GetDouble();
            foreach (JsonElement step in deployment.GetProperty("trace").EnumerateArray())
            {
                JsonElement action = step.GetProperty("action");
                if (action.GetProperty("Choice").ValueKind != JsonValueKind.Null) choices++;
                if (action.GetProperty("NestedChoices").ValueKind == JsonValueKind.Array) choices += action.GetProperty("NestedChoices").GetArrayLength();
            }
            if (deployment.GetProperty("status").GetString() == "teacher_deployment_drift")
            {
                source = null;
                deploymentDriftReplans++;
                trace.Add(new { turn = turnNumber, reused, reason = deployment.GetProperty("reason").GetString(), deployment });
                Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_deployment_drift_replan", turn = turnNumber, reason = deployment.GetProperty("reason").GetString(),
                    executedActions = deployment.GetProperty("actionCount").GetInt32() }));
                continue;
            }
            ((Task)cm.GetType().GetMethod("CheckWinCondition", Type.EmptyTypes)!.Invoke(cm, null)!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            trace.Add(new { turn = turnNumber, reused, battleDamage = JsonSerializer.SerializeToElement(damage), searchMilliseconds = search.Elapsed.TotalMilliseconds, deployment });
            Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_turn_completed", turn = turnNumber, hp = Read(hero, "CurrentHp") }));
            if (!(bool)Read(cm, "IsInProgress")) break;
            if (!Items(Read(Read(result, "BestNode"), "Actions")).Any(a =>
                Convert.ToInt32(Read(a, "Turn")) == turnNumber && Read(a, "Kind").ToString() == "EndTurn"))
            {
                // Pinned SolverController clears its continuation and searches from the current
                // live state when deployment exhausts a route without an EndTurn boundary.
                source = null;
                exhaustedPlanReplans++;
                Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_plan_exhausted_replan", turn = turnNumber,
                    executedActions = deployment.GetProperty("actionCount").GetInt32() }));
                continue;
            }
            if (nativeTurnLoop)
            {
                // The searched next-turn choices become irrelevant if an enemy
                // dies to poison before that turn. Replay only permits this
                // at its final recorded boundary and checks the native terminal.
                boundaryChoices += RequestBattleProbe.AdvanceTurn(get, solver, cm, player, result, turnNumber,
                    requireAllRecordedChoices: false, nativeTerminal: nativeTerminal);
                continue;
            }
            object turn = cm.GetType().GetField("_turnState", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(cm)!;
            Task end = (Task)cm.GetType().GetMethod("AwaitTurnEndAndSwitchSides", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn])!;
            cm.GetType().GetMethod("SetReadyToEndTurn")!.Invoke(cm, [player, false, null]);
            end.WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            Task Start() => (Task)cm.GetType().GetMethod("StartTurn", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(cm, [turn, null])!;
            if ((bool)Read(cm, "IsInProgress")) Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if ((bool)Read(cm, "IsInProgress")) Start().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
            if ((bool)Read(cm, "IsInProgress") && Convert.ToInt32(Read(pcs, "TurnNumber")) != turnNumber + 1)
                throw new InvalidOperationException("Native turn failed to advance.");
        }
        if ((bool)Read(cm, "IsInProgress")) throw new InvalidOperationException("No native terminal outcome.");
        if (nativeTurnLoop)
        {
            // CombatEnded is raised after victory hooks and room finalization; the turn loop may still await an input signal.
            (nativeTerminal ?? throw new InvalidOperationException("Missing native completion event."))
                .WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        }
        int hp = Convert.ToInt32(Read(hero, "CurrentHp"));
        bool enemiesDead = Items(Read(combat, "Enemies")).All(e => Convert.ToInt32(Read(e, "CurrentHp")) <= 0);
        bool roomCompleted = (bool)Read(Read(Read(combat, "RunState"), "CurrentRoom"), "IsPreFinished");
        if (hp > 0 && (!enemiesDead || !roomCompleted)) throw new InvalidOperationException("Invalid native victory.");
        return new { status = "teacher_battle_completed", productionReady = false, productionLabels = false,
            policy = reuseContinuations ? "original TryCreateContinuation with exact native stamp; short-only search on miss" : "fresh short-only search each native player turn",
            searches, reusedTurns, rejectedContinuations, negativeChecks, exhaustedPlanReplans, injectedExhaustedPlan, deploymentDriftReplans, injectedDeploymentDrift, injectedMissingCard, injectedUnconsumedChoice,
            outcome = hp > 0 ? "win" : "loss", finalHp = hp, roomCompleted, choicesConsumed = choices, boundaryChoicesConsumed = boundaryChoices,
            elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, searchMilliseconds = searchMs, deploymentMilliseconds = deploymentMs, trace };
    }
}
