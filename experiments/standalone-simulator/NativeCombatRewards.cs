using System.Reflection;
using System.Linq.Expressions;

// The rendered combat UI starts this original game pipeline on CombatWon.
// Run its reward generation and hooks without offering/claiming the rewards.
internal sealed class NativeCombatRewards : IDisposable
{
    private readonly Func<string, Type> get;
    private readonly Assembly solver;
    private readonly object manager;
    private readonly EventInfo won;
    private readonly Delegate handler;
    private object? wonCombat;
    public Task Completion { get; private set; } = Task.CompletedTask;
    public string? BeforeGenerationStamp { get; private set; }
    public int Generations { get; private set; }
    private static object Read(object value, string name) => value.GetType().GetProperty(name)!.GetValue(value)!;

    public NativeCombatRewards(Func<string, Type> get, Assembly solver, object manager)
    {
        this.get = get; this.solver = solver; this.manager = manager;
        won = manager.GetType().GetEvent("CombatWon")!;
        ParameterExpression room = Expression.Parameter(won.EventHandlerType!.GetMethod("Invoke")!.GetParameters()[0].ParameterType);
        Action<object> start = value =>
        {
            wonCombat = Read(value, "CombatState");
            Completion = Generate(value);
        };
        handler = Expression.Lambda(won.EventHandlerType,
            Expression.Call(Expression.Constant(start), typeof(Action<object>).GetMethod("Invoke")!, Expression.Convert(room, typeof(object))), room).Compile();
        won.AddEventHandler(manager, handler);
    }

    private async Task Generate(object room)
    {
        if (!(bool)Read(Read(room, "Encounter"), "ShouldGiveRewards")) return;
        if (++Generations != 1) throw new InvalidOperationException("Combat rewards generated twice.");
        object combat = Read(room, "CombatState");
        BeforeGenerationStamp = (string)Read(solver.GetType("CombatSolver.ContinuationStamp", true)!
            .GetMethod("CaptureLive")!.Invoke(null, [combat])!, "StateText");
        var rewards = new List<object>();
        foreach (object player in (System.Collections.IEnumerable)Read(combat, "Players"))
        {
            Task task = (Task)get("Commands.RewardsCmd").GetMethod("GenerateForRoomEnd")!.Invoke(null, [player, room])!;
            await task;
            rewards.Add(Read(task, "Result"));
        }
        foreach (object reward in rewards)
            await (Task)get("Hooks.Hook").GetMethod("BeforeCombatRewardOffered")!
                .Invoke(null, [reward, Read(combat, "RunState"), room])!;
    }

    public void Wait() => Completion.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult();
    public void AssertVictory(object combat)
    {
        // A Fabricator killed by retaliation can spawn a secondary enemy after
        // its death cleanup. Only the native event for this combat certifies a win.
        if (!ReferenceEquals(wonCombat, combat))
            throw new InvalidOperationException("Missing native victory event for this combat.");
        if (!(bool)Read(Read(Read(combat, "RunState"), "CurrentRoom"), "IsPreFinished"))
            throw new InvalidOperationException("Native victory room is not complete.");
        foreach (object enemy in (System.Collections.IEnumerable)Read(combat, "Enemies"))
            if ((bool)Read(enemy, "IsAlive") && (bool)Read(enemy, "IsPrimaryEnemy"))
                throw new InvalidOperationException("Native victory still has a living primary enemy.");
    }
    public void Dispose() => won.RemoveEventHandler(manager, handler);
}
