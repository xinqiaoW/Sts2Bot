using System.Reflection;

// Replay diagnostics only. Observe the original cleanup entry without suppressing it.
internal sealed class TerminalCleanupObservation : IDisposable
{
    private static TerminalCleanupObservation? current;
    private readonly Func<string> live;
    private readonly object patcher;
    private readonly Type harmonyType;
    private readonly MethodInfo target;
    private readonly MethodInfo prefix;
    public string? Stamp { get; private set; }
    public int Captures { get; private set; }

    public TerminalCleanupObservation(Type combatManager, Func<string> live)
    {
        if (current != null) throw new InvalidOperationException("Nested terminal replay observer.");
        this.live = live;
        Assembly harmony = Assembly.Load("0Harmony");
        harmonyType = harmony.GetType("HarmonyLib.Harmony", true)!;
        patcher = Activator.CreateInstance(harmonyType, ["sts2.replay-terminal-boundary"])!;
        target = combatManager.GetMethods(BindingFlags.Instance | BindingFlags.NonPublic)
            .Single(m => m.Name == "EndCombatInternal" && m.GetParameters().Length == 1);
        prefix = typeof(TerminalCleanupObservation).GetMethod(nameof(BeforeCleanup))!;
        MethodInfo patch = harmonyType.GetMethods().Single(m => m.Name == "Patch");
        object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        args[0] = target;
        args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [prefix]);
        patch.Invoke(patcher, args);
        current = this;
    }

    public void BeginAction() { Stamp = null; Captures = 0; }
    public static void BeforeCleanup()
    {
        if (current == null) return;
        current.Stamp = current.live();
        current.Captures++;
    }
    public void Dispose()
    {
        current = null;
        harmonyType.GetMethods().Single(m => m.Name == "Unpatch" && m.GetParameters().Length == 2
            && m.GetParameters()[1].ParameterType == typeof(MethodInfo)).Invoke(patcher, [target, prefix]);
    }
}
