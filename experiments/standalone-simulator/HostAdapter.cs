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
        RemoveReattachTextureLoad(gameBytes);
        UseManagedRewardHotkeyNames(gameBytes);
        // Loaded PE files are memory mapped; never truncate a shared loaded inode.
        // Publish immutable content-addressed bytes so concurrent starts are safe.
        string digest = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(gameBytes)).ToLowerInvariant();
        string hostGame = Path.Combine(output, "sts2.host-experiment-" + digest + ".dll");
        if (!File.Exists(hostGame))
        {
            string temporary = hostGame + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    stream.Write(gameBytes);
                    stream.Flush(flushToDisk: true);
                }
                Verify(temporary, digest);
                try { File.Move(temporary, hostGame, overwrite: false); }
                catch (IOException) when (File.Exists(hostGame)) { /* Another process published first. */ }
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        Verify(hostGame, digest);

        return hostGame;
    }
    private static void RemoveReattachTextureLoad(byte[] bytes)
    {
        using var pe = new PEReader(new MemoryStream(bytes));
        var reader = pe.GetMetadataReader();
        var type = reader.TypeDefinitions.Select(reader.GetTypeDefinition).Single(t =>
            reader.GetString(t.Name).StartsWith("<ReattachMove>d__", StringComparison.Ordinal)
            && reader.GetString(reader.GetTypeDefinition(t.GetDeclaringType()).Name) == "DecimillipedeSegment");
        var method = type.GetMethods().Select(reader.GetMethodDefinition).Single(m => reader.GetString(m.Name) == "MoveNext");
        var body = pe.GetMethodBody(method.RelativeVirtualAddress);
        byte[] il = body.GetILBytes()!;
        var opcodes = typeof(System.Reflection.Emit.OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(f => f.FieldType == typeof(System.Reflection.Emit.OpCode))
            .Select(f => (System.Reflection.Emit.OpCode)f.GetValue(null)!).ToDictionary(o => unchecked((ushort)o.Value));
        int found = 0;
        var section = pe.PEHeaders.SectionHeaders.Single(s => method.RelativeVirtualAddress >= s.VirtualAddress && method.RelativeVirtualAddress < s.VirtualAddress + s.VirtualSize);
        int offset = section.PointerToRawData + method.RelativeVirtualAddress - section.VirtualAddress;
        int header = (bytes[offset] & 3) == 2 ? 1 : (bytes[offset + 1] >> 4) * 4;
        for (int i = 0; i < il.Length;)
        {
            int start = i;
            ushort key = il[i++];
            if (key == 0xfe) key = (ushort)(0xfe00 | il[i++]);
            var op = opcodes[key];
            if (op == System.Reflection.Emit.OpCodes.Call)
            {
                var handle = MetadataTokens.EntityHandle(BitConverter.ToInt32(il, i));
                if (handle.Kind == HandleKind.MethodSpecification)
                {
                    var target = reader.GetMethodSpecification((MethodSpecificationHandle)handle).Method;
                    if (target.Kind == HandleKind.MemberReference)
                    {
                        var member = reader.GetMemberReference((MemberReferenceHandle)target);
                        if (member.Parent.Kind == HandleKind.TypeReference)
                        {
                            var owner = reader.GetTypeReference((TypeReferenceHandle)member.Parent);
                            if (reader.GetString(owner.Namespace) == "Godot" && reader.GetString(owner.Name) == "ResourceLoader"
                                && reader.GetString(member.Name) == "Load")
                            {
                                // The reviewed generic Load<Texture2D>(path, typeHint, cacheMode) is visual only.
                                // Keep IL length/branches/EH identical: consume its three arguments and supply null.
                                new byte[] { 0x26, 0x26, 0x26, 0x14, 0x00 }.CopyTo(bytes, offset + header + start);
                                found++;
                            }
                        }
                    }
                }
            }
            i += op.OperandType switch {
                System.Reflection.Emit.OperandType.InlineNone => 0,
                System.Reflection.Emit.OperandType.ShortInlineBrTarget or System.Reflection.Emit.OperandType.ShortInlineI or System.Reflection.Emit.OperandType.ShortInlineVar => 1,
                System.Reflection.Emit.OperandType.InlineVar => 2,
                System.Reflection.Emit.OperandType.InlineI8 or System.Reflection.Emit.OperandType.InlineR => 8,
                System.Reflection.Emit.OperandType.InlineSwitch => 4 + 4 * BitConverter.ToInt32(il, i),
                _ => 4 };
        }
        if (found != 1) throw new NotSupportedException("Expected exactly one reviewed ReattachMove texture load.");
    }

    private static void UseManagedRewardHotkeyNames(byte[] bytes)
    {
        // Reward alternatives store strings, but their constructor unnecessarily
        // goes through MegaInput's Godot StringName fields. Reuse the original
        // literal tokens directly; preserve the same strings and all reward logic.
        using var pe = new PEReader(new MemoryStream(bytes));
        var reader = pe.GetMetadataReader();
        var opcodes = typeof(System.Reflection.Emit.OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(f => f.FieldType == typeof(System.Reflection.Emit.OpCode))
            .Select(f => (System.Reflection.Emit.OpCode)f.GetValue(null)!).ToDictionary(o => unchecked((ushort)o.Value));
        List<(int Start, int Operand, System.Reflection.Emit.OpCode Code)> Decode(byte[] il)
        {
            var result = new List<(int, int, System.Reflection.Emit.OpCode)>();
            for (int i = 0; i < il.Length;)
            {
                int start = i;
                ushort key = il[i++];
                if (key == 0xfe) key = (ushort)(0xfe00 | il[i++]);
                var op = opcodes[key];
                result.Add((start, i, op));
                i += op.OperandType switch {
                    System.Reflection.Emit.OperandType.InlineNone => 0,
                    System.Reflection.Emit.OperandType.ShortInlineBrTarget or System.Reflection.Emit.OperandType.ShortInlineI or System.Reflection.Emit.OperandType.ShortInlineVar => 1,
                    System.Reflection.Emit.OperandType.InlineVar => 2,
                    System.Reflection.Emit.OperandType.InlineI8 or System.Reflection.Emit.OperandType.InlineR => 8,
                    System.Reflection.Emit.OperandType.InlineSwitch => 4 + 4 * BitConverter.ToInt32(il, i),
                    _ => 4 };
            }
            return result;
        }
        var input = reader.TypeDefinitions.Select(reader.GetTypeDefinition).Single(t => reader.GetString(t.Name) == "MegaInput");
        var initializer = input.GetMethods().Select(reader.GetMethodDefinition).Single(m => reader.GetString(m.Name) == ".cctor");
        byte[] init = pe.GetMethodBody(initializer.RelativeVirtualAddress).GetILBytes()!;
        var names = new Dictionary<int, int>();
        int literal = 0;
        foreach (var instruction in Decode(init))
        {
            if (instruction.Code == System.Reflection.Emit.OpCodes.Ldstr) literal = BitConverter.ToInt32(init, instruction.Operand);
            if (instruction.Code == System.Reflection.Emit.OpCodes.Stsfld)
            {
                if (literal == 0) throw new NotSupportedException("Hotkey field has no original literal.");
                names.Add(BitConverter.ToInt32(init, instruction.Operand), literal);
                literal = 0;
            }
        }
        var alternative = reader.TypeDefinitions.Select(reader.GetTypeDefinition).Single(t => reader.GetString(t.Name) == "CardRewardAlternative");
        int replaced = 0;
        foreach (var method in alternative.GetMethods().Select(reader.GetMethodDefinition).Where(m => reader.GetString(m.Name) == ".ctor"))
        {
            var body = pe.GetMethodBody(method.RelativeVirtualAddress);
            if (body.ExceptionRegions.Length != 0) throw new NotSupportedException("Unexpected reward constructor handlers.");
            byte[] il = body.GetILBytes()!;
            var instructions = Decode(il);
            var section = pe.PEHeaders.SectionHeaders.Single(part => method.RelativeVirtualAddress >= part.VirtualAddress && method.RelativeVirtualAddress < part.VirtualAddress + part.VirtualSize);
            int offset = section.PointerToRawData + method.RelativeVirtualAddress - section.VirtualAddress;
            int header = (bytes[offset] & 3) == 2 ? 1 : (bytes[offset + 1] >> 4) * 4;
            for (int i = 0; i < instructions.Count; i++)
            {
                var instruction = instructions[i];
                if (instruction.Code != System.Reflection.Emit.OpCodes.Ldsfld || !names.TryGetValue(BitConverter.ToInt32(il, instruction.Operand), out int textToken)) continue;
                var conversion = instructions[i + 1];
                if (conversion.Code != System.Reflection.Emit.OpCodes.Call || conversion.Start != instruction.Start + 5)
                    throw new NotSupportedException("Expected direct hotkey StringName conversion.");
                var member = reader.GetMemberReference((MemberReferenceHandle)MetadataTokens.EntityHandle(BitConverter.ToInt32(il, conversion.Operand)));
                var owner = reader.GetTypeReference((TypeReferenceHandle)member.Parent);
                if (reader.GetString(owner.Namespace) != "Godot" || reader.GetString(owner.Name) != "StringName" || reader.GetString(member.Name) != "op_Implicit")
                    throw new NotSupportedException("Unexpected hotkey conversion target.");
                bytes[offset + header + instruction.Start] = 0x72; // ldstr, same five-byte size as ldsfld
                BitConverter.GetBytes(textToken).CopyTo(bytes, offset + header + instruction.Operand);
                Array.Clear(bytes, offset + header + conversion.Start, 5); // remove redundant conversion
                replaced++;
            }
        }
        if (replaced != 3) throw new NotSupportedException("Expected exactly three reward hotkey name conversions.");
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
    public static string? ProgressSnapshotSha256 { get; private set; }
    public static object LoadProgressSnapshot(Func<string, Type> get, string path)
    {
        byte[] bytes = File.ReadAllBytes(path);
        string text = System.Text.Encoding.UTF8.GetString(bytes);
        ProgressSnapshotSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
        using var document = System.Text.Json.JsonDocument.Parse(text);
        if (document.RootElement.GetProperty("schema_version").GetInt32() != 24)
            throw new NotSupportedException("Only verified progress schema 24 is supported.");
        Type schema = get("Saves.SerializableProgress");
        object read = get("Saves.JsonSerializationUtility").GetMethod("FromJson")!.MakeGenericMethod(schema).Invoke(null, [text])!;
        if (!(bool)read.GetType().GetProperty("Success")!.GetValue(read)!)
            throw new InvalidOperationException("Original progress parser rejected snapshot.");
        object data = read.GetType().GetProperty("SaveData")!.GetValue(read)!;
        object context = Activator.CreateInstance(get("Saves.Validation.DeserializationContext"))!;
        object progress = get("Saves.ProgressState").GetMethod("FromSerializable")!.Invoke(null, [data, context])!;
        if (((System.Collections.IEnumerable)context.GetType().GetProperty("Errors")!.GetValue(context)!).Cast<object>().Any())
            throw new InvalidOperationException("Progress snapshot has native validation errors.");
        object save = get("Saves.SaveManager").GetProperty("Instance")!.GetValue(null)!;
        object manager = save.GetType().GetField("_progressSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(save)!;
        manager.GetType().GetProperty("Progress")!.SetValue(manager, progress);
        return save.GetType().GetMethod("GenerateUnlockStateFromProgress")!.Invoke(save, null)!;
    }

    public static void ConfigureTestSave(Func<string, Type> get)
    {
        object progress = get("Saves.ProgressState").GetMethod("CreateDefault")!.Invoke(null, null)!;
        // The full save constructor runs keyboard-settings migrations requiring Godot StringName.
        // This fixture reads Progress and test preferences. Other save services stay unavailable.
        object save = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(get("Saves.SaveManager"));
        object manager = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(get("Saves.Managers.ProgressSaveManager"));
        manager.GetType().GetProperty("Progress")!.SetValue(manager, progress);
        save.GetType().GetField("_progressSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, manager);
        // Card effects read presentation preferences even in TestMode (e.g. Neutralize's animation delay).
        object prefsManager = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(get("Saves.Managers.PrefsSaveManager"));
        save.GetType().GetField("_prefsSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, prefsManager);
        save.GetType().GetMethod("InitPrefsDataForTest")!.Invoke(save, null);
        object store = Activator.CreateInstance(get("Saves.Test.MockGodotFileIo"), ["user://standalone-test"])!;
        save.GetType().GetField("_saveStore", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, store);
        save.GetType().GetField("_currentProfileId", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, 0);
        // Only progress is persisted, into the game's own in-memory store. Settings migrations
        // construct Godot input objects, and are not needed for a fresh offline test profile.
        Type migrationType = get("Saves.Migrations.MigrationManager");
        object migrations = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(migrationType);
        foreach (string field in new[] { "_latestVersions", "_minimumSupportedVersions", "_registry" })
        {
            FieldInfo info = migrationType.GetField(field, BindingFlags.NonPublic | BindingFlags.Instance)!;
            info.SetValue(migrations, Activator.CreateInstance(info.FieldType));
        }
        migrationType.GetField("_saveStore", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(migrations, store);
        Type migrationInterface = get("Saves.Migrations.IMigration");
        foreach (Type type in migrationType.Assembly.GetTypes().Where(t => !t.IsAbstract && migrationInterface.IsAssignableFrom(t)
            && t.Namespace == "MegaCrit.Sts2.Core.Saves.Migrations.ProgressSaves"))
            migrationType.GetMethod("RegisterMigration")!.Invoke(migrations, [Activator.CreateInstance(type)]);
        migrationType.GetMethod("DeriveAndSetLatestVersions", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(migrations, null);
        migrationType.GetMethod("ValidateMigrationPaths", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(migrations, null);
        foreach (string field in new[] { "_saveStore", "_migrationManager", "_profileIdProvider" })
            manager.GetType().GetField(field, BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(manager,
                field == "_saveStore" ? store : field == "_migrationManager" ? migrations : save);
        object runSaves = Activator.CreateInstance(get("Saves.Managers.RunSaveManager"), [store, migrations, save, true])!;
        save.GetType().GetField("_runSaveManager", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(save, runSaves);
        save.GetType().GetMethod("MockInstanceForTesting")!.Invoke(null, [save]);
    }
}
