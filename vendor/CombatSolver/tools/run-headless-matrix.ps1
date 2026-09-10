#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateRange(1, 10000)]
    [int]$StartAt = 1,
    [ValidateRange(0, 10000)]
    [int]$MaxCases = 0,
    [switch]$ContinueOnFailure,
    [string]$Sts2GameRoot = "C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2",
    [string]$RitsuWorkshopRoot = "C:\Program Files (x86)\Steam\steamapps\workshop\content\2868840\3747602295",
    [string]$ResultsPath = ".local\headless-matrix-results.jsonl"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($null -eq ("CombatSolverHeadlessMatrixCancellation" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Diagnostics;
using System.Threading;

public static class CombatSolverHeadlessMatrixCancellation
{
    private static int requested;
    private static int installed;

    public static bool IsCancellationRequested => Volatile.Read(ref requested) != 0;

    public static void Install()
    {
        Interlocked.Exchange(ref requested, 0);
        if (Interlocked.Exchange(ref installed, 1) == 0)
            Console.CancelKeyPress += HandleCancelKeyPress;
    }

    public static void Uninstall()
    {
        if (Interlocked.Exchange(ref installed, 0) != 0)
            Console.CancelKeyPress -= HandleCancelKeyPress;
    }

    public static bool WaitForExit(Process process, bool observeCancellation)
    {
        while (!process.WaitForExit(100))
        {
            if (observeCancellation && IsCancellationRequested)
                return false;
        }
        return !(observeCancellation && IsCancellationRequested);
    }

    private static void HandleCancelKeyPress(object sender, ConsoleCancelEventArgs args)
    {
        args.Cancel = true;
        Interlocked.Exchange(ref requested, 1);
    }
}
"@
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$runner = Join-Path $PSScriptRoot "run-unattended-test.ps1"

$commands = @(Get-Content -LiteralPath "docs\TEST_MATRIX.md" |
    Where-Object { $_ -match '^pwsh -NoProfile -File tools\\run-unattended-test\.ps1(?: |$)' })
if ($commands.Count -eq 0) {
    throw "No PowerShell unattended commands were found in docs\TEST_MATRIX.md."
}
if ($StartAt -gt $commands.Count) {
    throw "StartAt exceeds the $($commands.Count) documented commands."
}

function Get-MissingFixtureReason([string]$ScenarioId) {
    if ($ScenarioId -eq "CHOICES-PARADOX-SCROLLS-0160") {
        if ([string]::IsNullOrWhiteSpace($env:CHOICES_PARADOX_RUN_SNAPSHOT_PATH) -or
            [string]::IsNullOrWhiteSpace($env:CHOICES_PARADOX_PROGRESS_SNAPSHOT_PATH) -or
            -not (Test-Path -LiteralPath $env:CHOICES_PARADOX_RUN_SNAPSHOT_PATH -PathType Leaf) -or
            -not (Test-Path -LiteralPath $env:CHOICES_PARADOX_PROGRESS_SNAPSHOT_PATH -PathType Leaf)) {
            return "missing external choices-paradox run/progress snapshots"
        }
    }
    if ($ScenarioId -in @("QUEEN-CHAINS-REUSE-FINAL-085", "CORPSE-SLUGS-USER-RUN-073")) {
        if ([string]::IsNullOrWhiteSpace($env:RUN_SNAPSHOT_PATH) -or
            -not (Test-Path -LiteralPath $env:RUN_SNAPSHOT_PATH -PathType Leaf)) {
            return "missing external user profile save"
        }
    }
    return $null
}

$resultsFullPath = [IO.Path]::GetFullPath($ResultsPath)
$resultsDirectory = Split-Path -Parent $resultsFullPath
New-Item -ItemType Directory -Path $resultsDirectory -Force | Out-Null
if (Test-Path -LiteralPath $resultsFullPath -PathType Leaf) {
    Remove-Item -LiteralPath $resultsFullPath -Force
}

$escapedGameRoot = $Sts2GameRoot.Replace("'", "''")
$escapedRitsuRoot = $RitsuWorkshopRoot.Replace("'", "''")
$attempted = 0
$passed = 0
$failed = 0
$skipped = 0
$ranCase = $false
$suiteStopwatch = [Diagnostics.Stopwatch]::StartNew()
$headlessRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "CombatSolver\headless-runtime"
$processMarkerPath = Join-Path $headlessRoot "process.json"
$gameRootFullPath = [IO.Path]::GetFullPath($Sts2GameRoot)
$gameModsFullPath = [IO.Path]::GetFullPath((Join-Path $gameRootFullPath "mods"))
$headlessDependencyDir = [IO.Path]::GetFullPath(
    (Join-Path $gameModsFullPath ".combatsolver-headless-ritsulib"))
$headlessDependencyMarker = Join-Path $headlessDependencyDir ".combatsolver-headless-only"
$primaryError = $null
$cleanupError = $null
$cleanupExitCode = 0
$lifecycleMode = "documented"
$pwshExecutable = (Get-Command pwsh -ErrorAction Stop).Source

function Start-MatrixPwshProcess([string[]]$Arguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $script:pwshExecutable
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    foreach ($argument in $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $child = [Diagnostics.Process]::new()
    $child.StartInfo = $startInfo
    if (-not $child.Start()) {
        $child.Dispose()
        throw "Could not start the matrix PowerShell child process."
    }
    return $child
}

function Invoke-MatrixCaseCommand([string]$CaseCommand) {
    if ([CombatSolverHeadlessMatrixCancellation]::IsCancellationRequested) {
        throw [OperationCanceledException]::new("Headless matrix cancellation was requested.")
    }
    $wrapper = @"
`$ErrorActionPreference = 'Stop'
try {
    $CaseCommand
    `$nativeExitCode = if (`$null -eq `$LASTEXITCODE) { 0 } else { [int]`$LASTEXITCODE }
    exit `$nativeExitCode
} catch {
    [Console]::Error.WriteLine(`$_.Exception.ToString())
    exit 1
}
"@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($wrapper))
    $child = Start-MatrixPwshProcess @("-NoProfile", "-EncodedCommand", $encoded)
    try {
        $completed = [CombatSolverHeadlessMatrixCancellation]::WaitForExit($child, $true)
        if (-not $completed) {
            if (-not $child.HasExited) {
                $child.Kill($true)
            }
            [CombatSolverHeadlessMatrixCancellation]::WaitForExit($child, $false) | Out-Null
            throw [OperationCanceledException]::new("Headless matrix cancellation was requested.")
        }
        return [int]$child.ExitCode
    } finally {
        $child.Dispose()
    }
}

function Remove-CancelledCaseOrphanedDependency {
    $orphanCleanupLockPath = Join-Path $script:headlessRoot "launcher.lock"
    try {
        $orphanCleanupLock = [IO.File]::Open(
            $orphanCleanupLockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None)
    } catch {
        throw "Could not acquire the unattended launcher lock for cancelled-case cleanup; " +
            "the headless dependency was preserved. error=$($_.Exception.Message)"
    }

    try {
        # The case wrapper has already been killed and waited. Do not infer that
        # a numeric PID is ours here: any remaining game may be the player's
        # process. A live or uninspectable game therefore fails closed.
        $gameProcesses = @([Diagnostics.Process]::GetProcessesByName("SlayTheSpire2"))
        try {
            foreach ($gameProcess in $gameProcesses) {
                $gameProcessSafeHandle = $gameProcess.SafeHandle
                $gameProcess.Refresh()
                if (-not $gameProcess.HasExited) {
                    throw "A live SlayTheSpire2 process remains after the cancelled case; " +
                        "the headless dependency was preserved. pid=$($gameProcess.Id)"
                }
            }
        } finally {
            foreach ($gameProcess in $gameProcesses) {
                $gameProcess.Dispose()
            }
        }

        if (-not (Test-Path -LiteralPath $script:headlessDependencyDir -PathType Container)) {
            return
        }
        $modsPrefix = $script:gameModsFullPath.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $dependencyFullPath = [IO.Path]::GetFullPath($script:headlessDependencyDir)
        if (-not $dependencyFullPath.StartsWith($modsPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals(
                [IO.Path]::GetFileName($dependencyFullPath),
                ".combatsolver-headless-ritsulib",
                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a cancelled-case dependency outside the exact managed path: $dependencyFullPath"
        }
        if (-not (Test-Path -LiteralPath $script:headlessDependencyMarker -PathType Leaf)) {
            $orphanEntries = @(Get-ChildItem -LiteralPath $dependencyFullPath -Force)
            if ($orphanEntries.Count -eq 0) {
                Remove-Item -LiteralPath $dependencyFullPath -Force
                Write-Host "MATRIX_CANCELLED_EMPTY_DEPENDENCY_REMOVED path=$dependencyFullPath"
                return
            }
            throw "Cancelled-case dependency lacks its ownership marker and was preserved: $dependencyFullPath"
        }
        $ownershipMarker = (Get-Content -LiteralPath $script:headlessDependencyMarker -Raw).Trim()
        if ($ownershipMarker -ne "CombatSolver isolated headless dependency") {
            throw "Cancelled-case dependency has an unexpected ownership marker and was preserved: $dependencyFullPath"
        }
        Remove-Item -LiteralPath $dependencyFullPath -Recurse -Force
        Write-Host "MATRIX_CANCELLED_DEPENDENCY_REMOVED path=$dependencyFullPath"
    } finally {
        $orphanCleanupLock.Dispose()
    }
}

function Invoke-HeadlessCleanup(
    [switch]$AllowBeforeFirstCase,
    [switch]$RecoverCancelledOrphan) {
    if (-not $script:ranCase -and -not $AllowBeforeFirstCase.IsPresent) {
        return 0
    }
    if (-not (Test-Path -LiteralPath $script:processMarkerPath -PathType Leaf)) {
        if ($RecoverCancelledOrphan.IsPresent) {
            Remove-CancelledCaseOrphanedDependency
        }
        return 0
    }

    $markerProcessLabel = "unknown"
    $markerProcessId = 0
    try {
        $marker = Get-Content -LiteralPath $script:processMarkerPath -Raw | ConvertFrom-Json
        if ([int]::TryParse([string]$marker.pid, [ref]$markerProcessId) -and
            $markerProcessId -gt 0) {
            $markerProcessLabel = [string]$markerProcessId
        }
    } catch {
        $markerProcessLabel = "unknown"
    }
    Write-Host "MATRIX_CLEANUP_BEGIN pid=$markerProcessLabel"
    $child = Start-MatrixPwshProcess @(
        "-NoProfile",
        "-File", $script:runner,
        "-ScenarioId", "MATRIX-CLEANUP",
        "-Sts2GameRoot", $script:Sts2GameRoot,
        "-RitsuWorkshopRoot", $script:RitsuWorkshopRoot,
        "-StopAfterCombatRootSnapshotAssertion",
        "-TimeoutSeconds", "90",
        "-ExitOnComplete")
    try {
        [CombatSolverHeadlessMatrixCancellation]::WaitForExit($child, $false) | Out-Null
        $exitCode = [int]$child.ExitCode
    } finally {
        $child.Dispose()
    }
    Write-Host "MATRIX_CLEANUP_END exit_code=$exitCode"
    return [int]$exitCode
}

[CombatSolverHeadlessMatrixCancellation]::Install()
$matrixCancellationInstalled = $true
Write-Host (
    "MATRIX_BEGIN total=$($commands.Count) start_at=$StartAt max_cases=$MaxCases " +
    "lifecycle_mode=$lifecycleMode")

try {
    if ([CombatSolverHeadlessMatrixCancellation]::IsCancellationRequested) {
        throw [OperationCanceledException]::new("Headless matrix cancellation was requested.")
    }
    $preflightCleanupExitCode = Invoke-HeadlessCleanup -AllowBeforeFirstCase
    if ($preflightCleanupExitCode -ne 0) {
        throw "Matrix preflight cleanup request exited with code $preflightCleanupExitCode."
    }
    for ($offset = $StartAt - 1; $offset -lt $commands.Count; $offset++) {
        $index = $offset + 1
        $command = $commands[$offset]
        if ($command -notmatch '-ScenarioId\s+([^\s]+)') {
            throw "Command $index does not contain a ScenarioId: $command"
        }
        $scenarioId = $Matches[1].Trim("'", '"')
        $fixtureReason = Get-MissingFixtureReason $scenarioId
        if ($null -ne $fixtureReason) {
            $skipped++
            [ordered]@{
                index = $index
                scenarioId = $scenarioId
                status = "SkippedMissingFixture"
                reason = $fixtureReason
                elapsedMilliseconds = 0
                exitCode = $null
            } | ConvertTo-Json -Compress | Add-Content -LiteralPath $resultsFullPath -Encoding UTF8
            Write-Host "MATRIX_SKIP index=$index scenario=$scenarioId reason=$fixtureReason"
            if ($command -match '(?i)(?:^|\s)-ExitOnComplete(?:\s|$)') {
                $skippedBoundaryCleanupExitCode = Invoke-HeadlessCleanup -AllowBeforeFirstCase
                if ($skippedBoundaryCleanupExitCode -ne 0) {
                    throw (
                        "Skipped exit boundary cleanup request exited with code " +
                        "$skippedBoundaryCleanupExitCode.")
                }
            }
            continue
        }
        if ($MaxCases -gt 0 -and $attempted -ge $MaxCases) {
            break
        }

        $attempted++
        $ranCase = $true
        $caseCommand = $command
        $caseCommand += " -Sts2GameRoot '$escapedGameRoot' -RitsuWorkshopRoot '$escapedRitsuRoot'"

        $caseStopwatch = [Diagnostics.Stopwatch]::StartNew()
        Write-Host "MATRIX_CASE_BEGIN index=$index scenario=$scenarioId"
        $exitCode = 1
        $failure = $null
        try {
            $exitCode = Invoke-MatrixCaseCommand $caseCommand
        } catch [OperationCanceledException] {
            throw
        } catch {
            $failure = $_.Exception.Message
            $exitCode = 1
            Write-Error -ErrorAction Continue (
                "MATRIX_CASE_EXCEPTION index=$index scenario=$scenarioId error=$failure")
        }
        $caseStopwatch.Stop()

        $status = if ($exitCode -eq 0) { "Passed" } else { "Failed" }
        if ($exitCode -eq 0) {
            $passed++
        } else {
            $failed++
        }
        $elapsedMilliseconds = [Math]::Round($caseStopwatch.Elapsed.TotalMilliseconds, 3)
        [ordered]@{
            index = $index
            scenarioId = $scenarioId
            status = $status
            elapsedMilliseconds = $elapsedMilliseconds
            exitCode = $exitCode
            error = $failure
            command = $caseCommand
            documentedCommand = $command
            lifecycleMode = $lifecycleMode
        } | ConvertTo-Json -Compress | Add-Content -LiteralPath $resultsFullPath -Encoding UTF8
        Write-Host (
            "MATRIX_CASE_END index=$index scenario=$scenarioId status=$status " +
            "elapsed_ms=$elapsedMilliseconds exit_code=$exitCode")

        if ($exitCode -ne 0) {
            try {
                $failureCleanupExitCode = Invoke-HeadlessCleanup
                if ($failureCleanupExitCode -ne 0) {
                    throw "Matrix cleanup request exited with code $failureCleanupExitCode."
                }
            } catch {
                $primaryError = $_
                break
            }
            if (-not $ContinueOnFailure.IsPresent) {
                break
            }
        }
    }
} catch {
    $primaryError = $_
} finally {
    try {
        $recoverCancelledOrphan =
            [CombatSolverHeadlessMatrixCancellation]::IsCancellationRequested -or
            ($null -ne $primaryError -and $primaryError.Exception -is [OperationCanceledException])
        $cleanupExitCode = Invoke-HeadlessCleanup -RecoverCancelledOrphan:$recoverCancelledOrphan
        if ($cleanupExitCode -ne 0) {
            throw "Matrix cleanup request exited with code $cleanupExitCode."
        }
    } catch {
        $cleanupError = $_
        if ($cleanupExitCode -eq 0) {
            $cleanupExitCode = 1
        }
    }
    $suiteStopwatch.Stop()
    Write-Host (
        "MATRIX_END total=$($commands.Count) attempted=$attempted passed=$passed failed=$failed " +
        "skipped=$skipped cleanup_exit_code=$cleanupExitCode " +
        "elapsed_ms=$([Math]::Round($suiteStopwatch.Elapsed.TotalMilliseconds, 3)) " +
        "results=$resultsFullPath")
    if ($matrixCancellationInstalled) {
        [CombatSolverHeadlessMatrixCancellation]::Uninstall()
    }
}

if ([CombatSolverHeadlessMatrixCancellation]::IsCancellationRequested -or
    ($null -ne $primaryError -and $primaryError.Exception -is [OperationCanceledException])) {
    if ($null -ne $primaryError) {
        Write-Error -ErrorAction Continue $primaryError
    }
    if ($null -ne $cleanupError) {
        Write-Error -ErrorAction Continue $cleanupError
    }
    exit 130
}
if ($null -ne $primaryError -and $null -ne $cleanupError) {
    throw "Matrix failed: $($primaryError.Exception.Message) Cleanup also failed: $($cleanupError.Exception.Message)"
}
if ($null -ne $primaryError) {
    throw $primaryError
}
if ($null -ne $cleanupError) {
    throw $cleanupError
}
if ($failed -gt 0) {
    exit 1
}
