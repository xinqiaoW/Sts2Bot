using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Runs;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    // Inventory animations/input blocking can outlive purchase completion. A
    // missing/disabled Back button is not evidence that the inventory closed.
    internal static async Task LeaveShopAsync(NMerchantRoom shop, Action<string> record, CancellationToken ct)
    {
        var room = shop.Room;
        void RequireCurrentShop()
        {
            ct.ThrowIfCancellationRequested();
            if (!GodotObject.IsInstanceValid(shop) || !shop.IsInsideTree() || shop.IsQueuedForDeletion()
                || !ReferenceEquals(RunManager.Instance.DebugOnlyGetState()?.CurrentRoom, room))
                throw new InvalidOperationException("Shop exit lost its owning room.");
        }
        bool Ready(NProceedButton button) => GodotObject.IsInstanceValid(button)
            && button.IsInsideTree() && button.IsVisibleInTree() && button.IsEnabled;
        record("requested");
        RequireCurrentShop();
        if (shop.Inventory.IsOpen)
        {
            var back = shop.Inventory.GetNode<NBackButton>("%BackButton");
            await WaitHelper.Until(() =>
            {
                RequireCurrentShop();
                return !shop.Inventory.IsOpen || (NOverlayStack.Instance?.Peek() == null
                    && GodotObject.IsInstanceValid(back) && back.IsInsideTree()
                    && back.IsVisibleInTree() && back.IsEnabled);
            }, ct, TimeSpan.FromSeconds(10), "Shop exit: inventory Back button did not become available.");
            RequireCurrentShop();
            if (shop.Inventory.IsOpen) await ClickLegalAsync(back);
        }
        await WaitHelper.Until(() =>
        {
            RequireCurrentShop();
            return !shop.Inventory.IsOpen && NOverlayStack.Instance?.Peek() == null && Ready(shop.ProceedButton);
        }, ct, TimeSpan.FromSeconds(10), "Shop exit: inventory did not close or Proceed stayed disabled.");
        record("inventory_closed");
        RequireCurrentShop();
        if (NMapScreen.Instance?.IsOpen != true)
        {
            await ClickLegalAsync(shop.ProceedButton);
            await WaitHelper.Until(() => NMapScreen.Instance?.IsOpen == true,
                ct, TimeSpan.FromSeconds(10), "Shop exit: Proceed did not open the map.");
        }
        record("map_open");
    }
}
