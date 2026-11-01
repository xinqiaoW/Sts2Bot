using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Unlocks;
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
