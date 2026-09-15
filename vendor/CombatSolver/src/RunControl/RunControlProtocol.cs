using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Godot;

namespace CombatSolver;

// This is a separate envelope on the existing exclusive request mailbox. The
// single-combat schema and training-observation versions are unchanged.
internal sealed record RunControlRequest
{
    public int SchemaVersion { get; init; } = 1;
    public string Kind { get; init; } = "run";
    public string RunId { get; init; } = "";
    public string Seed { get; init; } = "";
    public string CharacterId { get; init; } = "SILENT";
    public int Ascension { get; init; } = 10;
    public string CombatMode { get; init; } = "solver";
    public int PolicySeed { get; init; }
    public int TimeoutSeconds { get; init; } = 3600;
    public int ActionTimeoutSeconds { get; init; } = 60;
    public int CombatTimeoutSeconds { get; init; } = 120;

    public void Validate()
    {
        if (SchemaVersion != 1 || Kind != "run" || CharacterId != "SILENT" || Ascension != 10
            || CombatMode != "solver" || !Regex.IsMatch(RunId, "^[a-zA-Z0-9_-]{1,80}$")
            || string.IsNullOrWhiteSpace(Seed) || Seed.Length > 100
            || TimeoutSeconds is < 1 or > 14400 || ActionTimeoutSeconds is < 1 or > 300
            || CombatTimeoutSeconds is < 1 or > 120)
            throw new InvalidDataException("Invalid run request: v1 supports Silent A10, solver combat, and bounded deadlines only.");
    }
}

internal sealed record RunControlAction
{
    public required int SchemaVersion { get; init; }
    public required string RunId { get; init; }
    public required int DecisionSeq { get; init; }
    public required int Choice { get; init; }
}

internal sealed class RunControlFiles
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = false,
        IncludeFields = true,
        Converters = { new JsonStringEnumConverter() },
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public string DirectoryPath { get; }
    public string DecisionPath => Path.Combine(DirectoryPath, "decision.json");
    public string ActionPath => Path.Combine(DirectoryPath, "action.json");
    private readonly string _runId;
    private int _eventSequence;

    public RunControlFiles(RunControlRequest request)
    {
        request.Validate();
        _runId = request.RunId;
        DirectoryPath = ProjectSettings.GlobalizePath($"user://combat_solver_runs/{request.RunId}");
        Directory.CreateDirectory(DirectoryPath);
        // A run ID is never reused, even following a crash.
        using FileStream claim = new(Path.Combine(DirectoryPath, "accepted.json"), FileMode.CreateNew);
        JsonSerializer.Serialize(claim, request, Json);
    }

    public static void AtomicWrite(string path, object value)
    {
        string temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(value, Json));
        File.Move(temp, path, true);
    }

    public void Record(string kind, object payload)
    {
        string line = JsonSerializer.Serialize(new
        {
            schemaVersion = 1, runId = _runId, eventSeq = ++_eventSequence,
            utc = DateTimeOffset.UtcNow, kind, payload,
        }, Json);
        File.AppendAllText(Path.Combine(DirectoryPath, "events.jsonl"), line + "\n");
    }

    public void Result(object result) => AtomicWrite(Path.Combine(DirectoryPath, "result.json"), result);
}
