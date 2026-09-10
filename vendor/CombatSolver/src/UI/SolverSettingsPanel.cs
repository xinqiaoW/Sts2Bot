using Godot;
using MegaCrit.Sts2.Core.Localization.Fonts;

namespace CombatSolver;

internal sealed partial class SolverSettingsPanel : PanelContainer
{
    private readonly Label _status;
    private readonly Button _generalTab;
    private readonly Button _performanceTab;
    private readonly Button _bugReportsTab;
    private readonly Control _generalPage;
    private readonly Control _performancePage;
    private readonly Control _bugReportsPage;
    private readonly List<Action<SolverSettingsData>> _reloadInputs = [];
    private readonly List<Func<bool>> _commitInputs = [];
    private SettingsPage _activePage = SettingsPage.General;
    private bool _loading;

    public event Action? ResetPositionRequested;

    public SolverSettingsPanel()
    {
        Name = "SolverSettingsPanel";
        MouseFilter = MouseFilterEnum.Pass;
        SizeFlagsHorizontal = SizeFlags.ExpandFill;
        AddThemeStyleboxOverride("panel", SolverUiTokens.CreateBox(
            SolverUiTokens.Palette.Surface,
            SolverUiTokens.Palette.BorderSubtle,
            SolverUiTokens.Radius.Medium,
            SolverUiTokens.Spacing.Md,
            SolverUiTokens.Spacing.Md));

        VBoxContainer root = new()
        {
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        root.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Sm);

        HBoxContainer heading = new()
        {
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        Label title = SolverUiTokens.CreateLabel(
            "求解器设置",
            SolverUiTokens.Type.Title,
            SolverUiTokens.Palette.TextPrimary,
            FontType.Bold);
        title.SizeFlagsHorizontal = SizeFlags.ExpandFill;
        heading.AddChild(title);
        Button reset = SolverUiTokens.CreateButton("恢复默认", SolverButtonStyle.Secondary);
        reset.CustomMinimumSize = new Vector2(96, SolverUiTokens.Size.ButtonHeight);
        reset.Pressed += ResetDefaults;
        heading.AddChild(reset);
        root.AddChild(heading);

        HBoxContainer tabs = new()
        {
            Name = "SettingsTabs",
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        tabs.AddThemeConstantOverride("separation", SolverUiTokens.Spacing.Xs);
        _generalTab = CreateTabButton("常规", SettingsPage.General);
        _performanceTab = CreateTabButton("性能", SettingsPage.Performance);
        _bugReportsTab = CreateTabButton("反馈", SettingsPage.BugReports);
        tabs.AddChild(_generalTab);
        tabs.AddChild(_performanceTab);
        tabs.AddChild(_bugReportsTab);
        root.AddChild(tabs);

        _status = SolverUiTokens.CreateLabel(
            string.Empty,
            SolverUiTokens.Type.Caption,
            SolverUiTokens.Palette.Success,
            FontType.Bold);
        _status.CustomMinimumSize = new Vector2(0, 20);

        VBoxContainer pageHost = new()
        {
            Name = "SettingsPageHost",
            MouseFilter = MouseFilterEnum.Pass,
            SizeFlagsHorizontal = SizeFlags.ExpandFill,
        };
        _generalPage = CreateGeneralPage();
        _performancePage = CreatePerformancePage();
        _bugReportsPage = CreateBugReportsPage();
        pageHost.AddChild(_generalPage);
        pageHost.AddChild(_performancePage);
        pageHost.AddChild(_bugReportsPage);
        root.AddChild(pageHost);
        root.AddChild(_status);
        AddChild(root);

        SetProcess(false);
        UpdatePageVisibility();
        Reload();
    }

    public void Reload()
    {
        _loading = true;
        SolverSettingsData data = SolverSettings.Current;
        ReloadGeneralPage(data);
        ReloadBugReportsPage(data);
        foreach (Action<SolverSettingsData> reload in _reloadInputs)
            reload(data);
        ReloadPerformancePage(data);
        _status.Text = string.Empty;
        _loading = false;
    }

    public bool CommitPending()
    {
        foreach (Func<bool> commit in _commitInputs)
        {
            if (!commit())
                return false;
        }
        return true;
    }

    public bool OpenPerformancePage() => TrySelectPage(SettingsPage.Performance);

    internal bool SettingsTabsConfiguredForTesting
        => _generalTab.Text == "常规"
           && _performanceTab.Text == "性能"
           && _bugReportsTab.Text == "反馈"
           && _generalPage.Visible
           && !_performancePage.Visible
           && !_bugReportsPage.Visible;

    internal bool ExerciseSettingsTabSwitchingForTesting()
    {
        SettingsPage original = _activePage;
        bool switched = TrySelectPage(SettingsPage.Performance)
                        && _performancePage.Visible
                        && TrySelectPage(SettingsPage.BugReports)
                        && _bugReportsPage.Visible
                        && TrySelectPage(SettingsPage.General)
                        && _generalPage.Visible;
        if (_activePage != original)
            TrySelectPage(original);
        return switched;
    }

    private Button CreateTabButton(string text, SettingsPage page)
    {
        Button button = SolverUiTokens.CreateButton(text, SolverButtonStyle.Secondary);
        button.Name = $"{page}Tab";
        button.SizeFlagsHorizontal = SizeFlags.ExpandFill;
        button.Pressed += () => TrySelectPage(page);
        return button;
    }

    private bool TrySelectPage(SettingsPage page)
    {
        if (page == _activePage)
            return true;
        if (!_loading && !CommitPending())
            return false;
        _activePage = page;
        UpdatePageVisibility();
        return true;
    }

    private void UpdatePageVisibility()
    {
        _generalPage.Visible = _activePage == SettingsPage.General;
        _performancePage.Visible = _activePage == SettingsPage.Performance;
        _bugReportsPage.Visible = _activePage == SettingsPage.BugReports;
        SolverUiTokens.ApplyButtonStyle(
            _generalTab,
            _activePage == SettingsPage.General ? SolverButtonStyle.Primary : SolverButtonStyle.Secondary);
        SolverUiTokens.ApplyButtonStyle(
            _performanceTab,
            _activePage == SettingsPage.Performance ? SolverButtonStyle.Primary : SolverButtonStyle.Secondary);
        SolverUiTokens.ApplyButtonStyle(
            _bugReportsTab,
            _activePage == SettingsPage.BugReports ? SolverButtonStyle.Primary : SolverButtonStyle.Secondary);
    }

    private void SetStatus(string text, Color color)
    {
        _status.AddThemeColorOverride("font_color", color);
        _status.Text = text;
    }

    private void ResetDefaults()
    {
        bool wasDisabled = SolverController.SolverDisabled;
        SolverOverlayTheme activeTheme = SolverOverlay.ActiveThemeForTesting;
        SolverSettings.ResetToDefaults();
        SolverSettingsSnapshot defaults = SolverSettings.Capture();
        SolverController.ApplyPersistentSettings(defaults);
        if (wasDisabled != defaults.SolverDisabled)
            SolverController.SetSolverDisabled(defaults.SolverDisabled, persist: false);
        SolverOverlay.RefreshControls();
        ResetPositionRequested?.Invoke();
        Reload();
        SolverOverlay.ApplyOverlayOpacity();
        SetStatus("已恢复默认设置", SolverUiTokens.Palette.Success);
        if (activeTheme != SolverSettings.Current.OverlayTheme)
            SolverOverlay.ApplyConfiguredTheme();
    }

    private enum SettingsPage
    {
        General,
        Performance,
        BugReports,
    }
}
