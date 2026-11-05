using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Runs;

namespace CombatSolver;

// Manual on-demand prediction controller: never calls Python in a loop; only evaluates on user click.
internal sealed partial class CardAdvisorController : Node
{
    private readonly System.Net.Http.HttpClient _client = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(120) };
    private CardAdvisorOverlay _overlay = null!;
    private CancellationTokenSource? _cancel;
    private Task<CardAdvisorView>? _pending;
    private long _generation;
    private long _pendingGeneration;
    private string _endpoint = "http://127.0.0.1:18765/score";
    private bool _autoStartAttempted;
    private double _tipClock;

    public override void _Ready()
    {
        _endpoint = System.Environment.GetEnvironmentVariable("STS2_CARD_ADVISOR_URL") ?? _endpoint;
        if (!Uri.TryCreate(_endpoint, UriKind.Absolute, out Uri? uri) || uri.Scheme != "http" || !uri.IsLoopback)
            throw new InvalidOperationException("STS2_CARD_ADVISOR_URL must be a loopback HTTP address.");
        _overlay = new CardAdvisorOverlay();
        AddChild(_overlay);
        _overlay.CalculateRequested += OnUserManualCalculate;
    }

    private void OnUserManualCalculate()
    {
        Cancel();
        CardAdvisorSnapshot? snap;
        try
        {
            snap = CardAdvisorCapture.Capture(GetParent().GetParent());
        }
        catch (NotSupportedException ex)
        {
            _overlay.Render(new CardAdvisorView("????", "???????????", ex.Message, []));
            return;
        }
        if (snap == null)
        {
            _overlay.Render(new CardAdvisorView("????", "???????????????", "????????????", []));
            return;
        }

        _overlay.SetCalculating(snap.Title);
        _cancel = new CancellationTokenSource();
        _pendingGeneration = _generation;
        _pending = RequestAsync(snap, _generation.ToString(), _cancel.Token);
    }

    public override void _Process(double delta)
    {
        // Update small button tip every 1.0s without sending HTTP requests
        _tipClock += delta;
        if (_tipClock >= 1.0)
        {
            _tipClock = 0;
            if (!_overlay.IsPanelOpen)
            {
                if (CombatManager.Instance.IsInProgress)
                {
                    var p = LocalContext.GetMe(CombatManager.Instance.DebugOnlyGetState());
                    int turn = p?.PlayerCombatState?.TurnNumber ?? 1;
                    _overlay.SetContextTip($"?? T{turn}");
                }
                else
                {
                    _overlay.SetContextTip("");
                }
            }
        }

        if (_pending is { IsCompleted: true })
        {
            Task<CardAdvisorView> completed = _pending;
            _pending = null;
            if (_pendingGeneration == _generation)
            {
                CardAdvisorView result = completed.GetAwaiter().GetResult();
                _overlay.Render(result);
            }
            else if (completed.IsFaulted)
            {
                Entry.Logger.Error($"[CardAdvisor] stale_request_failed {completed.Exception}");
            }
        }
    }

    private void Cancel()
    {
        _generation++;
        _cancel?.Cancel();
        _cancel?.Dispose();
        _cancel = null;
    }

    private bool TryAutoStartService()
    {
        if (_autoStartAttempted) return false;
        _autoStartAttempted = true;
        try
        {
            string userProfile = System.Environment.GetFolderPath(System.Environment.SpecialFolder.UserProfile);
            string[] candidateDirs =
            [
                System.Environment.GetEnvironmentVariable("STS2_ADVISOR_SERVICE_DIR") ?? "",
                Path.Combine(userProfile, "Downloads", "advisor-service"),
                Path.Combine(userProfile, ".gemini", "antigravity", "scratch", "Sts2Bot-step-v3"),
            ];
            foreach (string dir in candidateDirs)
            {
                if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir)) continue;
                string py = Path.Combine(dir, ".venv", "Scripts", "python.exe");
                if (!File.Exists(py))
                    py = Path.Combine(userProfile, "Downloads", "advisor-service", ".venv", "Scripts", "python.exe");
                if (!File.Exists(py)) continue;
                var psi = new ProcessStartInfo
                {
                    FileName = py,
                    Arguments = "-m train.advisor_service --port 18765",
                    WorkingDirectory = dir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                Process.Start(psi);
                Entry.Logger.Info($"[CardAdvisor] Auto-started advisor_service from {dir}");
                return true;
            }
        }
        catch (Exception ex)
        {
            Entry.Logger.Error($"[CardAdvisor] Failed to auto-start advisor_service: {ex.Message}");
        }
        return false;
    }

    internal async Task<CardAdvisorView> RequestAsync(CardAdvisorSnapshot snapshot, string id, CancellationToken token)
    {
        try
        {
            JsonObject body = JsonNode.Parse(snapshot.Json)!.AsObject();
            body["request_id"] = id;
            using var content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
            using HttpResponseMessage response = await _client.PostAsync(_endpoint, content, token).ConfigureAwait(false);
            using JsonDocument json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token).ConfigureAwait(false));
            JsonElement root = json.RootElement;
            if (!response.IsSuccessStatusCode)
                return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????" + root.GetProperty("error").GetString(), []);
            if (root.GetProperty("protocol").GetInt32() != 1 || root.GetProperty("request_id").GetString() != id)
                throw new InvalidDataException("?????????????");

            string[]? infoLines = null;
            if (root.TryGetProperty("info_lines", out JsonElement infoElem) && infoElem.ValueKind == JsonValueKind.Array)
                infoLines = infoElem.EnumerateArray().Select(x => x.GetString() ?? "").ToArray();

            var candidates = root.GetProperty("candidates").EnumerateArray().ToArray();
            List<CardAdvisorRow> rows = [];
            for (int i = 0; i < candidates.Length; i++)
            {
                JsonElement c = candidates[i];
                double[] v = new[] { "combined_score", "delta", "short_expected_hp_loss", "long_expected_hp_loss" }.Select(k => c.GetProperty(k).GetDouble()).ToArray();
                if (v.Any(x => !double.IsFinite(x))) throw new InvalidDataException("??????????");
                string name = i < snapshot.Names.Length ? snapshot.Names[i] : $"?? {i+1}";
                rows.Add(new CardAdvisorRow(name, v[0], v[1], v[2], v[3]));
            }
            string excluded = string.Join(", ", root.GetProperty("normalized_relics").EnumerateArray().Select(x => x.GetString()));
            string note = snapshot.Note + (excluded.Length > 0 ? " ????????" + excluded : "");
            if (root.TryGetProperty("scenario_note", out JsonElement scenario))
                note += " " + scenario.GetString();
            note += " " + string.Join("?", root.GetProperty("warnings").EnumerateArray().Select(x => x.GetString()));
            return new CardAdvisorView(snapshot.Title, note, "", rows.ToArray(), infoLines);
        }
        catch (OperationCanceledException) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????????", []); }
        catch (HttpRequestException ex)
        {
            if (TryAutoStartService())
            {
                await Task.Delay(1500, token).ConfigureAwait(false);
                return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????????? step_v3 ??????????????????", []);
            }
            return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????? advisor_service ??? (" + ex.Message + ")", []);
        }
        catch (JsonException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????????" + ex.Message, []); }
        catch (InvalidDataException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, ex.Message, []); }
        catch (KeyNotFoundException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "?????????" + ex.Message, []); }
        catch (InvalidOperationException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "???????????" + ex.Message, []); }
    }

    public override void _ExitTree()
    {
        Cancel();
        _client.Dispose();
    }
}
