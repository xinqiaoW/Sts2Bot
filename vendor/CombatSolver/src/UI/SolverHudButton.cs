using Godot;

namespace CombatSolver;

internal sealed partial class SolverDetailsButton : Button
{
    private readonly Label _arrowLabel;

    public SolverDetailsButton()
    {
        FocusMode = FocusModeEnum.None;
        MouseDefaultCursorShape = CursorShape.PointingHand;
        CustomMinimumSize = new Vector2(106, 28);
        ToggleMode = true;
        SolverUiTokens.ApplyButtonStyle(this, SolverButtonStyle.Secondary);

        HBoxContainer layout = new()
        {
            Alignment = BoxContainer.AlignmentMode.Center,
            MouseFilter = MouseFilterEnum.Ignore,
        };
        layout.SetAnchorsAndOffsetsPreset(LayoutPreset.FullRect);
        layout.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Xs);
        layout.AddChild(SolverUiTokens.CreateLabel(
            "状态详情",
            SolverUiTokens.Type.Body,
            SolverUiTokens.Palette.TextPrimary,
            MegaCrit.Sts2.Core.Localization.Fonts.FontType.Bold));

        _arrowLabel = SolverUiTokens.CreateLabel(
            "▾",
            SolverUiTokens.Type.Caption,
            SolverUiTokens.Palette.TextSecondary,
            outlineSize: SolverUiTokens.IsLightTheme ? 0 : 1);
        layout.AddChild(_arrowLabel);
        AddChild(layout);
    }

    public void SetExpanded(bool expanded)
    {
        ButtonPressed = expanded;
        _arrowLabel.Text = expanded ? "▴" : "▾";
    }
}
