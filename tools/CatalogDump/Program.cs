using System.Collections;
using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using Mono.Cecil;

string gameData = Path.GetFullPath(args[0]);
if (args.Length == 3 && args[1] == "--inspect")
{
    using var inspection = ModuleDefinition.ReadModule(Path.Combine(gameData, "sts2.dll"));
    foreach (string name in args[2].Split(','))
    {
        TypeDefinition type = inspection.GetType("MegaCrit.Sts2.Core.Models.Relics." + name);
        foreach (var t in new[] { type }.Concat(type.NestedTypes))
            foreach (var method in t.Methods.Where(m => m.HasBody))
            {
                Console.WriteLine(method.FullName);
                foreach (var instruction in method.Body.Instructions) Console.WriteLine(instruction);
            }
    }
    return;
}
AssemblyLoadContext.Default.Resolving += (_, name) => File.Exists(Path.Combine(gameData, name.Name + ".dll"))
    ? AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(gameData, name.Name + ".dll")) : null;
Assembly game = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(gameData, "sts2.dll"));
Type db = game.GetType("MegaCrit.Sts2.Core.Models.ModelDb")!;
Type modelType = game.GetType("MegaCrit.Sts2.Core.Models.AbstractModel")!;
db.GetMethod("Init")!.Invoke(null, new object[] { game.GetTypes().Where(t => !t.IsAbstract && modelType.IsAssignableFrom(t)).ToArray() });
object? Get(object item, string field) {
    const BindingFlags flags=BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance;
    if(item.GetType().GetProperty(field,flags) is { } property) return property.GetValue(item);
    if(item.GetType().GetField(field,flags) is { } member) return member.GetValue(item);
    throw new MissingMemberException(item.GetType().FullName,field);
}
string Id(object item) => Get(Get(item, "Id")!, "Entry")!.ToString()!;
object[] List(object item) => ((IEnumerable)item).Cast<object>().ToArray();
object[] All(string field) => List(db.GetProperty(field)!.GetValue(null)!);
using var module = ModuleDefinition.ReadModule(Path.Combine(gameData,"sts2.dll"));
IEnumerable<TypeDefinition> Descendants(TypeDefinition type) => new[] { type }.Concat(type.NestedTypes.SelectMany(Descendants));
string[] Calls(Type type) => Descendants(module.GetType(type.FullName)).SelectMany(t => t.Methods)
    .Where(m => m.HasBody).SelectMany(m => m.Body.Instructions).Select(i => i.Operand)
    .OfType<MethodReference>().Select(m => m.FullName).Distinct().Order().ToArray();
string[] RelicRefs(Type type) => Descendants(module.GetType(type.FullName)).SelectMany(t => t.Methods)
    .Where(m => m.HasBody).SelectMany(m => m.Body.Instructions).Select(i => i.Operand)
    .OfType<GenericInstanceMethod>().SelectMany(m => m.GenericArguments)
    .Where(t => t.Namespace == "MegaCrit.Sts2.Core.Models.Relics").Select(t => t.Name).Distinct().Order().ToArray();
object[] relicObjects = All("AllRelics");
var relicIds = relicObjects.ToDictionary(x => x.GetType().Name, Id);
var cards = All("AllCards").Select(c => new {
    id=Id(c), pool=Id(Get(c,"Pool")!), rarity=Get(c,"Rarity")!.ToString(), type=Get(c,"Type")!.ToString(),
    cost=Get(c,"CanonicalEnergyCost"), max_upgrade_level=Get(c,"MaxUpgradeLevel"),
    multiplayer_constraint=Get(c,"MultiplayerConstraint")!.ToString(), calls=Calls(c.GetType())
}).ToArray();
var relics = relicObjects.Select(r => new {
    id=Id(r), class_name=r.GetType().Name, pool=Id(Get(r,"Pool")!), rarity=Get(r,"Rarity")!.ToString(), calls=Calls(r.GetType()),
    state_properties=r.GetType().GetProperties(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly)
        .Where(p=>p.GetCustomAttributesData().Any(a=>a.AttributeType.Name.Contains("Saved")))
        .Select(p=>new {name=p.Name,type=p.PropertyType.Name}).ToArray(),
    declared_methods=r.GetType().GetMethods(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly).Select(m=>m.Name).ToArray()
}).ToArray();
var actsByIndex = All("ActsByIndex");
var acts = actsByIndex.SelectMany((group,index) => List(group).Select(a => new {
    id=Id(a), act=index+1, is_default=Get(a,"IsDefault"),
    encounters=List(Get(a,"AllEncounters")!).Select(e=>new {id=Id(e),room_type=Get(e,"RoomType")!.ToString(),weak=Get(e,"IsWeak"),monsters=List(Get(e,"AllPossibleMonsters")!).Select(Id).ToArray()}).ToArray(),
    ancients=List(Get(a,"AllAncients")!).Select(Id).ToArray()
})).ToArray();
var ancients=All("AllAncients").Select(a=>new {id=Id(a),possible_relics=RelicRefs(a.GetType()).Select(t=>relicIds[t]).ToArray()}).ToArray();
// ActModel.AllAncients explicitly excludes shared Ancients. RunManager assigns
// each shared Ancient to at most one act after act 1 before rolling its room.
var sharedAncients=All("AllSharedAncients").Select(Id).ToArray();
Type enchantmentType = game.GetType("MegaCrit.Sts2.Core.Models.EnchantmentModel")!;
var enchantments=game.GetTypes().Where(t=>!t.IsAbstract && enchantmentType.IsAssignableFrom(t))
    .Select(t=>db.GetMethod("Enchantment")!.MakeGenericMethod(t).Invoke(null,null)!)
    .Select(e=>new {id=Id(e),class_name=e.GetType().Name,is_stackable=Get(e,"IsStackable")}).ToArray();
object silent = All("AllCharacters").Single(c=>Id(c)=="SILENT");
var output=new {schema_version=1,game_version="0.111.0",game_sha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(Path.Combine(gameData,"sts2.dll")))) .ToLowerInvariant(),
    character=new {id=Id(silent),starting_hp=Get(silent,"StartingHp"),starting_deck=List(Get(silent,"StartingDeck")!).Select(Id).ToArray(),starting_relics=List(Get(silent,"StartingRelics")!).Select(Id).ToArray()},cards,relics,acts,ancients,enchantments,shared_ancients=sharedAncients};
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[1]))!);
File.WriteAllText(args[1],JsonSerializer.Serialize(output,new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine($"CATALOG cards={cards.Length} relics={relics.Length} acts={acts.Length} ancients={ancients.Length} path={args[1]}");
