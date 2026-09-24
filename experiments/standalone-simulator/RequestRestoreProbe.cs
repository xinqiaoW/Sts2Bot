using System.Reflection;
using System.Text.Json;

internal static class RequestRestoreProbe
{
    private static object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    private static object[] Items(object o) => ((System.Collections.IEnumerable)o).Cast<object>().ToArray();

    public static object Run(Func<string, Type> get, Assembly collector, object run, object player, JsonElement fixture, bool preserveInitializedAct = false, bool compareHistorical = true)
    {
        JsonElement json = fixture.GetProperty("request");
        if (json.GetProperty("characterId").GetString() != "SILENT" || json.GetProperty("ascension").GetInt32() != 10
            || !json.GetProperty("trainingCollection").GetBoolean() || !json.GetProperty("clearRunDeck").GetBoolean()
            || json.GetProperty("cards").GetArrayLength() != 0 || json.GetProperty("potions").GetArrayLength() != 0)
            throw new NotSupportedException("Not a formal precombat Silent A10 restoration fixture.");
        var options = (JsonSerializerOptions)collector.GetType("CombatSolver.UnattendedTestFiles", true)!.GetField("JsonOptions")!.GetValue(null)!;
        object request = JsonSerializer.Deserialize(json, collector.GetType("CombatSolver.UnattendedTestRequest", true)!, options)!;
        Type runner = collector.GetType("CombatSolver.UnattendedTestRunner", true)!;
        int index = json.GetProperty("actIndexForTest").GetInt32();
        string actId = json.GetProperty("trainingActId").GetString()!;
        object act = Items(get("Models.ModelDb").GetProperty("Acts")!.GetValue(null)!).Single(a => Read(Read(a, "Id"), "Entry").ToString() == actId);
        act = act.GetType().GetMethod("ToMutable")!.Invoke(act, null)!;
        if (!preserveInitializedAct)
        {
            run.GetType().GetProperty("CurrentActIndex")!.SetValue(run, index);
            run.GetType().GetMethod("SetActDebug")!.Invoke(run, [act]);
        }
        runner.GetMethod("ClearRunDeck", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [run, player]);
        foreach (object card in Items(Read(request, "RunCards")))
            ((Task)runner.GetMethod("InjectRunCardAsync", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [run, player, card])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        foreach (object relic in Items(Read(request, "Relics")))
            ((Task)runner.GetMethod("InjectRelicAsync", BindingFlags.NonPublic | BindingFlags.Static)!.Invoke(null, [player, relic])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        object hero = Read(player, "Creature");
        ((Task)get("Commands.CreatureCmd").GetMethod("SetCurrentHp")!.Invoke(null, [hero, Convert.ToDecimal(Read(hero, "MaxHp"))])!).GetAwaiter().GetResult();
        // Capture through the same protocol-3 readback code used by collection, not a reconstructed expectation.
        object observer = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(runner);
        runner.GetField("_request", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(observer, request);
        runner.GetMethod("CaptureTrainingStart", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(observer, [player]);
        object observed = runner.GetField("_trainingObservation", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(observer)!;
        JsonElement actual = (JsonElement)Read(observed, "InitialBuild");
        if (compareHistorical)
        {
        JsonElement expected = fixture.GetProperty("expected");
        if (!JsonElement.DeepEquals(actual, expected.GetProperty("initialBuild"))
            || Convert.ToInt32(Read(observed, "InitialHp")) != expected.GetProperty("initialHp").GetInt32()
            || Convert.ToInt32(Read(observed, "InitialMaxHp")) != expected.GetProperty("initialMaxHp").GetInt32())
        {
            Console.WriteLine(JsonSerializer.Serialize(new { status = "restoration_mismatch", actual, expected }));
            throw new InvalidOperationException("Precombat readback differs from historical native observation.");
        }
        }
        return new { status = compareHistorical ? "request_restoration_matched" : "request_restored", productionReady = false, productionLabels = false,
            scope = "precombat deck/relic restoration and protocol-3 readback only; no map RNG, room entry or battle",
            attemptId = fixture.GetProperty("attemptId").GetInt32(), initialHp = Read(observed, "InitialHp"), initialMaxHp = Read(observed, "InitialMaxHp"), actual };
    }
}
