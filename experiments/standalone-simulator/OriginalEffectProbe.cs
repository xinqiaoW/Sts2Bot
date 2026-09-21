using System.Reflection;

internal static class OriginalEffectProbe
{
    private static object Read(object o, string name) => o.GetType().GetProperty(name)!.GetValue(o)!;
    public static object Run(Func<string, Type> get, object root, object player, object enemy, object monster)
    {
        object sim = root.GetType().GetMethod("ForkSimulator")!.Invoke(root, null)!;
        object state = Read(sim, "State");
        object ps = state.GetType().GetMethod("GetPlayerCombatState")!.Invoke(state, [player])!;
        object[] cards = ((System.Collections.IEnumerable)Read(Read(ps, "Hand"), "Cards")).Cast<object>().ToArray();
        object creature = Read(player, "Creature");
        // This is an effect-level oracle: mark the already constructed fixture active,
        // without claiming that game startup or combat-start hooks have been executed.
        object manager = get("Combat.CombatManager").GetProperty("Instance")!.GetValue(null)!;
        Type turnType = get("Combat.CombatTurnState");
        object turn = Activator.CreateInstance(turnType, [Read(creature, "CombatState")])!;
        turnType.GetProperty("IsInProgress")!.SetValue(turn, true);
        manager.GetType().GetField("_turnState", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(manager, turn);
        object context = Activator.CreateInstance(get("GameActions.Multiplayer.ThrowingPlayerChoiceContext"))!;
        for (int i = 0; i < cards.Length; i++)
        {
            object card = Read(cards[i], "Original");
            object? target = i == 0 ? enemy : null;
            sim.GetType().GetMethod("ManualPlay")!.Invoke(sim, [cards[i], target, null]);
            object play = Activator.CreateInstance(get("Entities.Cards.CardPlay"))!;
            void Set(string n, object? v) => play.GetType().GetProperty(n)!.SetValue(play, v);
            Set("Card", card); Set("Target", target); Set("ResultPile", Enum.Parse(get("Entities.Cards.PileType"), "Discard"));
            Set("Resources", Activator.CreateInstance(play.GetType().GetProperty("Resources")!.PropertyType));
            Set("IsAutoPlay", false); Set("PlayIndex", 0); Set("PlayCount", 1);
            // Original game effect method, not a mirrored formula. Wrapper/cost/piles are outside this oracle.
            var task = (Task)card.GetType().GetMethod("OnPlay", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(card, [context, play])!;
            task.WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        }
        object expectedFoe = state.GetType().GetMethod("GetCreature")!.Invoke(state, [enemy])!;
        object expectedMe = state.GetType().GetMethod("GetCreature")!.Invoke(state, [creature])!;
        if (!Equals(Read(enemy, "CurrentHp"), Read(expectedFoe, "CurrentHp")) || !Equals(Read(creature, "Block"), Read(expectedMe, "Block")))
            throw new InvalidOperationException($"Original effects differ: enemy {Read(enemy, "CurrentHp")} vs {Read(expectedFoe, "CurrentHp")}; block {Read(creature, "Block")} vs {Read(expectedMe, "Block")}");
        int blockBeforeAttack = (int)Read(creature, "Block");
        object shadow = Read(state, "CombatState");
        object move = shadow.GetType().GetMethod("CurrentMonsterMove")!.Invoke(shadow, [enemy])!;
        var semantics = sim.GetType().Assembly.GetType("CombatSolver.MonsterMoveSemantics", true)!;
        semantics.GetMethod("ApplyForecastMove")!.Invoke(null, [sim, shadow, move, creature, new HashSet<uint>(), null]);
        var allies = Read(Read(creature, "CombatState"), "PlayerCreatures");
        ((Task)monster.GetType().GetMethod("ClampMove", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(monster, [allies])!).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        if (!Equals(Read(creature, "CurrentHp"), Read(expectedMe, "CurrentHp")) || !Equals(Read(creature, "Block"), Read(expectedMe, "Block")))
            throw new InvalidOperationException("Original Chomper attack differs from simulation.");
        return new { status = "original_effects_matched", scope = "StrikeSilent/DefendSilent OnPlay and Chomper ClampMove effects; excludes play wrapper, cost, piles and turn lifecycle", enemyHp = Read(enemy, "CurrentHp"), blockBeforeAttack, playerHpAfterAttack = Read(creature, "CurrentHp"), playerBlockAfterAttack = Read(creature, "Block"), productionReady = false };
    }
}
