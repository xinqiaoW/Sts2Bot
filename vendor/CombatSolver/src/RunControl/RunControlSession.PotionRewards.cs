using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Rewards;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    // The policy chooses ranks; this boundary only executes an exact visible
    // reward/slot transaction. It never creates a potion or edits inventory.
    internal static Func<Task> CapturePotionReplacement(NRewardsScreen screen, NRewardButton button,
        PotionReward reward, Player player, int slot, CancellationToken ct)
    {
        PotionModel?[] before = player.PotionSlots.ToArray();
        PotionModel incoming = reward.Potion ?? throw new InvalidOperationException("Missing potion reward.");
        if (slot < 0 || slot >= before.Length || before.Any(p => p == null))
            throw new InvalidOperationException("Potion replacement requires a full inventory and an occupied slot.");
        return () =>
        {
            ct.ThrowIfCancellationRequested();
            ValidateReward();
            if (!before.SequenceEqual(player.PotionSlots, ReferenceEqualityComparer.Instance))
                throw new StaleUiChoiceException("potion_inventory_changed");
            if (!Hook.ShouldProcurePotion(player.RunState, player.Creature.CombatState, incoming, player))
                throw new InvalidOperationException("Potion procurement is blocked; no potion was discarded.");
            // Returning a Task marks the mutation boundary. Faults after this
            // point must propagate, never become a stale-choice retry.
            return ExecuteAsync();
        };

        void ValidateReward()
        {
            if (!IsCurrentSurface(screen) || CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting)
                throw new StaleUiChoiceException("potion_reward_surface_changed");
            RequireLegalButton(button);
            if (!ReferenceEquals(button.Reward, reward) || !ReferenceEquals(reward.Potion, incoming)
                || reward.ClaimedPotion != null || !ReferenceEquals(reward.Player, player))
                throw new StaleUiChoiceException("potion_reward_changed");
        }

        async Task ExecuteAsync()
        {
            await PotionCmd.Discard(before[slot]!);
            ct.ThrowIfCancellationRequested();
            ValidateReward();
            if (player.PotionSlots.Count != before.Length || player.PotionSlots[slot] != null)
                throw new InvalidOperationException("Potion inventory changed after discard.");
            for (int i = 0; i < before.Length; i++)
                if (i != slot && !ReferenceEquals(player.PotionSlots[i], before[i]))
                    throw new InvalidOperationException("Another potion changed after discard.");
            // Same native completion path as pressing the reward button, with
            // reward synchronization, hooks, removal and pickup animation.
            await button.GetReward();
            if (!ReferenceEquals(reward.ClaimedPotion, incoming)
                || !ReferenceEquals(player.PotionSlots[slot], incoming))
                throw new InvalidOperationException("Replacement reward was not acquired after discard.");
        }
    }
}
