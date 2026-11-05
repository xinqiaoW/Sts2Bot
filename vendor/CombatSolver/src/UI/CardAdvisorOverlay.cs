using Godot;

namespace CombatSolver;

internal sealed record CardAdvisorRow(string Name, double Score, double Delta, double ShortLoss, double LongLoss);
internal sealed record CardAdvisorView(string Title, string Note, string Status, CardAdvisorRow[] Rows, string[]? InfoLines = null);

// Manual on-demand prediction overlay: shows a small floating badge/button; calculation only happens when clicked.
internal sealed partial class CardAdvisorOverlay : CanvasLayer
{
    internal event Action? CalculateRequested;
    private PanelContainer _panel = null!;
    private VBoxContainer _body = null!;
    private Label _title = null!;
    private Label _note = null!;
    private Button _calcButton = null!;
    private Button _floatPill = null!;
    private bool _panelOpen;
    private bool _dragging;
    private Vector2 _dragOffset;

    public override void _Ready()
    {
        Layer = 100;

        // Floating trigger button (always small & unobtrusive)
        _floatPill = new Button
        {
            Text = "?? ????",
            Position = new Vector2(18, 120),
            CustomMinimumSize = new Vector2(100, 32),
            FocusMode = Control.FocusModeEnum.None,
        };
        var pillStyle = new StyleBoxFlat
        {
            BgColor = new Color(0.08f, 0.12f, 0.18f, 0.90f),
            BorderColor = new Color(0.22f, 0.74f, 0.97f, 0.75f),
            BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
            CornerRadiusTopLeft = 6, CornerRadiusTopRight = 6, CornerRadiusBottomLeft = 6, CornerRadiusBottomRight = 6,
        };
        _floatPill.AddThemeStyleboxOverride("normal", pillStyle);
        _floatPill.AddThemeColorOverride("font_color", new Color(0.35f, 0.82f, 1.0f));
        _floatPill.AddThemeFontSizeOverride("font_size", 14);
        _floatPill.Pressed += OnFloatPillPressed;
        AddChild(_floatPill);

        // Result panel (hidden until user clicks)
        _panel = new PanelContainer { Position = new Vector2(18, 160), CustomMinimumSize = new Vector2(420, 0) };
        var panelStyle = new StyleBoxFlat
        {
            BgColor = new Color(0.07f, 0.10f, 0.15f, 0.95f),
            BorderColor = new Color(0.22f, 0.74f, 0.97f, 0.55f),
            BorderWidthLeft = 1, BorderWidthTop = 1, BorderWidthRight = 1, BorderWidthBottom = 1,
            CornerRadiusTopLeft = 8, CornerRadiusTopRight = 8, CornerRadiusBottomLeft = 8, CornerRadiusBottomRight = 8,
        };
        _panel.AddThemeStyleboxOverride("panel", panelStyle);

        var margin = new MarginContainer();
        foreach (string side in new[] { "left", "top", "right", "bottom" }) margin.AddThemeConstantOverride("margin_" + side, 12);
        var column = new VBoxContainer();
        var header = new HBoxContainer { MouseFilter = Control.MouseFilterEnum.Stop };
        header.GuiInput += OnHeaderGuiInput;
        _title = new Label { Text = "????", SizeFlagsHorizontal = Control.SizeFlags.ExpandFill, MouseFilter = Control.MouseFilterEnum.Ignore };
        _title.AddThemeColorOverride("font_color", new Color(0.35f, 0.82f, 1.0f));
        _title.AddThemeFontSizeOverride("font_size", 17);

        _calcButton = new Button { Text = "????", FocusMode = Control.FocusModeEnum.None };
        _calcButton.Pressed += () => CalculateRequested?.Invoke();

        var closeBtn = new Button { Text = "??", FocusMode = Control.FocusModeEnum.None };
        closeBtn.Pressed += () => SetPanelOpen(false);

        header.AddChild(_title); header.AddChild(_calcButton); header.AddChild(closeBtn); column.AddChild(header);

        var scroll = new ScrollContainer { CustomMinimumSize = new Vector2(396, 0) };
        scroll.SetMeta("advisor_scroll", true);
        _body = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        scroll.AddChild(_body); column.AddChild(scroll);

        _note = new Label { AutowrapMode = TextServer.AutowrapMode.WordSmart, CustomMinimumSize = new Vector2(396, 0) };
        _note.AddThemeFontSizeOverride("font_size", 14);
        _note.AddThemeColorOverride("font_color", new Color(0.65f, 0.72f, 0.82f));
        column.AddChild(_note); margin.AddChild(column); _panel.AddChild(margin); AddChild(_panel);

        _panel.Visible = false;
        _floatPill.Visible = true;
    }

    private void OnFloatPillPressed()
    {
        SetPanelOpen(!_panelOpen);
        if (_panelOpen)
        {
            CalculateRequested?.Invoke();
        }
    }

    public void SetPanelOpen(bool open)
    {
        _panelOpen = open;
        _panel.Visible = open;
        _floatPill.Text = open ? "? ????" : "?? ????";
    }

    public bool IsPanelOpen => _panelOpen;

    public void SetContextTip(string text)
    {
        if (!_panelOpen)
        {
            _floatPill.Text = string.IsNullOrEmpty(text) ? "?? ????" : $"?? ???? ({text})";
        }
    }

    public void SetCalculating(string title)
    {
        if (!_panelOpen) return;
        _title.Text = title;
        _note.Text = "??????????????";
        foreach (Node child in _body.GetChildren()) { _body.RemoveChild(child); child.QueueFree(); }
        var statusLbl = new Label { Text = "? ?????", AutowrapMode = TextServer.AutowrapMode.WordSmart };
        statusLbl.AddThemeFontSizeOverride("font_size", 15);
        _body.AddChild(statusLbl);
    }

    private void OnHeaderGuiInput(InputEvent @event)
    {
        if (@event is InputEventMouseButton mb && mb.ButtonIndex == MouseButton.Left)
        {
            _dragging = mb.Pressed;
            if (_dragging) _dragOffset = _panel.GetGlobalMousePosition() - _panel.Position;
        }
        else if (@event is InputEventMouseMotion && _dragging)
        {
            _panel.Position = _panel.GetGlobalMousePosition() - _dragOffset;
        }
    }

    internal void Render(CardAdvisorView? view)
    {
        if (view == null)
        {
            _panel.Visible = false;
            return;
        }
        if (!_panelOpen)
        {
            return;
        }
        _panel.Visible = true;
        _title.Text = view.Title;
        _note.Text = view.Note;
        foreach (Node child in _body.GetChildren()) { _body.RemoveChild(child); child.QueueFree(); }
        if (view.Status.Length > 0)
        {
            var statusLbl = new Label { Text = view.Status, AutowrapMode = TextServer.AutowrapMode.WordSmart };
            statusLbl.AddThemeFontSizeOverride("font_size", 15);
            _body.AddChild(statusLbl);
        }
        int itemCount = 0;
        if (view.InfoLines != null)
        {
            foreach (string line in view.InfoLines)
            {
                var infoLbl = new Label { Text = line, AutowrapMode = TextServer.AutowrapMode.WordSmart, MouseFilter = Control.MouseFilterEnum.Ignore };
                infoLbl.AddThemeFontSizeOverride("font_size", 16);
                _body.AddChild(infoLbl);
                itemCount++;
            }
        }
        foreach (CardAdvisorRow row in view.Rows)
        {
            var label = new Label
            {
                Text = $"{row.Name}\n?? {row.Score:F2}   ?? {row.Delta:+0.00;-0.00;0.00}   ? {row.ShortLoss:F1} / ? {row.LongLoss:F1}",
                MouseFilter = Control.MouseFilterEnum.Ignore
            };
            label.AddThemeFontSizeOverride("font_size", 17);
            _body.AddChild(label);
            itemCount += 2;
        }
        var scroll = (ScrollContainer)_body.GetParent();
        scroll.CustomMinimumSize = new Vector2(396, Math.Min(420, Math.Max(42, itemCount * 28)));
    }
}
