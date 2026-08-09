[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)][string]$SessionId,
    [string]$SdkRoot,
    [string]$ReportRoot,
    [int]$TimeoutSeconds = 60,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: delete_disposable_avd.ps1 -SessionId <id> [-SdkRoot <path>] [-ReportRoot <path>] [-Help]
Stops and deletes only health-tracker-beta1-qa-<id> after validating its session metadata.
It never deletes Pixel_7, another AVD, app data, or an external device.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
if (-not $SessionId) { [Console]::Error.WriteLine('SessionId is required.'); exit 2 }

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$SessionId = Get-Beta1SessionId $SessionId
$expectedName = Get-Beta1AvdName $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$metadataPath = Join-Path $sessionRoot 'avd.json'
$avdHome = Join-Path $sessionRoot 'avd-home'
$profilePath = Join-Path $sessionRoot 'avd-profile'
$previousAvdHome = [Environment]::GetEnvironmentVariable('ANDROID_AVD_HOME')

try {
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) { throw 'session_metadata_missing' }
    $metadata = Get-Content -Raw -Encoding UTF8 -LiteralPath $metadataPath | ConvertFrom-Json
    if ($metadata.session_id -ne $SessionId -or $metadata.avd_name -ne $expectedName) { throw 'session_metadata_mismatch' }
    if ($expectedName -eq 'Pixel_7' -or $expectedName -notlike 'health-tracker-beta1-qa-*') { throw 'protected_avd_name' }

    $resolvedSdk = Resolve-Beta1SdkRoot $SdkRoot $projectRoot
    $adb = Find-Beta1AndroidTool $resolvedSdk 'platform-tools' 'adb'
    $avdManager = Find-Beta1AndroidTool $resolvedSdk 'cmdline-tools' 'avdmanager'
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', $avdHome)

    $devices = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
    $matching = @($devices | Where-Object { $_.Kind -eq 'emulator' -and $_.AvdName -eq $expectedName })
    if ($matching.Count -gt 1) { throw 'duplicate_disposable_avd_runtime' }
    if ($matching.Count -eq 1) {
        $stopResult = Invoke-Beta1NativeCommand $adb @('-s', $matching[0].Serial, 'emu', 'kill')
        if ($stopResult.ExitCode -ne 0) { throw 'disposable_avd_stop_failed' }
        Wait-Beta1Condition -TimeoutSeconds $TimeoutSeconds -TimeoutCode 'disposable_avd_stop_timeout' -Probe {
            $remaining = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
            return @($remaining | Where-Object { $_.Kind -eq 'emulator' -and $_.AvdName -eq $expectedName }).Count -eq 0
        }
    }

    $deleteResult = Invoke-Beta1NativeCommand $avdManager @('delete', 'avd', '--name', $expectedName)
    if ($deleteResult.ExitCode -ne 0) {
        $postDeleteDevices = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
        if (@($postDeleteDevices | Where-Object { $_.AvdName -eq $expectedName }).Count -gt 0) {
            throw 'disposable_avd_delete_failed'
        }
    }

    foreach ($owned in @($profilePath, $avdHome)) {
        if (Test-Path -LiteralPath $owned) {
            $validated = Assert-Beta1OwnedPath $sessionRoot $owned
            Remove-Item -LiteralPath $validated -Recurse -Force
        }
    }
    Write-Beta1Json ([ordered]@{
        schema = 'health-tracker-beta1-avd-cleanup-v1'
        session_id = $SessionId
        avd_name = $expectedName
        running_instance_removed = ($matching.Count -eq 1)
        avdmanager_exit_code = $deleteResult.ExitCode
        direct_owned_profile_cleanup = ($deleteResult.ExitCode -ne 0)
        profile_removed = -not (Test-Path -LiteralPath $profilePath)
        avd_home_removed = -not (Test-Path -LiteralPath $avdHome)
        completed_at_utc = [DateTime]::UtcNow.ToString('o')
    }) (Join-Path $sessionRoot 'avd-cleanup.json')
    Write-Output "Removed disposable AVD $expectedName; reports remain in the temporary session."
    exit 0
} catch {
    [Console]::Error.WriteLine("Beta 1 AVD cleanup refused or failed: " + $_.Exception.Message)
    exit 3
} finally {
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', $previousAvdHome)
}
