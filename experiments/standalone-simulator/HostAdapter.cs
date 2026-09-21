using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;

// Prototype-only environment shims. Never use these objects for real save/network operations.
// Three host adaptations; game rules and the solver assembly remain unchanged.
internal static class HostAdapter
{
    public const string GameHash = "0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9";
    public const string SolverHash = "1950d98b8aa742f651a2c09d59e6044da8c0836a29f4c1258047a8d1048f9bfb";
    public static void Verify(string path, string expected)
    {
        using var stream = File.OpenRead(path);
        if (!Convert.ToHexStringLower(SHA256.HashData(stream)).Equals(expected, StringComparison.Ordinal))
            throw new NotSupportedException("Unreviewed runtime assembly: " + path);
    }
    public static string CreateGameCopy(string source, string output)
    {
        Verify(source, GameHash);
        // Experimental host copy only: the process is neither a Godot editor nor a rendered game.
        // The second adaptation disables native console output; LogCallback remains wired to stderr.
        string hostGame = Path.Combine(output, "sts2.host-experiment.dll");
        byte[] gameBytes = File.ReadAllBytes(source);
        using (var pe = new PEReader(new MemoryStream(gameBytes)))
        {
            var reader = pe.GetMetadataReader();
            foreach (var patch in new[] {
                (Namespace: "MegaCrit.Sts2.Core.Logging", Type: "Logger", Method: "GetIsRunningFromGodotEditor", IL: new byte[] { 0x16, 0x2a }),
                (Namespace: "MegaCrit.Sts2.Core.Logging", Type: "ConsoleLogPrinter", Method: "Print", IL: new byte[] { 0x2a }),
                (Namespace: "MegaCrit.Sts2.Core.Platform.Null", Type: "NullPlatformUtilStrategy", Method: ".ctor", IL: OfflinePlatformConstructor(reader))
            })
            {
                var type = reader.TypeDefinitions.Select(reader.GetTypeDefinition).Single(t => reader.GetString(t.Namespace) == patch.Namespace && reader.GetString(t.Name) == patch.Type);
                var method = type.GetMethods().Select(reader.GetMethodDefinition).Single(m => reader.GetString(m.Name) == patch.Method);
                var body = pe.GetMethodBody(method.RelativeVirtualAddress);
                if (body.GetILBytes()!.Length < patch.IL.Length) throw new NotSupportedException("Replacement exceeds original method body.");
                if (body.ExceptionRegions.Length != 0) throw new NotSupportedException("Unexpected editor detector exception handlers.");
                var section = pe.PEHeaders.SectionHeaders.Single(s => method.RelativeVirtualAddress >= s.VirtualAddress && method.RelativeVirtualAddress < s.VirtualAddress + s.VirtualSize);
                int offset = section.PointerToRawData + method.RelativeVirtualAddress - section.VirtualAddress;
                int header = (gameBytes[offset] & 3) == 2 ? 1 : (gameBytes[offset + 1] >> 4) * 4;
                if (header == 1) gameBytes[offset] = (byte)((patch.IL.Length << 2) | 2);
                else BitConverter.GetBytes(patch.IL.Length).CopyTo(gameBytes, offset + 4);
                patch.IL.CopyTo(gameBytes, offset + header);
            }
        }
        File.WriteAllBytes(hostGame, gameBytes);

        return hostGame;
    }
    private static byte[] OfflinePlatformConstructor(MetadataReader reader)
    {
        // Preserve the vanilla offline net ID (1), omit optional mp_names.json / Godot file I/O.
        // Other methods and the vanilla fallback names remain unchanged.
        var type = reader.TypeDefinitions.Select(reader.GetTypeDefinition).Single(t =>
            reader.GetString(t.Namespace) == "MegaCrit.Sts2.Core.Platform.Null" && reader.GetString(t.Name) == "NullPlatformUtilStrategy");
        var field = type.GetFields().Single(f => reader.GetString(reader.GetFieldDefinition(f).Name) == "<LocalPlayerId>k__BackingField");
        var baseCtor = reader.MemberReferences.Single(h =>
        {
            var member = reader.GetMemberReference(h);
            if (reader.GetString(member.Name) != ".ctor" || member.Parent.Kind != HandleKind.TypeReference) return false;
            var owner = reader.GetTypeReference((TypeReferenceHandle)member.Parent);
            return reader.GetString(owner.Namespace) == "System" && reader.GetString(owner.Name) == "Object";
        });
        return [0x02, 0x28, ..BitConverter.GetBytes(MetadataTokens.GetToken(baseCtor)),
            0x02, 0x17, 0x6e, 0x7d, ..BitConverter.GetBytes(MetadataTokens.GetToken(field)), 0x2a];
    }
    public static void ConfigureTestSave(Func<string, Type> get)
    {
        object progress = get("Saves.ProgressState").GetMethod("CreateDefault")!.Invoke(null, null)!;
        // The full save constructor runs keyboard-settings migrations requiring Godot StringName.
        // This fixture only reads Progress. Other save services intentionally stay unavailable.
        object save = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(get("Saves.SaveManager"));
        object manager = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(get("Saves.Managers.ProgressSaveManager"));
        manager.GetType().GetProperty("Progress")!.SetValue(manager, progress);
        save.GetType().GetField("_progressSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, manager);
        save.GetType().GetMethod("MockInstanceForTesting")!.Invoke(null, [save]);
    }
}
