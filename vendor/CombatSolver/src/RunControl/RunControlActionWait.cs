namespace CombatSolver;

internal static class RunControlActionWait
{
    internal static async Task WaitAsync(string path, int timeoutSeconds, string screen, int sequence,
        CancellationToken parent)
    {
        using CancellationTokenSource waiting = CancellationTokenSource.CreateLinkedTokenSource(parent);
        waiting.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
        try
        {
            // Check cancellation even if a late action file already exists.
            while (true)
            {
                waiting.Token.ThrowIfCancellationRequested();
                if (File.Exists(path)) return;
                await Task.Delay(50, waiting.Token);
            }
        }
        catch (OperationCanceledException ex) when (!parent.IsCancellationRequested && waiting.IsCancellationRequested)
        {
            throw new TimeoutException($"Decision timeout: screen={screen}, decisionSeq={sequence}, "
                + $"actionTimeoutSeconds={timeoutSeconds}; no action received at {path}. "
                + "Inspect the Python policy log; computation may be slow or the policy process may have stopped.", ex);
        }
    }
}
