using System.Reflection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Relics;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    // Directed native fixtures invoke this helper; ordinary collection never does.
    private static async Task AssertGamblingChipDiscardDrawAsync(CombatState live, Player player, string scenario)
    {
        await ClearPlayerPilesAsync(player);
        int slyCount = scenario == "two-sly-shuffle" ? 2 : 1;
        for (int index = 0; index < slyCount; index++)
            await CardPileCmd.Add(live.CreateCard(ModelDb.Card<Untouchable>(), player), PileType.Hand);
        await CardPileCmd.Add(live.CreateCard(ModelDb.Card<StrikeSilent>(), player), PileType.Hand);
        int drawCount = scenario == "no-shuffle" ? 8 : 1;
        for (int index = 0; index < drawCount; index++)
            await CardPileCmd.Add(live.CreateCard(ModelDb.Card<DefendSilent>(), player), PileType.Draw);
        RelicModel relic = player.Relics.OfType<GamblingChip>().SingleOrDefault()
            ?? await RelicCmd.Obtain(ModelDb.Relic<GamblingChip>().ToMutable(), player);
        CardModel[] selected = scenario == "empty" ? [] : player.PlayerCombatState!.Hand.Cards.ToArray();
        var occurrences = new Dictionary<string, int>();
        PlanCardToken[] tokens = selected.Select(card =>
        {
            int occurrence = occurrences.GetValueOrDefault(card.Id.Entry);
            occurrences[card.Id.Entry] = occurrence + 1;
            return new PlanCardToken(card.Id.Entry, card.CurrentUpgradeLevel, "", occurrence, occurrence, card.Id.Entry);
        }).ToArray();
        PlanCardChoice choice = new(PlanChoiceEffect.DiscardAndDraw, PileType.Hand, tokens,
            "GAMBLING_CHIP", "AFTER_PLAYER_TURN_START", PlanChoiceTiming.PlayerTurnStart);
        CombatRootSnapshot root = CombatRootSnapshot.Capture(live);
        CombatPredictionSimulator simulator = root.ForkSimulator();
        CombatPredictionSimulator fork = simulator.Fork();
        ContinuationStamp before = ContinuationStamp.CaptureLive(live);
        var predicted = new List<ContinuationStamp>();
        foreach (CombatPredictionSimulator branch in new[] { simulator, fork })
        {
            var combat = (SimulatedCombatState)branch.State.CombatState;
            TurnStartChoiceCursor cursor = new([choice]);
            combat.BeginActionChoices(cursor);
            combat.SetActionChoiceTiming(PlanChoiceTiming.PlayerTurnStart);
            try
            {
                if (!TurnStartChoiceSupport.ResolveDiscardAndDraw(branch, combat, player, cursor,
                        "GAMBLING_CHIP", "AFTER_PLAYER_TURN_START"))
                    throw new InvalidOperationException("Gambling Chip fixture left a pending choice.");
                cursor.AssertConsumed();
            }
            finally { combat.EndActionChoices(); }
            predicted.Add(ContinuationStamp.CapturePredicted(player, branch, root.StartTurnNumber,
                root.Forecast, root.StartTurnNumber));
        }
        if (ContinuationStamp.CaptureLive(live).StateText != before.StateText)
            throw new InvalidOperationException("Gambling Chip prediction mutated its live root.");
        if (predicted[0].StateText != predicted[1].StateText)
            throw new InvalidOperationException("Gambling Chip fork differs from direct prediction.");
        PlannedCardSelector selector = new(choice);
        using (CardSelectCmd.PushSelector(selector))
        {
            MethodInfo hook = typeof(GamblingChip).GetMethod(nameof(GamblingChip.AfterPlayerTurnStart))!;
            object[] args = hook.GetParameters().Select(parameter => parameter.ParameterType == typeof(Player)
                ? (object)player : new ThrowingPlayerChoiceContext()).ToArray();
            await (Task)hook.Invoke(relic, args)!;
        }
        selector.AssertConsumed();
        ContinuationStamp actual = ContinuationStamp.CaptureLive(live);
        if (predicted[0].StateText != actual.StateText)
            throw new InvalidOperationException("Gambling Chip discard/draw differs: " + predicted[0].DescribeFirstDifference(actual));
    }
}
