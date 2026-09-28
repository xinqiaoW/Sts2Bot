using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.ValueProps;
using CombatSolver.Engine.InCombat.Mirrors.Cards;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    // Invoked only by isolated directed fixtures; no hooks installed in normal play.
    private static Action? _turnEndNativeObserver;
    private static Action<CombatPredictionSimulator>? _turnEndPredictedObserver;
    private static void ObserveNativeTurnEndCard() => _turnEndNativeObserver!();
    private static void ObservePredictedTurnEndCard(CombatPredictionSimulator simulator)
        => _turnEndPredictedObserver!(simulator);

    private static async Task AssertTurnEndCardsAsync(CombatState live, Player player, string scenario)
    {
        if (scenario == "dealer-snapshot")
        {
            await AssertTurnEndDamageDealerSnapshotAsync(live, player);
            return;
        }
        await ClearPlayerPilesAsync(player);
        CardModel[] models = scenario switch
        {
            "burn-lethal" or "burn-survive" => Enumerable.Repeat<CardModel>(ModelDb.Card<Burn>(), 5).ToArray(),
            "regret-lethal" => Enumerable.Repeat<CardModel>(ModelDb.Card<Regret>(), 5).ToArray(),
            "mixed" => [ModelDb.Card<Burn>(), ModelDb.Card<Doubt>(), ModelDb.Card<Regret>(), ModelDb.Card<Beckon>(), ModelDb.Card<Wither>()],
            _ => throw new ArgumentException("Unknown turn-end fixture: " + scenario),
        };
        await CreatureCmd.SetCurrentHp(player.Creature, scenario.EndsWith("lethal", StringComparison.Ordinal) ? 5 : 70);
        foreach (CardModel model in models)
            await CardPileCmd.Add(live.CreateCard(model, player), PileType.Hand);
        await Hook.BeforeSideTurnEnd(live, CombatSide.Player, [player.Creature]);
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        CombatPredictionSimulator fork = root.Fork();
        IntentForecast forecast = IntentForecaster.Build(live, 1);
        int turn = player.PlayerCombatState!.TurnNumber;
        var actual = new List<ContinuationStamp>();
        var predicted = new List<ContinuationStamp>();
        _turnEndNativeObserver = () => actual.Add(ContinuationStamp.CaptureLive(live));
        _turnEndPredictedObserver = sim => predicted.Add(ContinuationStamp.CapturePredicted(player, sim, turn, forecast, turn));
        Harmony harmony = new("CombatSolver.IsolatedTurnEndCards");
        MethodInfo nativeHook = typeof(CardModel).GetMethod(nameof(CardModel.OnTurnEndInHandWrapper))!;
        MethodInfo predictedHook = typeof(CardOnTurnEndInHandMirrors).GetMethod(nameof(CardOnTurnEndInHandMirrors.Invoke))!;
        try
        {
            harmony.Patch(nativeHook, prefix: new HarmonyMethod(typeof(UnattendedTestRunner), nameof(ObserveNativeTurnEndCard)));
            harmony.Patch(predictedHook, prefix: new HarmonyMethod(typeof(UnattendedTestRunner), nameof(ObservePredictedTurnEndCard)));
            CombatManager manager = CombatManager.Instance;
            object turnState = typeof(CombatManager).GetField("_turnState", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(manager)!;
            MethodInfo native = typeof(CombatManager).GetMethod("DoTurnEndCards", BindingFlags.Instance | BindingFlags.NonPublic)!;
            await (Task)native.Invoke(manager, [turnState, player.PlayerCombatState.Hand.Cards.ToList(), new ThrowingPlayerChoiceContext()])!;
            ContinuationStamp final = ContinuationStamp.CaptureLive(live);
            if (actual.Count != models.Length) throw new InvalidOperationException("Missing original turn-end card observations.");
            foreach (CombatPredictionSimulator simulator in new[] { root, fork })
            {
                predicted.Clear();
                typeof(CombatPredictionSimulator).GetMethod("DoTurnEndCards", BindingFlags.Instance | BindingFlags.NonPublic)!
                    .Invoke(simulator, [simulator.State.GetPlayerCombatState(player).Hand.Cards.ToArray()]);
                if (predicted.Count != actual.Count) throw new InvalidOperationException("Missing predicted turn-end card observations.");
                for (int index = 0; index < actual.Count; index++)
                    if (predicted[index].StateText != actual[index].StateText)
                        throw new InvalidOperationException($"Turn-end card {index} differs: " + predicted[index].DescribeFirstDifference(actual[index]));
                ContinuationStamp after = ContinuationStamp.CapturePredicted(player, simulator, turn, forecast, turn);
                if (after.StateText != final.StateText)
                    throw new InvalidOperationException("Turn-end final state differs: " + after.DescribeFirstDifference(final));
            }
        }
        finally
        {
            harmony.Unpatch(nativeHook, HarmonyPatchType.All, harmony.Id);
            harmony.Unpatch(predictedHook, HarmonyPatchType.All, harmony.Id);
            _turnEndNativeObserver = null;
            _turnEndPredictedObserver = null;
        }
    }

    private static async Task AssertTurnEndDamageDealerSnapshotAsync(CombatState live, Player player)
    {
        var dealer = live.Enemies.First(enemy => enemy.IsAlive);
        int hp = dealer.CurrentHp;
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        CombatPredictionSimulator fork = root.Fork();
        await CreatureCmd.SetCurrentHp(dealer, 0);
        foreach (CombatPredictionSimulator simulator in new[] { root, fork })
        {
            int before = simulator.State.GetCreature(player.Creature).CurrentHp;
            simulator.Damage(player.Creature, 1, ValueProp.Unpowered | ValueProp.Unblockable, dealer);
            simulator.Damage([player.Creature], 1, ValueProp.Unpowered | ValueProp.Unblockable, dealer);
            if (simulator.State.GetCreature(player.Creature).CurrentHp != before - 2)
                throw new InvalidOperationException("Damage read live dealer death after root capture.");
        }
        await CreatureCmd.SetCurrentHp(dealer, hp);
        foreach (CombatPredictionSimulator simulator in new[] { root, fork })
        {
            simulator.State.GetCreature(dealer).CurrentHp = 0;
            int before = simulator.State.GetCreature(player.Creature).CurrentHp;
            simulator.Damage(player.Creature, 1, ValueProp.Unpowered | ValueProp.Unblockable, dealer);
            simulator.Damage([player.Creature], 1, ValueProp.Unpowered | ValueProp.Unblockable, dealer);
            if (simulator.State.GetCreature(player.Creature).CurrentHp != before)
                throw new InvalidOperationException("Dead branch dealer damaged a target while live dealer survived.");
        }
    }
}
