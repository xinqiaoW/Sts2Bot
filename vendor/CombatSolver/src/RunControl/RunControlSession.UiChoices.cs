using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;

namespace CombatSolver;

internal sealed partial class RunControlSession
{
    // Only thrown synchronously, before any input signal or game operation.
    internal sealed class StaleUiChoiceException(string reason) : InvalidOperationException(reason);

    internal static bool IsCurrentSurface(IOverlayScreen screen) => screen is Node node
        && GodotObject.IsInstanceValid(node) && node.IsInsideTree() && !node.IsQueuedForDeletion()
        && ReferenceEquals(NOverlayStack.Instance?.Peek(), screen)
        && (node is not CanvasItem item || item.IsVisibleInTree());

    internal static Task? TryStartUiChoice(Func<Task> execute, Func<bool> isCurrent, out string? staleReason)
    {
        staleReason = null;
        if (!isCurrent())
        {
            staleReason = "decision_state_or_surface_changed";
            return null;
        }
        try { return execute(); }
        catch (StaleUiChoiceException ex)
        {
            staleReason = ex.Message;
            return null;
        }
        // Never catch faults from the returned task: an input may already have
        // caused a purchase/selection. Retrying that action would be unsafe.
    }

    internal static bool RewardSelectionReady(NCardRewardSelectionScreen screen) => IsCurrentSurface(screen)
        && screen._completionSource is { Task.IsCompleted: false }
        && screen._options.All(option => screen._cardRow.GetChildren().OfType<NCardHolder>().Any(h =>
            !h.IsQueuedForDeletion() && h.IsVisibleInTree() && h._isClickable
            && ReferenceEquals(h.CardModel, option.Card)));

    internal static Func<Task> CaptureRewardChoice(NCardRewardSelectionScreen screen, int index, bool alternative)
    {
        CardModel[] cards = screen._options.Select(o => o.Card).ToArray();
        var alternatives = screen._extraOptions.ToArray();
        var completion = screen._completionSource;
        string cardsBefore = JsonSerializer.Serialize(cards.Select(CardAdvisorCapture.Card), RunControlFiles.Json);
        return () =>
        {
            if (!IsCurrentSurface(screen)) throw new StaleUiChoiceException("reward_surface_changed");
            if (completion == null || completion.Task.IsCompleted || !ReferenceEquals(completion, screen._completionSource))
                throw new StaleUiChoiceException("reward_selection_already_completed_or_replaced");
            if (!cards.SequenceEqual(screen._options.Select(o => o.Card), ReferenceEqualityComparer.Instance)
                || !alternatives.SequenceEqual(screen._extraOptions, ReferenceEqualityComparer.Instance)
                || cardsBefore != JsonSerializer.Serialize(cards.Select(CardAdvisorCapture.Card), RunControlFiles.Json))
                throw new StaleUiChoiceException("reward_options_changed");
            if (alternative)
            {
                var buttons = screen._rewardAlternativesContainer.GetChildren()
                    .OfType<NCardRewardAlternativeButton>().Where(b => !b.IsQueuedForDeletion()).ToArray();
                if (buttons.Length != alternatives.Length)
                    throw new StaleUiChoiceException("reward_alternatives_rebuilding");
                return ClickLegalAsync(buttons[index]);
            }
            NCardHolder? holder = screen._cardRow.GetChildren().OfType<NCardHolder>().FirstOrDefault(h =>
                !h.IsQueuedForDeletion() && h.IsVisibleInTree() && ReferenceEquals(h.CardModel, cards[index]));
            if (holder == null || !holder._isClickable)
                throw new StaleUiChoiceException("reward_card_not_ready");
            return PressCardAsync(holder);
        };
    }
}
