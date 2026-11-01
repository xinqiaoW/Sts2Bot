using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves.Runs;

namespace CombatSolver;

internal sealed record CardAdvisorSnapshot(string Json, string Title, string[] Names, string Note);

// Main-thread-only adapter. No Godot or live game objects cross the HTTP boundary.
internal static class CardAdvisorCapture
{
    internal static readonly JsonSerializerOptions JsonOptions = new() { IncludeFields = true };

    internal static IEnumerable<T> Descendants<T>(Node node) where T : Node
    {
        foreach (Node child in node.GetChildren())
        {
            if (child is T typed) yield return typed;
            foreach (T nested in Descendants<T>(child)) yield return nested;
        }
    }

    internal static CardAdvisorSnapshot? Capture(Node host)
    {
        if (!Entry.Enabled || CombatManager.Instance.IsInProgress || CombatManager.Instance.IsStarting
            || !RunManager.Instance.IsInProgress) return null;
        RunState? run = RunManager.Instance.DebugOnlyGetState();
        if (run == null || run.Players.Count != 1) return null;
        Player? player = LocalContext.GetMe(run);
        if (player == null) return null;
        object? surface = NOverlayStack.Instance?.Peek();
        List<CardModel> cards = [];
        List<int?> prices = [];
        string operation = "take", title;
        bool canSkip = true;
        string note = "";
        if (surface is NCardRewardSelectionScreen reward)
        {
            cards = reward._options.Select(o => o.Card).ToList();
            title = "奖励选牌";
            if (reward._extraOptions.Count > 0) note = "其他奖励按钮及跳过触发效果未计分。";
        }
        else if (surface is NChooseACardSelectionScreen choose)
        {
            cards = choose._cards.ToList();
            if (cards.Any(c => player.Deck.Cards.Contains(c)))
                throw new NotSupportedException("此事件选牌效果尚未适配，不能按加牌评分。");
            title = "事件选牌"; canSkip = choose._canSkip;
            note = "按选入牌组评分；事件额外代价未计入。";
        }
        else if (surface is NSimpleCardSelectScreen simple && simple._cardResults != null)
        {
            cards = simple._cards.ToList(); title = "事件奖励选牌";
            canSkip = simple._prefs.MinSelect == 0 || simple._prefs.Cancelable;
            if (simple._prefs.MaxSelect != 1) note = "逐张独立评分，不代表多选组合收益。";
        }
        else if (surface is NDeckUpgradeSelectScreen upgrade)
        {
            cards = upgrade._cards.ToList(); title = "升级选牌"; operation = "upgrade";
            canSkip = upgrade._prefs.MinSelect == 0 || upgrade._prefs.Cancelable;
            note = "逐张升级评分；不含额外事件效果。";
        }
        else if (surface is NDeckCardSelectScreen remove)
        {
            if (remove._prefs.Prompt.LocEntryKey != CardSelectorPrefs.RemoveSelectionPrompt.LocEntryKey)
                throw new NotSupportedException("此事件的牌组操作尚未适配评分。");
            cards = remove._cards.ToList(); title = "移除选牌"; operation = "remove";
            canSkip = remove._prefs.MinSelect == 0 || remove._prefs.Cancelable;
            note = "逐张移除评分；价格及事件额外代价未计入。";
        }
        else if (surface is NDeckTransformSelectScreen or NDeckEnchantSelectScreen)
            throw new NotSupportedException("随机变牌或附魔结果尚未适配评分。");
        else if (surface == null)
        {
            NMerchantCard[] slots = Descendants<NMerchantCard>(host)
                .Where(s => s.IsVisibleInTree() && s.Entry is MerchantCardEntry { IsStocked: true })
                .ToArray();
            if (slots.Length == 0) return null;
            title = "商店选牌";
            foreach (NMerchantCard slot in slots)
            {
                MerchantCardEntry entry = (MerchantCardEntry)slot.Entry;
                cards.Add(entry.CreationResult!.Card); prices.Add(entry.Cost);
            }
            note = "仅比较单张购入的构筑收益，不含金币机会成本。" + FilterShopCards(cards, prices);
            if (cards.Count == 0)
                throw new NotSupportedException(note + "当前没有其他可评分的商店卡牌。");
        }
        else return null;
        if (cards.Count == 0) return null;
        if (player.Character.Id.Entry != "SILENT" || run.AscensionLevel != 10 || run.Modifiers.Count != 0)
            throw new NotSupportedException("评分模型仅支持无额外修饰的单人静默猎手 A10。");

        List<object> options = [];
        List<string> names = [];
        foreach (CardModel card in cards)
        {
            int index = player.Deck.Cards.ToList().FindIndex(c => ReferenceEquals(c, card));
            if (operation != "take" && index < 0)
                throw new NotSupportedException("选牌实例不在当前牌组中。");
            CardModel scored = card;
            if (operation == "upgrade")
            {
                // Deep mutable clone, never RunState.CloneCard (which registers
                // a new live card) and never invoke upgrade hooks on the player.
                scored = (CardModel)card.MutableClone();
                scored.UpgradeInternal(); scored.FinalizeUpgradeInternal();
            }
            options.Add(new { action = operation, deck_index = index, card = Card(scored) });
            string price = prices.Count > 0 ? $"  {prices[names.Count]} 金" + (prices[names.Count] > player.Gold ? "（不足）" : "") : "";
            names.Add(card.Title + price);
        }
        names.Add(canSkip ? (prices.Count > 0 ? "不购买" : "跳过 / 保持牌组") : "原牌组基准（不可跳过）");

        List<object[]> history = [];
        for (int act = 0; act < run.MapPointHistory.Count; act++)
            foreach (var point in run.MapPointHistory[act])
                foreach (var chosen in point.GetEntry(player.NetId).AncientChoices.Where(c => c.WasChosen))
                {
                    var events = point.Rooms.Where(r => r.ModelId != null && r.ModelId.ToString().StartsWith("EVENT.", StringComparison.Ordinal)).ToArray();
                    if (events.Length != 1) throw new NotSupportedException("古代事件历史不明确。");
                    history.Add([act + 1, events[0].ModelId!.Entry, chosen.TextKey]);
                }
        MapPoint current = run.CurrentMapPoint ?? throw new NotSupportedException("当前地图位置尚未就绪。");
        Dictionary<MapPoint, double> frontier = new() { [current] = 1 };
        List<Dictionary<string, double>> future = [];
        for (int layer = 0; layer < 2; layer++)
        {
            Dictionary<MapPoint, double> next = [];
            foreach (var (point, probability) in frontier)
                foreach (MapPoint child in point.Children)
                    next[child] = next.GetValueOrDefault(child) + probability / point.Children.Count;
            if (next.Count == 0) break;
            Dictionary<string, double> types = [];
            foreach (var (point, probability) in next)
                types[point.PointType.ToString()] = types.GetValueOrDefault(point.PointType.ToString()) + probability;
            future.Add(types); frontier = next;
        }
        var payload = new
        {
            protocol = 1, character = player.Character.Id.Entry, ascension = run.AscensionLevel,
            build = new { act_id = run.Act.Id.Entry, act = run.CurrentActIndex + 1, family = "live-advisor",
                cards = player.Deck.Cards.Select(Card).ToArray(), relics = player.Relics.Select(Relic).ToArray(), ancient_history = history },
            max_hp = player.Creature.MaxHp, gold = player.Gold,
            options, future_room_types = future,
            floors_to_boss = Math.Max(0, run.Map.BossMapPoint.coord.row - current.coord.row),
            boss_targets = new Dictionary<string, double> { [run.Act.BossEncounter.Id.Entry] = 1 },
        };
        if (run.Act.HasSecondBoss) note += "当前以本幕首个 Boss 为长期目标。";
        return new CardAdvisorSnapshot(JsonSerializer.Serialize(payload, JsonOptions), title, names.ToArray(),
            "满血构筑评分，越大越好；地图分支及同类敌人等概率估计。" + note);
    }

    // Keep each price paired with its card while excluding the user's explicit
    // shop-only exception. This does not change the inventory or owned deck.
    internal static string FilterShopCards(List<CardModel> cards, List<int?> prices)
    {
        if (cards.Count != prices.Count) throw new InvalidOperationException("商店卡牌与价格数量不匹配。");
        List<string> ignored = [];
        for (int i = cards.Count - 1; i >= 0; i--)
        {
            if (cards[i].Id.Entry != "ALCHEMIZE") continue;
            ignored.Add(cards[i].Title);
            cards.RemoveAt(i); prices.RemoveAt(i);
        }
        return ignored.Count == 0 ? "" : "已跳过评分：" + string.Join("、", ignored) + "。";
    }

    private static object Card(CardModel card)
    {
        SerializableCard saved = card.ToSerializable();
        return new { id = card.Id.Entry, upgrade = card.CurrentUpgradeLevel,
            enchantment_id = saved.Enchantment?.Id?.Entry ?? "", enchantment_amount = saved.Enchantment?.Amount ?? 0,
            persistent_state = saved.Props?.ints?.ToDictionary(p => p.name, p => p.value) ?? new Dictionary<string, int>(),
            unsupported_fields = NonScalar(saved.Props).Concat(saved.Props?.bools?.Select(p => p.name) ?? []).ToArray() };
    }

    private static object Relic(RelicModel relic)
    {
        // SavedProperties omits default-valued counters. Read all declared
        // saved scalars so zero/false remain explicit in the model input.
        var properties = relic.GetType().GetProperties(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
            .Where(p => p.GetCustomAttributes(typeof(SavedPropertyAttribute), true).Length > 0).ToArray();
        return new { id = relic.Id.Entry,
            state = properties.Where(p => p.PropertyType == typeof(int) || p.PropertyType == typeof(bool))
                .Select(p => new object[] { p.Name, p.GetValue(relic)! }).ToArray(),
            unsupported_fields = properties.Where(p => p.PropertyType != typeof(int) && p.PropertyType != typeof(bool)).Select(p => p.Name).ToArray() };
    }

    private static IEnumerable<string> NonScalar(SavedProperties? props)
    {
        if (props == null) yield break;
        if (props.strings?.Count > 0) yield return "strings";
        if (props.intArrays?.Count > 0) yield return "int_arrays";
        if (props.modelIds?.Count > 0) yield return "model_ids";
        if (props.cards?.Count > 0) yield return "cards";
        if (props.cardArrays?.Count > 0) yield return "card_arrays";
    }
}
