using System.Text.Json;

internal static class RequestExecution
{
    public static JsonElement Envelope(JsonElement request)
    {
        string[] allowed = ["schemaVersion", "runId", "scenarioId", "characterId", "ascension", "seed", "encounterId",
            "actIndexForTest", "trainingCollection", "trainingActId", "clearRunDeck", "runCards", "cards", "potions", "relics",
            "potionPolicyForTest", "forceShortSearchOnly", "shortSearchBudgetOverrideMilliseconds", "searchMaxDegreeOfParallelismForTest",
            "enableNoGcRegionForTest", "performancePresetForTest", "headlessFastModeForTest", "deploymentFastModeForTest",
            "deploymentInterActionDelaySecondsForTest", "enableDetailedDiagnosticLogsForTest", "timeoutSeconds", "exitOnComplete"];
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (JsonProperty property in request.EnumerateObject())
            if (!allowed.Contains(property.Name) || !names.Add(property.Name))
                throw new NotSupportedException("Unknown or duplicate request field: " + property.Name);
        foreach (string name in allowed)
            if (!names.Contains(name)) throw new InvalidOperationException("Missing request field: " + name);
        void EqualsValue(string key, object expected)
        {
            if (!JsonElement.DeepEquals(request.GetProperty(key), JsonSerializer.SerializeToElement(expected)))
                throw new NotSupportedException("Unsupported request policy: " + key);
        }
        EqualsValue("schemaVersion", 1); EqualsValue("characterId", "SILENT"); EqualsValue("ascension", 10);
        EqualsValue("trainingCollection", true); EqualsValue("clearRunDeck", true); EqualsValue("potionPolicyForTest", "Disabled");
        EqualsValue("forceShortSearchOnly", true); EqualsValue("shortSearchBudgetOverrideMilliseconds", 8000);
        EqualsValue("searchMaxDegreeOfParallelismForTest", 1); EqualsValue("enableNoGcRegionForTest", false);
        EqualsValue("performancePresetForTest", "Medium"); EqualsValue("headlessFastModeForTest", "Instant");
        EqualsValue("deploymentFastModeForTest", "Instant"); EqualsValue("deploymentInterActionDelaySecondsForTest", 0);
        EqualsValue("enableDetailedDiagnosticLogsForTest", false); EqualsValue("timeoutSeconds", 120); EqualsValue("exitOnComplete", false);
        foreach (string key in new[] { "runId", "scenarioId", "seed", "encounterId", "trainingActId" })
            if (string.IsNullOrWhiteSpace(request.GetProperty(key).GetString())) throw new InvalidOperationException("Empty " + key);
        if (request.GetProperty("cards").GetArrayLength() != 0 || request.GetProperty("potions").GetArrayLength() != 0
            || request.GetProperty("runCards").GetArrayLength() == 0)
            throw new NotSupportedException("Only complete precombat decks and no potions are supported.");
        return JsonSerializer.SerializeToElement(new { request, attemptId = 0 });
    }
    public static object Result(JsonElement request, object restored, object completed, string? progressSnapshot = null)
    {
        JsonElement initial = JsonSerializer.SerializeToElement(restored), terminal = JsonSerializer.SerializeToElement(completed);
        int hp = terminal.GetProperty("finalHp").GetInt32(), initialHp = initial.GetProperty("initialHp").GetInt32();
        return new { schemaVersion = 1, status = "StandaloneCompleted", productionReady = false, productionLabels = false,
            runId = request.GetProperty("runId").GetString(), scenarioId = request.GetProperty("scenarioId").GetString(),
            combatEnded = true, collectionRequest = request,
            finishedTurn = terminal.GetProperty("finishedTurn").GetInt32(),
            finishedAtUtc = terminal.GetProperty("finishedAtUtc").GetDateTimeOffset(),
            provenance = new { backend = "standalone-managed-native", collectorProtocol = 3,
                gameSha256 = HostAdapter.GameHash, solverSha256 = HostAdapter.SolverHash,
                hostSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(System.Reflection.Assembly.GetExecutingAssembly().Location))).ToLowerInvariant(),
                testMode = true, unlockState = progressSnapshot == null ? "all" : "progress-snapshot",
                progressSnapshotSha256 = HostAdapter.ProgressSnapshotSha256,
                productionValidated = false },
            trainingObservation = new { complete = true, initialHp,
                initialMaxHp = initial.GetProperty("initialMaxHp").GetInt32(), finalHp = hp,
                finalMaxHp = terminal.GetProperty("finalMaxHp").GetInt32(), netHpLoss = initialHp - hp,
                playerDied = hp <= 0, initialBuild = initial.GetProperty("actual"),
                finalCombatState = terminal.GetProperty("finalCombatState").GetString() },
            execution = terminal.GetProperty("battle") };
    }
}
