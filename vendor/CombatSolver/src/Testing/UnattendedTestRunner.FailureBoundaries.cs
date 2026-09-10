using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Mirrors.Cards.OnPlay;
using CombatSolver.Engine.InCombat.Simulation;
using STS2RitsuLib.Cards.DynamicVars;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private sealed class TrackingComputedDynamicVar : IComputedDynamicVar
    {
        public bool CalculateCalled { get; private set; }

        public decimal Calculate(Creature? target)
        {
            CalculateCalled = true;
            throw new InvalidOperationException("Computed dynamic variable native evaluator was called.");
        }
    }

    private static void AssertPredictionFailureBoundaries(CombatState combat, Player player)
    {
        CardModel card = player.PlayerCombatState?.Hand.Cards.FirstOrDefault()
            ?? throw new InvalidOperationException("失败边界测试要求手牌中至少有一张牌。");
        CombatPredictionSimulator simulator = new(new SimulatedCombatState(combat));
        TrackingComputedDynamicVar computed = new();
        try
        {
            computed.InvokeCalculate(
                simulator,
                new PredictedCard(card),
                combat.Enemies.FirstOrDefault());
            throw new InvalidOperationException("未知计算型动态变量没有显式失败。");
        }
        catch (PredictionUnsupportedException ex)
        {
            if (!ex.Message.Contains(card.Id.Entry, StringComparison.Ordinal)
                || !ex.Message.Contains(nameof(TrackingComputedDynamicVar), StringComparison.Ordinal))
            {
                throw new InvalidOperationException("计算型动态变量失败缺少卡牌或变量类型上下文。", ex);
            }
        }
        if (computed.CalculateCalled)
            throw new InvalidOperationException("未知计算型动态变量仍调用了原生求值器。");

        bool scoreEvaluatorCalled = false;
        ComputedDynamicVar computedDamage = new(
            "Damage",
            17m,
            _ =>
            {
                scoreEvaluatorCalled = true;
                return 99m;
            });
        DynamicVarSet computedVars = new([computedDamage]);
        if (CardChoiceSupport.DynamicVarBaseValue(computedVars, "Damage") != 17d)
            throw new InvalidOperationException("选牌估值没有读取计算型动态变量的基础值。");
        if (scoreEvaluatorCalled)
            throw new InvalidOperationException("选牌估值错误调用了计算型动态变量的实机求值器。");

        IncompatibleGameplayModException incompatible = new(
            "Watcher",
            "The Watcher [Test]",
            "WatcherMod.WatcherEnchantStackHookProxy",
            "combat");
        string playerMessage = SolverController.FormatSearchSetupFailure(incompatible);
        if (!playerMessage.Contains("The Watcher ［Test］（Watcher）", StringComparison.Ordinal)
            || !playerMessage.Contains("不兼容的第三方 Mod", StringComparison.Ordinal)
            || !playerMessage.Contains("建议卸载", StringComparison.Ordinal)
            || !playerMessage.Contains(SolverUiTokens.BugReportUploadInstruction, StringComparison.Ordinal)
            || playerMessage.Contains("WatcherEnchantStackHookProxy", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("第三方玩法 Mod 初始化失败提示缺少名称、卸载建议或上传入口。");
        }
        if (!incompatible.Message.Contains("WatcherEnchantStackHookProxy", StringComparison.Ordinal)
            || !incompatible.Message.Contains("Watcher", StringComparison.Ordinal))
        {
            throw new InvalidOperationException("第三方玩法 Mod 初始化失败日志缺少 Mod 或订阅器上下文。");
        }

        bool firstInferredActionRan = false;
        InvalidOperationException inferredFailure = new("inferred-action-failure");
        try
        {
            CardOnPlayInferrer.ExecuteInferredActions(
                [
                    (_, _) => firstInferredActionRan = true,
                    (_, _) => throw inferredFailure,
                ],
                null!,
                null!);
            throw new InvalidOperationException("推断动作失败没有向外传播。");
        }
        catch (InvalidOperationException ex) when (ReferenceEquals(ex, inferredFailure))
        {
        }
        if (!firstInferredActionRan)
            throw new InvalidOperationException("推断动作失败测试没有执行前置动作。");

        AssertSearchTransitionFailure(new PlanAction(
            PlanActionKind.PlayCard,
            Turn: 1,
            CardId: "FAILURE_CARD"));
        AssertSearchTransitionFailure(new PlanAction(
            PlanActionKind.UsePotion,
            Turn: 1,
            PotionSlot: 0,
            PotionId: "FAILURE_POTION"));
        AssertExpectedSearchTransitionExceptionsPassThrough();
    }

    private static void AssertSearchTransitionFailure(PlanAction action)
    {
        StateFingerprint parentState = new(11, 29);
        InvalidOperationException transitionFailure = new("transition-failure");
        try
        {
            SearchTransitionGuard.Execute<int>(
                action,
                parentState,
                parentActionCount: 3,
                () => throw transitionFailure);
            throw new InvalidOperationException($"{action.Kind} 回放失败没有终止搜索转移。");
        }
        catch (SearchTransitionException ex)
        {
            if (!ReferenceEquals(ex.InnerException, transitionFailure)
                || ex.Action != action
                || ex.ParentState != parentState
                || ex.ParentActionCount != 3)
            {
                throw new InvalidOperationException($"{action.Kind} 回放失败上下文不完整。", ex);
            }
        }
    }

    private static void AssertExpectedSearchTransitionExceptionsPassThrough()
    {
        PlanAction action = new(PlanActionKind.EndTurn, Turn: 1);
        try
        {
            SearchTransitionGuard.Execute<int>(
                action,
                default,
                0,
                static () => throw new OperationCanceledException("canceled"));
            throw new InvalidOperationException("取消异常没有传播。");
        }
        catch (OperationCanceledException)
        {
        }

        InvalidPlannedChoiceBranchException invalidChoice = new("invalid-choice");
        try
        {
            SearchTransitionGuard.Execute<int>(
                action,
                default,
                0,
                () => throw invalidChoice);
            throw new InvalidOperationException("无效选择异常没有传播。");
        }
        catch (InvalidPlannedChoiceBranchException ex) when (ReferenceEquals(ex, invalidChoice))
        {
        }
    }
}
