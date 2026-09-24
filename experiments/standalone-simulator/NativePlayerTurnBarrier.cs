using System.Linq.Expressions;
using System.Reflection;

// Phase=Play is assigned before StartTurn unpauses the action queues. Observe
// the original TurnStarted event as well, then drain any completing hook action.
internal sealed class NativePlayerTurnBarrier : IDisposable
{
    private readonly object manager;
    private readonly EventInfo started;
    private readonly Delegate handler;
    private int signaled;
    public bool IsSignaled => Volatile.Read(ref signaled) != 0;

    public NativePlayerTurnBarrier(object manager)
    {
        this.manager = manager;
        started = manager.GetType().GetEvent("TurnStarted")!;
        Type type = started.EventHandlerType!;
        var parameters = type.GetMethod("Invoke")!.GetParameters()
            .Select(p => Expression.Parameter(p.ParameterType)).ToArray();
        if (parameters.Length != 1) throw new InvalidOperationException("Unexpected TurnStarted event signature.");
        Action<object> observe = state => {
            if (state.GetType().GetProperty("CurrentSide")!.GetValue(state)!.ToString() == "Player")
                Volatile.Write(ref signaled, 1);
        };
        handler = Expression.Lambda(type, Expression.Call(Expression.Constant(observe),
            typeof(Action<object>).GetMethod("Invoke")!, Expression.Convert(parameters[0], typeof(object))), parameters).Compile();
        started.AddEventHandler(manager, handler);
    }

    public void Dispose() => started.RemoveEventHandler(manager, handler);
}
