[CmdletBinding()]
param(
    [string]$SessionId,
    [string]$SdkRoot,
    [int]$ApiLevel = 0,
    [string]$Abi = 'x86_64',
    [string]$ReportRoot,
    [int]$BootTimeoutSeconds = 240,
    [switch]$NoStart,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: create_disposable_avd.ps1 [-SessionId <id>] [-SdkRoot <path>] [-ApiLevel 35|36]
       [-Abi x86_64] [-ReportRoot <path>] [-BootTimeoutSeconds <seconds>] [-NoStart] [-Help]
Creates only health-tracker-beta1-qa-<id> from an already-installed non-Play image.
The AVD profile and JSON report stay under %TEMP%\health-tracker-beta1\<id>.
Exit 0=created/booted, 2=unsafe device state, 3=SDK/image issue, 4=boot failure.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$SessionId = Get-Beta1SessionId $SessionId
$avdName = Get-Beta1AvdName $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$avdHome = Join-Path $sessionRoot 'avd-home'
$profilePath = Join-Path $sessionRoot 'avd-profile'
$metadataPath = Join-Path $sessionRoot 'avd.json'
$emulatorProcess = $null
$selected = $null
$adb = $null
$previousAvdHome = [Environment]::GetEnvironmentVariable('ANDROID_AVD_HOME')

try {
    if (Test-Path -LiteralPath $sessionRoot) { throw 'session_already_exists' }
    New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $avdHome -Force | Out-Null
    $resolvedSdk = Resolve-Beta1SdkRoot $SdkRoot $projectRoot
    $adb = Find-Beta1AndroidTool $resolvedSdk 'platform-tools' 'adb'
    $emulator = Find-Beta1AndroidTool $resolvedSdk 'emulator' 'emulator'
    $avdManager = Find-Beta1AndroidTool $resolvedSdk 'cmdline-tools' 'avdmanager'
    $image = Select-Beta1SystemImage (Get-Beta1SystemImages $resolvedSdk) $ApiLevel $Abi
    Assert-Beta1SystemImageMetadata $image | Out-Null

    $preflightDevices = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
    if (@($preflightDevices | Where-Object { $_.Kind -ne 'emulator' }).Count -gt 0) { throw 'physical_device_detected' }
    if (@($preflightDevices | Where-Object { $_.AvdName -eq 'Pixel_7' }).Count -gt 0) { throw 'protected_avd_running' }
    if ($preflightDevices.Count -gt 0) { throw 'preexisting_connected_device_detected' }

    $globalInventory = Invoke-Beta1NativeCommand $emulator @('-list-avds')
    if ($globalInventory.ExitCode -ne 0) { throw 'emulator_inventory_failed' }
    if ($avdName -in $globalInventory.Output) { throw 'disposable_avd_name_collision' }
    if ('Pixel_7' -eq $avdName) { throw 'protected_avd_name' }
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', $avdHome)
    $sessionInventory = Invoke-Beta1NativeCommand $emulator @('-list-avds')
    if ($sessionInventory.ExitCode -ne 0) { throw 'emulator_inventory_failed' }
    if ($avdName -in $sessionInventory.Output) { throw 'disposable_avd_name_collision' }

    $createResult = Invoke-Beta1NativeCommand $avdManager @(
        'create', 'avd', '--name', $avdName, '--package', $image.Package,
        '--path', $profilePath, '--device', 'pixel_5'
    ) @('no')
    if ($createResult.ExitCode -ne 0) { throw 'avd_creation_failed' }
    Assert-Beta1AvdConfig (Join-Path $profilePath 'config.ini') $avdName $image.Api | Out-Null
    $createdInventory = Invoke-Beta1NativeCommand $emulator @('-list-avds')
    if ($createdInventory.ExitCode -ne 0 -or $createdInventory.Output.Count -ne 1 -or $createdInventory.Output[0] -ne $avdName) {
        throw 'disposable_avd_inventory_mismatch'
    }
    $metadata = [ordered]@{
        schema = 'health-tracker-beta1-avd-v1'
        session_id = $SessionId
        avd_name = $avdName
        state = if ($NoStart) { 'created' } else { 'starting' }
        system_image = $image.Package
        api = $image.Api
        abi = $image.Abi
        play_store = $false
        profile_location = 'session-temp'
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Beta1Json $metadata $metadataPath
    if ($NoStart) {
        Write-Output "Created disposable AVD $avdName under the temporary Beta 1 session."
        exit 0
    }

    $emulatorArguments = @(
        '-avd', $avdName,
        '-no-window', '-no-audio', '-no-boot-anim',
        '-no-snapshot', '-no-snapshot-save', '-wipe-data',
        '-gpu', 'swiftshader_indirect'
    )
    $emulatorProcess = Start-Process -FilePath $emulator -ArgumentList $emulatorArguments -PassThru -WindowStyle Hidden

    Wait-Beta1Condition -TimeoutSeconds $BootTimeoutSeconds -TimeoutCode 'disposable_avd_not_detected' -Probe {
        $devices = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
        if (@($devices | Where-Object { $_.Kind -ne 'emulator' }).Count -gt 0) { throw 'physical_device_detected' }
        $candidate = @($devices | Where-Object { $_.State -eq 'device' -and $_.AvdName -eq $avdName })
        if ($candidate.Count -eq 1) { $script:selected = $candidate[0]; return $true }
        return $false
    }
    $selected = Select-Beta1DisposableDevice (Add-Beta1AvdNames $adb (Get-Beta1ConnectedDevices $adb)) $avdName

    Wait-Beta1Condition -TimeoutSeconds $BootTimeoutSeconds -TimeoutCode 'disposable_avd_boot_timeout' -Probe {
        $boot = ((& $adb -s $selected.Serial shell getprop sys.boot_completed 2>$null) -join '').Trim()
        if ($LASTEXITCODE -ne 0 -or $boot -ne '1') { return $false }
        $packageManager = ((& $adb -s $selected.Serial shell cmd package list packages android 2>$null) -join '').Trim()
        if ($LASTEXITCODE -ne 0 -or $packageManager -notmatch 'package:android') { return $false }
        $storage = ((& $adb -s $selected.Serial shell getprop sys.user.0.ce_available 2>$null) -join '').Trim()
        if ($LASTEXITCODE -ne 0 -or $storage -notin @('true', '1')) { return $false }
        $launcher = ((& $adb -s $selected.Serial shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME 2>$null) -join '').Trim()
        return ($LASTEXITCODE -eq 0 -and $launcher -match '/')
    }

    $accountResult = Invoke-Beta1NativeCommand $adb @('-s', $selected.Serial, 'shell', 'dumpsys', 'account')
    if ($accountResult.ExitCode -ne 0) { throw 'avd_account_check_failed' }
    $accountSummary = $accountResult.Output -join "`n"
    if ($accountSummary -notmatch '(?im)^\s*Accounts:\s*0(?:\s|$)' -or
        $accountSummary -match '(?im)^\s*Account\s*\{') { throw 'avd_accounts_present' }

    $metadata.state = 'booted'
    $metadata.serial_fingerprint = $selected.Fingerprint
    $metadata.android_version = ((& $adb -s $selected.Serial shell getprop ro.build.version.release 2>$null) -join '').Trim()
    $metadata.resolution = ((& $adb -s $selected.Serial shell wm size 2>$null) -join ' ').Trim()
    $metadata.density = ((& $adb -s $selected.Serial shell wm density 2>$null) -join ' ').Trim()
    $metadata.locale = ((& $adb -s $selected.Serial shell getprop persist.sys.locale 2>$null) -join '').Trim()
    $metadata.timezone = ((& $adb -s $selected.Serial shell getprop persist.sys.timezone 2>$null) -join '').Trim()
    $metadata.accounts_present = $false
    $metadata.booted_at_utc = [DateTime]::UtcNow.ToString('o')
    Write-Beta1Json $metadata $metadataPath
    Write-Output "Disposable AVD booted: $avdName (serial fingerprint $($selected.Fingerprint))."
    exit 0
} catch {
    $failure = $_.Exception.Message
    if ($selected -and $adb) {
        try {
            $stopResult = Invoke-Beta1NativeCommand $adb @('-s', $selected.Serial, 'emu', 'kill')
            if ($stopResult.ExitCode -eq 0) {
                Wait-Beta1Condition -TimeoutSeconds 60 -TimeoutCode 'failed_avd_stop_timeout' -Probe {
                    $remaining = @(Add-Beta1AvdNames $adb @(Get-Beta1ConnectedDevices $adb))
                    return @($remaining | Where-Object { $_.AvdName -eq $avdName }).Count -eq 0
                }
            }
        } catch {
            # Preserve the original failure; the dedicated cleanup script can retry this owned AVD.
        }
    }
    if ($emulatorProcess -and -not $emulatorProcess.HasExited) {
        Stop-Process -Id $emulatorProcess.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($owned in @($profilePath, $avdHome)) {
        if (Test-Path -LiteralPath $owned) {
            $validated = Assert-Beta1OwnedPath $sessionRoot $owned
            Remove-Item -LiteralPath $validated -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $sessionRoot -PathType Container) {
        Write-Beta1Json ([ordered]@{
            schema = 'health-tracker-beta1-avd-v1'
            session_id = $SessionId
            avd_name = $avdName
            state = 'blocked_or_failed'
            error_code = $failure
            completed_at_utc = [DateTime]::UtcNow.ToString('o')
        }) (Join-Path $sessionRoot 'avd-create-failure.json')
    }
    [Console]::Error.WriteLine("Beta 1 AVD creation failed: " + $failure)
    if ($failure -match 'physical_device|connected_device|protected_avd_running|ambiguous|identity') { exit 2 }
    if ($failure -match 'sdk|tool|image|creation|collision') { exit 3 }
    exit 4
} finally {
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', $previousAvdHome)
}
