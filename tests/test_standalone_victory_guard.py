"""Exercise the actual host victory observer with controlled native events."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_native_victory_observer_requires_matching_event_and_primary_defeat(tmp_path):
    dotnet = os.environ.get('STS2_DOTNET') or shutil.which('dotnet')
    if not dotnet:
        pytest.skip('Set STS2_DOTNET to a .NET 9 SDK for host observer tests')
    source = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator/NativeCombatRewards.cs'
    shutil.copyfile(source, tmp_path / source.name)
    (tmp_path / 'Guard.csproj').write_text('''<Project Sdk="Microsoft.NET.Sdk">
      <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net9.0</TargetFramework>
      <ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup>
    </Project>''')
    (tmp_path / 'Program.cs').write_text('''
using System.Reflection;

static void Reject(Action action, string message)
{
    try { action(); }
    catch (InvalidOperationException e) when (e.Message.Contains(message)) { return; }
    throw new Exception("Expected rejection: " + message);
}
var manager = new Manager();
var combat = new Combat();
var observer = new NativeCombatRewards(_ => throw new Exception("Unexpected reward generation"),
    Assembly.GetExecutingAssembly(), manager);
Reject(() => observer.AssertVictory(combat), "Missing native victory event");
manager.Win(new Combat());
Reject(() => observer.AssertVictory(combat), "Missing native victory event");
manager.Win(combat);
observer.Wait();
observer.AssertVictory(combat); // Rewardless encounters still report native victory.
combat.Enemies.Add(new Enemy { IsAlive = true, IsPrimaryEnemy = false });
observer.AssertVictory(combat); // Surviving secondary enemies are legal.
combat.Enemies.Add(new Enemy { IsAlive = true, IsPrimaryEnemy = true });
Reject(() => observer.AssertVictory(combat), "living primary enemy");
combat.Enemies[1].IsAlive = false;
observer.AssertVictory(combat); // A dead primary enemy cannot prevent victory.
combat.RunState.CurrentRoom.IsPreFinished = false;
Reject(() => observer.AssertVictory(combat), "room is not complete");
combat.RunState.CurrentRoom.IsPreFinished = true;
manager.Win(new Combat());
Reject(() => observer.AssertVictory(combat), "Missing native victory event");
observer.Dispose();
if (manager.Subscribers != 0) throw new Exception("Victory observer leaked");
Console.WriteLine("victory observer checks passed");

public sealed class Manager
{
    public event Action<Room>? CombatWon;
    public int Subscribers => CombatWon?.GetInvocationList().Length ?? 0;
    public void Win(Combat combat) => CombatWon?.Invoke(new Room { CombatState = combat });
}
public sealed class Room
{
    public Combat CombatState { get; init; } = null!;
    public Encounter Encounter { get; } = new();
    public bool IsPreFinished { get; set; } = true;
}
public sealed class Encounter { public bool ShouldGiveRewards => false; }
public sealed class Run { public Room CurrentRoom { get; } = new(); }
public sealed class Combat
{
    public Run RunState { get; } = new();
    public List<Enemy> Enemies { get; } = new();
}
public sealed class Enemy
{
    public bool IsAlive { get; set; }
    public bool IsPrimaryEnemy { get; init; }
}
''')
    result = subprocess.run(
        [dotnet, 'run', '--project', str(tmp_path / 'Guard.csproj'), '-c', 'Release'],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, 'DOTNET_PROCESSOR_COUNT': '1'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'victory observer checks passed' in result.stdout
