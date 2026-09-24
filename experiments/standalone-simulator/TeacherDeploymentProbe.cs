using System.Reflection;
using System.Text.Json;

internal static class TeacherDeploymentProbe
{
    private static object Read(object o, string n) => o.GetType().GetProperty(n)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();

    public static object Run(Func<string, Type> get, Assembly solver, object result, object combat, object player, bool allowEmpty = false, bool openingSetupAlreadyConsumed = false)
    {
        object pcs = Read(player, "PlayerCombatState");
        int turn = Convert.ToInt32(Read(pcs, "TurnNumber"));
        object[] actions = Items(Read(Read(result, "BestNode"), "Actions"))
            .SkipWhile(a => Convert.ToInt32(Read(a, "Turn")) < turn)
            .TakeWhile(a => Convert.ToInt32(Read(a, "Turn")) == turn && Read(a, "Kind").ToString() != "EndTurn").ToArray();
        if (actions.Length == 0 && !allowEmpty) throw new InvalidOperationException("Teacher supplied no opening actions.");
        if (Items(Read(result, "TurnSetupChoices")).Length != 0 && !openingSetupAlreadyConsumed)
            throw new InvalidOperationException("Opening setup choices require separate deployment support.");
        Type controller = solver.GetType("CombatSolver.SolverController", true)!;
        Type selectorType = solver.GetType("CombatSolver.PlannedCardSelector", true)!;
        object manager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        var trace = new List<object>();
        var watch = System.Diagnostics.Stopwatch.StartNew();
        foreach (object action in actions)
        {
            if (Read(action, "Kind").ToString() != "PlayCard" || (bool)Read(action, "EndsPlayerTurn"))
                throw new InvalidOperationException("Opening deployment does not support this action kind.");
            object choices = action.GetType().GetMethod("GetActionChoicesInExecutionOrder")!.Invoke(action, null)!;
            object selector = Activator.CreateInstance(selectorType, [choices])!;
            selectorType.GetMethod("CaptureBefore")!.Invoke(selector, [player]);
            using var implicitChoices = new NativeImplicitChoiceObserver(get, solver, selector, player);
            MethodInfo push = get("Commands.CardSelectCmd").GetMethod("PushSelector")!;
            // Local selectors preserve the original choice pause/resume protocol.
            // The global test selector skips that protocol and changes hook ordering.
            object?[] selectorArgs = push.GetParameters().Select((parameter, index) => index == 0 ? selector
                : parameter.Name == "localOnly" ? true : parameter.HasDefaultValue ? parameter.DefaultValue
                : throw new InvalidOperationException("Unknown selector parameter: " + parameter.Name)).ToArray();
            using IDisposable scope = (IDisposable)push.Invoke(null, selectorArgs)!;
            object hand = Read(Read(pcs, "Hand"), "Cards");
            object card;
            try { card = controller.GetMethod("FindCardForDeployment", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [hand, action])!; }
            catch (TargetInvocationException error) when (error.InnerException is InvalidOperationException missing
                && (bool)controller.GetMethod("IsMissingDeploymentCard", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [missing])!)
            {
                return new { status = "teacher_deployment_drift", reason = "card_missing", turn,
                    actionCount = trace.Count, elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, trace };
            }
            object? target = combat.GetType().GetMethod("GetCreature")!.Invoke(combat, [Read(action, "TargetCombatId")]);
            if (!(bool)card.GetType().GetMethod("CanPlayTargeting")!.Invoke(card, [target])!)
                return new { status = "teacher_deployment_drift", reason = "card_unplayable", turn,
                    actionCount = trace.Count, elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, trace };
            // The queue can still look idle immediately after TryManualPlay enqueues work.
            // Use the native controller's capture-before-enqueue protocol and await this
            // exact action, keeping its selector installed throughout asynchronous execution.
            Func<object, bool> matches = candidate => candidate.GetType() == get("GameActions.PlayCardAction")
                && ReferenceEquals(Read(candidate, "NetCombatCard").GetType().GetMethod("ToCardModelOrNull")!
                    .Invoke(Read(candidate, "NetCombatCard"), null), card);
            Action enqueue = () => {
                if (!(bool)card.GetType().GetMethod("TryManualPlay")!.Invoke(card, [target])!)
                    throw new InvalidOperationException("Native engine rejected teacher action.");
            };
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            Task captured = (Task)controller.GetMethod("EnqueueAndCaptureActionAsync", BindingFlags.NonPublic | BindingFlags.Static)!
                .Invoke(null, [matches, enqueue, deadline.Token])!;
            captured.WaitAsync(deadline.Token).GetAwaiter().GetResult();
            object queued = Read(captured, "Result");
            ((Task)Read(queued, "CompletionTask")).WaitAsync(deadline.Token).GetAwaiter().GetResult();
            // CompletionTask resolves before the executor's final empty-queue
            // check. Enqueuing in that closing window can miss its wake-up.
            object executor = Read(manager, "ActionExecutor");
            ((Task)executor.GetType().GetMethod("FinishedExecutingActions")!.Invoke(executor, null)!)
                .WaitAsync(deadline.Token).GetAwaiter().GetResult();
            implicitChoices.AssertValid();
            selectorType.GetMethod("ReconcileImplicitChoices")!.Invoke(selector, [player]);
            if (Convert.ToInt32(Read(pcs, "TurnNumber")) != turn)
                throw new InvalidOperationException("Unexpected turn drift.");
            object stamp = solver.GetType("CombatSolver.ContinuationStamp", true)!.GetMethod("CaptureLive")!.Invoke(null, [combat])!;
            trace.Add(new { action = JsonSerializer.SerializeToElement(action), live = Read(stamp, "StateText") });
            // The queued game action is complete. An unused non-implicit plan is deployment drift,
            // matching NativeChoicePlanNotRequestedException in the original native controller.
            if (!(bool)Read(selector, "IsConsumed"))
                return new { status = "teacher_deployment_drift", reason = "choice_plan_unconsumed", turn,
                    actionCount = trace.Count, elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, trace };
            selectorType.GetMethod("AssertConsumed")!.Invoke(selector, null);
        }
        return new { status = "teacher_opening_deployed", productionReady = false, productionLabels = false,
            scope = "native queued execution of teacher opening actions with original planned-choice selector; no terminal label or prediction equality claim",
            actionCount = actions.Length, elapsedMilliseconds = watch.Elapsed.TotalMilliseconds, trace };
    }
}
