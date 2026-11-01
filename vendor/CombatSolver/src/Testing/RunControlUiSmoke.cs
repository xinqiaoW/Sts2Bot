using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Runs;
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
            if (!original.SequenceEqual(player.Deck.Cards))
                throw new InvalidOperationException("UI fixture unexpectedly changed the real deck.");
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
}
