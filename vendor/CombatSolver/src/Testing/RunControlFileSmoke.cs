using System.Text.Json;
using System.Text.Json.Serialization;
using MegaCrit.Sts2.Core.Nodes;

namespace CombatSolver;

// Explicit opt-in Windows file-sharing fixture. It never starts or edits a run.
internal static class RunControlFileSmoke
{
    private sealed class Payload(int value)
    {
        [JsonIgnore] public int Reads { get; private set; }
        public int Value { get { Reads++; return value; } }
    }

    private static int ReadValue(string path)
    {
        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        return document.RootElement.GetProperty("value").GetInt32();
    }

    internal static async Task RunAsync(NGame host, string resultPath)
    {
        string status = "failed", error = "";
        List<object> evidence = [];
        using CancellationTokenSource deadline = new(TimeSpan.FromSeconds(30));
        try
        {
            if (!OperatingSystem.IsWindows()) throw new InvalidOperationException("Requires Windows file-sharing semantics.");
            string directory = Path.ChangeExtension(resultPath, ".files");
            Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, "transient.json");
            await RunControlFiles.AtomicWriteAsync(path, new { value = 1 }, deadline.Token);
            var payload = new Payload(2);
            using (FileStream blocker = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                string probe = path + ".probe";
                File.WriteAllText(probe, "{}");
                Exception? originalFailure = null;
                try { File.Move(probe, path, true); }
                catch (Exception ex) when (RunControlFiles.IsWindowsReplaceConflict(ex)) { originalFailure = ex; }
                if (originalFailure == null) throw new InvalidOperationException("Old single-attempt replacement did not reproduce the conflict.");
                File.Delete(probe);
                Task pending = RunControlFiles.AtomicWriteAsync(path, payload, deadline.Token);
                await Task.Delay(150, deadline.Token);
                if (pending.IsCompleted || ReadValue(path) != 1 || payload.Reads != 1)
                    throw new InvalidOperationException("Writer did not await the lock with the old JSON intact and a single serialization.");
                blocker.Dispose();
                await pending;
                if (ReadValue(path) != 2 || payload.Reads != 1)
                    throw new InvalidOperationException("Released lock did not publish exactly the prepared snapshot.");
                evidence.Add(new { test = "transient", baseline = originalFailure.GetType().Name,
                    winerror = originalFailure.HResult & 0xffff, serializations = payload.Reads, passed = true });
            }

            path = Path.Combine(directory, "shared-delete.json");
            await RunControlFiles.AtomicWriteAsync(path, new { value = 1 }, deadline.Token);
            using (FileStream reader = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                await RunControlFiles.AtomicWriteAsync(path, new { value = 2 }, deadline.Token);
                using JsonDocument old = JsonDocument.Parse(reader);
                if (ReadValue(path) != 2 || old.RootElement.GetProperty("value").GetInt32() != 1)
                    throw new InvalidOperationException("Atomic replacement broke a compatible reader's snapshot.");
                evidence.Add(new { test = "shared-delete", passed = true });
            }

            path = Path.Combine(directory, "persistent.json");
            await RunControlFiles.AtomicWriteAsync(path, new { value = 1 }, deadline.Token);
            using (FileStream blocker = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                payload = new Payload(2);
                IOException? failure = null;
                try { await RunControlFiles.AtomicWriteAsync(path, payload, deadline.Token); }
                catch (IOException ex) when (ex.InnerException != null && RunControlFiles.IsWindowsReplaceConflict(ex.InnerException))
                { failure = ex; }
                string temporary = Directory.GetFiles(directory, "persistent.json.*.tmp").Single();
                if (failure == null || !failure.Message.Contains(path) || !failure.Message.Contains(temporary)
                    || !failure.Message.Contains("21 replacement attempts") || ReadValue(path) != 1
                    || ReadValue(temporary) != 2 || payload.Reads != 1)
                    throw new InvalidOperationException("Persistent denial was hidden or lost the diagnostic snapshot.");
                evidence.Add(new { test = "persistent", serializations = payload.Reads, error = failure.Message, passed = true });
            }

            path = Path.Combine(directory, "cancelled.json");
            await RunControlFiles.AtomicWriteAsync(path, new { value = 1 }, deadline.Token);
            using (FileStream blocker = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            using (CancellationTokenSource cancel = new())
            {
                Task pending = RunControlFiles.AtomicWriteAsync(path, new { value = 2 }, cancel.Token);
                cancel.Cancel();
                bool cancelled = false;
                try { await pending; }
                catch (OperationCanceledException ex) when (ex.CancellationToken == cancel.Token) { cancelled = true; }
                if (!cancelled || ReadValue(path) != 1) throw new InvalidOperationException("Cancellation was ignored.");
                evidence.Add(new { test = "cancellation", passed = true });
            }
            if (RunControlFiles.IsWindowsReplaceConflict(new IOException("disk full", unchecked((int)0x80070070)))
                || RunControlFiles.IsWindowsReplaceConflict(new IOException("missing", unchecked((int)0x80070002))))
                throw new InvalidOperationException("Unrelated I/O errors must not be retried.");
            evidence.Add(new { test = "unrelated-errors", passed = true });
            status = "passed";
        }
        catch (Exception ex)
        {
            // Terminal fixture boundary: report failure and exit, never continue a run.
            error = ex.ToString();
            Entry.Logger.Error("[RunControl/FileSmoke] " + error);
        }
        finally
        {
            File.WriteAllText(resultPath, JsonSerializer.Serialize(new { status, error, evidence }));
            host.GetTree().Quit(status == "passed" ? 0 : 1);
        }
    }
}
