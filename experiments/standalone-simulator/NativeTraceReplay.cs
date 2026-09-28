using System.Reflection;
using System.Text.Json;

internal static class NativeTraceReplay
{
    private sealed record Node(object Actions);
    private sealed record Result(object BestNode, object TurnSetupChoices);
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;
    public static object Run(Func<string, Type> get, Assembly solver, object combat, object player, Task terminal, JsonElement recording, NativeCombatRewards rewards)
    {
        JsonElement nativeResult = recording.GetProperty("result");
        if (nativeResult.GetProperty("status").GetString() != "Passed" || !nativeResult.GetProperty("combatEnded").GetBoolean())
            throw new InvalidOperationException("Native trace must have a complete terminal result.");
        object cm = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        object pcs = Read(player, "PlayerCombatState"), hero = Read(player, "Creature");
        Type actionType = solver.GetType("CombatSolver.PlanAction", true)!;
        object emptyChoices = Array.CreateInstance(solver.GetType("CombatSolver.PlanCardChoice", true)!, 0);
        string Live() => (string)Read(solver.GetType("CombatSolver.ContinuationStamp", true)!.GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText");
        using var cleanup = new TerminalCleanupObservation(cm.GetType(), Live);
        int terminalCleanupBoundaryComparisons = 0, terminalRewardBoundaryComparisons = 0;
        var compared = new List<object>();
        void Compare(string expected, string point, bool finalActionCompletion = false)
        {
            if (finalActionCompletion && !(bool)Read(cm, "IsInProgress"))
            {
                terminal.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
                rewards.Wait();
            }
            string actual = Live();
            string observedAfterCleanup = actual;
            bool usedTerminalCleanupBoundary = false, usedTerminalRewardBoundary = false;
            if (expected != actual && finalActionCompletion && cleanup.Captures == 1
                && cleanup.Stamp == expected && !(bool)Read(cm, "IsInProgress"))
            {
                // Native async producer observation can precede EndCombatInternal's cleanup,
                // while the synchronous host queue wait already includes that cleanup.
                // Compare the complete stamp at the same original method boundary, never
                // strip differing fields or accept a merely matching terminal HP.
                terminal.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
                actual = cleanup.Stamp;
                usedTerminalCleanupBoundary = true;
                terminalCleanupBoundaryComparisons++;
            }
            if (expected != actual && finalActionCompletion && rewards.Generations == 1
                && rewards.BeforeGenerationStamp == expected && !(bool)Read(cm, "IsInProgress"))
            {
                // Native presentation may start reward generation before or after
                // the final producer stamp. Compare the exact original boundary,
                // retaining every field and both the actual observed states.
                actual = rewards.BeforeGenerationStamp;
                usedTerminalRewardBoundary = true;
                terminalRewardBoundaryComparisons++;
            }
            bool matches = expected == actual;
            compared.Add(new { point, matches, expected, actual, usedTerminalCleanupBoundary, usedTerminalRewardBoundary,
                observedAfterCleanup = usedTerminalCleanupBoundary ? observedAfterCleanup : null,
                observedAfterRewards = usedTerminalRewardBoundary ? observedAfterCleanup : null });
            if (!matches)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { status = "native_replay_mismatch", point, expected, actual }));
                throw new InvalidOperationException("Cross-runtime state differs at " + point);
            }
        }
        JsonElement endChoices = JsonSerializer.SerializeToElement(Array.Empty<object>());
        int plays = 0, boundaries = 0, completions = 0, terminalBoundaryChoiceCancellations = 0;
        bool pendingPlay = false;
        long sequence = 0;
        JsonElement[] events = recording.GetProperty("events").EnumerateArray().ToArray();
        if (events.Length == 0 || events[0].GetProperty("kind").GetString() != "initialized")
            throw new InvalidOperationException("Native trace initialization is missing.");
        for (int index = 0; index < events.Length; index++)
        {
            JsonElement item = events[index];
            long current = item.GetProperty("sequence").GetInt64();
            if (current != ++sequence) throw new InvalidOperationException("Native trace sequence is incomplete.");
            string kind = item.GetProperty("kind").GetString()!;
            JsonElement value = item.GetProperty("value");
            switch (kind)
            {
                case "initialized":
                    if (sequence != 1 || !NativeTraceIdentity.IsReviewedCollector(value.GetProperty("collectorSha256").GetString()))
                        throw new InvalidOperationException("Native trace identity mismatch.");
                    break;
                case "choice_plan":
                    string owner = value.GetProperty("owner").GetString()!;
                    if (owner.StartsWith("deployment_end_turn:")) endChoices = value.GetProperty("choices");
                    else if (owner.StartsWith("turn_setup:"))
                    {
                        if (owner != "turn_setup:" + Read(pcs, "TurnNumber"))
                            throw new InvalidOperationException("Unexpected turn setup choice owner.");
                    }
                    else if (!owner.StartsWith("deployment:") && value.GetProperty("choices").GetArrayLength() != 0)
                        throw new NotSupportedException("Unsupported native choice owner: " + owner);
                    break;
                case "play":
                    if (pendingPlay) throw new InvalidOperationException("Missing native action completion.");
                    Compare(value.GetProperty("before").GetString()!, "before_play_" + plays);
                    object action = JsonSerializer.Deserialize(value.GetProperty("action"), actionType)!;
                    var result = new Result(new Node(new[] { action }), emptyChoices);
                    cleanup.BeginAction();
                    JsonElement deployed = JsonSerializer.SerializeToElement(TeacherDeploymentProbe.Run(get, solver, result, combat, player));
                    if (deployed.GetProperty("status").GetString() != "teacher_opening_deployed")
                    {
                        // Native shutdown may cancel a now-unused choice plan after
                        // the final action itself has killed the enemy. Accept only
                        // the recorded terminal-without-post-stamp case, after this
                        // exact action completed and the original terminal event fired.
                        bool finalChoiceCancellation = index == events.Length - 1
                            && deployed.GetProperty("status").GetString() == "teacher_deployment_drift"
                            && deployed.GetProperty("reason").GetString() == "choice_plan_unconsumed"
                            && deployed.GetProperty("actionCount").GetInt32() == 1;
                        if (!finalChoiceCancellation)
                        {
                            Console.WriteLine(JsonSerializer.Serialize(new { status = "native_replay_deployment_failed", deployed }));
                            throw new InvalidOperationException("Recorded native action cannot be deployed.");
                        }
                        terminal.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
                        if ((bool)Read(cm, "IsInProgress"))
                            throw new InvalidOperationException("Unconsumed recorded choice before terminal.");
                        Console.WriteLine("{\"status\":\"native_terminal_choice_plan_cancelled\"}");
                    }
                    plays++; pendingPlay = true;
                    break;
                case "action_completed":
                    if (!pendingPlay) throw new InvalidOperationException("Unexpected native action completion.");
                    Compare(value.GetProperty("after").GetString()!, "after_play_" + (plays - 1), index == events.Length - 1);
                    pendingPlay = false; completions++;
                    break;
                case "end_turn":
                    if (pendingPlay) throw new InvalidOperationException("Missing native action completion before end turn.");
                    Compare(value.GetProperty("before").GetString()!, "end_turn_" + boundaries);
                    int turn = Convert.ToInt32(Read(pcs, "TurnNumber"));
                    var recordedChoices = endChoices.EnumerateArray().ToList();
                    // These choices were observed after native enemy execution, before the next play.
                    // Supplying them to the replay selector does not search or choose a new route.
                    foreach (JsonElement future in events.Skip(index + 1).TakeWhile(e => e.GetProperty("kind").GetString() != "play" && e.GetProperty("kind").GetString() != "end_turn"))
                        if (future.GetProperty("kind").GetString() == "choice_plan"
                            && future.GetProperty("value").GetProperty("owner").GetString() == "turn_setup:" + (turn + 1))
                            recordedChoices.AddRange(future.GetProperty("value").GetProperty("choices").EnumerateArray());
                    object boundary = JsonSerializer.Deserialize(JsonSerializer.Serialize(new {
                        Kind = Convert.ToInt32(Enum.Parse(solver.GetType("CombatSolver.PlanActionKind", true)!, "EndTurn")),
                        Turn = turn, TurnStartChoices = recordedChoices }), actionType)!;
                    // The recorder logs the planned enemy/next-turn selections
                    // before ending turn. Death can cancel them without a choice
                    // being requested. Only the final recorded boundary may do
                    // this, after the original CombatEnded event has completed.
                    // Turn setup plans are recorded after the end-turn event.
                    // A Sly auto-play in the first setup choice can kill the last
                    // enemy and cancel a later setup choice (e.g. Toasty Mittens).
                    // Such trailing plans do not constitute a later action.
                    bool finalBoundary = events.Skip(index + 1).All(e =>
                        e.GetProperty("kind").GetString() == "choice_plan"
                        && e.GetProperty("value").GetProperty("owner").GetString() == "turn_setup:" + (turn + 1));
                    int consumed = RequestBattleProbe.AdvanceTurn(get, solver, cm, player,
                        new Result(new Node(new[] { boundary }), emptyChoices), turn,
                        requireAllRecordedChoices: !finalBoundary, nativeTerminal: terminal);
                    if (finalBoundary) terminalBoundaryChoiceCancellations = recordedChoices.Count - consumed;
                    endChoices = JsonSerializer.SerializeToElement(Array.Empty<object>()); boundaries++;
                    break;
                default: throw new InvalidOperationException("Unsupported or failed native trace event: " + kind);
            }
        }
        // A lethal turn-start hook can finish its choice action before the turn
        // loop publishes CombatEnded. Await the original terminal event first.
        terminal.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        rewards.Wait();
        // Opening auto-plays and poison/relic effects can win a battle whose
        // recorded player actions consist solely of ending turns. Those are
        // real actions; require an observed action, not a manually played card.
        if (plays + boundaries == 0 || plays - completions != (pendingPlay ? 1 : 0) || (bool)Read(cm, "IsInProgress"))
            throw new InvalidOperationException("Native trace did not replay a complete battle.");
        JsonElement observation = nativeResult.GetProperty("trainingObservation");
        int hp = Convert.ToInt32(Read(hero, "CurrentHp")), maxHp = Convert.ToInt32(Read(hero, "MaxHp"));
        int finishedTurn = Convert.ToInt32(Read(pcs, "TurnNumber"));
        if (finishedTurn != nativeResult.GetProperty("finishedTurn").GetInt32())
            throw new InvalidOperationException("Native fixed-action terminal turn differs.");
        if (hp != observation.GetProperty("finalHp").GetInt32() || maxHp != observation.GetProperty("finalMaxHp").GetInt32())
            throw new InvalidOperationException("Native fixed-action terminal differs.");
        return new { status = "native_fixed_action_replay_matched", productionReady = false, productionLabels = false,
            plays, boundaries, completions, terminalBoundaryChoiceCancellations, terminalCleanupBoundaryComparisons, terminalRewardBoundaryComparisons, terminalActionWithoutPostStamp = pendingPlay, finalHp = hp, finalMaxHp = maxHp, finishedTurn, compared };
    }
}
