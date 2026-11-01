using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;

namespace CombatSolver;

// Explicit opt-in headless fixture. Uses synthetic immutable inputs, not a
// gameplay session. Tests the real C# HTTP client and real Godot renderer.
internal static class CardAdvisorSmoke
{
    internal static async Task RunAsync(NGame host, CardAdvisorController client, string path)
    {
        string status = "failed", error = "";
        List<object> evidence = [];
        try
        {
            client.SetProcess(false);
            await host.GameStartupComplete;
            VerifyShopFilter();
            using JsonDocument fixture = JsonDocument.Parse(File.ReadAllText(path));
            var overlay = new CardAdvisorOverlay(); host.AddChild(overlay);
            foreach (JsonElement scenario in fixture.RootElement.EnumerateArray())
            {
                string title = scenario.GetProperty("title").GetString()!;
                string[] names = scenario.GetProperty("names").EnumerateArray().Select(n => n.GetString()!).ToArray();
                var snapshot = new CardAdvisorSnapshot(scenario.GetProperty("payload").GetRawText(), title, names, "headless structural fixture");
                using CancellationTokenSource timeout = new(TimeSpan.FromSeconds(90));
                CardAdvisorView view = await client.RequestAsync(snapshot, title, timeout.Token);
                if (view.Status != "" || view.Rows.Length != names.Length)
                    throw new InvalidOperationException($"{title}: {view.Status}; row_count={view.Rows.Length}");
                overlay.Render(view);
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                int labels = CardAdvisorCapture.Descendants<Label>(overlay).Count(l => l.Text.Contains("综合 "));
                if (labels != names.Length) throw new InvalidOperationException($"{title}: rendered {labels}/{names.Length}");
                overlay.Render(null);
                bool visible = CardAdvisorCapture.Descendants<PanelContainer>(overlay).Any(p => p.Visible);
                if (visible) throw new InvalidOperationException("Stale scores remained after closing the surface");
                evidence.Add(new { title, rows = labels, hidden_after_close = !visible, scores = view.Rows });
            }
            status = "passed";
        }
        catch (Exception ex)
        {
            // Test terminal boundary: fail the process and retain full evidence.
            error = ex.ToString(); Entry.Logger.Error("[CardAdvisor/Smoke] FAILED " + error);
        }
        finally
        {
            File.WriteAllText(path + ".result.json", JsonSerializer.Serialize(new { status, error, evidence }));
            Entry.Logger.Info($"[CardAdvisor/Smoke] {status} scenarios={evidence.Count}");
            host.GetTree().Quit(status == "passed" ? 0 : 1);
        }
    }

    private static void VerifyShopFilter()
    {
        CardModel first = ModelDb.Card<Footwork>();
        CardModel second = ModelDb.Card<Backflip>();
        CardModel ignored = ModelDb.Card<Alchemize>();
        // Leading/middle/trailing exclusions must not shift the remaining
        // prices. Use the same native-card adapter as the real shop capture.
        for (int position = 0; position < 3; position++)
        {
            List<CardModel> cards = [first, second];
            List<int?> prices = [71, 43];
            cards.Insert(position, ignored); prices.Insert(position, 159);
            string note = CardAdvisorCapture.FilterShopCards(cards, prices);
            if (!cards.SequenceEqual(new[] { first, second }) || !prices.SequenceEqual(new int?[] { 71, 43 })
                || !note.Contains(ignored.Title))
                throw new InvalidOperationException("Shop filtering shifted card identities/prices or omitted the notice.");
        }
        List<CardModel> onlyIgnored = [ignored]; List<int?> onlyPrice = [159];
        string emptyNote = CardAdvisorCapture.FilterShopCards(onlyIgnored, onlyPrice);
        if (onlyIgnored.Count != 0 || onlyPrice.Count != 0 || emptyNote.Length == 0)
            throw new InvalidOperationException("Shop with only Alchemize was not excluded.");
        Entry.Logger.Info("[CardAdvisor/Smoke] shop_filter passed positions=3 only_ignored=true");
    }
}
