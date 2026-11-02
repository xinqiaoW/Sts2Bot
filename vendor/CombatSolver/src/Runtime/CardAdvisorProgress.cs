namespace CombatSolver;

// Pure public-map boundary calculation, shared by the advisor and run control.
internal sealed record CardAdvisorProgress(int NormalCombatsCompleted, bool ActBossDefeated,
    bool TargetSecondBoss, int FloorsToBoss)
{
    internal string[] RemainingBosses(string first, string? second)
    {
        if (TargetSecondBoss)
            return [second ?? throw new InvalidOperationException("Second Boss map point has no encounter.")];
        return second is null ? [first] : [first, second];
    }

    internal static CardAdvisorProgress Evaluate(int? currentRow, int firstBossRow, int? secondBossRow,
        bool finishedBossRoom, int normalCombatsCompleted)
    {
        bool second = secondBossRow.HasValue && (currentRow > firstBossRow
            || (currentRow == firstBossRow && finishedBossRoom));
        int targetRow = second ? secondBossRow!.Value : firstBossRow;
        bool completed = finishedBossRoom && currentRow >= (secondBossRow ?? firstBossRow);
        return new(normalCombatsCompleted, completed, second,
            currentRow.HasValue ? Math.Max(0, targetRow - currentRow.Value) : targetRow);
    }
}
