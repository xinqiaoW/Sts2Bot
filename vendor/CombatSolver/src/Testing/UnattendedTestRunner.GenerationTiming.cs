using System.Reflection;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using CombatSolver.Engine.InCombat.Mirrors;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    // These observers are installed only by the isolated fixture, never normal play.
    private static List<ContinuationStamp>? _generationTimingStamps;
    private static CombatState? _generationTimingLive;
    private static Player? _generationTimingPlayer;
    private static IntentForecast? _generationTimingForecast;
    private static int _generationTimingTurn;

    private static void ObserveNativeGenerationTiming()
        => _generationTimingStamps!.Add(ContinuationStamp.CaptureLive(_generationTimingLive!));

    private static void ObservePredictedGenerationTiming(CombatPredictionSimulator simulator)
        => _generationTimingStamps!.Add(ContinuationStamp.CapturePredicted(
            _generationTimingPlayer!, simulator, _generationTimingTurn,
            _generationTimingForecast!, _generationTimingTurn));

    private static async Task AssertGenerationTimingAsync(CombatState live, Player player, string scenario)
    {
        PowerModel power = scenario switch
        {
            "creative-ai" => ModelDb.Power<CreativeAiPower>().ToMutable(),
            "call-of-void-control" => ModelDb.Power<CallOfTheVoidPower>().ToMutable(),
            _ => throw new ArgumentException("Unknown generation timing fixture: " + scenario),
        };
        power.ApplyInternal(player.Creature, 3, silent: true);
        CombatPredictionSimulator root = new(new SimulatedCombatState(live));
        CombatPredictionSimulator fork = root.Fork();
        _generationTimingLive = live;
        _generationTimingPlayer = player;
        _generationTimingForecast = IntentForecaster.Build(live, 1);
        _generationTimingTurn = player.PlayerCombatState!.TurnNumber;
        Harmony harmony = new("CombatSolver.IsolatedGenerationTiming");
        MethodInfo actualMethod = typeof(Hook).GetMethod(nameof(Hook.AfterCardGeneratedForCombat))!;
        MethodInfo predictedMethod = typeof(HookMirrors).GetMethod(nameof(HookMirrors.AfterCardGeneratedForCombat))!;
        try
        {
            harmony.Patch(actualMethod, prefix: new HarmonyMethod(typeof(UnattendedTestRunner), nameof(ObserveNativeGenerationTiming)));
            harmony.Patch(predictedMethod, prefix: new HarmonyMethod(typeof(UnattendedTestRunner), nameof(ObservePredictedGenerationTiming)));
            _generationTimingStamps = [];
            await Hook.BeforeHandDraw(live, player, new ThrowingPlayerChoiceContext());
            ContinuationStamp[] actual = _generationTimingStamps.ToArray();
            if (actual.Length != 3)
                throw new InvalidOperationException("Original generation trace did not observe all three cards.");
            ContinuationStamp final = ContinuationStamp.CaptureLive(live);
            foreach (CombatPredictionSimulator sim in new[] { root, fork })
            {
                _generationTimingStamps = [];
                SimulatedCombatState state = (SimulatedCombatState)sim.State.CombatState;
                if (state.PrepareBeforeHandDraw(sim, player))
                    throw new InvalidOperationException("Generation timing fixture unexpectedly requires a choice.");
                PowerLifecycleSupport.ResolvePowerAmountChanges(sim, state);
                if (_generationTimingStamps.Count != actual.Length)
                    throw new InvalidOperationException("Predicted generation trace lost a card hook.");
                for (int index = 0; index < actual.Length; index++)
                {
                    if (_generationTimingStamps[index].StateText != actual[index].StateText)
                        throw new InvalidOperationException($"Generation timing differs at card {index}: "
                            + _generationTimingStamps[index].DescribeFirstDifference(actual[index]));
                }
                ContinuationStamp predictedFinal = ContinuationStamp.CapturePredicted(
                    player, sim, _generationTimingTurn, _generationTimingForecast, _generationTimingTurn);
                if (predictedFinal.StateText != final.StateText)
                    throw new InvalidOperationException("Generation final state differs: " + predictedFinal.DescribeFirstDifference(final));
            }
        }
        finally
        {
            harmony.Unpatch(actualMethod, HarmonyPatchType.All, harmony.Id);
            harmony.Unpatch(predictedMethod, HarmonyPatchType.All, harmony.Id);
            _generationTimingStamps = null;
            _generationTimingLive = null;
            _generationTimingPlayer = null;
            _generationTimingForecast = null;
        }
    }
}
