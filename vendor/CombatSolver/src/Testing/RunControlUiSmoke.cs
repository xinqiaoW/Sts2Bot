using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Rewards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Saves;

namespace CombatSolver;

// Opt-in UI fixture, separate from scored games and the production run loop.
internal static class RunControlUiSmoke
{
    internal static async Task RunAsync(NGame host, string path)
    {
        string status = "failed", error = "";
        List<object> evidence = [];
        using CancellationTokenSource deadline = new(TimeSpan.FromSeconds(110));
        try
        {
            await host.GameStartupComplete.WaitAsync(deadline.Token);
            SaveManager.Instance.SetFtuesEnabled(false);
            await host.StartNewSingleplayerRun(ModelDb.Character<Silent>(), false,
                ActModel.GetDefaultList().ToList(), [], "GRIDIDENTITY", GameMode.Standard, 10).WaitAsync(deadline.Token);
            RunState run = RunManager.Instance.DebugOnlyGetState()!;
            Player player = LocalContext.GetMe(run)!;
            CardModel[] original = player.Deck.Cards.ToArray();
            // Same card ID, distinct instances: selecting by ID would be wrong.
            CardModel[] cards = Enumerable.Range(0, 60).Select(_ => (CardModel)original[0].MutableClone()).ToArray();
            foreach (int index in new[] { 0, 59 })
            {
                var screen = NDeckCardSelectScreen.Create(cards,
                    new CardSelectorPrefs(CardSelectorPrefs.RemoveSelectionPrompt, 1));
                (NOverlayStack.Instance ?? throw new InvalidOperationException("Missing overlay stack.")).Push(screen);
                await Task.Delay(400, deadline.Token);
                NGridCardHolder? cached = screen._grid.GetCardHolder(cards[index]);
                screen._grid.SetScrollPosition(screen._grid.ScrollLimitBottom);
                screen._grid.AllocateCardHolders();
                await Task.Delay(250, deadline.Token);
                bool stale = cached == null || !GodotObject.IsInstanceValid(cached) || !cached.IsVisibleInTree()
                    || !ReferenceEquals(cached.CardModel, cards[index]);
                if (index == 0 && !stale)
                    throw new InvalidOperationException("Fixture did not reproduce a recycled/hidden holder.");
                await RunControlSession.PressGridCardAsync(screen, cards[index], deadline.Token);
                if (screen._selectedCards.Count != 1 || !ReferenceEquals(screen._selectedCards.Single(), cards[index]))
                    throw new InvalidOperationException("Grid click selected the wrong card instance.");
                await UiHelper.Click(screen._previewConfirmButton);
                CardModel[] selected = (await screen.CardsSelected().WaitAsync(deadline.Token)).ToArray();
                if (selected.Length != 1 || !ReferenceEquals(selected[0], cards[index]))
                    throw new InvalidOperationException("Native confirmation changed the selected instance.");
                evidence.Add(new { index, stale_cached_holder = stale, exact_instance_confirmed = true });
                await Task.Delay(150, deadline.Token);
            }
            await VerifyRewardChoicesAsync(original, evidence, deadline.Token);
            await VerifyPotionReplacementAsync(player, evidence, deadline.Token);
            if (!original.SequenceEqual(player.Deck.Cards))
                throw new InvalidOperationException("UI fixture unexpectedly changed the real deck.");
            await VerifyShopExitAsync(host, evidence, deadline.Token);
            status = "passed";
        }
        catch (Exception ex)
        {
            // Terminal fixture boundary: retain the failure and exit nonzero.
            error = ex.ToString();
            Entry.Logger.Error("[RunControl/UiSmoke] " + error);
        }
        finally
        {
            File.WriteAllText(path, JsonSerializer.Serialize(new { status, error, evidence }));
            host.GetTree().Quit(status == "passed" ? 0 : 1);
        }
    }

    private static async Task VerifyShopExitAsync(NGame host, List<object> evidence, CancellationToken ct)
    {
        await RunManager.Instance.EnterRoomDebug(RoomType.Shop, MapPointType.Shop, null);
        NMerchantRoom? shop = null;
        await WaitHelper.Until(() =>
        {
            shop = UiHelper.FindFirst<NMerchantRoom>(host);
            return shop != null && shop.IsInsideTree() && !host.Transition.InTransition;
        }, ct, TimeSpan.FromSeconds(10), "Shop fixture did not enter native merchant room.");
        shop!.OpenInventory();
        await Task.Delay(400, ct);
        var back = shop.Inventory.GetNode<NBackButton>("%BackButton");
        back.Disable(); // Reproduce the input-blocked interval after purchase.
        bool oldWouldSkipClose = !UiHelper.FindAll<NBackButton>(shop)
            .Any(b => b.IsEnabled && b.IsVisibleInTree());
        if (!oldWouldSkipClose || !shop.Inventory.IsOpen || shop.ProceedButton.IsEnabled)
            throw new InvalidOperationException("Shop fixture did not reproduce the old leave-without-close boundary.");
        List<string> phases = [];
        Task exit = RunControlSession.LeaveShopAsync(shop, phases.Add, ct);
        await Task.Delay(300, ct);
        if (exit.IsCompleted || !shop.Inventory.IsOpen || shop.ProceedButton.IsEnabled)
            throw new InvalidOperationException("Shop exit acted while its Back button was disabled.");
        back.Enable();
        await exit.WaitAsync(ct);
        if (shop.Inventory.IsOpen || NMapScreen.Instance?.IsOpen != true
            || !phases.SequenceEqual(new[] { "requested", "inventory_closed", "map_open" }))
            throw new InvalidOperationException("Shop exit did not confirm inventory close and map open.");
        evidence.Add(new { shop_exit = "delayed_back", old_would_skip_close = oldWouldSkipClose, phases, map_open = true });
    }

    private static async Task VerifyPotionReplacementAsync(Player player, List<object> evidence, CancellationToken ct)
    {
        foreach (var held in player.PotionSlots.Where(p => p != null).ToArray()) await PotionCmd.Discard(held!);
        for (int i = 0; i < player.PotionSlots.Count; i++)
        {
            var acquired = await PotionCmd.TryToProcure(ModelDb.Potion<MegaCrit.Sts2.Core.Models.Potions.WeakPotion>().ToMutable(), player, i);
            if (!acquired.success) throw new InvalidOperationException("Fixture could not fill potion slot.");
        }
        PotionModel incoming = ModelDb.Potion<MegaCrit.Sts2.Core.Models.Potions.FairyInABottle>().ToMutable();
        var reward = new PotionReward(incoming, player);
        var set = new RewardsSet(player, RunManager.Instance.RewardsSetSynchronizer).WithCustomRewards([reward]);
        Task offered = set.Offer();
        await Task.Delay(600, ct);
        var screen = NOverlayStack.Instance!.Peek() as NRewardsScreen
            ?? throw new InvalidOperationException("Missing potion rewards screen.");
        var button = UiHelper.FindAll<NRewardButton>(screen).Single(b => ReferenceEquals(b.Reward, reward));
        int slot = player.PotionSlots.Count - 1;
        PotionModel?[] before = player.PotionSlots.ToArray();
        Func<Task> captured = RunControlSession.CapturePotionReplacement(screen, button, reward, player, slot, ct);
        screen.Visible = false;
        Reject(captured, "potion_reward_surface_changed");
        screen.Visible = true;
        button.Disable();
        Reject(captured, "button_disabled");
        button.Enable();
        if (!before.SequenceEqual(player.PotionSlots, ReferenceEqualityComparer.Instance))
            throw new InvalidOperationException("Stale preflight discarded a potion.");
        // Same ID in the same slot is still a different instance after manual replacement.
        await PotionCmd.Discard(before[slot]!);
        var sameId = await PotionCmd.TryToProcure(ModelDb.Potion<MegaCrit.Sts2.Core.Models.Potions.WeakPotion>().ToMutable(), player, slot);
        if (!sameId.success) throw new InvalidOperationException("Fixture same-ID setup failed.");
        Reject(captured, "potion_inventory_changed");
        if (!ReferenceEquals(player.PotionSlots[slot], sameId.potion))
            throw new InvalidOperationException("Same-ID replacement was discarded by stale choice.");
        Func<Task> fresh = RunControlSession.CapturePotionReplacement(screen, button, reward, player, slot, ct);
        Task pending = RunControlSession.TryStartUiChoice(fresh, () => true, out var reason)
            ?? throw new InvalidOperationException("Fresh potion replacement rejected: " + reason);
        await pending.WaitAsync(ct);
        if (!ReferenceEquals(player.PotionSlots[slot], incoming) || !ReferenceEquals(reward.ClaimedPotion, incoming)
            || !before.Take(slot).SequenceEqual(player.PotionSlots.Take(slot), ReferenceEqualityComparer.Instance))
            throw new InvalidOperationException("Native potion reward did not replace exactly the chosen slot.");
        if (RunControlSession.TryStartUiChoice(fresh, () => true, out reason) != null)
            throw new InvalidOperationException("Consumed potion reward was executed twice.");
        evidence.Add(new { test = "potion-replacement-hidden-disabled-same-id-stale-and-exact-slot-native-pickup", passed = true,
            discarded = sameId.potion.Id.Entry, acquired = incoming.Id.Entry, slot, other_slots_preserved = true });
        if (RunControlSession.IsCurrentSurface(screen))
        {
            await Task.Delay(250, ct);
            var proceed = UiHelper.FindAll<NProceedButton>(screen).First(b => b.IsEnabled && b.IsVisibleInTree());
            await UiHelper.Click(proceed);
        }
        await offered.WaitAsync(ct);

        static void Reject(Func<Task> action, string expected)
        {
            if (RunControlSession.TryStartUiChoice(action, () => true, out var reason) != null || reason != expected)
                throw new InvalidOperationException($"Expected {expected}, got {reason}");
        }
    }

    private static async Task VerifyRewardChoicesAsync(CardModel[] original, List<object> evidence, CancellationToken ct)
    {
        CardCreationResult[] cards = original.Take(3).Select(c => new CardCreationResult((CardModel)c.MutableClone())).ToArray();
        CardRewardAlternative[] alternatives = [new("Skip", PostAlternateCardRewardAction.EndSelectionAndCompleteReward)];
        for (int scenario = 0; scenario < 3; scenario++)
        {
            var screen = NCardRewardSelectionScreen.ShowScreen(cards, alternatives)
                ?? throw new InvalidOperationException("Reward screen did not open.");
            Task<int?> selected = screen.OptionSelected();
            await Task.Delay(500, ct);
            if (!RunControlSession.RewardSelectionReady(screen)) throw new InvalidOperationException("Reward screen not ready.");
            Func<Task> skip = RunControlSession.CaptureRewardChoice(screen, 0, true);
            Func<Task> take = RunControlSession.CaptureRewardChoice(screen, 1, false);
            var oldButton = screen._rewardAlternativesContainer.GetChildren().OfType<NCardRewardAlternativeButton>().Single();
            if (scenario == 0)
            {
                screen.Visible = false;
                ExpectStale(skip, "reward_surface_changed", selected);
                screen.Visible = true;
                oldButton.Disable();
                ExpectStale(skip, "button_disabled", selected);
                oldButton.Enable();
                // Same semantic options, new native controls: no stale button
                // should be retained across a refresh while Python is working.
                screen.RefreshOptions(cards, alternatives);
                await Task.Delay(500, ct);
                bool oldInvalid = !GodotObject.IsInstanceValid(oldButton) || !oldButton.IsInsideTree()
                    || !oldButton.IsVisibleInTree() || !oldButton.IsEnabled;
                if (!oldInvalid) throw new InvalidOperationException("Fixture did not invalidate the cached button.");
                await Start(skip);
                if (await selected.WaitAsync(ct) != cards.Length) throw new InvalidOperationException("Wrong alternative selected.");
                evidence.Add(new { test = "reward-hidden-disabled-and-rebuilt-control", old_cached_button_illegal = oldInvalid, passed = true });
            }
            else if (scenario == 1)
            {
                CardCreationResult[] replacement = cards.Select(c => new CardCreationResult((CardModel)c.Card.MutableClone())).ToArray();
                screen.RefreshOptions(replacement, alternatives);
                await Task.Delay(500, ct);
                ExpectStale(take, "reward_options_changed", selected);
                ExpectStale(skip, "reward_options_changed", selected);
                await Start(RunControlSession.CaptureRewardChoice(screen, 1, false));
                if (await selected.WaitAsync(ct) != 1) throw new InvalidOperationException("Fresh choice used wrong same-ID instance.");
                evidence.Add(new { test = "reward-rerolled-same-id-cards-rejected-and-fresh-choice-succeeds", passed = true });
            }
            else
            {
                // Mimic a manual click occurring during model inference.
                await UiHelper.Click(oldButton);
                if (await selected.WaitAsync(ct) != cards.Length) throw new InvalidOperationException("Manual skip failed.");
                ExpectStale(skip, "reward_selection_already_completed_or_replaced", null);
                ExpectStale(take, "reward_selection_already_completed_or_replaced", null);
                evidence.Add(new { test = "reward-manual-choice-not-repeated", passed = true });
            }
            NOverlayStack.Instance!.Remove(screen);
            await Task.Delay(150, ct);
            ExpectStale(skip, "reward_surface_changed", null);
        }

        int started = 0;
        Task? rejected = RunControlSession.TryStartUiChoice(() => { started++; return Task.CompletedTask; },
            () => false, out string? reason);
        if (rejected != null || started != 0 || reason != "decision_state_or_surface_changed")
            throw new InvalidOperationException("Changed decision state was executed.");
        Task? faulted = RunControlSession.TryStartUiChoice(() =>
        {
            started++;
            return Task.FromException(new InvalidOperationException("after-input-fault"));
        }, () => true, out reason);
        bool propagated = false;
        try { await faulted!; }
        catch (InvalidOperationException ex) when (ex.Message == "after-input-fault") { propagated = true; }
        if (!propagated || started != 1 || reason != null)
            throw new InvalidOperationException("Post-input failure was hidden or retried.");
        evidence.Add(new { test = "changed-state-not-started-and-post-input-fault-propagates", passed = true });

        static Task Start(Func<Task> action) => RunControlSession.TryStartUiChoice(action, () => true, out var reason)
            ?? throw new InvalidOperationException("Unexpected stale choice: " + reason);
        static void ExpectStale(Func<Task> action, string expected, Task<int?>? selected)
        {
            if (RunControlSession.TryStartUiChoice(action, () => true, out var reason) != null
                || reason != expected || selected?.IsCompleted == true)
                throw new InvalidOperationException($"Expected {expected}, got {reason}; selection must not execute.");
        }
    }
}
