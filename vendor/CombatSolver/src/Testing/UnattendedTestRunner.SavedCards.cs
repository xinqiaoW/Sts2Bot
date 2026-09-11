using System.Reflection;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Saves.Runs;

namespace CombatSolver;

internal sealed partial class UnattendedTestRunner
{
    private static IEnumerable<PropertyInfo> SavedCardProperties(CardModel card) =>
        card.GetType().GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)
            .Where(property => property.IsDefined(typeof(SavedPropertyAttribute), inherit: true));

    private static void ApplySavedCardIntegers(CardModel card, IReadOnlyDictionary<string, int> state)
    {
        if (state.Count == 0) return;
        Dictionary<string, PropertyInfo> properties = SavedCardProperties(card).ToDictionary(p => p.Name);
        foreach ((string name, int value) in state)
        {
            if (!properties.TryGetValue(name, out PropertyInfo? property) || !property.CanWrite
                || (property.PropertyType != typeof(int) && !property.PropertyType.IsEnum))
                throw new InvalidOperationException($"Unsupported saved card field: {card.Id.Entry}.{name}");
            if (property.PropertyType.IsEnum && !Enum.IsDefined(property.PropertyType, value))
                throw new InvalidOperationException($"Invalid saved card enum: {card.Id.Entry}.{name}={value}");
            property.SetValue(card, property.PropertyType.IsEnum ? Enum.ToObject(property.PropertyType, value) : value);
        }
    }

    private static Dictionary<string, int> CaptureSavedCardIntegers(CardModel card)
    {
        Dictionary<string, int> result = new(StringComparer.Ordinal);
        foreach (PropertyInfo property in SavedCardProperties(card))
        {
            if (property.PropertyType != typeof(int) && !property.PropertyType.IsEnum)
                throw new InvalidOperationException($"Unsupported observed saved card field: {card.Id.Entry}.{property.Name}");
            result.Add(property.Name, Convert.ToInt32(property.GetValue(card)));
        }
        return result;
    }
}
