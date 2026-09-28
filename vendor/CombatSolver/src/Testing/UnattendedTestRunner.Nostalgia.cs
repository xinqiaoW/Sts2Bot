using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Mirrors.Hooks.Card;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static void AssertNostalgiaTurnHistory(CombatState live, Player player)
    {
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        SimulatedCombatState State(CombatPredictionSimulator sim) => (SimulatedCombatState)sim.State.CombatState;
        State(root).Apply<NostalgiaPower>(player.Creature, 2, player.Creature);
        PowerLifecycleSupport.ResolvePowerAmountChanges(root, State(root));
        PredictedCard attack = PredictedCard.Create(ModelDb.Card<StrikeSilent>(), player);
        PredictedCard skill = PredictedCard.Create(ModelDb.Card<DefendSilent>(), player);
        PredictedCard powerCard = PredictedCard.Create(ModelDb.Card<Footwork>(), player);
        void Check(CombatPredictionSimulator sim, PileType expected, string boundary, int expectedStarts = 0)
        {
            NostalgiaPower power = State(sim).GetPower<NostalgiaPower>(player.Creature)!;
            CardLocation actual = ModifyCardPlayResultLocationMirrors.Invoke(power, new()
            {
                Simulator = sim, Card = attack, IsAutoPlay = false, Resources = new ResourceInfo { EnergySpent = 0, EnergyValue = 0, StarsSpent = 0, StarValue = 0 },
                Location = new CardLocation { pileType = PileType.Discard, position = CardPilePosition.Bottom }
            });
            System.Text.StringBuilder text = new();
            State(sim).AppendPredictedTurnCardHistory(text, player);
            int starts = expected == PileType.Discard ? 2 : expectedStarts;
            if (!text.ToString().EndsWith($";nostalgiaStarts={starts}", StringComparison.Ordinal))
                throw new InvalidOperationException($"Nostalgia {boundary}: continuation omitted or changed start count: {text}.");
            if (actual.pileType != expected)
                throw new InvalidOperationException($"Nostalgia {boundary}: expected {expected}, got {actual.pileType}.");
        }
        void Start(CombatPredictionSimulator sim, PredictedCard card, int index = 0)
        {
            CardPlay play = new() { Card = card.Preview, Player = player, Target = null, Resources = new ResourceInfo { EnergySpent = 0, EnergyValue = 0, StarsSpent = 0, StarValue = 0 },
                ResultPile = PileType.Discard, IsAutoPlay = true, PlayIndex = index, PlayCount = 2 };
            sim.History.CardPlayStarted(card, play);
            ((ICombatPredictionCardExecutionSink)State(sim)).RecordCardPlayStarted(card, play);
        }
        StateFingerprint Fingerprint(CombatPredictionSimulator sim)
        {
            StateFingerprintBuilder builder = new();
            State(sim).AppendFingerprint(ref builder, sim);
            return builder.Finish();
        }
        Check(root, PileType.Draw, "empty history");
        Start(root, powerCard);
        Check(root, PileType.Draw, "power excluded");
        Start(root, attack);
        Check(root, PileType.Draw, "outer attack started but not finished", 1);
        CombatPredictionSimulator left = root.Fork(), right = root.Fork();
        StateFingerprint beforeRepeat = Fingerprint(left);
        Start(left, attack, 1);
        Check(left, PileType.Discard, "repeat counts as another start");
        bool repeatChangesFingerprint = Fingerprint(left) != beforeRepeat;
        Check(root, PileType.Draw, "parent isolated", 1);
        Check(right, PileType.Draw, "sibling isolated", 1);
        Start(right, skill);
        Check(right, PileType.Discard, "nested skill start");
        State(left).CurrentSide = CombatSide.Enemy;
        Check(left, PileType.Draw, "enemy side resets history");
        Start(left, attack); Start(left, skill);
        Check(left, PileType.Discard, "enemy side starts counted");
        State(left).CurrentSide = CombatSide.Player;
        Check(left, PileType.Draw, "player side resets history");
        Start(left, attack); Start(left, skill);
        State(left).AdvancePlayerTurn(player);
        Check(left, PileType.Draw, "extra player turn resets history");
        Start(left, attack); Start(left, skill);
        State(left).RoundNumber++;
        Check(left, PileType.Draw, "next round resets history");
        Check(right, PileType.Discard, "turn changes isolated from sibling");
        if (!repeatChangesFingerprint)
            throw new InvalidOperationException("Nostalgia repeat did not change branch fingerprint.");
    }
}
