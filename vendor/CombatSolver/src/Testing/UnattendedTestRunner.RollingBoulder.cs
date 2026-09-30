using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Monsters;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    // Isolated native fixtures invoke this helper before normal search starts.
    private static async Task AssertRollingBoulderHitsAsync(CombatState live, Player player, string scenario)
    {
        if (scenario is not ("all-segments" or "one-segment" or "survive"
                or "all-segments-no-reattach" or "one-segment-reattach"))
            throw new ArgumentException("Unknown rolling boulder fixture: " + scenario);
        bool allDie = scenario.StartsWith("all-segments", StringComparison.Ordinal);
        bool oneDies = scenario.StartsWith("one-segment", StringComparison.Ordinal);
        bool checkReattach = scenario.EndsWith("reattach", StringComparison.Ordinal);
        var segments = live.Enemies.Where(enemy => enemy.Monster is DecimillipedeSegment).ToArray();
        if (segments.Length != 3 || !live.Enemies.Any(enemy => enemy.Monster is not DecimillipedeSegment && enemy.IsPrimaryEnemy))
            throw new InvalidOperationException("Boulder fixture requires three segments and a surviving primary enemy.");
        for (int index = 0; index < segments.Length; index++)
            await CreatureCmd.SetCurrentHp(segments[index],
                allDie || oneDies && index == 0 ? 5 : 40);
        var context = new ThrowingPlayerChoiceContext();
        await PowerCmd.Apply(context, ModelDb.Power<RollingBoulderPower>().ToMutable(), player.Creature, 10, player.Creature, null);
        RollingBoulderPower power = player.Creature.Powers.OfType<RollingBoulderPower>().Single();
        CombatRootSnapshot root = CombatRootSnapshot.Capture(live);
        CombatPredictionSimulator simulator = root.ForkSimulator();
        CombatPredictionSimulator fork = simulator.Fork();
        ContinuationStamp before = ContinuationStamp.CaptureLive(live);
        var predicted = new List<ContinuationStamp>();
        foreach (CombatPredictionSimulator branch in new[] { simulator, fork })
        {
            var combat = (SimulatedCombatState)branch.State.CombatState;
            var processedDeaths = new HashSet<uint>();
            if (TurnStartPowerSupport.TriggerAfterPlayerTurnStart(
                    branch, combat, player, new TurnStartChoiceCursor([]), processedDeaths))
                throw new InvalidOperationException("Unexpected boulder choice boundary.");
            ContinuationStamp afterHit = ContinuationStamp.CapturePredicted(
                player, branch, root.StartTurnNumber, root.Forecast, root.StartTurnNumber);
            CorePowerSupport.ApplyEnemyDeathPowers(branch, combat, combat.KnownEnemies, processedDeaths);
            predicted.Add(ContinuationStamp.CapturePredicted(player, branch, root.StartTurnNumber, root.Forecast, root.StartTurnNumber));
            if (predicted[^1].StateText != afterHit.StateText)
                throw new InvalidOperationException("Boulder death hooks were settled again at the outer boundary.");
        }
        if (ContinuationStamp.CaptureLive(live).StateText != before.StateText)
            throw new InvalidOperationException("Boulder prediction mutated the live root.");
        if (predicted[0].StateText != predicted[1].StateText)
            throw new InvalidOperationException("Boulder fork differs from direct prediction.");
        await power.AfterPlayerTurnStart(context, player);
        ContinuationStamp actual = ContinuationStamp.CaptureLive(live);
        if (predicted[0].StateText != actual.StateText)
            throw new InvalidOperationException("Rolling boulder hits differ: " + predicted[0].DescribeFirstDifference(actual));
        if (!checkReattach)
            return;

        // Fork after the death boundary too: DEAD_MOVE is retained when all
        // siblings die, but it must not grant effective HP or allow healing.
        CombatPredictionSimulator afterDeathFork = simulator.Fork();
        predicted.Clear();
        foreach (CombatPredictionSimulator branch in new[] { simulator, afterDeathFork })
        {
            var combat = (SimulatedCombatState)branch.State.CombatState;
            int effectiveHp = combat.EffectiveEnemyHp(segments[0], branch.State.GetCreature(segments[0]));
            int expectedHp = allDie ? 0 : combat.GetAmount<ReattachPower>(segments[0]);
            if (effectiveHp != expectedHp)
                throw new InvalidOperationException($"Reattach effective HP {effectiveHp} != {expectedHp}.");
            combat.ResolveReviveMove(branch, segments[0], "REATTACH_MOVE");
            predicted.Add(ContinuationStamp.CapturePredicted(
                player, branch, root.StartTurnNumber, root.Forecast, root.StartTurnNumber));
        }
        if (predicted[0].StateText != predicted[1].StateText
            || ContinuationStamp.CaptureLive(live).StateText != actual.StateText)
            throw new InvalidOperationException("Reattach prediction changed its live root or diverged after Fork.");
        await segments[0].Powers.OfType<ReattachPower>().Single().DoReattach();
        ContinuationStamp afterReattach = ContinuationStamp.CaptureLive(live);
        if (predicted[0].StateText != afterReattach.StateText)
            throw new InvalidOperationException("Reattach differs: " + predicted[0].DescribeFirstDifference(afterReattach));
    }
}
