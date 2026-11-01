using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Godot;

namespace CombatSolver;

// Owns async request lifetime. Completion is consumed in this node's _Process,
// never in the combat dispatcher and never by the HTTP worker touching Godot.
internal sealed partial class CardAdvisorController : Node
{
    private readonly System.Net.Http.HttpClient _client = new(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(120) };
    private CardAdvisorOverlay _overlay = null!;
    private CancellationTokenSource? _cancel;
    private Task<CardAdvisorView>? _pending;
    private CardAdvisorSnapshot? _snapshot;
    private string? _key;
    private double _clock;
    private long _generation;
    private long _pendingGeneration;
    private string _endpoint = "http://127.0.0.1:18765/score";

    public override void _Ready()
    {
        _endpoint = System.Environment.GetEnvironmentVariable("STS2_CARD_ADVISOR_URL") ?? _endpoint;
        if (!Uri.TryCreate(_endpoint, UriKind.Absolute, out Uri? uri) || uri.Scheme != "http" || !uri.IsLoopback)
            throw new InvalidOperationException("STS2_CARD_ADVISOR_URL must be a loopback HTTP address.");
        _overlay = new CardAdvisorOverlay(); AddChild(_overlay);
        _overlay.RefreshRequested += () => { Cancel(); _key = null; };
    }

    public override void _Process(double delta)
    {
        _clock += delta;
        if (_clock < 0.5) return;
        _clock = 0;
        CardAdvisorSnapshot? next;
        try { next = CardAdvisorCapture.Capture(GetParent().GetParent()); }
        catch (NotSupportedException ex)
        {
            Cancel(); _key = null;
            _overlay.Render(new CardAdvisorView("选牌评分", "未更改原生选牌操作。", ex.Message, [])); return;
        }
        string? key = next?.Json;
        if (key != _key)
        {
            Cancel(); _key = key; _snapshot = next;
            _overlay.Render(next == null ? null : new CardAdvisorView(next.Title, next.Note, "评分中…", []));
        }
        if (_pending is { IsCompleted: true })
        {
            Task<CardAdvisorView> completed = _pending; _pending = null;
            if (_pendingGeneration == _generation)
                _overlay.Render(completed.GetAwaiter().GetResult());
            else if (completed.IsFaulted)
                Entry.Logger.Error($"[CardAdvisor] stale_request_failed {completed.Exception}");
        }
        if (_snapshot != null && _key != null && _pending == null && _cancel == null)
        {
            _cancel = new CancellationTokenSource(); _pendingGeneration = _generation;
            _pending = RequestAsync(_snapshot, _generation.ToString(), _cancel.Token);
        }
    }

    private void Cancel()
    {
        _generation++; _cancel?.Cancel(); _cancel?.Dispose(); _cancel = null; _snapshot = null;
    }

    internal async Task<CardAdvisorView> RequestAsync(CardAdvisorSnapshot snapshot, string id, CancellationToken token)
    {
        try
        {
            JsonObject body = JsonNode.Parse(snapshot.Json)!.AsObject(); body["request_id"] = id;
            using var content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
            using HttpResponseMessage response = await _client.PostAsync(_endpoint, content, token).ConfigureAwait(false);
            using JsonDocument json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token).ConfigureAwait(false));
            JsonElement root = json.RootElement;
            if (!response.IsSuccessStatusCode)
                return new CardAdvisorView(snapshot.Title, snapshot.Note, "无法评分：" + root.GetProperty("error").GetString(), []);
            if (root.GetProperty("protocol").GetInt32() != 1 || root.GetProperty("request_id").GetString() != id)
                throw new InvalidDataException("评分响应序号或协议不匹配。");
            var candidates = root.GetProperty("candidates").EnumerateArray().ToArray();
            if (candidates.Length != snapshot.Names.Length) throw new InvalidDataException("评分候选数量不匹配。");
            List<CardAdvisorRow> rows = [];
            for (int i = 0; i < candidates.Length; i++)
            {
                JsonElement c = candidates[i];
                if (c.GetProperty("option_index").GetInt32() != i) throw new InvalidDataException("评分候选顺序不匹配。");
                double[] v = new[] { "combined_score", "delta", "short_expected_hp_loss", "long_expected_hp_loss" }.Select(k => c.GetProperty(k).GetDouble()).ToArray();
                if (v.Any(x => !double.IsFinite(x))) throw new InvalidDataException("评分包含非有限数值。");
                rows.Add(new CardAdvisorRow(snapshot.Names[i], v[0], v[1], v[2], v[3]));
            }
            string excluded = string.Join(", ", root.GetProperty("normalized_relics").EnumerateArray().Select(x => x.GetString()));
            string note = snapshot.Note + (excluded.Length > 0 ? " 模型未计入遗物：" + excluded : "");
            note += " " + string.Join("；", root.GetProperty("warnings").EnumerateArray().Select(x => x.GetString()));
            return new CardAdvisorView(snapshot.Title, note, "", rows.ToArray());
        }
        catch (OperationCanceledException) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "评分已取消或超时。", []); }
        catch (HttpRequestException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "评分服务未连接，请启动本地 advisor_service。" + ex.Message, []); }
        catch (JsonException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "评分响应格式错误：" + ex.Message, []); }
        catch (InvalidDataException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, ex.Message, []); }
        catch (KeyNotFoundException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "评分响应缺少字段：" + ex.Message, []); }
        catch (InvalidOperationException ex) { return new CardAdvisorView(snapshot.Title, snapshot.Note, "评分响应字段类型错误：" + ex.Message, []); }
    }

    public override void _ExitTree()
    {
        Cancel(); _client.Dispose();
    }
}
