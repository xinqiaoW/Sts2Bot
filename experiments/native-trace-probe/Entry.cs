using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Modding;

namespace NativeTraceProbe;

[ModInitializer(nameof(Initialize))]
public static class Entry
{
    private static Assembly Solver = null!;
    private static MethodInfo Capture = null!;
    private static string Output = "";
    private static string DirectoryOutput = "";
    private static string ProgressSnapshot = "";
    private static long Sequence;
    private static object? SelectedCard, SelectedAction;
    private sealed record PlayObservation(JsonElement action, string before);
    private static readonly object Sync = new();
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;
    private static string Stamp(object combat) => (string)Read(Capture.Invoke(null, [combat])!, "StateText");
    private static object Combat()
    {
        Type type = typeof(ModInitializerAttribute).Assembly.GetType("MegaCrit.Sts2.Core.Combat.CombatManager", true)!;
        object manager = type.GetProperty("Instance")!.GetValue(null)!;
        return type.GetMethod("DebugOnlyGetState")!.Invoke(manager, null)!;
    }
    private static void Record(string kind, object value)
    {
        lock (Sync)
            if (Output.Length != 0)
                File.AppendAllText(Output, JsonSerializer.Serialize(new { sequence = ++Sequence, kind, value }) + "\n");
    }
    private static void Observe(string kind, Func<object> capture)
    {
        try { Record(kind, capture()); }
        catch (Exception error) { Record("trace_error", new { kind, error = error.ToString() }); }
    }
    public static void Initialize()
    {
        Output = Environment.GetEnvironmentVariable("STS2_NATIVE_TRACE_PATH") ?? "";
        DirectoryOutput = Environment.GetEnvironmentVariable("STS2_NATIVE_TRACE_DIRECTORY") ?? "";
        ProgressSnapshot = Environment.GetEnvironmentVariable("STS2_NATIVE_TRACE_PROGRESS") ?? "";
        if (Output.Length == 0 && DirectoryOutput.Length == 0) return; // Inert unless explicitly enabled in an isolated runtime.
        if (Output.Length != 0 && DirectoryOutput.Length != 0)
            throw new InvalidOperationException("Choose a single trace output mode.");
        if (DirectoryOutput.Length != 0 && ProgressSnapshot.Length == 0)
            throw new InvalidOperationException("Reusable trace capture requires an immutable progress snapshot.");
        Solver = AppDomain.CurrentDomain.GetAssemblies().Single(a => a.GetName().Name == "CombatSolver");
        string hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Solver.Location))).ToLowerInvariant();
        if (hash != "1950d98b8aa742f651a2c09d59e6044da8c0836a29f4c1258047a8d1048f9bfb")
            throw new InvalidOperationException("Native trace requires the pinned collector assembly.");
        Capture = Solver.GetType("CombatSolver.ContinuationStamp", true)!.GetMethod("CaptureLive")!;
        var harmony = new Harmony("sts2bot.isolated-native-trace");
        void Patch(Type type, string method, string hook, bool postfix = false)
        {
            MethodInfo target = AccessTools.Method(type, method) ?? throw new MissingMethodException(type.FullName, method);
            var patch = new HarmonyMethod(typeof(Entry).GetMethod(hook, BindingFlags.Static | BindingFlags.Public)!);
            harmony.Patch(target, prefix: postfix ? null : patch, postfix: postfix ? patch : null);
        }
        Patch(Solver.GetType("CombatSolver.SolverController", true)!, "FindCardForDeployment", nameof(SelectedForDeployment), true);
        Type card = typeof(ModInitializerAttribute).Assembly.GetType("MegaCrit.Sts2.Core.Models.CardModel", true)!;
        Patch(card, "TryManualPlay", nameof(BeforeManualPlay));
        Patch(card, "TryManualPlay", nameof(AfterManualPlay), true);
        Type session = Solver.GetType("CombatSolver.NativeChoiceSession", true)!;
        Patch(session, "SetPlanAndStartDriving", nameof(BeforeChoices));
        Patch(session, "AwaitProducerAndCompleteAsync", nameof(AfterProducer), true);
        Patch(typeof(ModInitializerAttribute).Assembly.GetType("MegaCrit.Sts2.Core.GameActions.EndPlayerTurnAction", true)!, "ExecuteAction", nameof(BeforeEndTurn));
        if (DirectoryOutput.Length != 0)
            // The first RunAsync starts before mod initialization and awaits
            // GameStartupComplete. This method is the first scenario boundary
            // after that await, including both the first and reused requests.
            Patch(Solver.GetType("CombatSolver.UnattendedTestRunner", true)!, "ApplyHeadlessFastModeOverride", nameof(BeforeRequest));
        else Record("initialized", new { collectorSha256 = hash, assemblySha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Assembly.GetExecutingAssembly().Location))).ToLowerInvariant() });
    }
    public static void BeforeRequest(object __instance)
    {
        object request = __instance.GetType().GetField("_request", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(__instance)!;
        string runId = (string)Read(request, "RunId");
        if (runId.Length != 32 || runId.Any(c => !Uri.IsHexDigit(c)))
            throw new InvalidOperationException("Trace request must have a generated hex run ID.");
        // Reuse the native process only after its protocol readiness boundary.
        // Restore the exact same progress input as a fresh capture, using the
        // game's parser and ProgressState factory before the original scenario starts.
        Assembly game = typeof(ModInitializerAttribute).Assembly;
        Type Get(string name) => game.GetType("MegaCrit.Sts2.Core." + name, true)!;
        byte[] bytes = File.ReadAllBytes(ProgressSnapshot);
        object parsed = Get("Saves.JsonSerializationUtility").GetMethod("FromJson")!
            .MakeGenericMethod(Get("Saves.SerializableProgress")).Invoke(null, [System.Text.Encoding.UTF8.GetString(bytes)])!;
        if (!(bool)Read(parsed, "Success")) throw new InvalidDataException("Progress snapshot rejected.");
        object context = Activator.CreateInstance(Get("Saves.Validation.DeserializationContext"))!;
        object progress = Get("Saves.ProgressState").GetMethod("FromSerializable")!.Invoke(null, [Read(parsed, "SaveData"), context])!;
        if (((System.Collections.IEnumerable)Read(context, "Errors")).Cast<object>().Any())
            throw new InvalidDataException("Progress snapshot validation failed.");
        object save = Get("Saves.SaveManager").GetProperty("Instance")!.GetValue(null)!;
        object manager = save.GetType().GetField("_progressSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(save)!;
        manager.GetType().GetProperty("Progress")!.SetValue(manager, progress);
        lock (Sync)
        {
            Output = Path.Combine(DirectoryOutput, runId + ".jsonl");
            using (File.Open(Output, FileMode.CreateNew, FileAccess.Write)) { }
            Sequence = 0; SelectedCard = SelectedAction = null;
            Record("initialized", new { collectorSha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Solver.Location))),
                assemblySha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Assembly.GetExecutingAssembly().Location))),
                runId, progressSnapshotSha256 = Convert.ToHexStringLower(SHA256.HashData(bytes)), reusableProcess = true });
        }
    }
    public static void SelectedForDeployment(object[] __args, object __result)
    {
        SelectedCard = __result;
        SelectedAction = __args[1];
    }
    public static void BeforeManualPlay(object __instance, out object? __state)
    {
        __state = null;
        if (!ReferenceEquals(__instance, SelectedCard) || SelectedAction == null)
        {
            Record("trace_error", new { kind = "manual_play", error = "No matching deployment plan for manual play." });
            return;
        }
        try { __state = new PlayObservation(JsonSerializer.SerializeToElement(SelectedAction, SelectedAction.GetType()), Stamp(Combat())); }
        catch (Exception error) { Record("trace_error", new { kind = "manual_play", error = error.ToString() }); }
        SelectedCard = SelectedAction = null;
    }
    public static void AfterManualPlay(bool __result, object? __state)
    {
        // A missing/unplayable plan is not an executed action. Record only accepted native enqueue operations.
        if (__result && __state is PlayObservation observation) Record("play", observation);
    }
    public static void BeforeChoices(object __instance, object[] __args) => Observe("choice_plan", () => new {
        owner = Read(__instance, "Owner"), choices = JsonSerializer.SerializeToElement(__args[1], __args[1].GetType()) });
    public static void BeforeEndTurn() => Observe("end_turn", () => new { before = Stamp(Combat()) });
    public static void AfterProducer(object __instance, object[] __args, ref Task __result) => __result = ObserveCompletion(__result, (Task)__args[0], __instance);
    private static async Task ObserveCompletion(Task original, Task producer, object session)
    {
        try { await original; }
        catch (Exception error) when (producer.IsCompletedSuccessfully
            && Solver.GetType("CombatSolver.NativeChoicePlanMismatchException", true)!.IsInstanceOfType(error))
        {
            // Native controller will replan. The game action itself completed; retain its actual effects.
            Observe("action_completed", () => new { owner = Read(session, "Owner"), after = Stamp(Read(session, "Combat")),
                choicePlanFailed = true, errorType = error.GetType().FullName });
            throw;
        }
        Observe("action_completed", () => new { owner = Read(session, "Owner"), after = Stamp(Read(session, "Combat")) });
    }
}
