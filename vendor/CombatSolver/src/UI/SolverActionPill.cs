using Godot;
using MegaCrit.Sts2.Core.Localization.Fonts;

namespace CombatSolver;

internal static class SolverActionPill
{
    public static Control Create(SolverOverlayActionSnapshot action)
    {
        bool killed = action.Kills.Count > 0;
        (Color border, Color background) = ActionColors(action.VisualKind);
        if (killed)
        {
            border = SolverUiTokens.Palette.Success;
            background = SolverUiTokens.Palette.KillBackground;
        }

        PanelContainer pill = new()
        {
            Name = "ActionPill",
            CustomMinimumSize = new Vector2(0, SolverUiTokens.Size.ActionPillHeight),
            MouseFilter = Control.MouseFilterEnum.Pass,
            TooltipText = action.Tooltip,
        };
        pill.AddThemeStyleboxOverride("panel", SolverUiTokens.CreateBox(
            background,
            border,
            SolverUiTokens.Radius.Pill,
            SolverUiTokens.Spacing.Sm,
            SolverUiTokens.Spacing.Xs));

        HBoxContainer content = new()
        {
            MouseFilter = Control.MouseFilterEnum.Ignore,
            Alignment = BoxContainer.AlignmentMode.Begin,
            SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
        };
        content.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Xs);
        content.AddChild(new ColorRect
        {
            Color = border,
            CustomMinimumSize = new Vector2(3, 14),
            SizeFlagsVertical = Control.SizeFlags.ShrinkCenter,
            MouseFilter = Control.MouseFilterEnum.Ignore,
        });
        content.AddChild(SolverUiTokens.CreateLabel(
            action.Title,
            SolverUiTokens.Type.Metric,
            killed ? SolverUiTokens.Palette.Success : SolverUiTokens.Palette.TextPrimary,
            FontType.Bold));
        if (action.ReplayCount > 0)
        {
            content.AddChild(SolverUiTokens.CreateLabel(
                $"重放×{action.ReplayCount}",
                SolverUiTokens.Type.Caption,
                SolverUiTokens.Palette.Warning,
                FontType.Bold));
        }
        if (!string.IsNullOrEmpty(action.TargetName))
        {
            content.AddChild(SolverUiTokens.CreateLabel(
                $"➔  {action.TargetName}",
                SolverUiTokens.Type.Body,
                SolverUiTokens.Palette.TextPrimary));
        }
        if (action.ChoiceText != null)
        {
            content.AddChild(SolverUiTokens.CreateLabel(
                action.ChoiceText,
                SolverUiTokens.Type.Body,
                SolverUiTokens.Palette.Accent));
        }
        if (action.RelicLabels.Count > 0)
        {
            const int maxVisibleRelics = 2;
            foreach (string relicLabel in action.RelicLabels.Take(maxVisibleRelics))
            {
                content.AddChild(SolverUiTokens.CreateLabel(
                    relicLabel,
                    SolverUiTokens.Type.Caption,
                    SolverUiTokens.Palette.Warning,
                    FontType.Bold));
            }
            if (action.RelicLabels.Count > maxVisibleRelics)
            {
                content.AddChild(SolverUiTokens.CreateLabel(
                    $"+{action.RelicLabels.Count - maxVisibleRelics}",
                    SolverUiTokens.Type.Caption,
                    SolverUiTokens.Palette.Warning,
                    FontType.Bold));
            }
        }
        if (killed)
        {
            content.AddChild(SolverUiTokens.CreateLabel(
                $"击杀：{string.Join("、", action.Kills)}",
                SolverUiTokens.Type.Caption,
                SolverUiTokens.Palette.Success,
                FontType.Bold));
        }
        pill.AddChild(content);
        return pill;
    }

    public static Control CreateStatus(string text, Color color)
    {
        PanelContainer pill = new()
        {
            CustomMinimumSize = new Vector2(0, SolverUiTokens.Size.ActionPillHeight),
            MouseFilter = Control.MouseFilterEnum.Ignore,
        };
        pill.AddThemeStyleboxOverride("panel", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.SurfaceRaised,
            SolverUiTokens.Palette.BorderSubtle,
            SolverUiTokens.Radius.Pill,
            SolverUiTokens.Spacing.Sm,
            SolverUiTokens.Spacing.Xs));
        pill.AddChild(SolverUiTokens.CreateLabel(text, SolverUiTokens.Type.Body, color));
        return pill;
    }

    private static (Color Border, Color Background) ActionColors(SolverOverlayActionVisualKind kind)
        => kind switch
        {
            SolverOverlayActionVisualKind.Attack => (SolverUiTokens.Palette.Attack, SolverUiTokens.Palette.AttackBackground),
            SolverOverlayActionVisualKind.Skill => (SolverUiTokens.Palette.Skill, SolverUiTokens.Palette.SkillBackground),
            SolverOverlayActionVisualKind.Power => (SolverUiTokens.Palette.Power, SolverUiTokens.Palette.PowerBackground),
            SolverOverlayActionVisualKind.Negative => (SolverUiTokens.Palette.Negative, SolverUiTokens.Palette.NegativeBackground),
            SolverOverlayActionVisualKind.Potion => (SolverUiTokens.Palette.Potion, SolverUiTokens.Palette.PotionBackground),
            _ => (SolverUiTokens.Palette.Border, SolverUiTokens.Palette.SurfaceRaised),
        };
}
