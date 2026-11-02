using CombatSolver;

var cases = new (int? row, int? second, bool ended, bool completed, bool targetSecond, int distance)[]
{
    (null, null, false, false, false, 16),
    (0, null, false, false, false, 16),
    (16, null, false, false, false, 0),
    (16, null, true, true, false, 0),
    (15, 18, false, false, false, 1),
    (16, 18, false, false, false, 0),
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
    string[] expected = c.targetSecond ? ["SECOND"] : c.second.HasValue ? ["FIRST", "SECOND"] : ["FIRST"];
    if (!result.RemainingBosses("FIRST", c.second.HasValue ? "SECOND" : null).SequenceEqual(expected))
        throw new Exception($"Incorrect remaining Bosses: {c}");
}
Console.WriteLine("PASS 10 public-map stage and remaining-Boss boundaries (including unfinished first Boss)");
