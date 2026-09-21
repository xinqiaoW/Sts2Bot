using System.Collections;
using System.Globalization;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

internal static class PackedLocalization
{
    // Read only standalone, unencrypted Godot 4.5 PCK v3. Layout reference:
    // https://github.com/godotengine/godot/blob/4.5/core/io/file_access_pack.cpp
    public static void Configure(Func<string, Type> get, string pack)
    {
        using var stream = File.OpenRead(pack);
        using var reader = new BinaryReader(stream);
        if (reader.ReadUInt32() != 0x43504447 || reader.ReadUInt32() != 3)
            throw new NotSupportedException("Requires standalone PCK v3.");
        if (reader.ReadUInt32() != 4 || reader.ReadUInt32() != 5 || reader.ReadUInt32() != 1 || reader.ReadUInt32() != 2)
            throw new NotSupportedException("Requires reviewed Godot 4.5.1 unencrypted pack flags.");
        long dataBase = checked((long)reader.ReadUInt64());
        long directory = checked((long)reader.ReadUInt64());
        stream.Position = directory;
        int count = reader.ReadInt32();
        if (count is < 1 or > 100000) throw new InvalidDataException("Invalid PCK entry count.");
        var entries = new List<(string Name, long Offset, int Size, byte[] Md5)>();
        for (int i = 0; i < count; i++)
        {
            int length = reader.ReadInt32();
            if (length is < 1 or > 4096) throw new InvalidDataException("Invalid PCK path length.");
            string path = Encoding.UTF8.GetString(reader.ReadBytes(length)).TrimEnd('\0');
            long offset = checked(dataBase + (long)reader.ReadUInt64());
            ulong size = reader.ReadUInt64();
            byte[] md5 = reader.ReadBytes(16);
            uint flags = reader.ReadUInt32();
            const string prefix = "localization/eng/";
            if (!path.StartsWith(prefix, StringComparison.Ordinal) || !path.EndsWith(".json", StringComparison.Ordinal)) continue;
            string name = path[prefix.Length..^5];
            if (name.Contains('/')) continue;
            if (flags != 0 || size > 4000000 || offset < 0 || offset > stream.Length - (long)size)
                throw new InvalidDataException("Unsupported localization PCK entry: " + path);
            entries.Add((name, offset, (int)size, md5));
        }
        Type locType = get("Localization.LocManager"), tableType = get("Localization.LocTable");
        object loc = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(locType);
        var tablesField = locType.GetField("_tables", BindingFlags.NonPublic | BindingFlags.Instance)!;
        var tables = (IDictionary)Activator.CreateInstance(tablesField.FieldType)!;
        foreach (var entry in entries)
        {
            stream.Position = entry.Offset;
            byte[] bytes = reader.ReadBytes(entry.Size);
            if (bytes.Length != entry.Size || !MD5.HashData(bytes).SequenceEqual(entry.Md5))
                throw new InvalidDataException("Localization entry checksum failed: " + entry.Name);
            var values = JsonSerializer.Deserialize<Dictionary<string, string>>(bytes)!;
            tables.Add(entry.Name, Activator.CreateInstance(tableType, [entry.Name, values, null]));
        }
        if (!tables.Contains("cards") || !tables.Contains("powers")) throw new InvalidDataException("Missing localization tables.");
        tablesField.SetValue(loc, tables);
        locType.GetProperty("Language")!.SetValue(loc, "eng");
        locType.GetProperty("CultureInfo")!.SetValue(loc, CultureInfo.GetCultureInfo("en"));
        locType.GetProperty("StringComparer")!.SetValue(loc, StringComparer.Create(CultureInfo.GetCultureInfo("en"), false));
        var callbacks = locType.GetField("_localeChangeCallbacks", BindingFlags.NonPublic | BindingFlags.Instance)!;
        callbacks.SetValue(loc, Activator.CreateInstance(callbacks.FieldType));
        locType.GetMethod("LoadLocFormatters", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(loc, null);
        locType.GetProperty("Instance")!.SetValue(null, loc);
        Console.WriteLine(JsonSerializer.Serialize(new { stage = "localization_loaded", tables = tables.Count, bytes = entries.Sum(e => e.Size) }));
    }
}
