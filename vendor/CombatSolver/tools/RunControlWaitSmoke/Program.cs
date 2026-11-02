using CombatSolver;

using CancellationTokenSource fixture = new(TimeSpan.FromSeconds(10));
string path = Path.Combine(Path.GetTempPath(), "runctl-wait-" + Guid.NewGuid().ToString("N"));
try
{
    bool timedOut = false;
    try { await RunControlActionWait.WaitAsync(path, 1, "SHOP", 155, fixture.Token); }
    catch (TimeoutException ex) when (ex.Message.Contains("screen=SHOP")
        && ex.Message.Contains("decisionSeq=155") && ex.Message.Contains("actionTimeoutSeconds=1")
        && ex.Message.Contains(path)) { timedOut = true; }
    if (!timedOut) throw new Exception("Decision deadline was not reported with context.");
    Console.WriteLine("PASS decision deadline with context");

    using (CancellationTokenSource parent = CancellationTokenSource.CreateLinkedTokenSource(fixture.Token))
    {
        Task waiting = RunControlActionWait.WaitAsync(path, 30, "SHOP", 156, parent.Token);
        parent.Cancel();
        bool cancelled = false;
        try { await waiting; }
        catch (OperationCanceledException) { cancelled = true; }
        if (!cancelled) throw new Exception("Parent cancellation was misclassified.");
    }
    Console.WriteLine("PASS parent cancellation remains cancellation");

    Task pending = RunControlActionWait.WaitAsync(path, 2, "SHOP", 157, fixture.Token);
    await Task.Delay(100, fixture.Token);
    File.WriteAllText(path, "action");
    await pending;
    Console.WriteLine("PASS action arriving before deadline");

    using (CancellationTokenSource cancelled = new())
    {
        cancelled.Cancel();
        bool rejected = false;
        try { await RunControlActionWait.WaitAsync(path, 1, "SHOP", 158, cancelled.Token); }
        catch (OperationCanceledException) { rejected = true; }
        if (!rejected) throw new Exception("Cancelled wait accepted a late action.");
    }
    Console.WriteLine("PASS late action cannot override parent cancellation");
}
finally { if (File.Exists(path)) File.Delete(path); }
