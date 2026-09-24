using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

// MonoMod's Linux helper extractor hardcodes /tmp, ignoring TMPDIR. Load the
// identical embedded library from the host's writable temporary directory before
// installing any detours. The original factory and architecture remain in use.
internal static class NativeDetourHost
{
    public static void Initialize()
    {
        if (!OperatingSystem.IsLinux()) return;
        if (RuntimeInformation.ProcessArchitecture != Architecture.X64)
            throw new PlatformNotSupportedException("The validated Linux host requires x64.");
        Assembly harmony = Assembly.Load("0Harmony");
        Type platform = harmony.GetType("MonoMod.Core.Platforms.PlatformTriple", true)!;
        FieldInfo current = platform.GetField("lazyCurrent", BindingFlags.NonPublic | BindingFlags.Static)!;
        object gate = platform.GetField("lazyCurrentLock", BindingFlags.NonPublic | BindingFlags.Static)!.GetValue(null)!;
        lock (gate)
        {
        if (current.GetValue(null) != null)
            throw new InvalidOperationException("Native detour platform was initialized before host setup.");
        object system = platform.GetMethod("CreateCurrentSystem")!.Invoke(null, null)!;
        object architecture = platform.GetMethod("CreateCurrentArchitecture")!.Invoke(null, [system])!;
        if (system.GetType().FullName != "MonoMod.Core.Platforms.Systems.LinuxSystem")
            throw new InvalidOperationException("Unexpected native detour platform.");
        FieldInfo cache = system.GetType().GetField("lazyNativeExceptionHelper", BindingFlags.NonPublic | BindingFlags.Instance)!;
        if (cache.GetValue(system) != null)
            throw new InvalidOperationException("Native detour helper was initialized before host setup.");
        const string resource = "exhelper_linux_x86_64.so";
        using Stream source = harmony.GetManifestResourceStream(resource)
            ?? throw new InvalidOperationException("Original native detour resource is missing.");
        using var bytes = new MemoryStream();
        source.CopyTo(bytes);
        byte[] payload = bytes.ToArray();
        string hash = Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
        string directory = Path.Combine(Path.GetTempPath(), "sts2-native-detour");
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, hash + ".so");
        if (!File.Exists(path))
        {
            string temporary = path + "." + Guid.NewGuid().ToString("N");
            try
            {
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                { output.Write(payload); output.Flush(flushToDisk: true); }
                try { File.Move(temporary, path); }
                catch (IOException) when (File.Exists(path)) { /* Another host published the same resource. */ }
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        if (!File.ReadAllBytes(path).AsSpan().SequenceEqual(payload))
            throw new InvalidOperationException("Cached native detour helper differs from original resource.");
        object helper = harmony.GetType("MonoMod.Core.Platforms.Systems.PosixExceptionHelper", true)!
            .GetMethod("CreateHelper")!.Invoke(null, [architecture, path])!;
        cache.SetValue(system, helper);
        // Use the original factories and constructor; only seed the helper cache
        // before runtime initialization can invoke its hardcoded /tmp extractor.
        object runtime = platform.GetMethod("CreateCurrentRuntime")!.Invoke(null, [system, architecture])!;
        object triple = Activator.CreateInstance(platform, [architecture, system, runtime])!;
        current.SetValue(null, triple);
        Console.WriteLine(JsonSerializer.Serialize(new { status = "native_detour_helper_loaded", resource, path, sha256 = hash }));
        }
    }
}
