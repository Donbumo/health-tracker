[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)][string]$SessionId,
    [string]$SdkRoot,
    [string]$ProjectRoot,
    [string]$ReportRoot,
    [string]$TestClass,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: run_beta1_instrumentation.ps1 -SessionId <id> [-SdkRoot <path>]
       [-ProjectRoot <repo>] [-ReportRoot <path>] [-TestClass <fully.qualified.Class>] [-Help]
Runs connectedDebugAndroidTest only when exactly one authorized device exists and it is
the disposable AVD recorded for this session. Physical/remote devices are always rejected.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
if (-not $SessionId) { [Console]::Error.WriteLine('SessionId is required.'); exit 2 }
if (-not $ProjectRoot) { $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path }
else { $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path }

$SessionId = Get-Beta1SessionId $SessionId
$expectedAvd = Get-Beta1AvdName $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$metadataPath = Join-Path $sessionRoot 'avd.json'
$reportPath = Join-Path $sessionRoot 'instrumentation.json'
$logPath = Join-Path $sessionRoot 'instrumentation.log'
$resultRoot = Join-Path $sessionRoot 'instrumentation-results'
$previousSerial = [Environment]::GetEnvironmentVariable('ANDROID_SERIAL')
$previousAvdHome = [Environment]::GetEnvironmentVariable('ANDROID_AVD_HOME')
$startedAt = [DateTime]::UtcNow
$gradleExit = $null
$selected = $null

try {
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) { throw 'session_metadata_missing' }
    $metadata = Get-Content -Raw -Encoding UTF8 -LiteralPath $metadataPath | ConvertFrom-Json
    if ($metadata.session_id -ne $SessionId -or $metadata.avd_name -ne $expectedAvd) { throw 'session_metadata_mismatch' }

    $resolvedSdk = Resolve-Beta1SdkRoot $SdkRoot $ProjectRoot
    $adb = Find-Beta1AndroidTool $resolvedSdk 'platform-tools' 'adb'
    try { $aapt = Find-Beta1AndroidTool $resolvedSdk 'build-tools' 'aapt' }
    catch { $aapt = Find-Beta1AndroidTool $resolvedSdk 'build-tools' 'aapt2' }
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', (Join-Path $sessionRoot 'avd-home'))
    $selected = Select-Beta1DisposableDevice (Add-Beta1AvdNames $adb (Get-Beta1ConnectedDevices $adb)) $expectedAvd
    [Environment]::SetEnvironmentVariable('ANDROID_SERIAL', $selected.Serial)

    $androidRoot = Join-Path $ProjectRoot 'android'
    $gradle = Join-Path $androidRoot 'gradlew.bat'
    if (-not (Test-Path -LiteralPath $gradle -PathType Leaf)) { throw 'gradle_wrapper_missing' }
    $arguments = @(':app:connectedDebugAndroidTest', '--no-parallel', '--stacktrace')
    if ($TestClass) { $arguments += "-Pandroid.testInstrumentationRunnerArguments.class=$TestClass" }
    $rawOutput = @(& $gradle @arguments 2>&1)
    $gradleExit = $LASTEXITCODE
    $safeOutput = ($rawOutput -join [Environment]::NewLine) -replace [regex]::Escape($selected.Serial), "emulator-fp:$($selected.Fingerprint)"
    [IO.File]::WriteAllText($logPath, $safeOutput + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
    Write-Output $safeOutput

    $targetApk = Join-Path $androidRoot 'app\build\outputs\apk\debug\app-debug.apk'
    $testApk = Join-Path $androidRoot 'app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk'
    if (-not (Test-Path -LiteralPath $targetApk -PathType Leaf) -or -not (Test-Path -LiteralPath $testApk -PathType Leaf)) {
        throw 'instrumentation_apk_missing'
    }
    $targetBadging = (& $aapt dump badging $targetApk 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'target_apk_inspection_failed' }
    $targetMatch = [regex]::Match($targetBadging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
    if (-not $targetMatch.Success) { throw 'target_apk_metadata_missing' }
    Test-Beta1ApkIdentity $targetMatch.Groups[1].Value ([long]$targetMatch.Groups[2].Value)
    $testBadging = (& $aapt dump badging $testApk 2>&1) -join "`n"
    $testMatch = [regex]::Match($testBadging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
    if ($LASTEXITCODE -ne 0 -or -not $testMatch.Success -or $testMatch.Groups[1].Value -ne 'io.healthtracker.companion.debug.test') {
        throw 'test_apk_package_mismatch'
    }

    $installed = ((& $adb -s $selected.Serial shell pm list packages io.healthtracker.companion.debug 2>$null) -join '').Trim()
    if ($installed -notmatch 'package:io\.healthtracker\.companion\.debug') { throw 'expected_debug_package_not_installed' }

    New-Item -ItemType Directory -Path $resultRoot -Force | Out-Null
    $sourceResults = Join-Path $androidRoot 'app\build\outputs\androidTest-results'
    $xmlFiles = @()
    if (Test-Path -LiteralPath $sourceResults -PathType Container) {
        foreach ($file in Get-ChildItem -LiteralPath $sourceResults -Filter '*.xml' -File -Recurse) {
            $destination = Join-Path $resultRoot $file.Name
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
            $xmlFiles += $destination
        }
    }
    $total = 0; $failed = 0; $skipped = 0; $errors = 0; $failedClasses = @()
    foreach ($path in $xmlFiles) {
        [xml]$document = Get-Content -Raw -Encoding UTF8 -LiteralPath $path
        foreach ($suite in @($document.testsuites.testsuite) + @($document.testsuite)) {
            if ($null -eq $suite -or -not $suite.tests) { continue }
            $total += [int]$suite.tests
            $failed += [int]$suite.failures
            $errors += [int]$suite.errors
            $skipped += [int]$suite.skipped
            if ([int]$suite.failures + [int]$suite.errors -gt 0) { $failedClasses += [string]$suite.name }
        }
    }
    $passed = $total - $failed - $errors - $skipped
    $report = [ordered]@{
        schema = 'health-tracker-beta1-instrumentation-v1'
        session_id = $SessionId
        avd_name = $expectedAvd
        serial_fingerprint = $selected.Fingerprint
        device_kind = 'disposable-emulator'
        package = $targetMatch.Groups[1].Value
        version_code = [long]$targetMatch.Groups[2].Value
        version_name = $targetMatch.Groups[3].Value
        target_apk_sha256 = (Get-FileHash -LiteralPath $targetApk -Algorithm SHA256).Hash.ToLowerInvariant()
        test_apk_sha256 = (Get-FileHash -LiteralPath $testApk -Algorithm SHA256).Hash.ToLowerInvariant()
        total = $total
        passed = $passed
        skipped = $skipped
        failed = $failed + $errors
        failed_classes = @($failedClasses | Select-Object -Unique)
        gradle_exit_code = $gradleExit
        result_xml_files = $xmlFiles.Count
        duration_seconds = [math]::Round(([DateTime]::UtcNow - $startedAt).TotalSeconds, 3)
        completed_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Beta1Json $report $reportPath
    if ($gradleExit -ne 0 -or $report.failed -gt 0 -or $total -eq 0) { throw 'instrumentation_failed_or_empty' }
    Write-Output "Instrumentation passed on ${expectedAvd}: $passed passed, $skipped skipped, 0 failed."
    exit 0
} catch {
    if (-not (Test-Path -LiteralPath $reportPath)) {
        Write-Beta1Json ([ordered]@{
            schema = 'health-tracker-beta1-instrumentation-v1'
            session_id = $SessionId
            avd_name = $expectedAvd
            serial_fingerprint = if ($selected) { $selected.Fingerprint } else { $null }
            status = 'blocked_or_failed'
            error_code = $_.Exception.Message
            gradle_exit_code = $gradleExit
            completed_at_utc = [DateTime]::UtcNow.ToString('o')
        }) $reportPath
    }
    [Console]::Error.WriteLine("Beta 1 instrumentation refused or failed: " + $_.Exception.Message)
    if ($_.Exception.Message -match 'physical_device|ambiguous|identity|metadata') { exit 2 }
    exit 4
} finally {
    [Environment]::SetEnvironmentVariable('ANDROID_SERIAL', $previousSerial)
    [Environment]::SetEnvironmentVariable('ANDROID_AVD_HOME', $previousAvdHome)
}
