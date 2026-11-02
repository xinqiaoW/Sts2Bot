using CombatSolver;

var cases = new (int? row, int? second, bool ended, bool completed, bool targetSecond, int distance)[]
{
    (null, null, false, false, false, 16),
    (0, null, false, false, false, 16),
    (16, null, false, false, false, 0),
    (16, null, true, true, false, 0),
    (16, 18, true, false, true, 2),
    (17, 18, false, false, true, 1),
    (18, 18, false, false, true, 0),
    (18, 18, true, true, true, 0),
};
foreach (var c in cases)
{
    var result = CardAdvisorProgress.Evaluate(c.row, 16, c.second, c.ended, 3);
    if (result.ActBossDefeated != c.completed || result.TargetSecondBoss != c.targetSecond
        || result.FloorsToBoss != c.distance || result.NormalCombatsCompleted != 3)
        throw new Exception($"Incorrect stage: {c} => {result}");
}
Console.WriteLine("PASS 8 public-map stage boundaries (including single/double Boss and unfinished fights)");
