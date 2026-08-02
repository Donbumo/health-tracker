[CmdletBinding()]
param([switch]$Help)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: dot-source alpha20_beta1_common.ps1
Shared PowerShell 5.1 helpers for disposable Beta 1 Android QA. This file does not
create, start, stop, install, or delete resources by itself.
'@
    exit 0
}

function Get-Beta1SessionId {
    param([string]$Value)
    if ($Value) {
        if ($Value -notmatch '^[a-z0-9][a-z0-9-]{5,47}$') { throw 'session_id_invalid' }
        return $Value
    }
    return ([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
}

function Get-Beta1AvdName {
    param([Parameter(Mandatory = $true)][string]$SessionId)
    return "health-tracker-beta1-qa-$SessionId"
}

function Get-Beta1ReportRoot {
    $temporary = [IO.Path]::GetTempPath()
    return (Join-Path $temporary 'health-tracker-beta1')
}

function Get-Beta1SessionRoot {
    param(
        [Parameter(Mandatory = $true)][string]$SessionId,
        [string]$ReportRoot
    )
    if (-not $ReportRoot) { $ReportRoot = Get-Beta1ReportRoot }
    return (Join-Path $ReportRoot $SessionId)
}

function Write-Beta1Json {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Depth = 8
    )
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))
}

function Get-Beta1TextFingerprint {
    param([Parameter(Mandatory = $true)][string]$Value)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        $hash = $algorithm.ComputeHash($bytes)
        return (([BitConverter]::ToString($hash) -replace '-', '').Substring(0, 8).ToLowerInvariant())
    } finally {
        $algorithm.Dispose()
    }
}

function Resolve-Beta1SdkRoot {
    param(
        [string]$ExplicitSdkRoot,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($ExplicitSdkRoot) { $candidates.Add($ExplicitSdkRoot) }
    $sdkEnvironment = [Environment]::GetEnvironmentVariable('ANDROID_SDK_ROOT')
    if ($sdkEnvironment) { $candidates.Add($sdkEnvironment) }
    $homeEnvironment = [Environment]::GetEnvironmentVariable('ANDROID_HOME')
    if ($homeEnvironment) { $candidates.Add($homeEnvironment) }
    $propertiesPath = Join-Path $ProjectRoot 'android\local.properties'
    if (Test-Path -LiteralPath $propertiesPath -PathType Leaf) {
        $line = Get-Content -LiteralPath $propertiesPath -Encoding UTF8 |
            Where-Object { $_ -match '^sdk\.dir=' } | Select-Object -First 1
        if ($line) {
            $fromProperties = ($line -replace '^sdk\.dir=', '') -replace '\\\\', '\'
            if ($fromProperties) { $candidates.Add($fromProperties) }
        }
    }
    $localApplicationData = [Environment]::GetFolderPath('LocalApplicationData')
    if ($localApplicationData) { $candidates.Add((Join-Path $localApplicationData 'Android\Sdk')) }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'android_sdk_not_found'
}

function Find-Beta1AndroidTool {
    param(
        [Parameter(Mandatory = $true)][string]$SdkRoot,
        [Parameter(Mandatory = $true)][ValidateSet('platform-tools', 'emulator', 'cmdline-tools', 'build-tools')][string]$Area,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $fileNames = if ($Name.EndsWith('.bat') -or $Name.EndsWith('.exe')) {
        @($Name)
    } elseif ($Area -eq 'cmdline-tools') {
        @("$Name.exe", "$Name.bat", $Name)
    } elseif ($Area -eq 'build-tools') {
        @("$Name.exe", "$Name.bat")
    } else {
        @($Name + '.exe')
    }
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Area -eq 'platform-tools' -or $Area -eq 'emulator') {
        foreach ($fileName in $fileNames) { $candidates.Add((Join-Path (Join-Path $SdkRoot $Area) $fileName)) }
    } elseif ($Area -eq 'cmdline-tools') {
        $root = Join-Path $SdkRoot 'cmdline-tools'
        if (Test-Path -LiteralPath $root -PathType Container) {
            Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | ForEach-Object {
                foreach ($fileName in $fileNames) { $candidates.Add((Join-Path (Join-Path $_.FullName 'bin') $fileName)) }
            }
        }
        foreach ($fileName in $fileNames) { $candidates.Add((Join-Path (Join-Path (Join-Path $SdkRoot 'tools') 'bin') $fileName)) }
    } else {
        $root = Join-Path $SdkRoot 'build-tools'
        if (Test-Path -LiteralPath $root -PathType Container) {
            Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | ForEach-Object {
                foreach ($fileName in $fileNames) { $candidates.Add((Join-Path $_.FullName $fileName)) }
            }
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "android_tool_not_found:$Area/$Name"
}

function Invoke-Beta1NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [AllowNull()][object[]]$InputObject = $null
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($null -eq $InputObject) {
            $output = @(& $FilePath @Arguments 2>&1)
        } else {
            $output = @($InputObject | & $FilePath @Arguments 2>&1)
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output | ForEach-Object { $_.ToString() })
    }
}

function Get-Beta1SystemImages {
    param([Parameter(Mandatory = $true)][string]$SdkRoot)
    $root = Join-Path $SdkRoot 'system-images'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    $images = @()
    foreach ($platform in Get-ChildItem -LiteralPath $root -Directory) {
        if ($platform.Name -notmatch '^android-(\d+)(?:\.\d+)?$') { continue }
        $api = [int]$Matches[1]
        foreach ($tag in Get-ChildItem -LiteralPath $platform.FullName -Directory) {
            foreach ($abi in Get-ChildItem -LiteralPath $tag.FullName -Directory) {
                $images += [pscustomobject]@{
                    Api = $api
                    Platform = $platform.Name
                    Tag = $tag.Name
                    Abi = $abi.Name
                    Package = "system-images;$($platform.Name);$($tag.Name);$($abi.Name)"
                    Path = $abi.FullName
                }
            }
        }
    }
    return @($images)
}

function Select-Beta1SystemImage {
    param(
        [Parameter(Mandatory = $true)][object[]]$Images,
        [int]$ApiLevel = 0,
        [string]$Abi = 'x86_64'
    )
    $eligible = @($Images | Where-Object {
        $expectedPackage = "system-images;android-$($_.Api);google_apis;x86_64"
        $_.Api -in @(36, 35) -and
        $_.Platform -eq "android-$($_.Api)" -and
        $_.Tag -eq 'google_apis' -and
        $_.Abi -eq 'x86_64' -and
        $_.Abi -eq $Abi -and
        $_.Package -eq $expectedPackage -and
        $_.Path -notmatch '(?i)playstore|google_apis_playstore|google_play|play store' -and
        ($ApiLevel -eq 0 -or $_.Api -eq $ApiLevel)
    })
    if ($eligible.Count -eq 0) { throw 'compatible_non_play_system_image_not_found' }
    return $eligible | Sort-Object @{ Expression = { $_.Api }; Descending = $true } | Select-Object -First 1
}

function Assert-Beta1SystemImageMetadata {
    param([Parameter(Mandatory = $true)]$Image)
    $expectedPackage = "system-images;android-$($Image.Api);google_apis;x86_64"
    if ($Image.Api -notin @(36, 35) -or $Image.Tag -ne 'google_apis' -or
        $Image.Abi -ne 'x86_64' -or $Image.Package -ne $expectedPackage -or
        $Image.Path -match '(?i)playstore|google_apis_playstore|google_play|play store') {
        throw 'system_image_identity_invalid'
    }
    $sourcePath = Join-Path $Image.Path 'source.properties'
    $packagePath = Join-Path $Image.Path 'package.xml'
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw 'system_image_source_properties_missing' }
    if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { throw 'system_image_package_xml_missing' }
    $source = Get-Content -Raw -Encoding UTF8 -LiteralPath $sourcePath
    $package = Get-Content -Raw -Encoding UTF8 -LiteralPath $packagePath
    if ($source -notmatch "(?m)^AndroidVersion\.ApiLevel=$($Image.Api)\s*$" -or
        $source -notmatch '(?m)^SystemImage\.TagId=google_apis\s*$' -or
        $source -notmatch '(?m)^SystemImage\.Abi=x86_64\s*$') {
        throw 'system_image_source_properties_mismatch'
    }
    $declaredPackage = [regex]::Match($source, '(?m)^Pkg\.Path=(.+?)\s*$')
    if ($declaredPackage.Success -and $declaredPackage.Groups[1].Value -ne $expectedPackage) {
        throw 'system_image_source_properties_mismatch'
    }
    if ($package -notmatch ('(?i)<localPackage\s+path="' + [regex]::Escape($expectedPackage) + '"')) {
        throw 'system_image_package_xml_mismatch'
    }
    return $true
}

function Assert-Beta1AvdConfig {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][string]$ExpectedAvdName,
        [Parameter(Mandatory = $true)][int]$ExpectedApi
    )
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'avd_config_missing' }
    $config = (Get-Content -Raw -Encoding UTF8 -LiteralPath $ConfigPath) -replace '\\', '/'
    $expectedImage = "system-images/android-$ExpectedApi/google_apis/x86_64/"
    $declaredId = [regex]::Match($config, '(?m)^AvdId=(.+?)\s*$')
    if (($declaredId.Success -and $declaredId.Groups[1].Value -ne $ExpectedAvdName) -or
        $config -notmatch '(?m)^tag\.id=google_apis\s*$' -or
        $config -notmatch ('(?m)^image\.sysdir\.1=' + [regex]::Escape($expectedImage) + '\s*$') -or
        $config -match '(?im)^PlayStore\.enabled=true\s*$') {
        throw 'avd_config_identity_mismatch'
    }
    return $true
}

function Get-Beta1ConnectedDevices {
    param([Parameter(Mandatory = $true)][string]$AdbPath)
    $result = Invoke-Beta1NativeCommand $AdbPath @('devices')
    if ($result.ExitCode -ne 0) { throw 'adb_devices_failed' }
    $lines = $result.Output
    $devices = @()
    foreach ($line in $lines | Select-Object -Skip 1) {
        $parts = @($line.ToString().Trim() -split '\s+')
        if ($parts.Count -lt 2 -or -not $parts[0]) { continue }
        $devices += [pscustomobject]@{
            Serial = $parts[0]
            State = $parts[1]
            Kind = if ($parts[0] -like 'emulator-*') { 'emulator' } else { 'physical-or-remote' }
            AvdName = $null
            Fingerprint = Get-Beta1TextFingerprint $parts[0]
        }
    }
    return @($devices)
}

function Add-Beta1AvdNames {
    param(
        [Parameter(Mandatory = $true)][string]$AdbPath,
        [Parameter(Mandatory = $true)][AllowNull()][AllowEmptyCollection()][object[]]$Devices
    )
    $inventory = @($Devices | Where-Object { $null -ne $_ })
    foreach ($device in $inventory) {
        if (-not ($device.PSObject.Properties.Name -contains 'Kind')) { throw 'device_inventory_contract_invalid' }
        if ($device.Kind -eq 'emulator' -and $device.State -eq 'device') {
            $result = Invoke-Beta1NativeCommand $AdbPath @('-s', $device.Serial, 'emu', 'avd', 'name')
            $name = @($result.Output | Where-Object { $_ -and $_ -ne 'OK' } | Select-Object -First 1)
            if ($result.ExitCode -eq 0 -and $name.Count -eq 1) { $device.AvdName = $name[0].Trim() }
        }
    }
    return $inventory
}

function Select-Beta1DisposableDevice {
    param(
        [Parameter(Mandatory = $true)][AllowNull()][AllowEmptyCollection()][object[]]$Devices,
        [Parameter(Mandatory = $true)][string]$ExpectedAvdName
    )
    $inventory = @($Devices | Where-Object { $null -ne $_ })
    foreach ($device in $inventory) {
        foreach ($property in @('Kind', 'State', 'AvdName')) {
            if (-not ($device.PSObject.Properties.Name -contains $property)) { throw 'device_inventory_contract_invalid' }
        }
    }
    if (@($inventory | Where-Object { $_.Kind -ne 'emulator' }).Count -gt 0) { throw 'physical_device_detected' }
    $authorized = @($inventory | Where-Object { $_.State -eq 'device' })
    if ($authorized.Count -ne 1) { throw "ambiguous_device_count:$($authorized.Count)" }
    $selected = $authorized[0]
    if ($selected.Kind -ne 'emulator' -or $selected.AvdName -ne $ExpectedAvdName) { throw 'disposable_avd_identity_mismatch' }
    return $selected
}

function Wait-Beta1Condition {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Probe,
        [int]$TimeoutSeconds = 180,
        [int]$PollMilliseconds = 1000,
        [string]$TimeoutCode = 'operation_timeout'
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Probe) { return }
        if ([DateTime]::UtcNow -ge $deadline) { throw $TimeoutCode }
        Start-Sleep -Milliseconds $PollMilliseconds
    } while ($true)
}

function Assert-Beta1OwnedPath {
    param(
        [Parameter(Mandatory = $true)][string]$SessionRoot,
        [Parameter(Mandatory = $true)][string]$TargetPath
    )
    $base = [IO.Path]::GetFullPath($SessionRoot).TrimEnd('\', '/')
    $target = [IO.Path]::GetFullPath($TargetPath).TrimEnd('\', '/')
    if ($target -eq $base -or -not $target.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'cleanup_target_outside_session'
    }
    return $target
}

function Test-Beta1ApkIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Package,
        [Parameter(Mandatory = $true)][long]$VersionCode,
        [string]$ExpectedPackage = 'io.healthtracker.companion.debug',
        [long]$ExpectedVersionCode = 21
    )
    if ($Package -ne $ExpectedPackage) { throw 'apk_package_mismatch' }
    if ($VersionCode -ne $ExpectedVersionCode) { throw 'apk_version_mismatch' }
}

function Get-Beta1JUnitSummary {
    param([Parameter(Mandatory = $true)][string[]]$Paths)
    $total = 0; $failed = 0; $skipped = 0; $errors = 0
    $failedClasses = @(); $failedMethods = @(); $executedClasses = @()
    foreach ($path in $Paths) {
        [xml]$document = Get-Content -Raw -Encoding UTF8 -LiteralPath $path
        $root = $document.DocumentElement
        if ($null -eq $root) { continue }
        $suites = if ($root.LocalName -eq 'testsuite') {
            @($root)
        } elseif ($root.LocalName -eq 'testsuites') {
            @($root.ChildNodes | Where-Object { $_.LocalName -eq 'testsuite' })
        } else {
            @()
        }
        foreach ($suite in $suites) {
            $suiteTests = $suite.GetAttribute('tests')
            if ([string]::IsNullOrWhiteSpace($suiteTests)) { continue }
            $suiteFailures = $suite.GetAttribute('failures')
            $suiteErrors = $suite.GetAttribute('errors')
            $suiteSkipped = $suite.GetAttribute('skipped')
            $suiteFailureCount = if ([string]::IsNullOrWhiteSpace($suiteFailures)) { 0 } else { [int]$suiteFailures }
            $suiteErrorCount = if ([string]::IsNullOrWhiteSpace($suiteErrors)) { 0 } else { [int]$suiteErrors }
            $total += [int]$suiteTests
            $failed += $suiteFailureCount
            $errors += $suiteErrorCount
            $skipped += if ([string]::IsNullOrWhiteSpace($suiteSkipped)) { 0 } else { [int]$suiteSkipped }
            foreach ($case in @($suite.SelectNodes('./testcase'))) {
                $className = $case.GetAttribute('classname')
                $methodName = $case.GetAttribute('name')
                if ($className) { $executedClasses += $className }
                if ($case.SelectSingleNode('./failure') -or $case.SelectSingleNode('./error')) {
                    if ($className) { $failedClasses += $className }
                    $failedMethods += ($className + '#' + $methodName)
                }
            }
        }
    }
    return [pscustomobject]@{
        Total = $total
        Passed = $total - $failed - $errors - $skipped
        Skipped = $skipped
        Failed = $failed + $errors
        ExecutedClasses = @($executedClasses | Sort-Object -Unique)
        FailedClasses = @($failedClasses | Where-Object { $_ } | Sort-Object -Unique)
        FailedMethods = @($failedMethods | Sort-Object -Unique)
    }
}

function Invoke-Beta1WithCleanup {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Body,
        [Parameter(Mandatory = $true)][scriptblock]$Cleanup
    )
    try { & $Body } finally { & $Cleanup }
}
