using System.Reflection;

// Only supplies the offline platform identity needed by snapshot capture.
// Any unexpected network operation is an error, not a silent default.
public class OfflinePlatformService : DispatchProxy
{
    protected override object? Invoke(MethodInfo? method, object?[]? args)
    {
        if (method?.Name == "get_Platform" && method.ReturnType.IsEnum)
            return Enum.Parse(method.ReturnType, "None");
        throw new NotSupportedException("Offline snapshot host does not implement: " + method);
    }
}
