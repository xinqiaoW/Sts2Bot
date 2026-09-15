using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Handlers;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Rooms;
using MegaCrit.Sts2.Core.AutoSlay.Handlers.Screens;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Rooms;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    private IOverlayScreen? _unchangedOverlay;
    private int _unchangedOverlayCount;
    private readonly Dictionary<Type, IScreenHandler> _screens = new IScreenHandler[]
    {
        new RewardsScreenHandler(), new CardRewardScreenHandler(), new DeckUpgradeScreenHandler(),
        new DeckTransformScreenHandler(), new DeckEnchantScreenHandler(), new DeckCardSelectScreenHandler(),
        new SimpleCardSelectScreenHandler(), new ChooseACardScreenHandler(), new ChooseABundleScreenHandler(),
        new ChooseARelicScreenHandler(), new CrystalSphereScreenHandler(),
    }.ToDictionary(h => h.ScreenType);

    private async Task OverlayAsync(IOverlayScreen overlay, CancellationToken ct)
    {
        _stage = "overlay:" + overlay.GetType().Name;
        if (!_screens.TryGetValue(overlay.GetType(), out IScreenHandler? handler))
            throw new NotSupportedException($"Unadapted overlay {overlay.GetType().FullName}.");
        string before = System.Text.Json.JsonSerializer.Serialize(State(), RunControlFiles.Json);
        Record("native_screen_before", new { screen = overlay.GetType().Name, policy = "native_random" });
        await RunHandlerAsync(handler, overlay, ct);
        bool unchanged = ReferenceEquals(NOverlayStack.Instance?.Peek(), overlay)
            && MegaCrit.Sts2.Core.Nodes.Screens.Map.NMapScreen.Instance?.IsOpen != true
            && before == System.Text.Json.JsonSerializer.Serialize(State(), RunControlFiles.Json);
        _unchangedOverlayCount = unchanged && ReferenceEquals(_unchangedOverlay, overlay) ? _unchangedOverlayCount + 1 : 0;
        _unchangedOverlay = unchanged ? overlay : null;
        if (_unchangedOverlayCount >= 3)
            throw new InvalidOperationException($"Overlay {overlay.GetType().Name} repeatedly failed to advance.");
        Record("native_screen_after", new { screen = overlay.GetType().Name });
    }

    // A room operation can await a nested selection screen. Drain that child
    // while its owner is suspended, without driving the same screen twice.
    private async Task RunHandlerAsync(IHandler handler, IOverlayScreen? owner, CancellationToken parent)
    {
        using CancellationTokenSource deadline = CancellationTokenSource.CreateLinkedTokenSource(parent);
        deadline.CancelAfter(handler.Timeout);
        CancellationToken ct = deadline.Token;
        Task pending = handler.HandleAsync(_random, ct);
        while (!pending.IsCompleted)
        {
            ct.ThrowIfCancellationRequested();
            if (CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting)
                await CombatAsync(ct);
            else if (NOverlayStack.Instance?.Peek() is { } child && !ReferenceEquals(child, owner))
                await OverlayAsync(child, ct);
            else
                await Task.Delay(100, ct);
        }
        await pending;
    }

    private async Task RoomStepAsync(CancellationToken ct)
    {
        AbstractRoom? room = Run.CurrentRoom;
        if (room == null) return;
        _stage = "room:" + room.RoomType;
        if (room.RoomType == RoomType.Event)
        {
            await EventStepAsync(ct);
            return;
        }
        IRoomHandler? handler = room.RoomType switch
        {
            // The outer owner pumps selection screens while a purchase awaits.
            RoomType.Shop => new ShopRoomHandler((pending, token) => pending.WaitAsync(token)),
            RoomType.RestSite => new RestSiteRoomHandler(),
            RoomType.Treasure => new TreasureRoomHandler(),
            // The native room can become Map before its screen finishes opening.
            // The outer loop waits for legal options, under its progress deadline.
            RoomType.Monster or RoomType.Elite or RoomType.Boss or RoomType.Map or RoomType.Unassigned => null,
            _ => throw new NotSupportedException($"Unadapted room {room.RoomType}."),
        };
        if (handler == null) return;
        if (_handledRooms.Add(room))
        {
            Record("native_room_before", new { type = room.RoomType.ToString(), policy = "native_random" });
            await RunHandlerAsync(handler, null, ct);
            Record("native_room_after", new { type = room.RoomType.ToString() });
        }
        // Rest-site handlers may yield to an upgrade screen before proceeding.
        Node? container = host.GetNodeOrNull<Node>("/root/Game/RootSceneContainer/Run/RoomContainer");
        NProceedButton? proceed = container == null ? null : UiHelper.FindAll<NProceedButton>(container)
            .FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
        if (proceed != null) await UiHelper.Click(proceed);
    }

    private async Task EventStepAsync(CancellationToken ct)
    {
        Node? room = host.GetNodeOrNull<Node>("/root/Game/RootSceneContainer/Run/RoomContainer/EventRoom");
        if (room == null) return;
        NEventOptionButton[] options = UiHelper.FindAll<NEventOptionButton>(room)
            .Where(b => b.IsEnabled && b.IsVisibleInTree() && !b.Option.IsLocked).ToArray();
        if (options.Length > 0)
        {
            int choice = _random.NextInt(options.Length);
            NEventOptionButton selected = options[choice];
            object previous = selected.Option;
            Record("event_choice", new { choice, eventId = selected.Event.Id.Entry,
                options = options.Select(b => new { title = b.Option.Title.GetFormattedText(), proceed = b.Option.IsProceed }).ToArray() });
            await UiHelper.Click(selected);
            await WaitHelper.Until(() => !GodotObject.IsInstanceValid(selected) || !selected.IsInsideTree()
                || !selected.IsEnabled || !ReferenceEquals(selected.Option, previous)
                || CombatManager.Instance.IsInProgress || NOverlayStack.Instance?.Peek() != null
                || MegaCrit.Sts2.Core.Nodes.Screens.Map.NMapScreen.Instance?.IsOpen == true,
                ct, TimeSpan.FromSeconds(15), "Event choice did not advance.");
            return;
        }
        NAncientEventLayout? ancient = UiHelper.FindFirst<NAncientEventLayout>(room);
        NButton? dialogue = ancient?.GetNodeOrNull<NButton>("%DialogueHitbox");
        if (dialogue is { IsEnabled: true } && dialogue.IsVisibleInTree())
        {
            Record("ancient_dialogue", new { });
            await UiHelper.Click(dialogue);
            await Task.Delay(400, ct);
            return;
        }
        // Fake Merchant and other explicit proceed layouts have no option list.
        NProceedButton? proceed = UiHelper.FindAll<NProceedButton>(room)
            .FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
        if (proceed != null)
        {
            Record("event_proceed", new { });
            await UiHelper.Click(proceed);
        }
    }
}
