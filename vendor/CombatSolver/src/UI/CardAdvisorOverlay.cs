using Godot;

namespace CombatSolver;

internal sealed record CardAdvisorRow(string Name, double Score, double Delta, double ShortLoss, double LongLoss);
internal sealed record CardAdvisorView(string Title, string Note, string Status, CardAdvisorRow[] Rows);

// Renderer consumes scalar snapshots only; no model, run, card, or HTTP access.
internal sealed partial class CardAdvisorOverlay : CanvasLayer
{
    internal event Action? RefreshRequested;
    private PanelContainer _panel = null!;
    private VBoxContainer _body = null!;
    private Label _title = null!;
    private Label _note = null!;
    private bool _collapsed;

    public override void _Ready()
    {
        Layer = 100;
        _panel = new PanelContainer { Position = new Vector2(18, 145), CustomMinimumSize = new Vector2(410, 0) };
        var margin = new MarginContainer();
        foreach (string side in new[] { "left", "top", "right", "bottom" }) margin.AddThemeConstantOverride("margin_" + side, 12);
        var column = new VBoxContainer();
        var header = new HBoxContainer();
        _title = new Label { Text = "选牌评分", SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        var toggle = new Button { Text = "收起" };
        var refresh = new Button { Text = "重算" };
        refresh.Pressed += () => RefreshRequested?.Invoke();
        toggle.Pressed += () => { _collapsed = !_collapsed; _body.Visible = !_collapsed; _note.Visible = !_collapsed; toggle.Text = _collapsed ? "展开" : "收起"; };
        header.AddChild(_title); header.AddChild(refresh); header.AddChild(toggle); column.AddChild(header);
        var scroll = new ScrollContainer { CustomMinimumSize = new Vector2(390, 0) };
        scroll.SetMeta("advisor_scroll", true);
        _body = new VBoxContainer { SizeFlagsHorizontal = Control.SizeFlags.ExpandFill };
        scroll.AddChild(_body); column.AddChild(scroll);
        _note = new Label { AutowrapMode = TextServer.AutowrapMode.WordSmart, CustomMinimumSize = new Vector2(390, 0) };
        _note.AddThemeFontSizeOverride("font_size", 15);
        column.AddChild(_note); margin.AddChild(column); _panel.AddChild(margin); AddChild(_panel);
        _panel.Visible = false;
    }

    internal void Render(CardAdvisorView? view)
    {
        _panel.Visible = view != null;
        if (view == null) return;
        _title.Text = view.Title;
        _note.Text = view.Note;
        foreach (Node child in _body.GetChildren()) { _body.RemoveChild(child); child.QueueFree(); }
        if (view.Status.Length > 0) _body.AddChild(new Label { Text = view.Status, AutowrapMode = TextServer.AutowrapMode.WordSmart });
        foreach (CardAdvisorRow row in view.Rows)
        {
            var label = new Label { Text = $"{row.Name}\n综合 {row.Score:F2}   分差 {row.Delta:+0.00;-0.00;0.00}   短 {row.ShortLoss:F1} / 长 {row.LongLoss:F1}",
                MouseFilter = Control.MouseFilterEnum.Ignore };
            label.AddThemeFontSizeOverride("font_size", 17);
            _body.AddChild(label);
        }
        var scroll = (ScrollContainer)_body.GetParent();
        scroll.CustomMinimumSize = new Vector2(390, Math.Min(420, Math.Max(42, view.Rows.Length * 58)));
        _body.Visible = !_collapsed; _note.Visible = !_collapsed;
    }
}
