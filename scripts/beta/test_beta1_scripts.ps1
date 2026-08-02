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
        'system-images\android-36\google_apis\x86_64',
        'system-images\android-36\default\x86_64',
        'system-images\android-36\google_play\x86_64',
        'system-images\android-34\google_apis\x86_64',
        'system-images\android-37\google_apis_playstore\x86_64'
    )) { New-Item -ItemType Directory -Path (Join-Path $sdkWithSpaces $relative) -Force | Out-Null }
    $toolRoot = Join-Path $sdkWithSpaces 'cmdline-tools\latest\bin'
    New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
    foreach ($toolName in @('android.exe', 'sdkmanager.bat', 'avdmanager.bat')) {
        [IO.File]::WriteAllText((Join-Path $toolRoot $toolName), '', (New-Object Text.UTF8Encoding($false)))
    }
    foreach ($api in @(35, 36)) {
        $packageName = "system-images;android-$api;google_apis;x86_64"
        $imageRoot = Join-Path $sdkWithSpaces "system-images\android-$api\google_apis\x86_64"
        $source = @(
            "AndroidVersion.ApiLevel=$api"
            'SystemImage.TagId=google_apis'
            'SystemImage.Abi=x86_64'
            "Pkg.Path=$packageName"
        ) -join [Environment]::NewLine
        [IO.File]::WriteAllText((Join-Path $imageRoot 'source.properties'), $source, (New-Object Text.UTF8Encoding($false)))
        [IO.File]::WriteAllText((Join-Path $imageRoot 'package.xml'), "<localPackage path=`"$packageName`" />", (New-Object Text.UTF8Encoding($false)))
    }

    Assert-Equal (Resolve-Path -LiteralPath $sdkWithSpaces).Path (Resolve-Beta1SdkRoot $sdkWithSpaces $projectWithSpaces) 'explicit_sdk_with_spaces'
    [Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $null)
    [Environment]::SetEnvironmentVariable('ANDROID_HOME', $null)
    $localProperties = Join-Path $projectWithSpaces 'android\local.properties'
    [IO.File]::WriteAllText($localProperties, 'sdk.dir=' + ($sdkWithSpaces -replace '\\', '\\') + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    Assert-Equal (Resolve-Path -LiteralPath $sdkWithSpaces).Path (Resolve-Beta1SdkRoot $null $projectWithSpaces) 'local_properties_sdk_with_spaces'

    $images = Get-Beta1SystemImages $sdkWithSpaces
    $selectedImage = Select-Beta1SystemImage $images 0 'x86_64'
    Assert-Equal 36 $selectedImage.Api 'preferred_api_36'
    Assert-Equal 'google_apis' $selectedImage.Tag 'exact_google_apis_tag_selected'
    Assert-True (Assert-Beta1SystemImageMetadata $selectedImage) 'installed_image_metadata_verified'
    Assert-Equal 35 (Select-Beta1SystemImage $images 35 'x86_64').Api 'api_35_fallback_selected'
    Assert-Throws { Select-Beta1SystemImage @($images | Where-Object { $_.Tag -ne 'google_apis' }) 0 'x86_64' } 'compatible_non_play' 'non_google_apis_image_rejected'
    Assert-Throws { Select-Beta1SystemImage $images 34 'x86_64' } 'compatible_non_play' 'unsupported_api_rejected'
    Assert-Throws { Select-Beta1SystemImage $images 37 'x86_64' } 'compatible_non_play' 'play_store_image_rejected'
    Assert-Throws { Select-Beta1SystemImage $images 34 'x86_64' } 'compatible_non_play' 'missing_image_rejected'

    Assert-Equal (Join-Path $toolRoot 'android.exe') (Find-Beta1AndroidTool $sdkWithSpaces 'cmdline-tools' 'android') 'new_android_cli_discovered'
    Assert-Equal (Join-Path $toolRoot 'sdkmanager.bat') (Find-Beta1AndroidTool $sdkWithSpaces 'cmdline-tools' 'sdkmanager') 'sdkmanager_fallback_discovered'
    Assert-Equal (Join-Path $toolRoot 'avdmanager.bat') (Find-Beta1AndroidTool $sdkWithSpaces 'cmdline-tools' 'avdmanager') 'avdmanager_discovered'

    $native = Invoke-Beta1NativeCommand $env:ComSpec @('/d', '/c', 'echo qa-native-warning 1>&2 & exit /b 0')
    Assert-Equal 0 $native.ExitCode 'native_stderr_exit_preserved'
    Assert-True (($native.Output -join "`n") -match 'qa-native-warning') 'native_stderr_captured'

    $configPath = Join-Path $fixtureRoot 'config.ini'
    $config = @(
        'AvdId=health-tracker-beta1-qa-qa0001'
        'PlayStore.enabled=false'
        'image.sysdir.1=system-images\android-36\google_apis\x86_64\'
        'tag.id=google_apis'
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText($configPath, $config, (New-Object Text.UTF8Encoding($false)))
    Assert-True (Assert-Beta1AvdConfig $configPath 'health-tracker-beta1-qa-qa0001' 36) 'exact_avd_config_accepted'
    $configWithoutId = @($config -split "`r?`n" | Where-Object { $_ -notmatch '^AvdId=' }) -join [Environment]::NewLine
    [IO.File]::WriteAllText($configPath, $configWithoutId, (New-Object Text.UTF8Encoding($false)))
    Assert-True (Assert-Beta1AvdConfig $configPath 'health-tracker-beta1-qa-qa0001' 36) 'avd_config_without_redundant_id_accepted'
    $wrongIdConfig = $config -replace 'AvdId=health-tracker-beta1-qa-qa0001', 'AvdId=Pixel_7'
    [IO.File]::WriteAllText($configPath, $wrongIdConfig, (New-Object Text.UTF8Encoding($false)))
    Assert-Throws { Assert-Beta1AvdConfig $configPath 'health-tracker-beta1-qa-qa0001' 36 } 'avd_config_identity' 'wrong_avd_id_rejected_when_present'
    $playConfig = $config -replace 'PlayStore.enabled=false', 'PlayStore.enabled=true'
    [IO.File]::WriteAllText($configPath, $playConfig, (New-Object Text.UTF8Encoding($false)))
    Assert-Throws { Assert-Beta1AvdConfig $configPath 'health-tracker-beta1-qa-qa0001' 36 } 'avd_config_identity' 'play_store_avd_config_rejected'

    $physical = [pscustomobject]@{ Serial = 'qa-physical'; State = 'device'; Kind = 'physical-or-remote'; AvdName = $null; Fingerprint = '00000000' }
    Assert-Equal 0 @(Add-Beta1AvdNames 'unused-adb' @()).Count 'empty_device_inventory_supported'
    Assert-Throws { Select-Beta1DisposableDevice @() 'health-tracker-beta1-qa-qa0001' } 'ambiguous_device_count:0' 'zero_devices_rejected_for_connected_gate'
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
    Assert-True ((Get-Beta1ReportRoot).StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase)) 'reports_default_outside_repository'

    $junitRootSuite = Join-Path $fixtureRoot 'junit-root-suite.xml'
    $junitRootSuites = Join-Path $fixtureRoot 'junit-root-suites.xml'
    [IO.File]::WriteAllText($junitRootSuite, '<testsuite name="qa.One" tests="1" failures="0" errors="0" skipped="0"><testcase classname="qa.One" name="passes" /></testsuite>', (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText($junitRootSuites, '<testsuites><testsuite name="qa.Container" tests="2" failures="1" errors="0" skipped="1"><testcase classname="qa.Two" name="fails"><failure /></testcase><testcase classname="qa.Two" name="skips"><skipped /></testcase></testsuite></testsuites>', (New-Object Text.UTF8Encoding($false)))
    $junit = Get-Beta1JUnitSummary @($junitRootSuite, $junitRootSuites)
    Assert-Equal 3 $junit.Total 'junit_both_root_shapes_counted'
    Assert-Equal 1 $junit.Passed 'junit_passed_counted'
    Assert-Equal 1 $junit.Failed 'junit_failed_counted'
    Assert-Equal 1 $junit.Skipped 'junit_skipped_counted'
    Assert-Equal 'qa.Two' $junit.FailedClasses[0] 'junit_failed_class_comes_from_testcase'
    Assert-Equal 'qa.Two#fails' $junit.FailedMethods[0] 'junit_failed_method_reported'

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
    $instrumentationText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'run_beta1_instrumentation.ps1')
    Assert-True ($instrumentationText -match 'source_test_methods') 'instrumentation_source_count_reported'
    Assert-True ($instrumentationText -match 'postRunSelected') 'instrumentation_device_identity_rechecked'
    Assert-True ($instrumentationText.Contains("'--project-dir', `$androidRoot")) 'instrumentation_gradle_project_dir_fixed'
    Assert-True ($instrumentationText -match 'instrumentation-history' -and $instrumentationText -match 'Move-Item') 'instrumentation_prior_reports_archived'
    $testPackageRegexLine = @($instrumentationText -split "`r?`n" | Where-Object { $_ -match '^\s*\$testMatch = ' } | Select-Object -First 1)
    Assert-True ($testPackageRegexLine.Count -eq 1 -and $testPackageRegexLine[0] -match "package: name" -and $testPackageRegexLine[0] -notmatch 'versionCode') 'test_apk_allows_empty_version_fields'
    Assert-True ($instrumentationText -match 'test_apk_target_package_mismatch' -and $instrumentationText -notmatch 'expected_debug_package_not_installed') 'test_target_verified_without_post_run_install_assumption'
    $createAvdText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'create_disposable_avd.ps1')
    Assert-True ($createAvdText -match "'dumpsys', 'account'" -and $createAvdText -notmatch 'cmd account list') 'android_16_account_inventory_supported'
    Assert-True ($createAvdText -match "'emu', 'kill'" -and $createAvdText -match 'failed_avd_stop_timeout') 'failed_boot_uses_owned_adb_cleanup'
    $qaReportText = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot 'beta1_qa_report.ps1')
    Assert-True ($qaReportText -match '1093d4d14c7aa52f180ed7d1ba17cea5437dc896') 'qa_report_expected_head_current'
    foreach ($scriptName in @('create_disposable_avd.ps1', 'delete_disposable_avd.ps1', 'run_beta1_mariadb.ps1')) {
        $mutatingScript = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot $scriptName)
        Assert-True ($mutatingScript -match '(?s)try\s*\{.*finally\s*\{') ("try_finally_present_" + $scriptName)
    }
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
