using System.Diagnostics;
using System.Reflection;
using System.Runtime.Loader;

internal static class HostClock
{
    private static readonly long Started = Stopwatch.GetTimestamp();
    public static bool Milliseconds(ref ulong __result)
    {
        __result = (ulong)Stopwatch.GetElapsedTime(Started).TotalMilliseconds;
        return false;
    }

    public static bool ProfileDirectory(int __0, bool? __1, ref string __result)
    {
        Type paths = Assembly.Load("sts2").GetType("MegaCrit.Sts2.Core.Saves.UserDataPathProvider", true)!;
        bool modded = __1 ?? (bool)paths.GetProperty("IsRunningModded")!.GetValue(null)!;
        __result = (modded ? "modded/" : "") + "profile" + __0;
        return false;
    }

    public static bool ProgressPath(int __0, bool? __1, ref string __result)
    {
        ProfileDirectory(__0, __1, ref __result);
        __result += "/saves/progress.save";
        return false;
    }

    public static bool ClearAbsentHoverTips()
    {
        if (!(bool)Assembly.Load("sts2").GetType("MegaCrit.Sts2.Core.TestSupport.TestMode", true)!.GetProperty("IsOn")!.GetValue(null)!)
            throw new InvalidOperationException("Visual host adapter requires TestMode.");
        return false; // This host creates no UI nodes. Avoid StringName allocation in the UI static initializer.
    }

    public static bool NoMonsterBackground(ref object? __result)
    {
        ClearAbsentHoverTips();
        __result = null;
        return false;
    }
    public static bool NoMonsterDeathPresentation(ref Task __result)
    {
        ClearAbsentHoverTips();
        __result = Task.CompletedTask;
        return false;
    }
    public static bool SoulDeathPresentation(object __instance)
    {
        ClearAbsentHoverTips();
        // Preserve the original event unsubscription; only the following animation lookup is omitted.
        object creature = __instance.GetType().GetProperty("Creature")!.GetValue(__instance)!;
        EventInfo died = creature.GetType().GetEvent("Died")!;
        MethodInfo callback = __instance.GetType().GetMethod("AfterDeath", BindingFlags.NonPublic | BindingFlags.Instance)!;
        died.RemoveEventHandler(creature, Delegate.CreateDelegate(died.EventHandlerType!, __instance, callback));
        return false;
    }

    public static void Configure(string data)
    {
        string harmonyPath = Path.Combine(data, "0Harmony.dll"), godotPath = Path.Combine(data, "GodotSharp.dll");
        HostAdapter.Verify(harmonyPath, "ef1898322c9f5c86dc1b0758b272a9c440823b4a41ca9a0b82a3aa6b3d206387");
        HostAdapter.Verify(godotPath, "0e4897ecdfb31456a97c7d8028dfb8d7dbdc632e2f73fc9b438d7b266a139289");
        Assembly harmony = AssemblyLoadContext.Default.LoadFromAssemblyPath(harmonyPath);
        Assembly godot = AssemblyLoadContext.Default.LoadFromAssemblyPath(godotPath);
        Type harmonyType = harmony.GetType("HarmonyLib.Harmony", true)!;
        object patcher = Activator.CreateInstance(harmonyType, ["sts2.standalone.host-clock"] )!;
        object prefix = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!,
            [typeof(HostClock).GetMethod(nameof(Milliseconds))!])!;
        MethodInfo original = godot.GetType("Godot.Time", true)!.GetMethod("GetTicksMsec")!;
        MethodInfo patch = harmonyType.GetMethods().Single(m => m.Name == "Patch");
        object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        args[0] = original; args[1] = prefix;
        patch.Invoke(patcher, args);
        Assembly game = Assembly.Load("sts2");
        NativeTurnEndScheduling.Configure(game, harmony);
        RollingBoulderHitScheduling.Configure(game, harmony);
        args[0] = game.GetType("MegaCrit.Sts2.Core.Nodes.HoverTips.NHoverTipSet", true)!.GetMethod("Clear")!;
        args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(HostClock).GetMethod(nameof(ClearAbsentHoverTips))!]);
        patch.Invoke(patcher, args);
        foreach (var target in new[] {
            (Type: "MegaCrit.Sts2.Core.Saves.UserDataPathProvider", Method: "GetProfileDir", Prefix: nameof(ProfileDirectory)),
            (Type: "MegaCrit.Sts2.Core.Saves.Managers.ProgressSaveManager", Method: "GetProgressPathForProfile", Prefix: nameof(ProgressPath)) })
        {
            args[0] = game.GetType(target.Type, true)!.GetMethod(target.Method, [typeof(int), typeof(bool?)])!;
            args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(HostClock).GetMethod(target.Prefix)!]);
            patch.Invoke(patcher, args);
        }
        foreach (string name in new[] { "Crusher", "Rocket" })
        {
            Type monster = game.GetType("MegaCrit.Sts2.Core.Models.Monsters." + name, true)!;
            args[0] = monster.GetProperty("Background", BindingFlags.NonPublic | BindingFlags.Instance)!.GetMethod!;
            args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(HostClock).GetMethod(nameof(NoMonsterBackground))!]);
            patch.Invoke(patcher, args);
            args[0] = monster.GetMethod("BeforeDeath")!;
            args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(HostClock).GetMethod(nameof(NoMonsterDeathPresentation))!]);
            patch.Invoke(patcher, args);
        }
        args[0] = game.GetType("MegaCrit.Sts2.Core.Models.Monsters.SoulNexus", true)!.GetMethod("AfterDeath", BindingFlags.NonPublic | BindingFlags.Instance)!;
        args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(HostClock).GetMethod(nameof(SoulDeathPresentation))!]);
        patch.Invoke(patcher, args);
        ulong before = (ulong)original.Invoke(null, null)!;
        Thread.Sleep(5);
        ulong after = (ulong)original.Invoke(null, null)!;
        if (after <= before) throw new InvalidOperationException("Managed host clock did not advance.");
    }
}
