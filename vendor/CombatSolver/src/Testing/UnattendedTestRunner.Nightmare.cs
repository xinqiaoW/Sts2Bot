using System.Reflection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Afflictions;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static void AssertNightmareSnapshot(CombatState live, Player player)
    {
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        SimulatedCombatState State(CombatPredictionSimulator sim) => (SimulatedCombatState)sim.State.CombatState;
        PredictedCard source = PredictedCard.Create(ModelDb.Card<StrikeSilent>(), player);
        source.Afflict((Smog)ModelDb.Affliction<Smog>().ToMutable(), 1);
        root.AddGeneratedCardsToCombat(new[] { source }, PileType.Discard, player,
            CardPilePosition.Bottom, CardGenerationResultKind.Fixed);
        CardModel nativeSource = source.Preview.CreateClone();
        NightmarePower native = (NightmarePower)ModelDb.Power<NightmarePower>().ToMutable();
        native._owner = player.Creature;
        native._amount = 3;
        native.SetSelectedCard(nativeSource);
        object data = typeof(PowerModel).GetField("_internalData", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(native)!;
        CardModel template = (CardModel)data.GetType().GetField("selectedCard")!.GetValue(data)!;
        string expected = CardChoiceSupport.ChoiceCardKey(template.CreateClone());
        NightmarePower predicted = State(root).AddPowerInstance<NightmarePower>(player.Creature, 3, player.Creature);
        State(root).SetNightmareSelection(predicted, source);
        if (source.Preview.Affliction == null || State(root).GetNightmareSelection(predicted).Affliction != null)
            throw new InvalidOperationException("Nightmare must clear the snapshot's affliction without changing its source.");
        nativeSource.UpgradeInternal();
        nativeSource.FinalizeUpgradeInternal();
        source.Upgrade();
        CombatPredictionSimulator fork = root.Fork();
        foreach (CombatPredictionSimulator sim in new[] { root, fork })
        {
            PredictedCard[] before = sim.State.GetPlayerCombatState(player).Hand.Cards.ToArray();
            if (State(sim).PrepareBeforeHandDraw(sim, player))
                throw new InvalidOperationException("Nightmare fixture unexpectedly requires a choice.");
            PredictedCard[] copies = sim.State.GetPlayerCombatState(player).Hand.Cards.Except(before).ToArray();
            if (copies.Length != 3 || copies.Any(card => CardChoiceSupport.ChoiceCardKey(card) != expected))
                throw new InvalidOperationException("Nightmare copies changed after the selected source was upgraded.");
            if (State(sim).EffectivePowers().OfType<NightmarePower>().Any(power => power.Amount > 0))
                throw new InvalidOperationException("Nightmare power survived its next draw.");
        }
        if (CardChoiceSupport.ChoiceCardKey(template.CreateClone()) != expected)
            throw new InvalidOperationException("Native Nightmare snapshot unexpectedly changed with its source.");

        // Start a new prediction root while the original power is already active.
        // Its internal selectedCard is reset by PowerModel.DeepCloneFields, so
        // capturing only the ordinary power clone loses this delayed effect.
        native.ApplyInternal(player.Creature, 3, silent: true);
        try
        {
            CombatPredictionSimulator captured = new(new SimulatedCombatState(live));
            NightmarePower capturedPower = State(captured).EffectivePowers().OfType<NightmarePower>().Single();
            if (CardChoiceSupport.ChoiceCardKey(State(captured).GetNightmareSelection(capturedPower)) != expected)
                throw new InvalidOperationException("Nightmare root did not capture its original selected template.");
            string liveStamp = ContinuationStamp.CaptureLive(live).StateText;
            if (!liveStamp.Contains("/nightmare=STRIKE_SILENT+0", StringComparison.Ordinal))
                throw new InvalidOperationException("Nightmare selected template is absent from the actual state stamp.");
            template.UpgradeInternal();
            template.FinalizeUpgradeInternal();
            if (CardChoiceSupport.ChoiceCardKey(State(captured).GetNightmareSelection(capturedPower)) != expected)
                throw new InvalidOperationException("Nightmare root retained a mutable live template.");
            CombatPredictionSimulator child = captured.Fork();
            if (State(child).PrepareBeforeHandDraw(child, player))
                throw new InvalidOperationException("Captured Nightmare unexpectedly requires a choice.");
            if (!State(captured).EffectivePowers().OfType<NightmarePower>().Any(power => power.Amount == 3))
                throw new InvalidOperationException("Nightmare child consumed its parent's power.");
            if (child.State.GetPlayerCombatState(player).Hand.Cards.Count(card =>
                    CardChoiceSupport.ChoiceCardKey(card) == expected) < 3)
                throw new InvalidOperationException("Captured Nightmare did not generate its frozen copies.");
        }
        finally
        {
            native.RemoveInternal();
        }
    }
}
