using System.Reflection;
using System.Text.Json;

// Reuse the collector's actual choice-boundary observers. An implicit all-card
// selection never calls ICardSelector; validate and consume its exact plan at
// that boundary, before the original game applies effects to those cards.
internal sealed class NativeImplicitChoiceObserver : IDisposable
{
    private static NativeImplicitChoiceObserver? current;
    private static bool installed;
    private readonly object selector, player;
    private Exception? failure;
    private static object[] Items(object value) => ((System.Collections.IEnumerable)value).Cast<object>().ToArray();
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;

    public NativeImplicitChoiceObserver(Func<string, Type> get, Assembly solver, object selector, object player)
    {
        if (current != null) throw new InvalidOperationException("Nested implicit choice observer.");
        this.selector = selector; this.player = player;
        if (!installed)
        {
            Assembly harmony = Assembly.Load("0Harmony");
            Type harmonyType = harmony.GetType("HarmonyLib.Harmony", true)!;
            object patcher = Activator.CreateInstance(harmonyType, ["sts2.host-native-implicit-choices"])!;
            MethodInfo patch = harmonyType.GetMethods().Single(m => m.Name == "Patch");
            void Prefix(MethodInfo target, MethodInfo hook)
            {
                object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
                args[0] = target;
                args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [hook]);
                patch.Invoke(patcher, args);
            }
            Prefix(solver.GetType("CombatSolver.NativeChoiceRuntime", true)!.GetMethod("Observe")!,
                typeof(NativeImplicitChoiceObserver).GetMethod(nameof(BeforeObserve))!);
            Type commands = get("Commands.CardSelectCmd");
            foreach (var item in new[] {
                ("ChooseCardObservationPatch", "FromChooseACardScreen", 4),
                ("SimpleGridObservationPatch", "FromSimpleGrid", 4),
                ("RewardGridObservationPatch", "FromSimpleGridForRewards", 4),
                ("CombatPileObservationPatch", "FromCombatPile", 5),
                ("HandObservationPatch", "FromHand", 5),
                ("HandUpgradeObservationPatch", "FromHandForUpgrade", 3) })
                Prefix(commands.GetMethods().Single(m => m.Name == item.Item2 && m.GetParameters().Length == item.Item3),
                    solver.GetType("CombatSolver." + item.Item1, true)!.GetMethod("Prefix")!);
            installed = true;
        }
        current = this;
    }

    public static void BeforeObserve(object[] __args)
    {
        var scope = current;
        if (scope == null || !ReferenceEquals(scope.player, __args[1]) || (bool)__args[5]) return;
        try { scope.Consume(__args); }
        catch (Exception error) { scope.failure ??= error; throw; }
    }

    public void AssertValid()
    {
        if (failure != null) throw new InvalidOperationException("Recorded implicit choice failed validation.", failure);
    }

    private void Consume(object[] args)
    {
        var scope = this;
        object options = args[2];
        object[] available = Items(options);
        Type type = scope.selector.GetType();
        int index = (int)type.GetField("_index", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(scope.selector)!;
        object[] choices = Items(type.GetField("_choices", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(scope.selector)!);
        // The native driver treats a zero-option request as a no-op and consumes
        // an empty plan only when one is next in the recorded sequence.
        if (available.Length == 0 && (index == choices.Length || Items(Read(choices[index], "Cards")).Length != 0)) return;
        Task selectedTask = (Task)type.GetMethod("GetSelectedCards")!.Invoke(scope.selector,
            [options, available.Length, available.Length])!;
        selectedTask.GetAwaiter().GetResult();
        object[] selected = Items(Read(selectedTask, "Result"));
        if (selected.Length != available.Length
            || selected.Distinct(ReferenceEqualityComparer.Instance).Count() != available.Length
            || selected.Any(card => !available.Any(option => ReferenceEquals(card, option))))
            throw new InvalidOperationException("Recorded implicit choice does not select exactly the original options.");
        Console.WriteLine(JsonSerializer.Serialize(new { status = "native_implicit_choice_consumed", index,
            surface = args[0].ToString(), source = args[8], count = available.Length }));
    }

    public void Dispose()
    {
        if (!ReferenceEquals(current, this)) throw new InvalidOperationException("Implicit choice scope changed.");
        current = null;
    }
}
