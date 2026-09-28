using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static void AssertReturnToHandOrder(CombatState live, Player player)
    {
        foreach (CardModel canonical in new CardModel[] { ModelDb.Card<Bolas>(), ModelDb.Card<ThrummingHatchet>() })
        {
            CombatPredictionSimulator root = new(new SimulatedCombatState(live));
            SimulatedCombatState State(CombatPredictionSimulator sim) => (SimulatedCombatState)sim.State.CombatState;
            PredictedCard first = PredictedCard.Create(canonical, player);
            first.MutablePreview.DeckVersion = player.Deck.Cards[0];
            PredictedCard second = first.CreateClone();
            root.AddGeneratedCardsToCombat(new[] { first, second }, PileType.Discard, player,
                CardPilePosition.Bottom, CardGenerationResultKind.Fixed);
            void Mark(CombatPredictionSimulator sim, PredictedCard card) => State(sim).RecordCardLifecycle(sim, card);
            void Return(CombatPredictionSimulator sim)
            {
                if (State(sim).PrepareBeforeHandDraw(sim, player))
                    throw new InvalidOperationException("Return-order fixture unexpectedly requires a choice.");
            }
            void Check(CombatPredictionSimulator sim, string boundary)
            {
                PredictedCard[] cards = sim.State.GetPlayerCombatState(player).Hand.Cards
                    .Where(card => card.Preview.GetType() == canonical.GetType()).ToArray();
                if (cards.Length != 2 || cards[0].Preview.DeckVersion == null || cards[1].Preview.DeckVersion != null)
                    throw new InvalidOperationException($"{canonical.Id.Entry} {boundary}: return order differs from pile listener order.");
            }
            Mark(root, first); Mark(root, second);
            Return(root); Check(root, "first cycle");
            root.AddToPile(new[] { first, second }, PileType.Discard);
            // Removing the first cycle's entries leaves HashSet free slots. A
            // fork rebuilds an empty set and must behave exactly like its parent.
            CombatPredictionSimulator fork = root.Fork();
            PredictedCard left = fork.State.GetPlayerCombatState(player).FindCard(first.Original)!;
            PredictedCard right = fork.State.GetPlayerCombatState(player).FindCard(second.Original)!;
            Mark(root, first); Mark(root, second);
            Mark(fork, left); Mark(fork, right);
            Return(root); Check(root, "reused pending set");
            Return(fork); Check(fork, "forked pending set");

            root.AddToPile(new[] { first, second }, PileType.Discard);
            CombatPredictionSimulator pendingFirst = root.Fork(), pendingSecond = root.Fork();
            Mark(pendingFirst, pendingFirst.State.GetPlayerCombatState(player).FindCard(first.Original)!);
            Mark(pendingSecond, pendingSecond.State.GetPlayerCombatState(player).FindCard(second.Original)!);
            StateFingerprint Fingerprint(CombatPredictionSimulator sim)
            {
                StateFingerprintBuilder builder = new();
                State(sim).AppendFingerprint(ref builder, sim);
                return builder.Finish();
            }
            if (Fingerprint(pendingFirst) == Fingerprint(pendingSecond))
                throw new InvalidOperationException("Return history conflated distinct same-name card instances.");
        }
    }
}
