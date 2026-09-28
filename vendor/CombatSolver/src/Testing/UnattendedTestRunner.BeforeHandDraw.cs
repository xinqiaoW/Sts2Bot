using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static async Task AssertBeforeHandDrawOrderAsync(CombatState live, Player player, string scenario)
    {
        T Apply<T>(int amount) where T : PowerModel
        {
            T power = (T)ModelDb.Power<T>().ToMutable();
            power.ApplyInternal(player.Creature, amount, silent: true);
            return power;
        }
        void Nightmare(int index)
        {
            NightmarePower power = Apply<NightmarePower>(3);
            power.SetSelectedCard(player.PlayerCombatState!.Hand.Cards[index]);
        }
        switch (scenario)
        {
            case "blades-nightmare":
            case "ninja-overflow":
                Apply<InfiniteBladesPower>(1);
                Nightmare(0);
                break;
            case "nightmare-blades":
                Nightmare(0);
                Apply<InfiniteBladesPower>(1);
                break;
            case "interleaved-instances":
                Nightmare(0);
                Apply<InfiniteBladesPower>(1);
                Nightmare(1);
                Apply<SentryModePower>(2);
                break;
            case "random-after-fixed":
                Apply<InfiniteBladesPower>(1);
                HelloWorldPower hello = Apply<HelloWorldPower>(2);
                hello.AmountOnTurnStart = 2;
                Nightmare(0);
                break;
            default:
                throw new ArgumentException("Unknown BeforeHandDraw fixture: " + scenario);
        }
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        CombatPredictionSimulator fork = root.Fork();
        IntentForecast forecast = IntentForecaster.Build(live, 1);
        int turn = player.PlayerCombatState.TurnNumber;
        await Hook.BeforeHandDraw(live, player, new ThrowingPlayerChoiceContext());
        ContinuationStamp actual = ContinuationStamp.CaptureLive(live);
        foreach (CombatPredictionSimulator simulator in new[] { root, fork })
        {
            SimulatedCombatState state = (SimulatedCombatState)simulator.State.CombatState;
            if (state.PrepareBeforeHandDraw(simulator, player))
                throw new InvalidOperationException("BeforeHandDraw order fixture unexpectedly requires a choice.");
            PowerLifecycleSupport.ResolvePowerAmountChanges(simulator, state);
            ContinuationStamp predicted = ContinuationStamp.CapturePredicted(player, simulator, turn, forecast, turn);
            if (predicted.StateText != actual.StateText)
                throw new InvalidOperationException("BeforeHandDraw full state differs: " + predicted.DescribeFirstDifference(actual));
        }
    }
}
