[CmdletBinding()]
param([switch]$Help)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: test_beta1_scripts.ps1 [-Help]
Runs the dependency-free PowerShell 5.1 harness for Beta 1 SDK/image/device/cleanup/
report/package safety. It creates only a unique temporary fixture directory.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
$script:passed = 0

function Assert-True {
    param([Parameter(Mandatory = $true)][bool]$Condition, [Parameter(Mandatory = $true)][string]$Name)
    if (-not $Condition) { throw "assertion_failed:$Name" }
    $script:passed++
}

function Assert-Equal {
    param($Expected, $Actual, [Parameter(Mandatory = $true)][string]$Name)
    if ($Expected -ne $Actual) { throw "assertion_failed:$Name" }
    $script:passed++
}

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Body,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Name
    )
    try { & $Body; throw "assertion_did_not_throw:$Name" } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw "assertion_wrong_error:$Name" }
    }
    $script:passed++
}

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('health-tracker-beta1-script-tests-' + [Guid]::NewGuid().ToString('N'))
$sdkWithSpaces = Join-Path $fixtureRoot 'Android SDK With Spaces'
$projectWithSpaces = Join-Path $fixtureRoot 'Project With Spaces'
$previousSdkRoot = [Environment]::GetEnvironmentVariable('ANDROID_SDK_ROOT')
$previousAndroidHome = [Environment]::GetEnvironmentVariable('ANDROID_HOME')

try {
    New-Item -ItemType Directory -Path $sdkWithSpaces -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $projectWithSpaces 'android') -Force | Out-Null
    foreach ($relative in @(
        'system-images\android-35\google_apis\x86_64',
        'system-images\android-36\default\x86_64',
        'system-images\android-37\google_apis_playstore\x86_64'
    )) { New-Item -ItemType Directory -Path (Join-Path $sdkWithSpaces $relative) -Force | Out-Null }

    Assert-Equal (Resolve-Path -LiteralPath $sdkWithSpaces).Path (Resolve-Beta1SdkRoot $sdkWithSpaces $projectWithSpaces) 'explicit_sdk_with_spaces'
    [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $null)
    [Environment]::SetEnvironmentVariable('ANDROID_HOME', $null)
    $localProperties = Join-Path $projectWithSpaces 'android\local.properties'
    [IO.File]::WriteAllText($localProperties, 'sdk.dir=' + ($sdkWithSpaces -replace '\\', '\\') + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    Assert-Equal (Resolve-Path -LiteralPath $sdkWithSpaces).Path (Resolve-Beta1SdkRoot $null $projectWithSpaces) 'local_properties_sdk_with_spaces'

    $images = Get-Beta1SystemImages $sdkWithSpaces
    $selectedImage = Select-Beta1SystemImage $images 0 'x86_64'
    Assert-Equal 36 $selectedImage.Api 'preferred_api_36'
    Assert-True ($selectedImage.Tag -notmatch 'playstore') 'play_store_image_rejected'
    Assert-Throws { Select-Beta1SystemImage $images 34 'x86_64' } 'compatible_non_play' 'missing_image_rejected'

    $physical = [pscustomobject]@{ Serial = 'qa-physical'; State = 'device'; Kind = 'physical-or-remote'; AvdName = $null; Fingerprint = '00000000' }
    Assert-Throws { Select-Beta1DisposableDevice @($physical) 'health-tracker-beta1-qa-qa0001' } 'physical_device_detected' 'physical_device_rejected'
    $wrong = [pscustomobject]@{ Serial = 'emulator-1'; State = 'device'; Kind = 'emulator'; AvdName = 'Pixel_7'; Fingerprint = '11111111' }
    Assert-Throws { Select-Beta1DisposableDevice @($wrong) 'health-tracker-beta1-qa-qa0001' } 'identity_mismatch' 'foreign_avd_rejected'
    $correct = [pscustomobject]@{ Serial = 'emulator-2'; State = 'device'; Kind = 'emulator'; AvdName = 'health-tracker-beta1-qa-qa0001'; Fingerprint = '22222222' }
    Assert-Equal '22222222' (Select-Beta1DisposableDevice @($correct) $correct.AvdName).Fingerprint 'exact_disposable_avd_selected'
    Assert-Throws { Select-Beta1DisposableDevice @($correct, $wrong) $correct.AvdName } 'ambiguous_device_count' 'multiple_devices_rejected'

    Assert-Throws { Wait-Beta1Condition -Probe { $false } -TimeoutSeconds 0 -PollMilliseconds 1 -TimeoutCode 'qa_boot_timeout' } 'qa_boot_timeout' 'boot_timeout_reported'
    $owned = Join-Path (Join-Path $fixtureRoot 'session') 'avd-profile'
    Assert-Equal ([IO.Path]::GetFullPath($owned).TrimEnd('\', '/')) (Assert-Beta1OwnedPath (Join-Path $fixtureRoot 'session') $owned) 'owned_cleanup_allowed'
    Assert-Throws { Assert-Beta1OwnedPath (Join-Path $fixtureRoot 'session') (Join-Path $fixtureRoot 'Pixel_7') } 'outside_session' 'foreign_cleanup_rejected'

    $cleanupCalled = $false
    Assert-Throws {
        Invoke-Beta1WithCleanup -Body { throw (New-Object OperationCanceledException 'qa-cancelled') } -Cleanup { $script:cleanupCalled = $true }
    } 'qa-cancelled' 'ctrl_c_propagated'
    Assert-True $cleanupCalled 'ctrl_c_cleanup_called'

    $jsonPath = Join-Path $fixtureRoot 'report.json'
    $rawSerial = 'qa-sensitive-serial-1234'
    Write-Beta1Json ([ordered]@{ serial_fingerprint = Get-Beta1TextFingerprint $rawSerial }) $jsonPath
    $bytes = [IO.File]::ReadAllBytes($jsonPath)
    Assert-True (-not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) 'json_utf8_without_bom'
    $jsonText = [IO.File]::ReadAllText($jsonPath)
    Assert-True (-not $jsonText.Contains($rawSerial)) 'serial_sanitized'

    Assert-Throws { Test-Beta1ApkIdentity 'wrong.package' 21 } 'apk_package_mismatch' 'wrong_apk_package_rejected'
    Assert-Throws { Test-Beta1ApkIdentity 'io.healthtracker.companion.debug' 20 } 'apk_version_mismatch' 'wrong_apk_version_rejected'
    Test-Beta1ApkIdentity 'io.healthtracker.companion.debug' 21
    $script:passed++

    $scriptText = (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File |
        Where-Object { $_.Name -ne 'test_beta1_scripts.ps1' } | ForEach-Object {
        Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName
    }) -join "`n"
    Assert-True ($scriptText -notmatch '(?i)Invoke-Expression') 'invoke_expression_absent'
    Assert-True ($scriptText -notmatch '(?i)adb(?:\.exe)?\s+uninstall|shell\s+pm\s+clear') 'external_uninstall_and_pm_clear_absent'
    $mariaDbText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'run_beta1_mariadb.ps1')
    Assert-True ($mariaDbText -notmatch "(?im)^\s*&\s*docker\s+compose|Invoke-DockerChecked\s+@?\(\s*'compose'") 'mariadb_compose_command_absent'
    Assert-True ($mariaDbText -notmatch '(?i)docker\s+volume\s+(create|rm|prune)') 'mariadb_volume_mutation_absent'
    Assert-True ($mariaDbText -match "--tmpfs', '/var/lib/mysql") 'mariadb_tmpfs_required'
    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
    $staged = (& git -C $repoRoot diff --cached --name-only 2>$null) -join ''
    Assert-True ([string]::IsNullOrWhiteSpace($staged)) 'staging_empty'

    Write-Output "Beta 1 PowerShell harness passed: $script:passed assertions."
    exit 0
} finally {
    [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $previousSdkRoot)
    [Environment]::SetEnvironmentVariable('ANDROID_HOME', $previousAndroidHome)
    if (Test-Path -LiteralPath $fixtureRoot) {
        $resolvedFixture = [IO.Path]::GetFullPath($fixtureRoot)
        $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if ($resolvedFixture.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedFixture) -like 'health-tracker-beta1-script-tests-*') {
            Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
        }
    }
}
