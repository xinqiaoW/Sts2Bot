using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Localization.Fonts;
using MegaCrit.Sts2.Core.Models;

namespace CombatSolver;

internal sealed partial class SolverPotionStrategyPanel : PanelContainer
{
    internal const float PreferredWidth = 184f;
    private const float CardMinimumWidth = 152f;
    private readonly GridContainer _cards;
    private string? _renderedSignature;

    public SolverPotionStrategyPanel()
    {
        Name = "PotionStrategyPanel";
        Visible = false;
        MouseFilter = MouseFilterEnum.Stop;
        CustomMinimumSize = new Vector2(PreferredWidth, 0);
        SizeFlagsHorizontal = SizeFlags.ShrinkEnd;
        SizeFlagsVertical = SizeFlags.ExpandFill;
        AddThemeStyleboxOverride("panel", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.Surface,
            SolverUiTokens.Palette.BorderSubtle,
            SolverUiTokens.Radius.Medium,
            SolverUiTokens.Spacing.Sm,
            SolverUiTokens.Spacing.Sm));

        VBoxContainer layout = new()
        {
            Name = "PotionStrategyLayout",
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        layout.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Sm);
        Label heading = SolverUiTokens.CreateLabel(
            "药水策略",
            SolverUiTokens.Type.Body,
            SolverUiTokens.Palette.TextPrimary,
            FontType.Bold);
        layout.AddChild(heading);

        _cards = new GridContainer
        {
            Name = "PotionCards",
            Columns = 1,
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        _cards.AddThemeConstantOverride("h_separation", SolverUiTokens.Spacing.Sm);
        _cards.AddThemeConstantOverride("v_separation", SolverUiTokens.Spacing.Sm);
        ScrollContainer scroll = new()
        {
            Name = "PotionCardScroll",
            CustomMinimumSize = new Vector2(0, 176),
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
            SizeFlagsVertical = SizeFlags.ExpandFill,
            HorizontalScrollMode = ScrollContainer.ScrollMode.Disabled,
            VerticalScrollMode = ScrollContainer.ScrollMode.Auto,
            MouseFilter = MouseFilterEnum.Pass,
        };
        scroll.AddChild(_cards);
        layout.AddChild(scroll);
        AddChild(layout);
        Resized += UpdateGridColumns;
    }

    public event Action<int, string, SolverPotionDirective>? DirectiveChanged;

    internal int RowCountForTesting { get; private set; }
    internal bool RowsUseIconAndTextForTesting { get; private set; }
    internal bool UsesGridCardsForTesting { get; private set; }
    internal bool IsSlimForTesting
        => CustomMinimumSize.X == PreferredWidth && _cards.Columns == 1;

    public void Refresh(CombatState? state, bool controlsDisabled)
    {
        Player? player = state == null ? null : LocalContext.GetMe(state);
        List<(int Slot, PotionModel Potion, SolverPotionDirective Directive, bool Searchable)> potions = [];
        if (player != null)
        {
            for (int slot = 0; slot < player.PotionSlots.Count; slot++)
            {
                PotionModel? potion = player.GetPotionAtSlotIndex(slot);
                if (potion == null)
                    continue;
                potions.Add((
                    slot,
                    potion,
                    SolverController.ResolvePotionDirective(state!, slot, potion.Id.Entry),
                    PotionOnUseSupport.CanSearch(potion)));
            }
        }

        string signature = string.Join('|', potions.Select(item =>
            $"{item.Slot}:{item.Potion.Id.Entry}:{item.Directive}:{item.Searchable}"))
            + $";disabled={controlsDisabled}";
        if (string.Equals(signature, _renderedSignature, StringComparison.Ordinal))
            return;
        _renderedSignature = signature;
        RebuildRows(potions, controlsDisabled);
    }

    public void Invalidate() => _renderedSignature = null;

    private void RebuildRows(
        IReadOnlyList<(int Slot, PotionModel Potion, SolverPotionDirective Directive, bool Searchable)> potions,
        bool controlsDisabled)
    {
        foreach (Node child in _cards.GetChildren())
        {
            _cards.RemoveChild(child);
            child.QueueFree();
        }

        RowCountForTesting = potions.Count;
        RowsUseIconAndTextForTesting = potions.Count > 0;
        UsesGridCardsForTesting = potions.Count > 0;
        if (potions.Count == 0)
        {
            Label empty = SolverUiTokens.CreateLabel(
                "当前没有药水",
                SolverUiTokens.Type.Body,
                SolverUiTokens.Palette.TextMuted);
            empty.CustomMinimumSize = new Vector2(0, 32);
            _cards.AddChild(empty);
            return;
        }

        foreach ((int slot, PotionModel potion, SolverPotionDirective directive, bool searchable) in potions)
            _cards.AddChild(CreatePotionCard(slot, potion, directive, searchable, controlsDisabled));
        Callable.From(UpdateGridColumns).CallDeferred();
    }

    private Control CreatePotionCard(
        int slot,
        PotionModel potion,
        SolverPotionDirective directive,
        bool searchable,
        bool controlsDisabled)
    {
        PanelContainer card = new()
        {
            Name = $"PotionStrategyCard{slot}",
            CustomMinimumSize = new Vector2(CardMinimumWidth, 64),
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        card.AddThemeStyleboxOverride("panel", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.SurfaceRaised,
            SolverUiTokens.Palette.BorderSubtle,
            SolverUiTokens.Radius.Medium,
            SolverUiTokens.Spacing.Sm,
            SolverUiTokens.Spacing.Xs));
        HBoxContainer layout = new()
        {
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
            Alignment = BoxContainer.AlignmentMode.Begin,
        };
        layout.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Sm);

        TextureRect icon = new()
        {
            Name = "PotionIcon",
            Texture = potion.Image,
            CustomMinimumSize = new Vector2(44, 44),
            SizeFlagsHorizontal = SizeFlags.ShrinkBegin,
            SizeFlagsVertical = SizeFlags.ShrinkCenter,
            ExpandMode = TextureRect.ExpandModeEnum.IgnoreSize,
            StretchMode = TextureRect.StretchModeEnum.KeepAspectCentered,
            MouseFilter = MouseFilterEnum.Ignore,
        };
        layout.AddChild(icon);

        Label title = SolverUiTokens.CreateLabel(
            $"#{slot + 1} {potion.Title.GetFormattedText()}",
            SolverUiTokens.Type.Caption,
            SolverUiTokens.Palette.TextPrimary,
            FontType.Bold);
        title.Name = "PotionTitle";
        title.SizeFlagsHorizontal = SizeFlags.ExpandFill;
        title.HorizontalAlignment = HorizontalAlignment.Left;
        title.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        title.CustomMinimumSize = new Vector2(0, 44);
        title.TooltipText = potion.Title.GetFormattedText();
        layout.AddChild(title);

        Button input = CreateDirectiveToggle(directive);
        input.Name = "PotionDirectiveToggle";
        input.Disabled = controlsDisabled || !searchable;
        if (!searchable)
        {
            input.TooltipText = "该药水不可指定使用策略";
        }
        else
        {
            string potionId = potion.Id.Entry;
            input.Pressed += () =>
            {
                directive = NextDirective(directive);
                ApplyDirectiveToggle(input, directive);
                DirectiveChanged?.Invoke(slot, potionId, directive);
            };
        }
        layout.AddChild(input);
        card.AddChild(layout);
        return card;
    }

    private void UpdateGridColumns()
        => _cards.Columns = 1;

    private static Button CreateDirectiveToggle(SolverPotionDirective directive)
    {
        Button input = new()
        {
            FocusMode = FocusModeEnum.None,
            CustomMinimumSize = new Vector2(40, 40),
            SizeFlagsHorizontal = SizeFlags.ShrinkEnd,
            SizeFlagsVertical = SizeFlags.ShrinkCenter,
            MouseDefaultCursorShape = CursorShape.PointingHand,
        };
        input.AddThemeFontSizeOverride("font_size", 18);
        input.ApplyLocaleFontSubstitution(FontType.Bold, "font");
        SolverUiTokens.ApplyTextOutline(input);
        ApplyDirectiveToggle(input, directive);
        return input;
    }

    private static SolverPotionDirective NextDirective(SolverPotionDirective directive)
        => directive switch
        {
            SolverPotionDirective.Smart => SolverPotionDirective.Disabled,
            SolverPotionDirective.Disabled => SolverPotionDirective.Force,
            _ => SolverPotionDirective.Smart,
        };

    private static void ApplyDirectiveToggle(Button input, SolverPotionDirective directive)
    {
        (string text, string description, Color color) = directive switch
        {
            SolverPotionDirective.Disabled => ("x", "禁用 / 保护", SolverUiTokens.Palette.Danger),
            SolverPotionDirective.Force => ("✓", "强制使用", SolverUiTokens.Palette.Success),
            _ => ("-", "智能使用", SolverUiTokens.Palette.TextSecondary),
        };
        Color background = SolverUiTokens.IsLightTheme
            ? SolverUiTokens.Palette.Surface
            : SolverUiTokens.Palette.Background;
        input.Text = text;
        input.TooltipText = $"{description}（点击切换）";
        input.AddThemeColorOverride("font_color", color);
        input.AddThemeColorOverride("font_hover_color", color);
        input.AddThemeColorOverride("font_pressed_color", color);
        input.AddThemeColorOverride("font_disabled_color", SolverUiTokens.Palette.TextMuted);
        input.AddThemeStyleboxOverride("normal", SolverUiTokens.CreateBox(
            background,
            color,
            SolverUiTokens.Radius.Small,
            SolverUiTokens.Spacing.Xs,
            SolverUiTokens.Spacing.Xs));
        input.AddThemeStyleboxOverride("hover", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.SurfaceHover,
            color.Lightened(0.12f),
            SolverUiTokens.Radius.Small,
            SolverUiTokens.Spacing.Xs,
            SolverUiTokens.Spacing.Xs));
        input.AddThemeStyleboxOverride("pressed", SolverUiTokens.CreateBox(
            background.Darkened(0.12f),
            color,
            SolverUiTokens.Radius.Small,
            SolverUiTokens.Spacing.Xs,
            SolverUiTokens.Spacing.Xs));
        input.AddThemeStyleboxOverride("disabled", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.Background,
            SolverUiTokens.Palette.BorderSubtle,
            SolverUiTokens.Radius.Small,
            SolverUiTokens.Spacing.Xs,
            SolverUiTokens.Spacing.Xs));
    }
}
