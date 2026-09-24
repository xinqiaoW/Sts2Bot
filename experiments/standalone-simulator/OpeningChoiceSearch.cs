using System.Reflection;
using System.Text.Json;

// Capture the same pre-setup root as PlayerTurnSetupCoordinator. Only the
// presentation/choice transport differs: all setup hooks still run in the game.
internal sealed class OpeningChoiceSearch : IDisposable
{
    private static OpeningChoiceSearch? current;
    private readonly Func<string, Type> get;
    private readonly Assembly solver;
    private readonly object player;
    private readonly object patcher;
    private readonly Type harmonyType;
    private readonly MethodInfo target, prefix;
    private IDisposable? selectionScope;
    private object? selector;
    private NativeImplicitChoiceObserver? implicitChoices;
    public object? Result { get; private set; }
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;

    public OpeningChoiceSearch(Func<string, Type> get, Assembly solver, object player)
    {
        if (current != null) throw new InvalidOperationException("Nested opening search.");
        this.get = get; this.solver = solver; this.player = player;
        Assembly harmony = Assembly.Load("0Harmony");
        harmonyType = harmony.GetType("HarmonyLib.Harmony", true)!;
        patcher = Activator.CreateInstance(harmonyType, ["sts2.host-opening-search"])!;
        target = get("Combat.CombatManager").GetMethod("SetupPlayerTurn", BindingFlags.Instance | BindingFlags.NonPublic)!;
        prefix = typeof(OpeningChoiceSearch).GetMethod(nameof(BeforeSetup))!;
        MethodInfo patch = harmonyType.GetMethods().Single(m => m.Name == "Patch");
        object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        args[0] = target;
        args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [prefix]);
        patch.Invoke(patcher, args);
        current = this;
    }

    public static void BeforeSetup(object __instance, object __1)
    {
        var scope = current;
        if (scope == null || !ReferenceEquals(scope.player, __1)) return;
        object pcs = Read(__1, "PlayerCombatState");
        if (Convert.ToInt32(Read(pcs, "TurnNumber")) != 1) return;
        Type coordinator = scope.solver.GetType("CombatSolver.PlayerTurnSetupCoordinator", true)!;
        if (!(bool)coordinator.GetMethod("RequiresSolverChoice", BindingFlags.Static | BindingFlags.NonPublic)!
            .Invoke(null, [__1])!) return;
        if (scope.Result != null) throw new InvalidOperationException("Opening setup invoked twice.");
        object combat = __instance.GetType().GetMethod("DebugOnlyGetState")!.Invoke(__instance, null)!;
        Type tracker = scope.solver.GetType("CombatSolver.BattleDamageTracker", true)!;
        tracker.GetMethod("Begin")!.Invoke(null, [combat]);
        object damage = tracker.GetMethod("Observe")!.Invoke(null, [combat])!;
        object root = scope.solver.GetType("CombatSolver.CombatRootSnapshot", true)!.GetMethod("Capture")!.Invoke(null, [combat])!;
        object beam = RoundProbe.CreateBeam(scope.solver, root, damage, includeTurnSetup: true);
        object result = beam.GetType().GetMethod("Solve")!.Invoke(beam, null)!;
        if (Read(result, "SearchPhase").ToString() != "Short" || (bool)Read(result, "DeepSearchTriggered"))
            throw new InvalidOperationException("Unexpected opening teacher policy.");
        object choices = Read(result, "TurnSetupChoices");
        scope.selector = Activator.CreateInstance(scope.solver.GetType("CombatSolver.PlannedCardSelector", true)!, [choices])!;
        scope.selector.GetType().GetMethod("CaptureBefore")!.Invoke(scope.selector, [__1]);
        scope.implicitChoices = new NativeImplicitChoiceObserver(scope.get, scope.solver, scope.selector, scope.player);
        scope.selectionScope = (IDisposable)scope.get("Commands.CardSelectCmd").GetMethod("PushSelector")!
            .Invoke(null, [scope.selector, true])!;
        scope.Result = result;
        Console.WriteLine(JsonSerializer.Serialize(new { status = "teacher_opening_choice_plan",
            choices = JsonSerializer.SerializeToElement(choices), elapsedMilliseconds = ((TimeSpan)Read(result, "Elapsed")).TotalMilliseconds }));
    }

    public void AssertConsumed()
    {
        if (selector == null) return;
        implicitChoices?.AssertValid();
        selector.GetType().GetMethod("ReconcileImplicitChoices")!.Invoke(selector, [player]);
        selector.GetType().GetMethod("AssertConsumed")!.Invoke(selector, null);
    }

    public void Dispose()
    {
        current = null;
        selectionScope?.Dispose();
        implicitChoices?.Dispose();
        harmonyType.GetMethods().Single(m => m.Name == "Unpatch" && m.GetParameters().Length == 2
            && m.GetParameters()[1].ParameterType == typeof(MethodInfo)).Invoke(patcher, [target, prefix]);
    }
}
