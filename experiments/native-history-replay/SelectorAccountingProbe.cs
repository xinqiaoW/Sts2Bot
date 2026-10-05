using System.Collections;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using HarmonyLib;

// Isolated test wrapper: approve one explicitly supplied solver hash without
// changing the production host's frozen dependency pin. Observe real before/
// after piles; never drive choices or replace a game effect.
if (args.Length != 7)
    throw new ArgumentException("host.dll game-dir request.json progress.json solver-sha256 host-sha256 output.jsonl");
Probe.SolverPath = Path.GetFullPath(Path.Combine(args[1], "mods/CombatSolver/CombatSolver.dll"));
Probe.SolverSha = args[4];
Probe.Output = Path.GetFullPath(args[6]);
if (File.Exists(Probe.Output)) throw new IOException("Refusing to overwrite test evidence.");
Probe.Verify(Path.GetFullPath(args[0]), args[5]);
Probe.Verify(Probe.SolverPath, Probe.SolverSha);
string[] dirs = [Path.GetDirectoryName(Path.GetFullPath(args[0]))!,
    Path.Combine(args[1], "data_sts2_windows_x86_64"), Path.GetDirectoryName(Probe.SolverPath)!,
    Path.Combine(args[1], "mods/STS2-RitsuLib")];
AssemblyLoadContext.Default.Resolving += (context, name) =>
{
    string? path = dirs.Select(d => Path.Combine(d, name.Name + ".dll")).FirstOrDefault(File.Exists);
    return path == null ? null : context.LoadFromAssemblyPath(path);
};
Assembly host = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
MethodInfo initializeDetour = host.GetType("NativeDetourHost", true)!.GetMethod("Initialize", Probe.All)!;
initializeDetour.Invoke(null, null);
var harmony = new Harmony("sts2bot.selector-accounting-probe");
harmony.Patch(initializeDetour,
    transpiler: new HarmonyMethod(typeof(Probe).GetMethod(nameof(Probe.DetourAlreadyInitialized))!));
harmony.Patch(host.GetType("HostAdapter", true)!.GetMethod("Verify", Probe.All)!,
    prefix: new HarmonyMethod(typeof(Probe).GetMethod(nameof(Probe.VerifyPin))!));
MethodInfo advance = host.GetType("RequestBattleProbe", true)!.GetMethod("AdvanceTurn", Probe.All)!;
harmony.Patch(advance, prefix: new HarmonyMethod(typeof(Probe).GetMethod(nameof(Probe.BeforeBoundary))!),
    postfix: new HarmonyMethod(typeof(Probe).GetMethod(nameof(Probe.AfterBoundary))!));
// This wrapper owns a single disposable process. Keep the detour initializer
// replacement until exit: re-emitting its original nested handlers on unpatch
// hits the pinned Harmony emitter bug, just as patching that body would.
if (host.EntryPoint!.Invoke(null, [new[] { args[1], "--execute-request", args[2], args[3] }]) is Task task)
    await task;
if (!Probe.ActiveVerified || !Probe.TerminalVerified)
    throw new InvalidOperationException("Both active transform and terminal cleanup evidence are required.");
Probe.Record(new { kind = "probe_completed", passed = true });

public static class Probe
{
    public const BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
    public static string SolverPath = "", SolverSha = "", Output = "";
    public static bool ActiveVerified, TerminalVerified;
    public static IEnumerable<CodeInstruction> DetourAlreadyInitialized(IEnumerable<CodeInstruction> instructions) => [new(OpCodes.Ret)];
    private static object Read(object o, string n) => o.GetType().GetProperty(n, All)!.GetValue(o)!;
    private static object[] Items(object o) => ((IEnumerable)o).Cast<object>().ToArray();
    public static void Verify(string path, string expected)
    {
        if (Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path))) != expected)
            throw new InvalidDataException("Test dependency identity changed: " + path);
    }
    public static bool VerifyPin(string path, string expected)
    {
        if (Path.GetFullPath(path) != SolverPath) return true;
        if (expected != "f55809c52e58ba3bcbc01bbc9ad89eb59de6d468143fa9260a58c0f68d8a8d0b")
            throw new InvalidDataException("Unexpected host collector pin.");
        Verify(path, SolverSha);
        return false;
    }
    public static void BeforeBoundary(Assembly __1, object __3, object __4, int __5, out object? __state)
    {
        __state = null;
        object boundary = Items(Read(Read(__4, "BestNode"), "Actions")).Single(a =>
            Convert.ToInt32(Read(a, "Turn")) == __5 && Read(a, "Kind").ToString() == "EndTurn");
        object? choices = boundary.GetType().GetProperty("TurnStartChoices")!.GetValue(boundary);
        if (choices == null || Items(choices).Length != 1 || (string)Read(Items(choices)[0], "SourceId") != "ENTROPY_POWER") return;
        Type type = __1.GetType("CombatSolver.PlannedCardSelector", true)!;
        __state = Activator.CreateInstance(type, [choices])!;
        type.GetMethod("CaptureBefore")!.Invoke(__state, [__3]);
    }
    public static void AfterBoundary(object __2, object __3, int __5, object? __state)
    {
        if (__state == null) return;
        Type type = __state.GetType();
        bool active = (bool)Read(__2, "IsInProgress");
        object choice = Items(type.GetField("_choices", All)!.GetValue(__state)!)[0];
        bool inferredTransform = (bool)type.GetMethod("WasImplicitTransformApplied", All)!.Invoke(__state, [choice, __3])!;
        type.GetMethod("ReconcileImplicitChoices")!.Invoke(__state, [__3]);
        bool consumed = (bool)Read(__state, "IsConsumed");
        if (active && inferredTransform && !ActiveVerified)
        {
            if (!consumed) throw new InvalidOperationException("Actual active transform was not reconciled.");
            ActiveVerified = true;
            Record(new { kind = "active_transform", turn = __5, inferredTransform, consumed });
        }
        if (!active)
        {
            int remainingCards = Items(type.GetMethod("AllCombatCards", All)!.Invoke(null, [__3])!).Length;
            if (!inferredTransform || consumed || remainingCards != 0)
                throw new InvalidOperationException("Terminal cleanup inference was not rejected at the real cleared-pile boundary.");
            TerminalVerified = true;
            Record(new { kind = "terminal_cleanup", turn = __5, remainingCards, inferredTransform, consumed });
        }
    }
    public static void Record(object value)
    {
        using var stream = new FileStream(Output, FileMode.Append, FileAccess.Write, FileShare.Read);
        stream.Write(System.Text.Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value) + "\n"));
        stream.Flush(true);
    }
}
