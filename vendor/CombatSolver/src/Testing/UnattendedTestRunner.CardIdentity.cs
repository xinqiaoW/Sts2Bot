using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using CombatSolver.Engine.Common;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static void AssertCardIdentitySurvivesPreviewReplacement(Player player)
    {
        PredictedCard root = new(PredictionUtils.CreateCard(ModelDb.Card<Regret>(), player));
        ((Regret)root.MutablePreview).CardsInHand = 2;
        CardModel listener = root.Preview;
        using PredictionForkContext leftContext = new();
        using PredictionForkContext rightContext = new();
        PredictedCard left = root.Fork(leftContext);
        PredictedCard right = root.Fork(rightContext);
        SimCardPile hand = new(PileType.Hand, new[] { left });
        ((Regret)left.MutablePreview).CardsInHand = 5;
        ((Regret)right.MutablePreview).CardsInHand = 7;
        if (!ReferenceEquals(hand.Find(listener), left))
            throw new InvalidOperationException("An earlier hook's card reference was lost after COW.");
        if (((Regret)root.Preview).CardsInHand != 2
            || ((Regret)left.Preview).CardsInHand != 5
            || ((Regret)right.Preview).CardsInHand != 7)
            throw new InvalidOperationException("Card identity resolution crossed branch state ownership.");

        CardModel secondListener = left.Preview;
        using PredictionForkContext nextContext = new();
        PredictedCard next = left.Fork(nextContext);
        ((Regret)next.MutablePreview).CardsInHand = 9;
        if (!next.References(listener) || !next.References(secondListener))
            throw new InvalidOperationException("Card identity did not survive successive forks.");
        PredictedCard other = PredictedCard.Create(ModelDb.Card<Regret>(), player);
        if (other.References(listener) || next.References(other.Preview))
            throw new InvalidOperationException("Distinct copies of the same card shared an identity.");
        hand.Remove(left);
        if (hand.Find(listener) is not null)
            throw new InvalidOperationException("A departed card was resolved in its former pile.");
    }
}
