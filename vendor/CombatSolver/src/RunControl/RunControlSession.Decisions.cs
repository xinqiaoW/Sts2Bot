using System.Text.Json;
using System.Text.Json.Nodes;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Rooms;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    private string? _lastDecisionFingerprint;
    private int _identicalDecisions;
    // Only owned cards/relics, recorded history and the currently displayed act
    // map cross this boundary. No future encounters/events, rewards or RNG.
    private object DecisionState()
    {
        List<object[]> history = [];
        for (int act = 0; act < Run.MapPointHistory.Count; act++)
            foreach (var point in Run.MapPointHistory[act])
                foreach (var chosen in point.GetEntry(Me.NetId).AncientChoices.Where(c => c.WasChosen))
                {
                    var events = point.Rooms.Where(r => r.ModelId != null && r.ModelId.ToString().StartsWith("EVENT.", StringComparison.Ordinal)).ToArray();
                    if (events.Length != 1) throw new InvalidDataException("Ambiguous recorded ancient choice.");
                    history.Add([act + 1, events[0].ModelId!.Entry, chosen.TextKey]);
                }
        var current = Run.CurrentMapPoint;
        CardAdvisorProgress progress = CardAdvisorCapture.Progress(Run);
        bool afterFirstBoss = current != null && current.coord.row >= Run.Map.BossMapPoint.coord.row;
        MapPoint targetBoss = afterFirstBoss && Run.Map.SecondBossMapPoint != null
            ? Run.Map.SecondBossMapPoint : Run.Map.BossMapPoint;
        var visibleBoss = (ReferenceEquals(targetBoss, Run.Map.SecondBossMapPoint)
            ? Run.Act.SecondBossEncounter : Run.Act.BossEncounter)
            ?? throw new InvalidDataException("Visible boss map point has no boss model.");
        return new
        {
            act = Run.CurrentActIndex + 1, actId = Run.Act.Id.Entry, floor = Run.TotalFloor,
            actFloor = Run.ActFloor, ascension = Run.AscensionLevel,
            // Count only recorded normal rooms, not event-triggered fights.
            // Before entering the new act's first node, its history list has
            // not been created yet; there are exactly zero recorded combats.
            normalCombatsCompleted = progress.NormalCombatsCompleted,
            actBossDefeated = progress.ActBossDefeated,
            hp = Me.Creature.CurrentHp, maxHp = Me.Creature.MaxHp, gold = Me.Gold,
            build = new { act_id = Run.Act.Id.Entry, act = Run.CurrentActIndex + 1, family = "autobot",
                cards = Me.Deck.Cards.Select(CardAdvisorCapture.Card).ToArray(),
                relics = Me.Relics.Select(CardAdvisorCapture.Relic).ToArray(), ancient_history = history },
            potions = Me.PotionSlots.Select((p, slot) => new { slot, id = p?.Id.Entry }).ToArray(),
            currentNode = current == null ? null : new { row = current.coord.row, col = current.coord.col },
            // Boss icons are displayed by NBossMapPoint. Switch the scoring
            // target only after reaching the first boss; normal nodes never
            // export their future encounter identity.
            visibleBoss = visibleBoss.Id.Entry,
            floorsToBoss = current == null ? targetBoss.coord.row : Math.Max(0, targetBoss.coord.row - current.coord.row),
            map = Run.Map.GetAllMapPoints().Concat(new[] { Run.Map.StartingMapPoint, Run.Map.BossMapPoint })
                .Concat(Run.Map.SecondBossMapPoint is { } second ? new[] { second } : Array.Empty<MapPoint>()).Distinct().Select(p => new
            {
                row = p.coord.row, col = p.coord.col, type = p.PointType.ToString(),
                children = p.Children.Select(c => new { row = c.coord.row, col = c.coord.col }).ToArray(),
            }).ToArray(),
        };
    }

    private async Task<int> ChooseAsync(string screen, IReadOnlyList<object> options, object? context, CancellationToken ct)
    {
        if (options.Count == 0) throw new InvalidDataException($"No legal options for {screen}.");
        int seq = ++_decisionSequence;
        JsonObject[] indexed = options.Select((option, index) =>
        {
            JsonObject value = JsonSerializer.SerializeToNode(option, RunControlFiles.Json)!.AsObject();
            value["index"] = index;
            return value;
        }).ToArray();
        object state = request.DecisionMode == "all" ? DecisionState() : State();
        string fingerprint = JsonSerializer.Serialize(new { screen, state, options = indexed, context }, RunControlFiles.Json);
        _identicalDecisions = fingerprint == _lastDecisionFingerprint ? _identicalDecisions + 1 : 0;
        _lastDecisionFingerprint = fingerprint;
        if (_identicalDecisions >= 3) throw new InvalidOperationException($"Repeated decision without state/UI progress: {screen}");
        object decision = new { schemaVersion = 1, request.RunId, decisionSeq = seq, screen, state, options = indexed, context };
        files.Record("decision", decision);
        await RunControlFiles.AtomicWriteAsync(files.DecisionPath, decision, ct);
        await RunControlActionWait.WaitAsync(files.ActionPath, request.ActionTimeoutSeconds, screen, seq, ct);
        RunControlAction action = JsonSerializer.Deserialize<RunControlAction>(File.ReadAllText(files.ActionPath), RunControlFiles.Json)
            ?? throw new InvalidDataException("Empty action.");
        if (action.SchemaVersion != 1 || action.RunId != request.RunId || action.DecisionSeq != seq
            || action.Choice < 0 || action.Choice >= options.Count)
            throw new InvalidDataException("Stale, duplicate, foreign, or invalid action.");
        File.Move(files.ActionPath, Path.Combine(files.DirectoryPath, $"action-{seq:D5}.json"));
        Record("action", action);
        return action.Choice;
    }
}
