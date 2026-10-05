using System.Collections;
using System.Linq.Expressions;
using System.Reflection;
using System.Reflection.Emit;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Modding;
using Environment = System.Environment;
using FileAccess = System.IO.FileAccess;
using Expression = System.Linq.Expressions.Expression;

namespace NativeHistoryReplay;

// The original game's request builder, effects, RNG, action executor and native
// choice surfaces run unchanged. Only search/automatic deployment is replaced.
[ModInitializer(nameof(Initialize))]
public static class Entry
{
    private static Assembly Solver = null!;
    private static Assembly Game = null!;
    private static Context? Current;
    private static string PlanPath = "";
    private static string ProgressPath = "";
    private static bool PatchesInstalled;
    private const BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
    private static object Read(object value, string name) => value.GetType().GetProperty(name, All)!.GetValue(value)!;
    private static object Field(object value, string name) => value.GetType().GetField(name, All)!.GetValue(value)!;
    private static Type S(string name) => Solver.GetType("CombatSolver." + name, true)!;
    private static Type G(string name) => Game.GetType("MegaCrit.Sts2.Core." + name, true)!;
    private static object[] Items(object value) => ((IEnumerable)value).Cast<object>().ToArray();
    private static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value)));
    private static string Live(object combat) => (string)Read(S("ContinuationStamp").GetMethod("CaptureLive", All)!.Invoke(null, [combat])!, "StateText");

    private sealed class Context
    {
        public required JsonElement Plan;
        public required object Runner;
        public required object Host;
        public required string Output;
        public long Sequence;
        public int Matched;
        public string? CleanupStamp;
        public int CleanupCaptures;
        public object? Combat;
        public bool OpeningStarted;
        public object? OpeningSession;
        public object? OpeningPlayer;
        public CancellationTokenSource Deadline = new(TimeSpan.FromSeconds(115));
    }

    public static void Initialize()
    {
        PlanPath = Environment.GetEnvironmentVariable("STS2_HISTORY_REPLAY_PLAN") ?? "";
        if (PlanPath.Length == 0) return;
        ProgressPath = Environment.GetEnvironmentVariable("STS2_HISTORY_REPLAY_PROGRESS")
            ?? throw new InvalidOperationException("Missing frozen progress snapshot.");
        Solver = AppDomain.CurrentDomain.GetAssemblies().Single(a => a.GetName().Name == "CombatSolver");
        Game = typeof(ModInitializerAttribute).Assembly;
        string expected = Environment.GetEnvironmentVariable("STS2_HISTORY_REPLAY_SOLVER_SHA256")
            ?? throw new InvalidOperationException("Missing frozen native teacher identity.");
        if (Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Solver.Location))) != expected)
            throw new InvalidOperationException("Native collector identity changed.");
        var patcher = new Harmony("sts2bot.native-history-replay");
        void Patch(MethodInfo method, string hook, bool postfix = false)
        {
            GD.Print("HISTORY_REPLAY_PATCH " + method.DeclaringType!.FullName + "." + method.Name + " hook=" + hook);
            var patch = new HarmonyMethod(typeof(Entry).GetMethod(hook, All)!) { priority = Priority.First };
            patcher.Patch(method, prefix: postfix ? null : patch, postfix: postfix ? patch : null);
        }
        Patch(S("UnattendedTestRunner").GetMethod("ApplyHeadlessFastModeOverride", All)!, nameof(BeforeRequest));
        Patch(S("UnattendedTestRunner+Executor").GetMethod("ExecuteAsync", All)!, nameof(ReplaceExecution));
        Patch(S("SolverController").GetMethod("RequestSearch", All)!, nameof(SuppressSearch));
        Patch(S("PlayerTurnSetupCoordinator").GetMethod("TryInterceptSetup", All)!, nameof(SuppressSetupSearch));
        Patch(S("PlayerTurnSetupCoordinator").GetMethod("TryInterceptAutoPrePlay", All)!, nameof(SuppressSetupSearch));
        // Replacing the search entry body also avoids a Harmony/MonoMod emitter
        // failure on its nested exception handlers in the pinned Windows build.
        patcher.Patch(S("CombatSearchCoordinator").GetMethod("Solve", All)!,
            transpiler: new HarmonyMethod(typeof(Entry).GetMethod(nameof(DisableTeacherSearch), All)!));
        Patch(G("Combat.CombatManager").GetMethod("SetupPlayerTurn", All)!, nameof(BeforeOpening));
        Patch(G("Combat.CombatManager").GetMethod("RunAutoPrePlayPhase", All)!, nameof(AfterOpening), true);
        Patch(G("Combat.CombatManager").GetMethods(All).Single(m => m.Name == "EndCombatInternal" && m.GetParameters().Length == 1), nameof(BeforeCleanup));
        PatchesInstalled = true;
        GD.Print("HISTORY_REPLAY_READY no_teacher_search=true");
    }

    public static void BeforeRequest(object __instance)
    {
        if (!PatchesInstalled) throw new InvalidOperationException("Historical replay patches did not finish installing.");
        if (Current != null)
        {
            Current.Deadline.Cancel();
            (Current.OpeningSession as IDisposable)?.Dispose();
            Current.Deadline.Dispose();
        }
        JsonElement plan = JsonDocument.Parse(File.ReadAllText(PlanPath)).RootElement.Clone();
        object request = Field(__instance, "_request");
        if ((string)Read(request, "RunId") != plan.GetProperty("nativeRunId").GetString())
            throw new InvalidOperationException("Replay plan belongs to another native request.");
        byte[] bytes = File.ReadAllBytes(ProgressPath);
        if (Convert.ToHexStringLower(SHA256.HashData(bytes)) != plan.GetProperty("progressSnapshotSha256").GetString())
            throw new InvalidOperationException("Progress input changed.");
        object parsed = G("Saves.JsonSerializationUtility").GetMethod("FromJson")!.MakeGenericMethod(G("Saves.SerializableProgress"))
            .Invoke(null, [System.Text.Encoding.UTF8.GetString(bytes)])!;
        if (!(bool)Read(parsed, "Success")) throw new InvalidDataException("Progress snapshot rejected.");
        object validation = Activator.CreateInstance(G("Saves.Validation.DeserializationContext"))!;
        object progress = G("Saves.ProgressState").GetMethod("FromSerializable")!.Invoke(null, [Read(parsed, "SaveData"), validation])!;
        if (Items(Read(validation, "Errors")).Length != 0) throw new InvalidDataException("Progress snapshot invalid.");
        object save = G("Saves.SaveManager").GetProperty("Instance")!.GetValue(null)!;
        object manager = Field(save, "_progressSaveManager");
        manager.GetType().GetProperty("Progress")!.SetValue(manager, progress);
        string output = plan.GetProperty("checkpointPath").GetString()!;
        using (File.Open(output, FileMode.CreateNew, FileAccess.Write)) { }
        Current = new Context { Plan = plan, Runner = __instance, Host = Field(__instance, "_host"), Output = output };
        Record("initialized", new { nativeRunId = Read(request, "RunId"), sourceRunId = plan.GetProperty("sourceRunId").GetString(),
            sourceJobId = plan.GetProperty("sourceJobId").GetString(), noTeacherSearch = true });
    }

    public static bool SuppressSearch() => Current == null;
    public static bool SuppressSetupSearch(ref bool __result)
    {
        if (Current == null) return true;
        __result = false;
        return false;
    }
    public static IEnumerable<CodeInstruction> DisableTeacherSearch(IEnumerable<CodeInstruction> instructions) =>
    [
        new(OpCodes.Ldstr, "Historical replay must never search for a new route."),
        new(OpCodes.Newobj, typeof(InvalidOperationException).GetConstructor([typeof(string)])!),
        new(OpCodes.Throw),
    ];

    private static object Choices(JsonElement choices)
    {
        Type element = S("PlanCardChoice");
        Array array = Array.CreateInstance(element, choices.GetArrayLength());
        int i = 0;
        foreach (JsonElement choice in choices.EnumerateArray()) array.SetValue(JsonSerializer.Deserialize(choice, element), i++);
        return array;
    }
    private static object Session(object combat, object player, string owner, JsonElement choices)
    {
        object session = S("NativeChoiceRuntime").GetMethod("Begin", All)!.Invoke(null, [combat, player, owner])!;
        session.GetType().GetMethod("SetPlanAndStartDriving")!.Invoke(session, [Current!.Host, Choices(choices), Current.Deadline.Token]);
        return session;
    }
    public static void BeforeOpening(object __instance, object __1)
    {
        // Identify only the initial setup; subsequent setups are covered by the
        // session that drives each recorded end-turn boundary.
        if (Current == null || Current.OpeningStarted) return;
        Current.OpeningStarted = true;
        Record("opening_setup_started", new { turn = Read(Read(__1, "PlayerCombatState"), "TurnNumber"), choices = Current.Plan.GetProperty("openingChoices").GetArrayLength() });
        JsonElement choices = Current.Plan.GetProperty("openingChoices");
        if (choices.GetArrayLength() == 0) return;
        object combat = __instance.GetType().GetMethod("DebugOnlyGetState")!.Invoke(__instance, null)!;
        Current.OpeningPlayer = __1;
        Current.OpeningSession = Session(combat, __1, "history_opening:1", choices);
    }
    public static void AfterOpening(object __3, ref Task __result)
    {
        Context? c = Current;
        // RunAutoPrePlayPhase awaits SetupPlayerTurn and then executes IMBUED.
        // Completing at SetupPlayerTurn would close the session before those choices.
        if (c?.OpeningSession is { } session && ReferenceEquals(c.OpeningPlayer, __3))
            __result = CompleteOpening(c, session, __result);
    }
    private static async Task CompleteOpening(Context c, object session, Task original)
    {
        try
        {
            await ((Task)session.GetType().GetMethod("AwaitProducerAndCompleteAsync")!.Invoke(session, [original])!)
                .WaitAsync(c.Deadline.Token);
            Record("opening_choices_completed", new { phase = "AutoPrePlay" });
        }
        finally
        {
            ((IDisposable)session).Dispose();
            c.OpeningSession = null;
            c.OpeningPlayer = null;
        }
    }
    public static void BeforeCleanup()
    {
        if (Current?.Combat == null) return;
        Current.CleanupStamp = Live(Current.Combat);
        Current.CleanupCaptures++;
    }

    public static bool ReplaceExecution(object __0, MethodBase __originalMethod, ref object __result)
    {
        if (Current == null) return true;
        Type result = ((MethodInfo)__originalMethod).ReturnType.GetGenericArguments().Single();
        __result = typeof(Entry).GetMethod(nameof(Execute), All)!.MakeGenericMethod(result).Invoke(null, [__0])!;
        return false;
    }

    private sealed class EventScope : IDisposable
    {
        private readonly object owner;
        private readonly EventInfo info;
        private readonly Delegate handler;
        public EventScope(object owner, string name, Action<object[]> callback)
        {
            this.owner = owner;
            info = owner.GetType().GetEvent(name)!;
            var p = info.EventHandlerType!.GetMethod("Invoke")!.GetParameters().Select(v => Expression.Parameter(v.ParameterType)).ToArray();
            handler = Expression.Lambda(info.EventHandlerType, Expression.Call(Expression.Constant(callback), typeof(Action<object[]>).GetMethod("Invoke")!,
                Expression.NewArrayInit(typeof(object), p.Select(v => Expression.Convert(v, typeof(object))))), p).Compile();
            info.AddEventHandler(owner, handler);
        }
        public void Dispose() => info.RemoveEventHandler(owner, handler);
    }
    private static async Task Frame()
    {
        Current!.Deadline.Token.ThrowIfCancellationRequested();
        Node host = (Node)Current.Host;
        await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
    }
    private static void Compare(string expected, object combat, string point, bool permitCleanup = false)
    {
        string actual = Live(combat);
        string observed = actual;
        bool cleanupBoundary = false;
        if (permitCleanup && actual != expected && Current!.CleanupCaptures == 1 && Current.CleanupStamp == expected)
        {
            actual = Current.CleanupStamp;
            cleanupBoundary = true;
        }
        bool matches = expected == actual;
        Record("checkpoint", new { point, matches, expectedSha256 = Hash(expected), actualSha256 = Hash(actual), actual,
            cleanupBoundary, observedAfterCleanup = cleanupBoundary ? observed : null, expected = matches ? null : expected });
        if (!matches) throw new InvalidOperationException("Historical state mismatch at " + point);
        Current!.Matched++;
    }
    private static void Record(string kind, object value)
    {
        Context c = Current!;
        using var stream = new FileStream(c.Output, FileMode.Append, FileAccess.Write, FileShare.Read);
        byte[] line = System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new { sequence = ++c.Sequence, kind, value }) + "\n");
        stream.Write(line);
        stream.Flush(flushToDisk: true);
    }

    private static bool CanCancelTerminalChoice(Exception error, JsonElement step, object session,
        bool finalStep, bool ended, int finishedTurn, int expectedTurn)
    {
        if (!finalStep || !ended || finishedTurn != expectedTurn
            || !step.TryGetProperty("terminalChoiceCancellation", out JsonElement policy)
            || !(S("NativeChoicePlanNotRequestedException").IsInstanceOfType(error)
                || S("NativeChoiceSurfaceTimeoutException").IsInstanceOfType(error))) return false;
        int consumed = 0;
        JsonElement choices = step.GetProperty("choices");
        string owner = (string)Read(session, "Owner");
        foreach (object trace in Items(S("NativeChoiceRuntime").GetProperty("TraceSnapshotForTesting", All)!.GetValue(null)!))
        {
            if ((string)Read(trace, "Owner") != owner) continue;
            string stage = (string)Read(trace, "Stage");
            if (stage == "Selected") consumed++;
            else if (stage == "NoOp" && consumed < choices.GetArrayLength()
                && choices[consumed].GetProperty("Cards").GetArrayLength() == 0) consumed++;
        }
        return choices.GetArrayLength() - consumed == policy.GetProperty("count").GetInt32();
    }

    private static async Task<T> Execute<T>(object scenario)
    {
        Context c = Current!;
        object combat = Read(scenario, "CombatState"), player = Read(scenario, "Player");
        c.Combat = combat;
        object cm = G("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        object manager = G("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        object executor = Read(manager, "ActionExecutor");
        object pcs = Read(player, "PlayerCombatState");
        object outcome = Field(c.Runner, "_nativeCombatOutcome");
        bool Ended() => (bool)outcome.GetType().GetMethod("HasEnded", All)!.Invoke(outcome, [combat])!;
        JsonElement plan = c.Plan;
        Compare(plan.GetProperty("openingState").GetString()!, combat, "opening");
        int plays = 0, boundaries = 0;
        JsonElement steps = plan.GetProperty("steps");
        int stepIndex = 0;
        foreach (JsonElement step in steps.EnumerateArray())
        {
            c.Deadline.Token.ThrowIfCancellationRequested();
            int turn = step.GetProperty("turn").GetInt32();
            if (Convert.ToInt32(Read(pcs, "TurnNumber")) != turn || Ended())
                throw new InvalidOperationException("Historical action/turn cannot be reached.");
            c.CleanupCaptures = 0; c.CleanupStamp = null;
            string kind = step.GetProperty("kind").GetString()!;
            if (kind == "play")
            {
                if (step.TryGetProperty("before", out JsonElement before)) Compare(before.GetString()!, combat, "before_play_" + plays);
                object action = JsonSerializer.Deserialize(step.GetProperty("action"), S("PlanAction"))!;
                object hand = Read(Read(pcs, "Hand"), "Cards");
                object card = S("SolverController").GetMethod("FindCardForDeployment", All)!.Invoke(null, [hand, action])!;
                object? target = combat.GetType().GetMethod("GetCreature")!.Invoke(combat, [Read(action, "TargetCombatId")]);
                if (!(bool)card.GetType().GetMethod("CanPlayTargeting")!.Invoke(card, [target])!)
                    throw new InvalidOperationException("Historical card is not playable in native game.");
                JsonElement choices = JsonSerializer.SerializeToElement(action.GetType().GetMethod("GetActionChoicesInExecutionOrder")!.Invoke(action, null));
                using var session = (IDisposable)Session(combat, player, "history_play:" + turn + ":" + plays, choices);
                Func<object, bool> matches = queued => queued.GetType() == G("GameActions.PlayCardAction")
                    && ReferenceEquals(Read(queued, "NetCombatCard").GetType().GetMethod("ToCardModelOrNull")!.Invoke(Read(queued, "NetCombatCard"), null), card);
                Action enqueue = () =>
                {
                    if (!(bool)card.GetType().GetMethod("TryManualPlay")!.Invoke(card, [target])!)
                        throw new InvalidOperationException("Native game rejected historical action.");
                };
                Task capture = (Task)S("SolverController").GetMethod("EnqueueAndCaptureActionAsync", All)!.Invoke(null, [matches, enqueue, c.Deadline.Token])!;
                await capture.WaitAsync(c.Deadline.Token);
                Task completion = (Task)Read(Read(capture, "Result"), "CompletionTask");
                Task driven = (Task)session.GetType().GetMethod("AwaitProducerAndCompleteAsync")!.Invoke(session, [completion])!;
                try { await driven.WaitAsync(c.Deadline.Token); }
                catch (Exception error) when (step.GetProperty("allowUnconsumedPlan").GetBoolean()
                    && completion.IsCompletedSuccessfully && (
                        S("NativeChoicePlanNotRequestedException").IsInstanceOfType(error)
                        || (Ended() && S("NativeChoiceSurfaceTimeoutException").IsInstanceOfType(error))))
                {
                    Record("recorded_plan_not_requested", new { turn, plays, error = error.ToString() });
                }
                await ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!).WaitAsync(c.Deadline.Token);
                if (step.GetProperty("expected").ValueKind == JsonValueKind.String)
                    Compare(step.GetProperty("expected").GetString()!, combat, "after_play_" + plays, permitCleanup: Ended());
                else Record("diagnostic_action_completed", new { plays, actual = Live(combat) });
                plays++;
            }
            else if (kind == "end_turn")
            {
                if (step.TryGetProperty("before", out JsonElement before)) Compare(before.GetString()!, combat, "before_end_turn_" + turn);
                var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                using var turnEvent = new EventScope(cm, "TurnStarted", values =>
                {
                    if (Read(values.Single(), "CurrentSide").ToString() == "Player") started.TrySetResult();
                });
                using var session = (IDisposable)Session(combat, player, "history_end_turn:" + turn, step.GetProperty("choices"));
                cm.GetType().GetMethod("SetReadyToEndTurn")!.Invoke(cm, [player, false, null]);
                while (!Ended() && !(started.Task.IsCompleted && Convert.ToInt32(Read(pcs, "TurnNumber")) > turn
                    && Read(pcs, "Phase").ToString() == "Play" && !(bool)Read(cm, "IsStarting"))) await Frame();
                await ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!).WaitAsync(c.Deadline.Token);
                try { await ((Task)session.GetType().GetMethod("CompleteAsync")!.Invoke(session, null)!).WaitAsync(c.Deadline.Token); }
                catch (Exception error) when (CanCancelTerminalChoice(error, step, session,
                    stepIndex == steps.GetArrayLength() - 1, Ended(), Convert.ToInt32(Read(pcs, "TurnNumber")),
                    plan.GetProperty("finishedTurn").GetInt32()))
                {
                    Record("recorded_terminal_plan_cancelled", new { turn,
                        policy = step.GetProperty("terminalChoiceCancellation"), error = error.ToString() });
                }
                Record("end_turn_completed", new { turn, nextTurn = Read(pcs, "TurnNumber"), terminal = Ended() });
                boundaries++;
            }
            else throw new InvalidDataException("Unknown historical step.");
            stepIndex++;
        }
        if (plan.TryGetProperty("partialReplay", out JsonElement partial) && partial.GetBoolean())
        {
            Record("diagnostic_prefix_completed", new { plays, boundaries, checkpoints = c.Matched, terminal = Ended(), actual = Live(combat) });
            throw new InvalidOperationException("Diagnostic prefix completed; no complete battle label is produced.");
        }
        while (!Ended()) await Frame();
        // Allow the original native reward callbacks to finish before the stable
        // terminal checkpoint; never replace it with an earlier cleanup stamp.
        await Frame();
        await ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!).WaitAsync(c.Deadline.Token);
        Compare(plan.GetProperty("terminalState").GetString()!, combat, "terminal");
        int finished = Convert.ToInt32(Read(pcs, "TurnNumber"));
        if (finished != plan.GetProperty("finishedTurn").GetInt32()) throw new InvalidOperationException("Historical terminal turn differs.");
        if (plays != plan.GetProperty("plays").GetInt32()) throw new InvalidOperationException("Historical action list was not fully replayed.");
        Record("replay_completed", new { matched = true, plays, boundaries, checkpoints = c.Matched, finishedTurn = finished,
            nativeTerminalObserved = true, noTeacherSearch = true });
        return (T)Activator.CreateInstance(typeof(T), All, null, [true, finished, true, true, true, false], null)!;
    }
}
