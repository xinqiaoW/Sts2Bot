param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$solverRoot = Split-Path -Parent $PSScriptRoot
$solverProject = Join-Path $solverRoot "CombatSolver.csproj"

dotnet build $solverProject -c $Configuration --nologo
if ($LASTEXITCODE -ne 0) {
    throw "CombatSolver build failed with exit code $LASTEXITCODE."
}
