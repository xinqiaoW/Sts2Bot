using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Rooms;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    private sealed record UiChoice(object Data, Func<Task> Execute);
    private readonly HashSet<AbstractRoom> _openedChests = [];

    private static Task ClickLegalAsync(NClickableControl button)
    {
        if (!GodotObject.IsInstanceValid(button)) throw new StaleUiChoiceException("button_freed");
        if (!button.IsInsideTree() || button.IsQueuedForDeletion()) throw new StaleUiChoiceException("button_detached");
        if (!button.IsVisibleInTree()) throw new StaleUiChoiceException("button_hidden");
        if (!button.IsEnabled) throw new StaleUiChoiceException("button_disabled");
        return UiHelper.Click(button);
    }

    private async Task SelectUiAsync(string screen, List<UiChoice> options, object? context, IOverlayScreen? owner, CancellationToken ct)
    {
        AbstractRoom? room = Run.CurrentRoom;
        string before = System.Text.Json.JsonSerializer.Serialize(State(), RunControlFiles.Json);
        int choice = await ChooseAsync(screen, options.Select(o => o.Data).ToArray(), context, ct);
        Task? pending = TryStartUiChoice(options[choice].Execute,
            () => ReferenceEquals(room, Run.CurrentRoom) && (owner == null || IsCurrentSurface(owner))
                && before == System.Text.Json.JsonSerializer.Serialize(State(), RunControlFiles.Json), out string? staleReason);
        if (pending == null)
            Record("stale_ui_choice", new { screen, choice, reason = staleReason, actionStarted = false });
        else
            await DrainOperationAsync(pending, owner, ct);
        await Task.Delay(150, ct);
    }

    private async Task DrainOperationAsync(Task pending, IOverlayScreen? owner, CancellationToken ct)
    {
        while (!pending.IsCompleted)
        {
            ct.ThrowIfCancellationRequested();
            if (CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting) await CombatAsync(ct);
            else if (NOverlayStack.Instance?.Peek() is { } child && !ReferenceEquals(child, owner))
                await OverlayAsync(child, ct);
            else await Task.Delay(50, ct);
        }
        await pending;
    }

    private async Task PolicyRoomAsync(AbstractRoom room, CancellationToken ct)
    {
        Node? container = host.GetNodeOrNull<Node>("/root/Game/RootSceneContainer/Run/RoomContainer");
        if (container == null) return;
        // The room model advances before its UI transition and combat startup
        // finish. An old rest-site Proceed button can still be enabled here.
        if (room.RoomType is RoomType.Monster or RoomType.Elite or RoomType.Boss
            && !_completedCombatRooms.Contains(room)) return;
        if (room.RoomType == RoomType.Shop)
        {
            NMerchantRoom? shop = UiHelper.FindFirst<NMerchantRoom>(container);
            if (shop == null || !ReferenceEquals(shop.Room, room)) return;
            if (_handledRooms.Contains(room)) { await ProceedAsync(container, ct); return; }
            shop.OpenInventory();
            await Task.Delay(250, ct);
            if (!GodotObject.IsInstanceValid(shop) || !shop.IsInsideTree()
                || !ReferenceEquals(Run.CurrentRoom, room)
                || !GodotObject.IsInstanceValid(shop.Inventory) || !shop.Inventory.IsInsideTree()) return;
            List<UiChoice> options = [];
            foreach (NMerchantSlot slot in shop.Inventory.GetAllSlots().Where(s => s.IsVisibleInTree() && s.Entry.IsStocked && s.Entry.EnoughGold))
            {
                MerchantEntry entry = slot.Entry;
                object data = entry switch
                {
                    MerchantCardEntry card => new { kind = "card", price = entry.Cost, card = CardAdvisorCapture.Card(card.CreationResult!.Card) },
                    MerchantRelicEntry relic => new { kind = "relic", price = entry.Cost, relic = CardAdvisorCapture.Relic(relic.Model!) },
                    MerchantPotionEntry potion => new { kind = "potion", price = entry.Cost, id = potion.Model!.Id.Entry },
                    MerchantCardRemovalEntry => new { kind = "remove", price = entry.Cost },
                    _ => throw new NotSupportedException($"Unsupported merchant entry {entry.GetType().Name}"),
                };
                options.Add(new(data, async () =>
                {
                    if (!entry.IsStocked || !entry.EnoughGold) throw new InvalidOperationException("Shop option is no longer available.");
                    await entry.OnTryPurchaseWrapper(shop.Inventory.Inventory);
                }));
            }
            options.Add(new(new { kind = "leave" }, async () =>
            {
                NBackButton? back = UiHelper.FindAll<NBackButton>(shop).FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
                if (back != null) await ClickLegalAsync(back);
                _handledRooms.Add(room);
                await ProceedAsync(container, ct);
            }));
            await SelectUiAsync("SHOP", options, null, null, ct);
            return;
        }
        if (room.RoomType == RoomType.RestSite && !_handledRooms.Contains(room))
        {
            var buttons = UiHelper.FindAll<NRestSiteButton>(container)
                .Where(b => b.IsEnabled && b.IsVisibleInTree() && b.Option.IsEnabled).ToArray();
            if (buttons.Length == 0) return;
            var options = buttons.Select(b => new UiChoice(new { kind = "rest", id = b.Option.OptionId,
                title = b.Option.Title.GetFormattedText(), description = b.Option.Description.GetFormattedText() },
                () => ClickLegalAsync(b))).ToList();
            await SelectUiAsync("REST", options, null, null, ct);
            _handledRooms.Add(room);
            return;
        }
        if (room.RoomType == RoomType.Treasure)
        {
            NTreasureRoom? treasure = UiHelper.FindFirst<NTreasureRoom>(container);
            if (treasure == null) return;
            if (_openedChests.Add(room))
            {
                Record("open_chest", new { });
                await ClickLegalAsync(treasure.GetNode<NClickableControl>("Chest"));
                await Task.Delay(500, ct);
                return;
            }
            var holders = UiHelper.FindAll<NTreasureRoomRelicHolder>(treasure).Where(h => h.IsEnabled && h.IsVisibleInTree()).ToArray();
            if (holders.Length > 0)
            {
                var options = holders.Select(h => new UiChoice(new { kind = "relic", relic = CardAdvisorCapture.Relic(h.Relic.Model) },
                    () => ClickLegalAsync(h))).ToList();
                if (treasure.ProceedButton.IsEnabled)
                    options.Add(new(new { kind = "leave" }, () => ClickLegalAsync(treasure.ProceedButton)));
                await SelectUiAsync("TREASURE", options, null, null, ct);
                return;
            }
        }
        await ProceedAsync(container, ct);
    }

    private async Task ProceedAsync(Node container, CancellationToken ct)
    {
        var proceed = UiHelper.FindAll<NProceedButton>(container).FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
        if (proceed != null)
        {
            Record("proceed", new { });
            await ClickLegalAsync(proceed);
            await Task.Delay(100, ct);
        }
    }
}
