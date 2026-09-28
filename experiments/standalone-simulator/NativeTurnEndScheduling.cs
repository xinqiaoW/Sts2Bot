using System.Reflection;

// Instant native presentation starts every hand-to-play transfer before the
// first turn-end effect resumes from its tween. TestMode removes those awaits.
// Restore that scheduling boundary while retaining all original commands,
// effects, death checks, and the original serial effect dependency chain.
internal static class NativeTurnEndScheduling
{
    public sealed class Batch
    {
        internal readonly Batch? Parent = Current.Value;
        internal readonly TaskCompletionSource Ready = new();
    }

    private static readonly AsyncLocal<Batch?> Current = new();

    public static void Begin(out Batch __state)
    {
        __state = new Batch();
        Current.Value = __state;
    }

    public static void Scheduled(Batch __state)
    {
        Current.Value = __state.Parent;
        __state.Ready.SetResult();
    }

    public static void DeferEffect(ref Task __2)
    {
        Batch batch = Current.Value ?? throw new InvalidOperationException("Turn-end effect outside its scheduling batch.");
        __2 = Task.WhenAll(__2, batch.Ready.Task);
    }

    public static void Configure(Assembly game, Assembly harmony)
    {
        Type type = harmony.GetType("HarmonyLib.Harmony", true)!;
        object patcher = Activator.CreateInstance(type, ["sts2.standalone.turn-end-scheduling"])!;
        MethodInfo patch = type.GetMethods().Single(m => m.Name == "Patch");
        Type manager = game.GetType("MegaCrit.Sts2.Core.Combat.CombatManager", true)!;
        object Hook(string name) => Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!,
            [typeof(NativeTurnEndScheduling).GetMethod(name)!])!;
        void Install(string name, string prefix, string? postfix = null)
        {
            object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
            args[0] = manager.GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic)
                ?? throw new MissingMethodException(manager.FullName, name);
            args[1] = Hook(prefix);
            if (postfix != null) args[2] = Hook(postfix);
            patch.Invoke(patcher, args);
        }
        Install("DoTurnEndCards", nameof(Begin), nameof(Scheduled));
        Install("ResolveTurnEndCardEffects", nameof(DeferEffect));
    }
}
