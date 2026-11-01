using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Relics;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Rewards;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    private readonly HashSet<Reward> _attemptedRewards = [];

    private static Task PressCardAsync(NCardHolder holder)
    {
        if (!GodotObject.IsInstanceValid(holder) || !holder.IsInsideTree() || !holder.IsVisibleInTree())
            throw new InvalidOperationException("Card selection is no longer visible.");
        holder.EmitSignal(NCardHolder.SignalName.Pressed, holder);
        return Task.CompletedTask;
    }

    internal static async Task PressGridCardAsync(NCardGridSelectionScreen screen, CardModel card, CancellationToken ct)
    {
        // Grid holders are pooled and may be hidden, replaced or rebound while
        // Python scores the choice. Keep the model instance, never the holder.
        long deadline = System.Environment.TickCount64 + 5000;
        while (System.Environment.TickCount64 < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (!GodotObject.IsInstanceValid(screen) || !screen.IsInsideTree()
                || !ReferenceEquals(NOverlayStack.Instance?.Peek(), screen)
                || !screen._cards.Any(c => ReferenceEquals(c, card)))
                throw new InvalidOperationException("Card selection surface or exact candidate changed.");
            NCardGrid grid = screen._grid;
            if (!grid.IsVisibleInTree() || grid._needsReinit || grid._cardsAnimatingOutForSetCards || grid.Columns <= 0)
            {
                await Task.Delay(50, ct);
                continue;
            }
            int index = grid._cards.FindIndex(c => ReferenceEquals(c, card));
            if (index < 0) throw new InvalidOperationException("Selected card is no longer in the legal grid.");
            float center = grid.Size.Y * .5f - (grid.YOffset + 80 + grid._cardSize.Y * .5f
                + index / grid.Columns * (grid._cardSize.Y + grid.CardPadding));
            grid.SetScrollPosition(Mathf.Clamp(center, Math.Min(grid.ScrollLimitTop, grid.ScrollLimitBottom),
                Math.Max(grid.ScrollLimitTop, grid.ScrollLimitBottom)));
            // SetScrollPosition snaps both current and target positions, so the
            // native animation loop does not allocate rows for this jump.
            grid.AllocateCardHolders();
            await Task.Delay(50, ct); // Let the native grid recycle/reflow its rows.
            if (!GodotObject.IsInstanceValid(grid) || !GodotObject.IsInstanceValid(screen)
                || !ReferenceEquals(NOverlayStack.Instance?.Peek(), screen))
                throw new InvalidOperationException("Card selection surface changed while scrolling.");
            if (grid._needsReinit || grid._cardsAnimatingOutForSetCards) continue;
            NGridCardHolder? holder = grid.CurrentlyDisplayedCardHolders.FirstOrDefault(h =>
                GodotObject.IsInstanceValid(h) && h.IsInsideTree() && h.IsVisibleInTree()
                && ReferenceEquals(h.CardModel, card) && grid.GetGlobalRect().HasPoint(h.GlobalPosition));
            if (holder == null) continue;
            if (!ReferenceEquals(NOverlayStack.Instance?.Peek(), screen))
                throw new InvalidOperationException("Card selection surface changed before click.");
            if (screen is NSimpleCardSelectScreen)
                grid.EmitSignal(NCardGrid.SignalName.HolderPressed, holder);
            else
                await PressCardAsync(holder);
            return;
        }
        throw new TimeoutException($"Could not reveal the exact selected card: {card.Id.Entry}.");
    }

    private async Task PolicyOverlayAsync(IOverlayScreen overlay, CancellationToken ct)
    {
        Node node = (Node)overlay;
        await Task.Delay(200, ct);
        List<UiChoice> options = [];
        if (overlay is NRewardsScreen rewards)
        {
            foreach (var button in UiHelper.FindAll<NRewardButton>(node).Where(b => b.IsEnabled && b.IsVisibleInTree() && b.Reward != null && !_attemptedRewards.Contains(b.Reward)))
            {
                Reward reward = button.Reward!;
                // The reward's closed card offers are not player-visible yet.
                object data = reward switch
                {
                    GoldReward gold => new { kind = "gold", amount = gold.Amount },
                    RelicReward relic => new { kind = "relic", relic = CardAdvisorCapture.Relic(relic.Relic!) },
                    PotionReward potion => new { kind = "potion", id = potion.Potion!.Id.Entry },
                    CardReward => new { kind = "open_cards" },
                    _ => new { kind = "reward", id = reward.GetType().Name, description = reward.Description.GetFormattedText() },
                };
                options.Add(new(data, () => { _attemptedRewards.Add(reward); return ClickLegalAsync(button); }));
            }
            var proceed = UiHelper.FindAll<NProceedButton>(node).FirstOrDefault(b => b.IsVisibleInTree() && b.IsEnabled);
            if (proceed != null) options.Add(new(new { kind = "leave" }, () => ClickLegalAsync(proceed)));
            if (options.Count > 0) await SelectUiAsync("REWARDS", options, null, overlay, ct);
            return;
        }
        if (overlay is NCardRewardSelectionScreen rewardCards)
        {
            foreach (var holder in UiHelper.FindAll<NCardHolder>(node).Where(h => h.IsVisibleInTree() && h.CardModel != null))
                options.Add(new(new { kind = "card", action = "take", card = CardAdvisorCapture.Card(holder.CardModel!) }, () => PressCardAsync(holder)));
            var alternatives = UiHelper.FindAll<NCardRewardAlternativeButton>(rewardCards._rewardAlternativesContainer);
            if (alternatives.Count != rewardCards._extraOptions.Count) throw new InvalidDataException("Reward alternatives are not ready.");
            for (int i = 0; i < alternatives.Count; i++)
            {
                var button = alternatives[i]; var alternate = rewardCards._extraOptions[i];
                if (button.IsEnabled && button.IsVisibleInTree())
                    options.Add(new(new { kind = "alternative", id = alternate.OptionId, title = alternate.Title.GetFormattedText() }, () => ClickLegalAsync(button)));
            }
            await SelectUiAsync("CARD_REWARD", options, null, overlay, ct);
            return;
        }
        if (overlay is NChooseACardSelectionScreen choose)
        {
            foreach (var holder in UiHelper.FindAll<NCardHolder>(node).Where(h => h.CardModel != null && h.IsVisibleInTree()))
                options.Add(new(new { kind = "card", action = "take", card = CardAdvisorCapture.Card(holder.CardModel!) }, () => PressCardAsync(holder)));
            if (choose._canSkip && choose._skipButton.IsEnabled && choose._skipButton.IsVisibleInTree())
                options.Add(new(new { kind = "skip" }, () => ClickLegalAsync(choose._skipButton)));
            await SelectUiAsync("CHOOSE_CARD", options, null, overlay, ct);
            return;
        }
        if (overlay is NChooseARelicSelection)
        {
            foreach (var holder in UiHelper.FindAll<NRelicBasicHolder>(node).Where(h => h.IsVisibleInTree() && h.IsEnabled))
                options.Add(new(new { kind = "relic", relic = CardAdvisorCapture.Relic(holder.Relic.Model) }, () => ClickLegalAsync(holder)));
            foreach (var skip in UiHelper.FindAll<NChoiceSelectionSkipButton>(node).Where(b => b.IsEnabled && b.IsVisibleInTree()))
                options.Add(new(new { kind = "skip" }, () => ClickLegalAsync(skip)));
            await SelectUiAsync("RELIC", options, null, overlay, ct);
            return;
        }
        if (overlay is NChooseABundleSelectionScreen)
        {
            var confirm = UiHelper.FindAll<NConfirmButton>(node).FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
            if (confirm != null) { await ClickLegalAsync(confirm); return; }
            foreach (var bundle in UiHelper.FindAll<NCardBundle>(node).Where(b => b.IsVisibleInTree()))
                options.Add(new(new { kind = "bundle", cards = bundle.CardNodes.Select(c => CardAdvisorCapture.Card(c.Model ?? throw new InvalidDataException("Bundle card is not ready."))).ToArray() },
                    () => ClickLegalAsync(bundle.Hitbox)));
            await SelectUiAsync("BUNDLE", options, null, overlay, ct);
            return;
        }
        if (overlay is NCardGridSelectionScreen)
        {
            await PolicyGridAsync(node, overlay, ct);
            return;
        }
        if (overlay is NCrystalSphereScreen)
        {
            var proceed = UiHelper.FindAll<NProceedButton>(node).FirstOrDefault(b => b.IsEnabled && b.IsVisibleInTree());
            if (proceed != null) { await ClickLegalAsync(proceed); return; }
            // Only positions of still-covered cells; never expose their hidden
            // reward identities, sizes or the generated solution grid.
            foreach (var cell in UiHelper.FindAll<NCrystalSphereCell>(node).Where(c => c.IsVisibleInTree() && c.Entity.IsHidden))
                options.Add(new(new { kind = "reveal", x = cell.Position.X, y = cell.Position.Y }, () => ClickLegalAsync(cell)));
            if (options.Count > 0) await SelectUiAsync("CRYSTAL", options, null, overlay, ct);
            return;
        }
        throw new NotSupportedException($"Unadapted autonomous overlay {overlay.GetType().Name}.");
    }

    private async Task PolicyGridAsync(Node node, IOverlayScreen overlay, CancellationToken ct)
    {
        CardSelectorPrefs prefs;
        HashSet<CardModel> selected;
        string action;
        object? effect = null;
        switch (overlay)
        {
            case NDeckUpgradeSelectScreen s: prefs = s._prefs; selected = s._selectedCards; action = "upgrade"; break;
            case NDeckTransformSelectScreen s: prefs = s._prefs; selected = s._selectedCards; action = "transform"; break;
            case NDeckEnchantSelectScreen s:
                prefs = s._prefs; selected = s._selectedCards; action = "enchant";
                effect = new { id = s._enchantment.Id.Entry, amount = s._enchantmentAmount }; break;
            case NDeckCardSelectScreen s:
                prefs = s._prefs; selected = s._selectedCards;
                action = prefs.Prompt.LocEntryKey == CardSelectorPrefs.RemoveSelectionPrompt.LocEntryKey ? "remove" : "select"; break;
            case NSimpleCardSelectScreen s:
                prefs = s._prefs; selected = s._selectedCards; action = s._cardResults != null ? "take" : "select"; break;
            default: throw new NotSupportedException($"Unknown card grid {overlay.GetType().Name}.");
        }
        // Preview confirms an already logged choice. Never click cancel/back
        // merely because it is the first clickable control in a preview.
        var confirms = UiHelper.FindAll<NConfirmButton>(node).Where(b => b.IsEnabled && b.IsVisibleInTree()).ToArray();
        if (selected.Count > 0 && confirms.Length > 0)
        {
            await ClickLegalAsync(confirms[^1]);
            return;
        }
        List<UiChoice> options = [];
        var selection = (NCardGridSelectionScreen)overlay;
        // The native selector owns the complete player-visible legal list,
        // including cards currently outside the virtualized scroll viewport.
        foreach (CardModel card in selection._cards.Where(c => !selected.Contains(c)))
        {
            int deckIndex = Me.Deck.Cards.ToList().FindIndex(c => ReferenceEquals(c, card));
            CardModel scored = card;
            if (action == "upgrade")
            {
                scored = (CardModel)card.MutableClone(); scored.UpgradeInternal(); scored.FinalizeUpgradeInternal();
            }
            options.Add(new(new { kind = "card", action, deckIndex, card = CardAdvisorCapture.Card(scored) },
                () => PressGridCardAsync(selection, card, ct)));
        }
        if (prefs.MinSelect == 0 && confirms.Length > 0)
            options.Add(new(new { kind = "skip" }, () => ClickLegalAsync(confirms[^1])));
        await SelectUiAsync("CARD_GRID", options, new { action, min = prefs.MinSelect, max = prefs.MaxSelect,
            selected = selected.Select(CardAdvisorCapture.Card).ToArray(), prompt = prefs.Prompt.LocEntryKey, effect }, overlay, ct);
    }
}
