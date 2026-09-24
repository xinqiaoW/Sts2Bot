using System.Reflection;
using System.Text.Json;

internal static class RequestStartupProbe
{
    private static object Read(object o, string n) => o.GetType().GetProperty(n)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();
    public static object CreateRun(Func<string, Type> get, Array players, JsonElement fixture)
    {
        JsonElement request = fixture.GetProperty("request");
        object[] defaults = Items(get("Models.ActModel").GetMethod("GetDefaultList")!.Invoke(null, null)!);
        int index = request.GetProperty("actIndexForTest").GetInt32();
        object act = Items(get("Models.ModelDb").GetProperty("Acts")!.GetValue(null)!).Single(a => Read(Read(a, "Id"), "Entry").ToString() == request.GetProperty("trainingActId").GetString());
        if (index < 0 || index >= defaults.Length) throw new InvalidOperationException("Invalid act index.");
        object[] byIndex = Items(get("Models.ModelDb").GetProperty("ActsByIndex")!.GetValue(null)!);
        string requestedAct = Read(Read(act, "Id"), "Entry").ToString()!;
        if (!Items(byIndex[index]).Any(a => Read(Read(a, "Id"), "Entry").ToString() == requestedAct)
            || !Items(Read(act, "AllEncounters")).Any(e => Read(Read(e, "Id"), "Entry").ToString() == request.GetProperty("encounterId").GetString()))
            throw new InvalidOperationException("Encounter does not belong to requested act/index.");
        defaults[index] = act;
        Array acts = Array.CreateInstance(get("Models.ActModel"), defaults.Length);
        for (int i = 0; i < defaults.Length; i++) acts.SetValue(defaults[i].GetType().GetMethod("ToMutable")!.Invoke(defaults[i], null), i);
        return get("Runs.RunState").GetMethod("CreateForNewRun")!.Invoke(null, [players, acts,
            Array.CreateInstance(get("Models.ModifierModel"), 0), Enum.Parse(get("Runs.GameMode"), "Standard"), 10, request.GetProperty("seed").GetString()])!;
    }
    public static bool SkipEventAssets(ref Task __result)
    {
        HostClock.ClearAbsentHoverTips();
        __result = Task.CompletedTask;
        return false;
    }
    public static bool EmptyHoverTips(ref object __result)
    {
        HostClock.ClearAbsentHoverTips();
        __result = Array.CreateInstance(Assembly.Load("sts2").GetType("MegaCrit.Sts2.Core.HoverTips.IHoverTip", true)!, 0);
        return false;
    }
    private static void ConfigureVisualHost(Func<string, Type> get)
    {
        Assembly harmony = Assembly.Load("0Harmony");
        Type type = harmony.GetType("HarmonyLib.Harmony", true)!;
        object patcher = Activator.CreateInstance(type, ["sts2.startup-visual-host"])!;
        MethodInfo patch = type.GetMethods().Single(m => m.Name == "Patch");
        object?[] assetArgs = patch.GetParameters().Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray();
        assetArgs[0] = get("Assets.PreloadManager").GetMethod("LoadRoomEventAssets")!;
        assetArgs[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(RequestStartupProbe).GetMethod(nameof(SkipEventAssets))!]);
        patch.Invoke(patcher, assetArgs);
        assetArgs[0] = get("Models.RelicModel").GetProperty("HoverTipsExcludingRelic")!.GetMethod!;
        assetArgs[1] = Activator.CreateInstance(harmony.GetType("HarmonyLib.HarmonyMethod", true)!, [typeof(RequestStartupProbe).GetMethod(nameof(EmptyHoverTips))!]);
        patch.Invoke(patcher, assetArgs);
    }
    public static void Prepare(Func<string, Type> get, object run, JsonElement fixture)
    {
        object manager = get("Runs.RunManager").GetProperty("Instance")!.GetValue(null)!;
        ConfigureVisualHost(get);
        // The production standard single-player path enables these modifications outside TestMode.
        manager.GetType().GetProperty("ForceDiscoveryOrderModifications")!.SetValue(manager, true);
        Console.WriteLine("{\"stage\":\"request_generate_rooms\"}");
        manager.GetType().GetMethod("GenerateRooms")!.Invoke(manager, null);
        Console.WriteLine("{\"stage\":\"request_finalize_starting_relics\"}");
        ((Task)manager.GetType().GetMethod("FinalizeStartingRelics")!.Invoke(manager, null)!).WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        Console.WriteLine("{\"stage\":\"request_enter_first_act\"}");
        ((Task)manager.GetType().GetMethod("EnterAct")!.Invoke(manager, [0, false])!).WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        int index = fixture.GetProperty("request").GetProperty("actIndexForTest").GetInt32();
        if (index != 0)
            ((Task)manager.GetType().GetMethod("SetActInternal")!.Invoke(manager, [index])!).WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
        if (Read(Read(Read(run, "Act"), "Id"), "Entry").ToString() != fixture.GetProperty("request").GetProperty("trainingActId").GetString()
            || Convert.ToInt32(Read(run, "CurrentActIndex")) != index || Read(run, "Map") == null)
            throw new InvalidOperationException("Requested act or map was not initialized.");
        object sync = Read(manager, "EventSynchronizer");
        bool startedWithNeow = (bool)Read(Read(run, "ExtraFields"), "StartedWithNeow");
        string[] eventOptions = [];
        if (Items(Read(sync, "Events")).Length != 0)
        {
            object initialEvent = sync.GetType().GetMethod("GetLocalEvent")!.Invoke(sync, null)!;
            eventOptions = Items(Read(initialEvent, "CurrentOptions")).Select(o => Read(o, "TextKey").ToString()!).ToArray();
            if (eventOptions.Length == 0) throw new InvalidOperationException("Initial native event has no options.");
        }
        else if (startedWithNeow) throw new InvalidOperationException("Expected Neow event was not initialized.");
        Console.WriteLine(JsonSerializer.Serialize(new { status = "request_startup_prepared", productionReady = false,
            act = Read(Read(run, "Act"), "Id").ToString(), actIndex = Read(run, "CurrentActIndex"), startedWithNeow, eventOptions }));
    }
}
