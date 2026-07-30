[CmdletBinding()]
param(
    [string]$Serial,
    [string]$PackageName = 'io.healthtracker.companion.debug',
    [string]$AndroidSdkRoot,
    [string]$AdbPath,
    [switch]$Launch,
    [switch]$Restart,
    [switch]$CollectLogs,
    [switch]$ClearLogcat,
    [ValidateRange(20, 5000)][int]$LastLogLines = 500,
    [string]$Since,
    [string]$RawLogOutputPath,
    [string]$OutputPath,
    [switch]$Json,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage:
  alpha15_phone_smoke.ps1 [-Serial <exact-serial>]
    [-PackageName io.healthtracker.companion.debug] [-AndroidSdkRoot <sdk>]
    [-Launch] [-Restart] [-CollectLogs] [-ClearLogcat]
    [-LastLogLines 500] [-Since <logcat-time>] [-RawLogOutputPath <outside-repo>]
    [-OutputPath <json>] [-Json] [-Help]

Package inspection is always read-only. Launch, restart, log collection, and
logcat clear occur only when their switches are present. Restart uses force-stop
and launcher start; it never clears app data, permissions, connectivity, or logs
unless -ClearLogcat is explicitly supplied. Raw logs require an explicit path
outside the repository and may contain sensitive data.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')
. (Join-Path $PSScriptRoot 'alpha15_phone_logs.ps1')

$report = [ordered]@{
    schema = 'health-tracker-alpha15-phone-smoke-v1'
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    package = $PackageName
    status = 'blocked'
    exit_code = 10
    operations = @()
}

try {
    if ($PackageName -notmatch '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$') {
        Throw-Alpha15Failure 2 'invalid_package_name' 'PackageName is invalid.'
    }
    $toolchain = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $AndroidSdkRoot -AdbPath $AdbPath
    $devices = @(Get-Alpha15ConnectedDevices $toolchain.Internal.Adb)
    $selected = Select-Alpha15Device $devices $Serial
    $report.toolchain = $toolchain.Report
    $report.device = [pscustomobject]@{ serial_fingerprint = $selected.Fingerprint; state = $selected.State }

    $installed = Get-Alpha15InstalledPackageInfo $toolchain.Internal.Adb $selected.Serial $PackageName
    $report.installed = $installed.Report
    if (-not $installed.Present) {
        $report.status = 'package_missing'
        $report.exit_code = 5
        $report.results = @('package_missing')
    } else {
        $results = New-Object System.Collections.ArrayList
        if ($ClearLogcat) {
            $clear = Invoke-Alpha15Adb $toolchain.Internal.Adb $selected.Serial @('logcat', '-c')
            if ($clear.ExitCode -ne 0) { Throw-Alpha15Failure 5 'logcat_clear_failed' 'Explicit logcat clear failed.' }
            [void]$results.Add('logcat_cleared_explicitly')
        }

        $component = $null
        if ($Launch -or $Restart) {
            $component = Get-Alpha15LauncherComponent $toolchain.Internal.Adb $selected.Serial $PackageName
            if (-not $component) { Throw-Alpha15Failure 5 'launch_failed' 'Launcher activity could not be resolved.' }
        }
        if ($Restart) {
            $stop = Invoke-Alpha15Adb $toolchain.Internal.Adb $selected.Serial @('shell', 'am', 'force-stop', $PackageName)
            if ($stop.ExitCode -ne 0) { Throw-Alpha15Failure 5 'force_stop_failed' 'Explicit force-stop failed.' }
            $start = Invoke-Alpha15Adb $toolchain.Internal.Adb $selected.Serial @('shell', 'am', 'start', '-n', $component)
            if ($start.ExitCode -ne 0) { Throw-Alpha15Failure 5 'launch_failed' 'Restart launch failed.' }
            Start-Sleep -Seconds 2
            [void]$results.Add('restart_survived')
        } elseif ($Launch) {
            $start = Invoke-Alpha15Adb $toolchain.Internal.Adb $selected.Serial @('shell', 'am', 'start', '-n', $component)
            if ($start.ExitCode -ne 0) { Throw-Alpha15Failure 5 'launch_failed' 'Launch failed.' }
            Start-Sleep -Seconds 2
            [void]$results.Add('launch_requested')
        }

        $process = Get-Alpha15ProcessState $toolchain.Internal.Adb $selected.Serial $PackageName
        $report.process = $process
        if ($process.running) { [void]$results.Add('process_started') }
        elseif ($Launch -or $Restart) { [void]$results.Add('launch_failed') }

        $activityDump = Get-Alpha15AdbText $toolchain.Internal.Adb $selected.Serial @('shell', 'dumpsys', 'activity', 'activities') -AllowFailure
        $foregroundMatch = [regex]::Match($activityDump, '(?m)mResumedActivity[^\r\n]*\s([A-Za-z0-9_.]+)/')
        $report.foreground_package_matches = $foregroundMatch.Success -and $foregroundMatch.Groups[1].Value -eq $PackageName

        if ($CollectLogs) {
            $logs = Get-Alpha15SanitizedLogs -Adb $toolchain.Internal.Adb -Serial $selected.Serial -PackageName $PackageName `
                -LastLines $LastLogLines -Since $Since -RawOutputPath $RawLogOutputPath
            $report.logs = $logs
            if ($logs.crash_detected) { [void]$results.Add('crash_detected') }
            if ($logs.anr_detected) { [void]$results.Add('anr_detected') }
            if ($logs.sensitive_log_candidate) { [void]$results.Add('sensitive_log_candidate') }
        }
        if ($results.Count -eq 0 -or ($results -notcontains 'crash_detected' -and $results -notcontains 'anr_detected' -and $results -notcontains 'sensitive_log_candidate' -and $results -notcontains 'launch_failed')) {
            [void]$results.Add('clean_basic_smoke')
        }
        $report.results = @($results)
        $report.status = $(if ($results -contains 'crash_detected' -or $results -contains 'anr_detected' -or $results -contains 'sensitive_log_candidate' -or $results -contains 'launch_failed') { 'attention_required' } else { 'clean_basic_smoke' })
        $report.exit_code = $(if ($report.status -eq 'clean_basic_smoke') { 0 } else { 5 })
    }
} catch {
    $failure = Get-Alpha15ExitFromException $_
    $report.status = 'failed'
    $report.exit_code = $failure.ExitCode
    $report.reason = $failure.Reason
    $report.message = ConvertTo-Alpha15SafeLine $failure.Message
}

if ($OutputPath) { [void](Write-Alpha15Utf8Json -Value ([pscustomobject]$report) -OutputPath $OutputPath) }
if ($Json) { ([pscustomobject]$report) | ConvertTo-Json -Depth 12 } else { ([pscustomobject]$report) | Format-List | Out-String | Write-Output }
exit [int]$report.exit_code
