using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static async Task AssertPowerApplicationOrderAsync(CombatState live, Player player, string scenario)
    {
        SimulatedCombatState State(CombatPredictionSimulator sim) => (SimulatedCombatState)sim.State.CombatState;
        T ApplyLive<T>(int amount) where T : PowerModel
        {
            T power = (T)ModelDb.Power<T>().ToMutable();
            power.ApplyInternal(player.Creature, amount, silent: true);
            return power;
        }
        void AddNightmare(CombatPredictionSimulator sim, string cardId, bool alsoLive)
        {
            PredictedCard source = sim.State.GetPlayerCombatState(player).AllCards.First(card => card.Preview.Id.Entry == cardId);
            NightmarePower power = State(sim).AddPowerInstance<NightmarePower>(player.Creature, 3);
            State(sim).SetNightmareSelection(power, source);
            if (alsoLive)
                ApplyLive<NightmarePower>(3).SetSelectedCard(source.Preview);
        }
        StateFingerprint Fingerprint(CombatPredictionSimulator sim)
        {
            StateFingerprintBuilder builder = new();
            State(sim).AppendFingerprint(ref builder, sim);
            return builder.Finish();
        }
        InfiniteBladesPower? originalBlades = null;
        if (scenario == "remove-reapply-root")
        {
            originalBlades = ApplyLive<InfiniteBladesPower>(1);
            ApplyLive<SentryModePower>(1);
        }
        SlowPower? originalSlow = null;
        if (scenario == "slow-reset")
        {
            originalSlow = ApplyLive<SlowPower>(1);
            originalSlow.DynamicVars["SlowAmount"].BaseValue = 3;
            originalSlow.DynamicVars["DisplayAmount"].BaseValue = 30;
        }
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        IntentForecast forecast = IntentForecaster.Build(live, 1);
        int turn = player.PlayerCombatState!.TurnNumber;
        ContinuationStamp Stamp(CombatPredictionSimulator sim)
            => ContinuationStamp.CapturePredicted(player, sim, turn, forecast, turn);
        if (scenario == "slow-reset")
        {
            CombatPredictionSimulator child = root.Fork();
            await originalSlow!.AfterSideTurnStart(CombatSide.Player, [player.Creature], live);
            ContinuationStamp actualReset = ContinuationStamp.CaptureLive(live);
            foreach (CombatPredictionSimulator sim in new[] { root, child })
            {
                State(sim).TriggerSideTurnStart(sim, CombatSide.Player, [player.Creature], decrementPlating: false);
                SlowPower[] powers = State(sim).EffectivePowers().OfType<SlowPower>().ToArray();
                if (powers.Length != 1 || powers[0].DynamicVars["SlowAmount"].BaseValue != 0)
                    throw new InvalidOperationException("Slow reset left a stale or duplicate ordered power instance.");
                if (Stamp(sim).StateText != actualReset.StateText)
                    throw new InvalidOperationException("Slow reset full state differs: " + Stamp(sim).DescribeFirstDifference(actualReset));
                if (Fingerprint(sim) != Fingerprint(sim.Fork()))
                    throw new InvalidOperationException("Slow reset order changed during Fork.");
            }
            return;
        }
        if (scenario is "fingerprint-order" or "continuation-order" or "template-order")
        {
            CombatPredictionSimulator reverse = root.Fork();
            if (scenario == "template-order")
            {
                AddNightmare(root, "STRIKE_SILENT", false);
                AddNightmare(root, "DEFEND_SILENT", false);
                AddNightmare(reverse, "DEFEND_SILENT", false);
                AddNightmare(reverse, "STRIKE_SILENT", false);
            }
            else
            {
                State(root).SetAmount<InfiniteBladesPower>(player.Creature, 1);
                State(root).SetAmount<SentryModePower>(player.Creature, 1);
                State(reverse).SetAmount<SentryModePower>(player.Creature, 1);
                State(reverse).SetAmount<InfiniteBladesPower>(player.Creature, 1);
            }
            if (scenario != "continuation-order" && Fingerprint(root) == Fingerprint(reverse))
                throw new InvalidOperationException("Power order was erased from the search fingerprint: " + scenario);
            if (Stamp(root).StateText == Stamp(reverse).StateText)
                throw new InvalidOperationException("Power order was erased from the complete continuation: " + scenario);
            if (Fingerprint(root) != Fingerprint(root.Fork()) || Stamp(root).StateText != Stamp(root.Fork()).StateText)
                throw new InvalidOperationException("Power order changed during Fork.");
            return;
        }
        if (scenario == "added-interleaving")
        {
            AddNightmare(root, "STRIKE_SILENT", true);
            State(root).SetAmount<InfiniteBladesPower>(player.Creature, 1);
            ApplyLive<InfiniteBladesPower>(1);
            AddNightmare(root, "DEFEND_SILENT", true);
        }
        else if (scenario == "remove-reapply-root")
        {
            originalBlades!.RemoveInternal();
            State(root).SetAmount<InfiniteBladesPower>(player.Creature, 0);
            ApplyLive<InfiniteBladesPower>(1);
            State(root).SetAmount<InfiniteBladesPower>(player.Creature, 1);
        }
        else
            throw new ArgumentException("Unknown power order fixture: " + scenario);

        CombatPredictionSimulator fork = root.Fork();
        string nativeOrder = string.Join(",", player.Creature.Powers.Select(power => power.Id.Entry));
        foreach (CombatPredictionSimulator sim in new[] { root, fork })
        {
            string predictedOrder = string.Join(",", State(sim).EffectivePowers()
                .Where(power => ReferenceEquals(power.Owner, player.Creature)).Select(power => power.Id.Entry));
            if (nativeOrder != predictedOrder)
                throw new InvalidOperationException($"Power application order differs: live={nativeOrder}; predicted={predictedOrder}");
            ContinuationStamp before = ContinuationStamp.CaptureLive(live);
            if (before.StateText != Stamp(sim).StateText)
                throw new InvalidOperationException("Before-hand-draw root differs: " + Stamp(sim).DescribeFirstDifference(before));
        }
        await Hook.BeforeHandDraw(live, player, new ThrowingPlayerChoiceContext());
        ContinuationStamp actual = ContinuationStamp.CaptureLive(live);
        foreach (CombatPredictionSimulator sim in new[] { root, fork })
        {
            if (State(sim).PrepareBeforeHandDraw(sim, player))
                throw new InvalidOperationException("Power order fixture unexpectedly requires a choice.");
            PowerLifecycleSupport.ResolvePowerAmountChanges(sim, State(sim));
            if (Stamp(sim).StateText != actual.StateText)
                throw new InvalidOperationException("Power-order full state differs: " + Stamp(sim).DescribeFirstDifference(actual));
        }
    }
}
