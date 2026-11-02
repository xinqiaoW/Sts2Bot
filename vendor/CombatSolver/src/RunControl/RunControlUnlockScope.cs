using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Unlocks;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Random;
using STS2RitsuLib;
using STS2RitsuLib.Patching.Models;

namespace CombatSolver;

// Only scopes creation of an isolated evaluation run. Complete content
// discovery prevents the first-run tutorial encounter order and boss order
// from changing across otherwise paired experiments. No live run, encounter
// queue, RNG, reward, HP or persistent win/loss counter is modified.
internal sealed class RunControlUnlockScope : IDisposable
{
    internal static bool Active { get; private set; }

    public RunControlUnlockScope()
    {
        if (Environment.GetEnvironmentVariable("COMBATSOLVER_RUN_CONTROL") != "1" || Active)
            throw new InvalidOperationException("Full-content startup requires one isolated run-control owner.");
        Active = true;
    }

    public void Dispose() => Active = false;

    internal static List<ActModel> SelectActs(string seed)
    {
        // Match the fully discovered native lobby's act_selection stream.
        // Fresh isolated profiles must not force the undiscovered alternate
        // act every time; do not modify persistent discovery to avoid that.
        Rng rng = new(StringHelper.GetDeterministicHashCode(seed), "act_selection");
        return ModelDb.ActsByIndex.Select(pool => rng.NextItem(
            pool.Where(act => act.IsUnlocked(UnlockState.all)).ToList())
            ?? throw new InvalidOperationException("No unlocked act in evaluation pool.")).ToList();
    }
}

internal sealed class RunControlUnlockPatch : IPatchMethod
{
    public static string PatchId => "combat_solver_run_control_unlocks";
    public static string Description => "隔离整局评测的新局完整解锁与内容发现";
    public static ModPatchTarget[] GetTargets() =>
        [new(typeof(SaveManager), nameof(SaveManager.GenerateUnlockStateFromProgress), [])];

    public static bool Prefix(ref UnlockState __result)
    {
        if (!RunControlUnlockScope.Active) return true;
        __result = UnlockState.all;
        return false;
    }
}
