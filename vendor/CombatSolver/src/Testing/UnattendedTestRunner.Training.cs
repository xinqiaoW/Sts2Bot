using System.Text.Json;
using System.Reflection;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace CombatSolver;

internal sealed class UnattendedTrainingObservation
{
    public int InitialHp { get; set; }
    public int InitialMaxHp { get; set; }
    public int? FinalHp { get; set; }
    public int? FinalMaxHp { get; set; }
    public int? NetHpLoss { get; set; }
    public bool? PlayerDied { get; set; }
    public bool Complete { get; set; }
    public JsonElement InitialBuild { get; set; }
}

internal sealed partial class UnattendedTestRunner
{
    private UnattendedTrainingObservation? _trainingObservation;

    private void CaptureTrainingStart(Player player)
    {
        if (!_request.TrainingCollection) return;
        _trainingObservation = new UnattendedTrainingObservation
        {
            InitialHp = player.Creature.CurrentHp,
            InitialMaxHp = player.Creature.MaxHp,
            InitialBuild = JsonSerializer.SerializeToElement(new
            {
                Character = player.Character.Id.Entry,
                Ascension = _request.Ascension,
                ActId = _request.TrainingActId,
                ActIndex = _request.ActIndexForTest,
                Cards = player.Deck.Cards.Select(card => new
                {
                    Id = card.Id.Entry,
                    UpgradeLevel = card.CurrentUpgradeLevel,
                }).ToArray(),
                Relics = player.Relics.Select(relic => new
                {
                    Id = relic.Id.Entry,
                    State = relic.ToSerializable(),
                    Counters = CaptureTrainingRelicCounters(relic),
                }).ToArray(),
            }, UnattendedTestFiles.JsonOptions),
        };
    }

    private Dictionary<string, object> CaptureTrainingRelicCounters(RelicModel relic)
    {
        UnattendedRelicInjection? injection = _request.Relics.SingleOrDefault(item => item.RelicId == relic.Id.Entry);
        Dictionary<string, object> result = [];
        if (injection == null) return result;
        foreach (string name in injection.IntegerMembers.Keys.Concat(injection.BooleanMembers.Keys))
        {
            object? value = null;
            for (Type? type = relic.GetType(); type != null; type = type.BaseType)
            {
                const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
                if (type.GetProperty(name, flags) is { } property) { value = property.GetValue(relic); break; }
                if (type.GetField(name, flags) is { } field) { value = field.GetValue(relic); break; }
            }
            result.Add(name, value ?? throw new InvalidOperationException($"Missing training relic state: {relic.Id.Entry}.{name}"));
        }
        return result;
    }

    private void CaptureTrainingEnd(ScenarioContext scenario, ExecutionOutcome outcome)
    {
        if (!_request.TrainingCollection) return;
        UnattendedTrainingObservation observation = _trainingObservation
            ?? throw new InvalidOperationException("Training start state was not captured.");
        observation.FinalHp = scenario.Player.Creature.CurrentHp;
        observation.FinalMaxHp = scenario.Player.Creature.MaxHp;
        observation.PlayerDied = scenario.Player.Creature.IsDead;
        observation.Complete = outcome.CombatEnded;
        if (!observation.Complete)
            throw new InvalidOperationException("Training battle did not reach a terminal state.");
        observation.NetHpLoss = observation.InitialHp - observation.FinalHp;
        _writer.TrainingObservation = observation;
    }
}
