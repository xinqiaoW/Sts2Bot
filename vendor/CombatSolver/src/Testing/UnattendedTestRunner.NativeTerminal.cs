using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Rooms;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private NativeCombatOutcome? _nativeCombatOutcome;

    // Subscribe before entering the encounter, including lethal opening hooks.
    // The room's CombatState identity prevents another combat from certifying it.
    private sealed class NativeCombatOutcome : IDisposable
    {
        private CombatState? _wonCombat;
        public CombatState? EndedCombat { get; private set; }

        public NativeCombatOutcome()
        {
            CombatManager.Instance.CombatWon += OnWon;
            CombatManager.Instance.CombatEnded += OnEnded;
        }

        private void OnWon(CombatRoom room) => _wonCombat = room.CombatState;
        private void OnEnded(CombatRoom room) => EndedCombat = room.CombatState;
        public bool HasWon(CombatState combat) => ReferenceEquals(_wonCombat, combat);
        public bool HasEnded(CombatState combat) => ReferenceEquals(EndedCombat, combat);

        public void Dispose()
        {
            CombatManager.Instance.CombatWon -= OnWon;
            CombatManager.Instance.CombatEnded -= OnEnded;
        }
    }
}
