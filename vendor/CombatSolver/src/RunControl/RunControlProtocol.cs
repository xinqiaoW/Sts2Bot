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
    public string CombatSearchMode { get; init; } = "evaluation8s";
    [JsonIgnore] public bool UsePlayerSearchSettings => CombatSearchMode == "settings";
    public string DecisionMode { get; init; } = "map";
    public int PolicySeed { get; init; }
    public int TimeoutSeconds { get; init; } = 3600;
    public int ActionTimeoutSeconds { get; init; } = 60;
    public int CombatTimeoutSeconds { get; init; } = 120;

    public void Validate()
    {
        if (SchemaVersion != 1 || Kind != "run" || CharacterId != "SILENT" || Ascension != 10
            || CombatMode != "solver" || CombatSearchMode is not ("evaluation8s" or "settings")
            || DecisionMode is not ("map" or "all") || !Regex.IsMatch(RunId, "^[a-zA-Z0-9_-]{1,80}$")
            || string.IsNullOrWhiteSpace(Seed) || Seed.Length > 100
            || TimeoutSeconds is < 1 or > 14400 || ActionTimeoutSeconds is < 1 or > 300
            || CombatTimeoutSeconds < 1 || CombatTimeoutSeconds > (UsePlayerSearchSettings ? 3600 : 120))
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

    internal static bool IsWindowsReplaceConflict(Exception error)
        => OperatingSystem.IsWindows()
            && error is IOException or UnauthorizedAccessException
            && (uint)(error.HResult & unchecked((int)0xffff0000)) == 0x80070000u
            && (error.HResult & 0xffff) is 5 or 32 or 33;

    public static async Task AtomicWriteAsync(string path, object value, CancellationToken ct = default)
    {
        ct.ThrowIfCancellationRequested();
        path = Path.GetFullPath(path);
        string temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        // Serialize once. Only publication is retried, never a game operation.
        File.WriteAllText(temp, JsonSerializer.Serialize(value, Json));
        for (int attempt = 0; ; attempt++)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                // ReplaceFile supports an existing snapshot's DELETE-sharing
                // readers; MoveFileEx(REPLACE_EXISTING) can still deny access.
                if (OperatingSystem.IsWindows() && File.Exists(path))
                    File.Replace(temp, path, null);
                else
                    File.Move(temp, path, true);
                return;
            }
            catch (Exception ex) when (IsWindowsReplaceConflict(ex))
            {
                // A reader/scanner can briefly deny DELETE sharing on Windows.
                // Genuine ACL/read-only failures stay failures after this bound.
                if (attempt == 20)
                    throw new IOException($"Could not publish run-control JSON '{path}' after 21 replacement attempts "
                        + $"(Windows error {ex.HResult & 0xffff}); temporary snapshot retained at '{temp}'.", ex);
                await Task.Delay(50, ct);
            }
        }
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

    public Task ResultAsync(object result) => AtomicWriteAsync(Path.Combine(DirectoryPath, "result.json"), result);
}
