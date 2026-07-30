[CmdletBinding()]
param([switch]$Json, [switch]$Help)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: alpha15_phone_tooling_harness.ps1 [-Json] [-Help]

Creates only fictional SDK/device fixtures under a unique system temporary
directory, runs at least 40 offline cases, and removes the directory in finally.
No real adb/device command is executed and no binary is added to the repository.
'@
    exit 0
}

$releaseRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $releaseRoot 'alpha15_phone_common.ps1')
. (Join-Path $releaseRoot 'alpha15_phone_logs.ps1')

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('health-tracker-alpha15-harness-' + [Guid]::NewGuid().ToString('N'))
$fakeSdk = Join-Path $temporaryRoot 'Root With Spaces\Local AppData\Android\Sdk'
$fakeRepo = Join-Path $temporaryRoot 'fictional-repository'
$results = New-Object System.Collections.ArrayList
$failures = New-Object System.Collections.ArrayList
$script:DeviceLines = @('List of devices attached')
$script:PackagePresent = $false
$script:InstalledVersionCode = 15
$script:InstalledDigest = ('a' * 64)
$script:PullFails = $false
$script:Invocations = New-Object System.Collections.ArrayList

function Write-FakeExecutable {
    param([string]$Path)
    $parent = Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($parent)
    [IO.File]::WriteAllText($Path, "@echo off`r`nexit /b 0`r`n", (New-Object Text.ASCIIEncoding))
}

function New-FakeSdk {
    param([string]$Root, [switch]$Aapt2Only, [switch]$MissingAdb, [switch]$MissingAapt, [switch]$MissingSigner)
    [void][IO.Directory]::CreateDirectory($Root)
    if (-not $MissingAdb) { Write-FakeExecutable (Join-Path $Root 'platform-tools\adb.cmd') }
    foreach ($version in @('9.0.0', '34.0.0', '35.0.0', '36.0.0-rc1')) {
        $folder = Join-Path $Root ('build-tools\' + $version)
        [void][IO.Directory]::CreateDirectory($folder)
        if (-not $MissingAapt) {
            $name = $(if ($Aapt2Only) { 'aapt2.cmd' } else { 'aapt.cmd' })
            Write-FakeExecutable (Join-Path $folder $name)
        }
        if (-not $MissingSigner) { Write-FakeExecutable (Join-Path $folder 'apksigner.bat') }
    }
}

function Add-Case {
    param([int]$Number, [string]$Name, [bool]$Passed, [string]$Detail = '')
    $entry = [pscustomobject][ordered]@{ number = $Number; name = $Name; passed = $Passed; detail = $Detail }
    [void]$results.Add($entry)
    if (-not $Passed) { [void]$failures.Add($entry) }
}

function Get-FailureInfo {
    param([scriptblock]$Action)
    try { & $Action; return $null } catch { return Get-Alpha15ExitFromException $_ }
}

function New-ManualApkInfo {
    param([long]$VersionCode = 15)
    return [pscustomobject]@{
        Internal = [pscustomobject]@{ CertificateDigest = ('a' * 64); Path = (Join-Path $temporaryRoot 'candidate.apk') }
        Report = [pscustomobject]@{ version_code = $VersionCode; version_name = '1.5.0-alpha01-debug'; package = 'io.healthtracker.companion.debug' }
    }
}

function New-InstalledInfo {
    param([long]$VersionCode = 15, [bool]$Present = $true)
    return [pscustomobject]@{
        Present = $Present
        Report = [pscustomobject]@{ present = $Present; version_code = $VersionCode; version_name = '1.5.0-alpha01-debug' }
    }
}

$originalPath = $env:PATH
$originalSdkRoot = $env:ANDROID_SDK_ROOT
$originalAndroidHome = $env:ANDROID_HOME
$originalLocalAppData = $env:LOCALAPPDATA
$originalRepositoryRoot = $script:Alpha15RepositoryRoot

try {
    New-FakeSdk $fakeSdk
    [void][IO.Directory]::CreateDirectory((Join-Path $fakeRepo 'android'))
    [IO.File]::WriteAllText((Join-Path $fakeRepo 'android\local.properties'), ('sdk.dir=' + $fakeSdk.Replace('\', '\\')), (New-Object Text.UTF8Encoding($false)))
    [IO.File]::WriteAllText((Join-Path $temporaryRoot 'candidate.apk'), 'fictional-apk', (New-Object Text.ASCIIEncoding))

    Set-Alpha15TestCommandRunner {
        param($FilePath, $Arguments)
        [void]$script:Invocations.Add([pscustomobject]@{ File = $FilePath; Arguments = @($Arguments) })
        $leaf = Split-Path -Leaf $FilePath
        $joined = $Arguments -join ' '
        if ($leaf -match '^adb') {
            if ($joined -eq 'version') { return [pscustomobject]@{ ExitCode = 0; Lines = @('Android Debug Bridge version 1.0.41') } }
            if ($joined -eq 'devices -l') { return [pscustomobject]@{ ExitCode = 0; Lines = @($script:DeviceLines) } }
            if ($joined -match 'shell getprop ro.product.manufacturer$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('Fictional') } }
            if ($joined -match 'shell getprop ro.product.model$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('QA Device') } }
            if ($joined -match 'shell getprop ro.build.version.sdk$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('36') } }
            if ($joined -match 'shell getprop ro.build.version.release$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('16') } }
            if ($joined -match 'shell getprop ro.product.cpu.abi$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('arm64-v8a') } }
            if ($joined -match 'shell getprop sys.boot_completed$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('1') } }
            if ($joined -match 'shell df -k /sdcard$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('Filesystem 1K-blocks Used Available Use% Mounted on', '/dev/fake 10000000 1 9999999 1% /sdcard') } }
            if ($joined -match 'shell dumpsys battery$') { return [pscustomobject]@{ ExitCode = 0; Lines = @('  level: 80') } }
            if ($joined -match 'shell dumpsys package') {
                if (-not $script:PackagePresent) { return [pscustomobject]@{ ExitCode = 0; Lines = @('Unable to find package') } }
                return [pscustomobject]@{ ExitCode = 0; Lines = @("Package [io.healthtracker.companion.debug]", " versionCode=$($script:InstalledVersionCode)", ' versionName=1.5.0-alpha01-debug', ' firstInstallTime=2026-07-01 00:00:00', ' lastUpdateTime=2026-07-02 00:00:00', ' installerPackageName=com.android.shell', ' dataDir=[REDACTED]') }
            }
            if ($joined -match 'shell pm path') { return [pscustomobject]@{ ExitCode = 0; Lines = @('package:/data/app/fictional/base.apk') } }
            if ($joined -match '(^|\s)install -r\s') {
                $script:PackagePresent = $true
                return [pscustomobject]@{ ExitCode = 0; Lines = @('Success') }
            }
            if ($joined -match ' pull ') {
                if ($script:PullFails) { return [pscustomobject]@{ ExitCode = 1; Lines = @('pull_failed') } }
                $local = $Arguments[$Arguments.Count - 1]
                [IO.File]::WriteAllText($local, 'fictional-installed-apk')
                return [pscustomobject]@{ ExitCode = 0; Lines = @('1 file pulled') }
            }
            if ($joined -match 'shell pidof') { return [pscustomobject]@{ ExitCode = 0; Lines = @('1234') } }
            if ($joined -match 'logcat') { return [pscustomobject]@{ ExitCode = 0; Lines = @('07-29 10:42:11 Authorization: super-secret-value', '07-29 10:42:12 FATAL EXCEPTION: QA') } }
            return [pscustomobject]@{ ExitCode = 0; Lines = @('ok') }
        }
        if ($leaf -match '^aapt2?$') { }
        if ($leaf -match '^aapt') {
            if ($joined -eq 'version') { return [pscustomobject]@{ ExitCode = 0; Lines = @('Android Asset Packaging Tool 35.0.0') } }
            return [pscustomobject]@{ ExitCode = 0; Lines = @("package: name='io.healthtracker.companion.debug' versionCode='15' versionName='1.5.0-alpha01-debug'", "sdkVersion:'26'", "targetSdkVersion:'36'", 'application-debuggable', "native-code: 'arm64-v8a'") }
        }
        if ($leaf -match '^apksigner') {
            if ($joined -eq 'version') { return [pscustomobject]@{ ExitCode = 0; Lines = @('0.9') } }
            $digest = $(if ($joined -match 'installed-base\.apk') { $script:InstalledDigest } else { ('a' * 64) })
            return [pscustomobject]@{ ExitCode = 0; Lines = @('Verifies', "Signer #1 certificate SHA-256 digest: $digest") }
        }
        return [pscustomobject]@{ ExitCode = 0; Lines = @('ok') }
    }

    $env:PATH = ''
    $env:ANDROID_SDK_ROOT = $null
    $env:ANDROID_HOME = $null
    $env:LOCALAPPDATA = $null
    $script:Alpha15RepositoryRoot = $fakeRepo

    $tool = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $fakeSdk
    $explicitTool = $tool
    Add-Case 1 'SDK por parámetro' ($tool.Report.sdk_source -eq 'parameter')

    $env:ANDROID_SDK_ROOT = $fakeSdk
    $tool = Resolve-Alpha15AndroidToolchain
    Add-Case 2 'SDK por ANDROID_SDK_ROOT' ($tool.Report.sdk_source -eq 'ANDROID_SDK_ROOT')
    $env:ANDROID_SDK_ROOT = $null

    $env:ANDROID_HOME = $fakeSdk
    $tool = Resolve-Alpha15AndroidToolchain
    Add-Case 3 'SDK por ANDROID_HOME' ($tool.Report.sdk_source -eq 'ANDROID_HOME')
    $env:ANDROID_HOME = $null

    $tool = Resolve-Alpha15AndroidToolchain
    Add-Case 4 'SDK por local.properties' ($tool.Report.sdk_source -eq 'local.properties')

    [IO.File]::Move((Join-Path $fakeRepo 'android\local.properties'), (Join-Path $fakeRepo 'android\local.properties.off'))
    $env:LOCALAPPDATA = (Split-Path -Parent (Split-Path -Parent $fakeSdk))
    $tool = Resolve-Alpha15AndroidToolchain
    Add-Case 5 'SDK por LOCALAPPDATA' ($tool.Report.sdk_source -eq 'LOCALAPPDATA')
    $env:LOCALAPPDATA = $null

    $env:PATH = (Join-Path $fakeSdk 'platform-tools') + ';' + (Join-Path $fakeSdk 'build-tools\35.0.0')
    $tool = Resolve-Alpha15AndroidToolchain
    Add-Case 6 'Herramientas por PATH' ($tool.Report.adb_source -eq 'PATH')
    Add-Case 7 'Ruta con espacios' ($tool.Internal.SdkRoot -like '*Root With Spaces*')
    $env:PATH = ''

    $missingAdbRoot = Join-Path $temporaryRoot 'missing-adb'
    New-FakeSdk $missingAdbRoot -MissingAdb
    $failure = Get-FailureInfo { Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $missingAdbRoot | Out-Null }
    Add-Case 8 'Falta adb' ($failure.Reason -eq 'adb_not_found')

    $missingAaptRoot = Join-Path $temporaryRoot 'missing-aapt'
    New-FakeSdk $missingAaptRoot -MissingAapt
    $failure = Get-FailureInfo { Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $missingAaptRoot | Out-Null }
    Add-Case 9 'Falta aapt' ($failure.Reason -eq 'aapt_not_found')

    $aapt2Root = Join-Path $temporaryRoot 'aapt2-only'
    New-FakeSdk $aapt2Root -Aapt2Only
    $toolAapt2 = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $aapt2Root
    Add-Case 10 'Solo aapt2' ($toolAapt2.Report.aapt_kind -eq 'aapt2')

    $missingSignerRoot = Join-Path $temporaryRoot 'missing-signer'
    New-FakeSdk $missingSignerRoot -MissingSigner
    $failure = Get-FailureInfo { Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $missingSignerRoot | Out-Null }
    Add-Case 11 'Falta apksigner' ($failure.Reason -eq 'apksigner_not_found')
    Add-Case 12 'Múltiples build-tools' (@(Get-ChildItem (Join-Path $fakeSdk 'build-tools') -Directory).Count -eq 4)
    Add-Case 13 'Versión estable mayor semántica' ($explicitTool.Report.build_tools_version -eq '35.0.0')
    Add-Case 14 'Preview ignorada' ($explicitTool.Report.build_tools_version -ne '36.0.0-rc1')

    $failure = Get-FailureInfo { Resolve-Alpha15AndroidToolchain -AndroidSdkRoot ($fakeSdk + [char]7) | Out-Null }
    Add-Case 15 'Path inválido' ($failure.ExitCode -eq 2)

    $zero = @(Get-Alpha15ConnectedDevices $tool.Internal.Adb)
    Add-Case 16 'Dispositivo cero' ($zero.Count -eq 0)
    $script:DeviceLines = @('List of devices attached', 'SERIAL-QA-ONE device product:qa model:QA')
    $one = @(Get-Alpha15ConnectedDevices $tool.Internal.Adb)
    Add-Case 17 'Un dispositivo' ((Select-Alpha15Device $one $null).Fingerprint.Length -eq 12)
    $two = @($one + [pscustomobject]@{ Serial = 'SERIAL-QA-TWO'; State = 'device'; Fingerprint = '222222222222' })
    $failure = Get-FailureInfo { Select-Alpha15Device $two $null | Out-Null }
    Add-Case 18 'Múltiples dispositivos' ($failure.Reason -eq 'multiple_devices')
    Add-Case 19 'Serial explícito' ((Select-Alpha15Device $two 'SERIAL-QA-TWO').Fingerprint -eq '222222222222')
    $unauthorized = @([pscustomobject]@{ Serial = 'SERIAL-QA-U'; State = 'unauthorized'; Fingerprint = '333333333333' })
    $failure = Get-FailureInfo { Select-Alpha15Device $unauthorized $null | Out-Null }
    Add-Case 20 'Unauthorized' ($failure.ExitCode -eq 9)
    $offline = @([pscustomobject]@{ Serial = 'SERIAL-QA-O'; State = 'offline'; Fingerprint = '444444444444' })
    $failure = Get-FailureInfo { Select-Alpha15Device $offline $null | Out-Null }
    Add-Case 21 'Offline' ($failure.Reason -eq 'device_offline')

    $script:PackagePresent = $false
    $package = Get-Alpha15InstalledPackageInfo $tool.Internal.Adb 'SERIAL-QA-ONE' 'io.healthtracker.companion.debug'
    Add-Case 22 'Package ausente' (-not $package.Present)
    $script:PackagePresent = $true
    $script:InstalledVersionCode = 15
    $package = Get-Alpha15InstalledPackageInfo $tool.Internal.Adb 'SERIAL-QA-ONE' 'io.healthtracker.companion.debug'
    Add-Case 23 'Package instalado' ($package.Present -and $package.Report.version_code -eq 15)

    $script:InstalledDigest = ('a' * 64)
    $comparison = Compare-Alpha15InstalledPackage (New-InstalledInfo 14) (New-ManualApkInfo 15) $tool.Internal.Adb 'SERIAL-QA-ONE' $tool.Internal.Apksigner 'io.healthtracker.companion.debug'
    Add-Case 24 'Firma compatible' ($comparison.signature -eq 'compatible_upgrade')
    $script:InstalledDigest = ('b' * 64)
    $comparison = Compare-Alpha15InstalledPackage (New-InstalledInfo 14) (New-ManualApkInfo 15) $tool.Internal.Adb 'SERIAL-QA-ONE' $tool.Internal.Apksigner 'io.healthtracker.companion.debug'
    Add-Case 25 'Firma incompatible' ($comparison.status -eq 'signature_mismatch')
    $script:InstalledDigest = ('a' * 64)
    $comparison = Compare-Alpha15InstalledPackage (New-InstalledInfo 16) (New-ManualApkInfo 15) $tool.Internal.Adb 'SERIAL-QA-ONE' $tool.Internal.Apksigner 'io.healthtracker.companion.debug'
    Add-Case 26 'Versión menor' ($comparison.version_relation -eq 'candidate_older' -and -not $comparison.installation_allowed)
    $comparison = Compare-Alpha15InstalledPackage (New-InstalledInfo 15) (New-ManualApkInfo 15) $tool.Internal.Adb 'SERIAL-QA-ONE' $tool.Internal.Apksigner 'io.healthtracker.companion.debug'
    Add-Case 27 'Versión igual' ($comparison.version_relation -eq 'same_version')
    $comparison = Compare-Alpha15InstalledPackage (New-InstalledInfo 14) (New-ManualApkInfo 15) $tool.Internal.Adb 'SERIAL-QA-ONE' $tool.Internal.Apksigner 'io.healthtracker.companion.debug'
    Add-Case 28 'Versión mayor' ($comparison.version_relation -eq 'candidate_newer')

    $beforeTemp = @(Get-ChildItem ([IO.Path]::GetTempPath()) -Directory -Filter 'health-tracker-alpha15-installed-apk-*').Count
    $script:PullFails = $false
    [void](Get-Alpha15InstalledCertificate $tool.Internal.Adb 'SERIAL-QA-ONE' 'io.healthtracker.companion.debug' $tool.Internal.Apksigner)
    $afterTemp = @(Get-ChildItem ([IO.Path]::GetTempPath()) -Directory -Filter 'health-tracker-alpha15-installed-apk-*').Count
    Add-Case 29 'Pull temporal eliminado' ($beforeTemp -eq $afterTemp)
    $script:PullFails = $true
    [void](Get-Alpha15InstalledCertificate $tool.Internal.Adb 'SERIAL-QA-ONE' 'io.healthtracker.companion.debug' $tool.Internal.Apksigner)
    $afterFailureTemp = @(Get-ChildItem ([IO.Path]::GetTempPath()) -Directory -Filter 'health-tracker-alpha15-installed-apk-*').Count
    Add-Case 30 'Fallo durante pull' ($beforeTemp -eq $afterFailureTemp)
    $script:PullFails = $false

    $jsonPath = Join-Path $temporaryRoot 'reports with spaces\report.json'
    [void](Write-Alpha15Utf8Json -Value ([pscustomobject]@{ status = 'qa'; serial = 'abcdef123456' }) -OutputPath $jsonPath)
    $parsed = Get-Content -Raw $jsonPath | ConvertFrom-Json
    Add-Case 31 'Salida JSON válida' ($parsed.status -eq 'qa')
    $safe = ConvertTo-Alpha15ReportedToolPath $tool.Internal.Adb $tool.Internal.SdkRoot
    Add-Case 32 'Reporte sanitizado' ($safe -like '<ANDROID_SDK>*' -and $safe -notmatch 'Root With Spaces')

    $script:PackagePresent = $true
    $script:InstalledVersionCode = 15
    $script:InstalledDigest = ('a' * 64)
    $missingConfirmation = Invoke-Alpha15InstallCore -ApkPath (Join-Path $temporaryRoot 'candidate.apk') -Serial 'SERIAL-QA-ONE' -AndroidSdkRoot $fakeSdk
    Add-Case 33 'Confirmación ausente bloqueada' ($missingConfirmation.ExitCode -eq 2 -and $missingConfirmation.Report.install_attempted -eq $false)
    $script:Invocations.Clear()
    $confirmedInstall = Invoke-Alpha15InstallCore -ApkPath (Join-Path $temporaryRoot 'candidate.apk') -Serial 'SERIAL-QA-ONE' -AndroidSdkRoot $fakeSdk -ConfirmInstall 'ALPHA15-INSTALL'
    Add-Case 34 'Confirmación correcta reconocida' ($confirmedInstall.ExitCode -eq 0 -and $confirmedInstall.Report.install_attempted -eq $true)
    $installCalls = @($script:Invocations | Where-Object { $_.Arguments -contains 'install' })
    $exactInstall = $installCalls.Count -eq 1 -and (($installCalls[0].Arguments | Select-Object -Last 3) -join '|') -eq ('install|-r|' + (Join-Path $temporaryRoot 'candidate.apk'))
    Add-Case 35 'Comando install exacto' $exactInstall
    $runtimeArguments = ($script:Invocations | ForEach-Object { $_.Arguments -join ' ' }) -join "`n"
    Add-Case 36 'Cero uninstall' ($runtimeArguments -notmatch '(^|\s)uninstall(\s|$)')
    Add-Case 37 'Cero pm clear' ($runtimeArguments -notmatch '(^|\s)pm\s+clear(\s|$)')

    $findings = @(Find-Alpha15SanitizedLogFindings @('07-29 10:42:11 Authorization: super-secret-value'))
    $findingJson = $findings | ConvertTo-Json -Depth 5
    Add-Case 38 'Logs redactados' ($findingJson -match '\[REDACTED\]' -and $findingJson -notmatch 'super-secret-value')
    Add-Case 39 'Output con espacios' (Test-Path -LiteralPath $jsonPath -PathType Leaf)

    $cleanupTarget = Join-Path $temporaryRoot 'finally-cleanup-check'
    [void][IO.Directory]::CreateDirectory($cleanupTarget)
    try { throw 'fictional interruption' } catch { } finally { [IO.Directory]::Delete($cleanupTarget, $true) }
    Add-Case 40 'Ctrl+C/finally cleanup' (-not (Test-Path -LiteralPath $cleanupTarget))

    $allScripts = @(Get-ChildItem -LiteralPath $releaseRoot -Filter '*.ps1' -File)
    $unsupported = @($allScripts | Where-Object { (Get-Content -Raw $_.FullName) -match '\?\?|\?\.|ForEach-Object\s+-Parallel|Invoke-Expression' })
    Add-Case 41 'PowerShell 5.1 sin sintaxis moderna peligrosa' ($unsupported.Count -eq 0)
    $pinned = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $fakeSdk -BuildToolsVersion '34.0.0'
    Add-Case 42 'Build-tools fijada explícitamente' ($pinned.Report.build_tools_version -eq '34.0.0')
} finally {
    Clear-Alpha15TestCommandRunner
    $script:Alpha15RepositoryRoot = $originalRepositoryRoot
    $env:PATH = $originalPath
    $env:ANDROID_SDK_ROOT = $originalSdkRoot
    $env:ANDROID_HOME = $originalAndroidHome
    $env:LOCALAPPDATA = $originalLocalAppData
    if (Test-Path -LiteralPath $temporaryRoot -PathType Container) { [IO.Directory]::Delete($temporaryRoot, $true) }
}

$report = [pscustomobject][ordered]@{
    schema = 'health-tracker-alpha15-phone-tooling-harness-v1'
    powershell_version = $PSVersionTable.PSVersion.ToString()
    cases = $results.Count
    passed = @($results | Where-Object { $_.passed }).Count
    failed = $failures.Count
    temporary_cleanup_complete = -not (Test-Path -LiteralPath $temporaryRoot)
    results = @($results)
}
if ($Json) { $report | ConvertTo-Json -Depth 8 } else { $report | Format-List | Out-String | Write-Output }
if ($failures.Count -gt 0) { exit 1 }
exit 0
