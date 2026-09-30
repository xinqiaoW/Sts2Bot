using System.Reflection;
using System.Collections;
// Rendered boulder hits call the original DoDamage separately for each target.
// TestMode batches those targets, changing death-hook observations. Preserve the
// original damage command and hook; adapt only the missing per-hit boundary.
internal static class RollingBoulderHitScheduling
{
    public static bool Prefix<T>(object __instance, object __0, object __1, ref Task<IEnumerable<T>> __result)
    {
        object[] targets = ((IEnumerable)__1).Cast<object>().ToArray();
        if (targets.Length <= 1) return true;
        __result = DamageEach<T>(__instance, __0, targets);
        return false;
    }
    private static async Task<IEnumerable<T>> DamageEach<T>(object power, object context, object[] targets)
    {
        MethodInfo damage = power.GetType().GetMethod("DoDamage", BindingFlags.NonPublic | BindingFlags.Instance)!;
        Type creature = damage.GetParameters()[1].ParameterType.GetGenericArguments().Single();
        var results = new List<T>();
        foreach (object target in targets)
        {
            Array singleton = Array.CreateInstance(creature, 1); singleton.SetValue(target, 0);
            var task = (Task<IEnumerable<T>>)damage.Invoke(power, [context, singleton])!;
            results.AddRange(await task);
        }
        return results;
    }
    public static void Configure(Assembly game, Assembly harmony)
    {
        Type type = harmony.GetType("HarmonyLib.Harmony", true)!;
        object patcher = Activator.CreateInstance(type, ["sts2.standalone.rolling-boulder-hits"])!;
        MethodInfo patch = type.GetMethods().Single(m => m.Name == "Patch");
        Type power = game.GetType("MegaCrit.Sts2.Core.Models.Powers.RollingBoulderPower", true)!;
        MethodInfo damage = power.GetMethod("DoDamage", BindingFlags.NonPublic | BindingFlags.Instance)!;
        Type result = damage.ReturnType.GetGenericArguments().Single().GetGenericArguments().Single();
        MethodInfo prefix = typeof(RollingBoulderHitScheduling).GetMethod(nameof(Prefix))!.MakeGenericMethod(result);
        object?[] args = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        args[0] = damage;
        args[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [prefix]);
        patch.Invoke(patcher, args);
    }
}
