Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Alpha15RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not (Get-Variable -Name Alpha15CommandRunner -Scope Script -ErrorAction SilentlyContinue)) {
    $script:Alpha15CommandRunner = $null
}

function Set-Alpha15TestCommandRunner {
    param([scriptblock]$Runner)
    $script:Alpha15CommandRunner = $Runner
}

function Clear-Alpha15TestCommandRunner {
    $script:Alpha15CommandRunner = $null
}

function New-Alpha15Failure {
    param([int]$ExitCode, [string]$Reason, [string]$Message)
    $exception = New-Object System.InvalidOperationException($Message)
    $exception.Data['Alpha15ExitCode'] = $ExitCode
    $exception.Data['Alpha15Reason'] = $Reason
    return $exception
}

function Throw-Alpha15Failure {
    param([int]$ExitCode, [string]$Reason, [string]$Message)
    throw (New-Alpha15Failure -ExitCode $ExitCode -Reason $Reason -Message $Message)
}

function Test-Alpha15ControlCharacters {
    param([AllowNull()][string]$Value)
    return ($null -ne $Value -and [regex]::IsMatch($Value, '[\x00-\x1f\x7f]'))
}

function Assert-Alpha15SafeText {
    param([AllowNull()][string]$Value, [string]$Name)
    if (Test-Alpha15ControlCharacters $Value) {
        Throw-Alpha15Failure 2 'invalid_path' "$Name contains control characters."
    }
}

function Resolve-Alpha15ExistingDirectory {
    param([string]$Path, [string]$Name, [int]$ExitCode = 3)
    Assert-Alpha15SafeText $Path $Name
    if ([string]::IsNullOrWhiteSpace($Path)) {
        Throw-Alpha15Failure $ExitCode 'path_missing' "$Name is required."
    }
    try {
        return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        Throw-Alpha15Failure $ExitCode 'path_not_found' "$Name was not found."
    }
}

function Test-Alpha15ExecutableFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $extension = [IO.Path]::GetExtension($Path).ToLowerInvariant()
    return $extension -in @('.exe', '.bat', '.cmd', '.com', '')
}

function Resolve-Alpha15ExecutableFile {
    param([string]$Path, [string]$Name)
    Assert-Alpha15SafeText $Path $Name
    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    } catch {
        Throw-Alpha15Failure 3 'tool_not_found' "$Name was not found."
    }
    if (-not (Test-Alpha15ExecutableFile $resolved)) {
        Throw-Alpha15Failure 3 'tool_not_executable' "$Name is not an executable file."
    }
    return $resolved
}

function Test-Alpha15PathUnderRoot {
    param([string]$Path, [string]$Root)
    if ([string]::IsNullOrWhiteSpace($Path) -or [string]::IsNullOrWhiteSpace($Root)) { return $false }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    return $fullPath.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Get-Alpha15ShortFingerprint {
    param([string]$Value, [int]$Length = 12)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hex = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    } finally {
        $sha.Dispose()
    }
    return $hex.Substring(0, [Math]::Min($Length, $hex.Length))
}

function ConvertTo-Alpha15SafeLine {
    param([AllowNull()][string]$Value)
    if ($null -eq $Value) { return $null }
    $safe = $Value -replace '(?i)[A-Z]:\\Users\\[^\\\s]+', '<USERPROFILE>'
    $safe = $safe -replace '(?i)Authorization\s*[:=]\s*\S+', 'Authorization=[REDACTED]'
    $safe = $safe -replace '(?i)Bearer\s+\S+', 'Bearer [REDACTED]'
    $safe = $safe -replace '(?i)(access[_ -]?token|refresh[_ -]?token|cookie)\s*[:=]\s*\S+', '$1=[REDACTED]'
    return $safe.Trim()
}

function Invoke-Alpha15External {
    param([string]$FilePath, [string[]]$Arguments = @())
    if ($script:Alpha15CommandRunner) {
        return & $script:Alpha15CommandRunner $FilePath $Arguments
    }
    $lines = @()
    $exitCode = 1
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 wraps native stderr as ErrorRecord. ADB writes
        # harmless daemon startup messages there, so capture them and decide by
        # the native exit code instead of converting them into terminating errors.
        $ErrorActionPreference = 'Continue'
        $lines = @(& $FilePath @Arguments 2>&1 | ForEach-Object { $_.ToString() })
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
    } catch {
        $lines = @('tool_execution_failed')
        $exitCode = 1
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [pscustomobject]@{ ExitCode = [int]$exitCode; Lines = @($lines) }
}

function Get-Alpha15PathCommand {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -CommandType Application, ExternalScript -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and (Test-Alpha15ExecutableFile $command.Source)) { return $command.Source }
    }
    return $null
}

function Get-Alpha15SdkRootFromToolPath {
    param([AllowNull()][string]$Path)
    if (-not $Path) { return $null }
    $parent = Split-Path -Parent $Path
    $leaf = Split-Path -Leaf $parent
    if ($leaf -eq 'platform-tools') { return (Split-Path -Parent $parent) }
    $grandParent = Split-Path -Parent $parent
    if ((Split-Path -Leaf $grandParent) -eq 'build-tools') { return (Split-Path -Parent $grandParent) }
    return $null
}

function Get-Alpha15LocalPropertiesSdkRoot {
    $properties = Join-Path $script:Alpha15RepositoryRoot 'android\local.properties'
    if (-not (Test-Path -LiteralPath $properties -PathType Leaf)) { return $null }
    foreach ($line in Get-Content -LiteralPath $properties) {
        if ($line -match '^\s*sdk\.dir\s*=\s*(.+?)\s*$') {
            $value = $Matches[1].Replace('\\:', ':').Replace('\\\\', '\')
            Assert-Alpha15SafeText $value 'sdk.dir'
            return $value
        }
    }
    return $null
}

function ConvertTo-Alpha15BuildToolsFolder {
    param([IO.DirectoryInfo]$Directory)
    $match = [regex]::Match($Directory.Name, '^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$')
    if (-not $match.Success) { return $null }
    $suffix = $match.Groups[4].Value
    return [pscustomobject]@{
        Directory = $Directory
        Name = $Directory.Name
        Major = [int]$match.Groups[1].Value
        Minor = $(if ($match.Groups[2].Success) { [int]$match.Groups[2].Value } else { 0 })
        Patch = $(if ($match.Groups[3].Success) { [int]$match.Groups[3].Value } else { 0 })
        Preview = -not [string]::IsNullOrWhiteSpace($suffix)
    }
}

function Get-Alpha15BuildToolsFolders {
    param([string]$SdkRoot, [string]$BuildToolsVersion, [switch]$AllowPreviewBuildTools)
    $root = Join-Path $SdkRoot 'build-tools'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return @() }
    $folders = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        ConvertTo-Alpha15BuildToolsFolder $_
    } | Where-Object { $null -ne $_ })
    if ($BuildToolsVersion) {
        Assert-Alpha15SafeText $BuildToolsVersion 'BuildToolsVersion'
        $folders = @($folders | Where-Object { $_.Name -eq $BuildToolsVersion })
        if ($folders.Count -eq 0) { Throw-Alpha15Failure 3 'build_tools_version_missing' 'Requested build-tools version was not found.' }
        if ($folders[0].Preview -and -not $AllowPreviewBuildTools) {
            Throw-Alpha15Failure 3 'preview_build_tools_not_allowed' 'Preview build-tools require explicit authorization.'
        }
        return $folders
    }
    $stable = @($folders | Where-Object { -not $_.Preview } | Sort-Object Major, Minor, Patch -Descending)
    if (-not $AllowPreviewBuildTools) { return $stable }
    $preview = @($folders | Where-Object { $_.Preview } | Sort-Object Major, Minor, Patch, Name -Descending)
    return @($stable + $preview)
}

function Find-Alpha15ToolInFolder {
    param([string]$Folder, [string[]]$Names)
    foreach ($name in $Names) {
        $candidate = Join-Path $Folder $name
        if (Test-Alpha15ExecutableFile $candidate) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

function Get-Alpha15ToolVersion {
    param([string]$Path, [string[]]$Arguments)
    $result = Invoke-Alpha15External $Path $Arguments
    if ($result.ExitCode -ne 0 -or $result.Lines.Count -eq 0) { return 'unavailable' }
    return ConvertTo-Alpha15SafeLine (($result.Lines | Select-Object -First 1).ToString())
}

function ConvertTo-Alpha15ReportedToolPath {
    param([string]$Path, [AllowNull()][string]$SdkRoot, [switch]$ShowSensitiveIdentifiers)
    if ($ShowSensitiveIdentifiers) { return $Path }
    if ($SdkRoot -and (Test-Alpha15PathUnderRoot $Path $SdkRoot)) {
        $relative = $Path.Substring($SdkRoot.TrimEnd('\', '/').Length).TrimStart('\', '/')
        return '<ANDROID_SDK>\' + $relative
    }
    return '<EXPLICIT_TOOL>\' + (Split-Path -Leaf $Path)
}

function ConvertTo-Alpha15ReportedFilePath {
    param([string]$Path, [switch]$ShowSensitiveIdentifiers)
    if ($ShowSensitiveIdentifiers) { return $Path }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if ($fullPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return '<TEMP>\' + $fullPath.Substring($tempRoot.Length)
    }
    if (Test-Alpha15PathUnderRoot $fullPath $script:Alpha15RepositoryRoot) {
        $repositoryRoot = $script:Alpha15RepositoryRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        return '<REPOSITORY>\' + $fullPath.Substring($repositoryRoot.Length)
    }
    return '<OUTPUT>\' + (Split-Path -Leaf $fullPath)
}

function Resolve-Alpha15AndroidToolchain {
    [CmdletBinding()]
    param(
        [string]$AndroidSdkRoot,
        [string]$AdbPath,
        [string]$AaptPath,
        [string]$ApksignerPath,
        [string]$BuildToolsVersion,
        [switch]$AllowPreviewBuildTools,
        [switch]$ShowSensitiveIdentifiers
    )

    foreach ($pair in @(
        @('AndroidSdkRoot', $AndroidSdkRoot), @('AdbPath', $AdbPath), @('AaptPath', $AaptPath),
        @('ApksignerPath', $ApksignerPath), @('BuildToolsVersion', $BuildToolsVersion)
    )) { Assert-Alpha15SafeText $pair[1] $pair[0] }

    $pathAdb = Get-Alpha15PathCommand @('adb.exe', 'adb')
    $pathAapt = Get-Alpha15PathCommand @('aapt.exe', 'aapt', 'aapt2.exe', 'aapt2')
    $pathSigner = Get-Alpha15PathCommand @('apksigner.bat', 'apksigner.exe', 'apksigner')

    $sdkCandidates = New-Object System.Collections.ArrayList
    if ($AndroidSdkRoot) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = $AndroidSdkRoot; Source = 'parameter' }) }
    if (-not $AndroidSdkRoot) {
        foreach ($pathTool in @($pathAdb, $pathAapt, $pathSigner)) {
            $inferred = Get-Alpha15SdkRootFromToolPath $pathTool
            if ($inferred) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = $inferred; Source = 'PATH' }); break }
        }
        if ($env:ANDROID_SDK_ROOT) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = $env:ANDROID_SDK_ROOT; Source = 'ANDROID_SDK_ROOT' }) }
        if ($env:ANDROID_HOME) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = $env:ANDROID_HOME; Source = 'ANDROID_HOME' }) }
        $localSdk = Get-Alpha15LocalPropertiesSdkRoot
        if ($localSdk) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = $localSdk; Source = 'local.properties' }) }
        if ($env:LOCALAPPDATA) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = (Join-Path $env:LOCALAPPDATA 'Android\Sdk'); Source = 'LOCALAPPDATA' }) }
        if ($env:ProgramFiles) { [void]$sdkCandidates.Add([pscustomobject]@{ Path = (Join-Path $env:ProgramFiles 'Android\Sdk'); Source = 'ProgramFiles' }) }
    }

    $sdkRoot = $null
    $sdkSource = $null
    foreach ($candidate in $sdkCandidates) {
        if ([string]::IsNullOrWhiteSpace($candidate.Path)) { continue }
        if (Test-Alpha15ControlCharacters $candidate.Path) { continue }
        if (Test-Path -LiteralPath $candidate.Path -PathType Container) {
            $sdkRoot = (Resolve-Path -LiteralPath $candidate.Path).Path
            $sdkSource = $candidate.Source
            break
        }
    }
    if ($AndroidSdkRoot -and -not $sdkRoot) {
        Throw-Alpha15Failure 3 'sdk_root_not_found' 'The explicit Android SDK root was not found.'
    }

    $sources = [ordered]@{}
    $adb = $null
    if ($AdbPath) { $adb = Resolve-Alpha15ExecutableFile $AdbPath 'AdbPath'; $sources.adb = 'parameter' }
    elseif ($pathAdb -and ($sdkRoot -and (Test-Alpha15PathUnderRoot $pathAdb $sdkRoot))) { $adb = $pathAdb; $sources.adb = 'PATH' }
    elseif ($sdkRoot) {
        $adb = Find-Alpha15ToolInFolder (Join-Path $sdkRoot 'platform-tools') @('adb.exe', 'adb.bat', 'adb.cmd', 'adb')
        if ($adb) { $sources.adb = $sdkSource }
    }
    if (-not $adb) { Throw-Alpha15Failure 3 'adb_not_found' 'adb was not found in the resolved SDK.' }

    $aapt = $null
    $aaptKind = $null
    if ($AaptPath) {
        $aapt = Resolve-Alpha15ExecutableFile $AaptPath 'AaptPath'
        $sources.aapt = 'parameter'
    } elseif (-not $BuildToolsVersion -and $pathAapt -and ($sdkRoot -and (Test-Alpha15PathUnderRoot $pathAapt $sdkRoot))) {
        $aapt = $pathAapt
        $sources.aapt = 'PATH'
    }
    if ($aapt) { $aaptKind = $(if ((Split-Path -Leaf $aapt) -match '^aapt2') { 'aapt2' } else { 'aapt' }) }

    $apksigner = $null
    if ($ApksignerPath) { $apksigner = Resolve-Alpha15ExecutableFile $ApksignerPath 'ApksignerPath'; $sources.apksigner = 'parameter' }
    elseif (-not $BuildToolsVersion -and $pathSigner -and ($sdkRoot -and (Test-Alpha15PathUnderRoot $pathSigner $sdkRoot))) { $apksigner = $pathSigner; $sources.apksigner = 'PATH' }

    $selectedBuildTools = $null
    if ((-not $aapt -or -not $apksigner) -and $sdkRoot) {
        $folders = Get-Alpha15BuildToolsFolders -SdkRoot $sdkRoot -BuildToolsVersion $BuildToolsVersion -AllowPreviewBuildTools:$AllowPreviewBuildTools
        foreach ($folder in $folders) {
            $candidateAapt = $aapt
            if (-not $candidateAapt) { $candidateAapt = Find-Alpha15ToolInFolder $folder.Directory.FullName @('aapt.exe', 'aapt.bat', 'aapt.cmd', 'aapt', 'aapt2.exe', 'aapt2.bat', 'aapt2.cmd', 'aapt2') }
            $candidateSigner = $apksigner
            if (-not $candidateSigner) { $candidateSigner = Find-Alpha15ToolInFolder $folder.Directory.FullName @('apksigner.bat', 'apksigner.exe', 'apksigner.cmd', 'apksigner') }
            if ($candidateAapt -and $candidateSigner) {
                if (-not $aapt) { $aapt = $candidateAapt; $sources.aapt = 'build-tools' }
                if (-not $apksigner) { $apksigner = $candidateSigner; $sources.apksigner = 'build-tools' }
                $selectedBuildTools = $folder.Name
                break
            }
        }
        if (-not $aapt) {
            foreach ($folder in $folders) {
                $candidateAapt = Find-Alpha15ToolInFolder $folder.Directory.FullName @('aapt.exe', 'aapt.bat', 'aapt.cmd', 'aapt', 'aapt2.exe', 'aapt2.bat', 'aapt2.cmd', 'aapt2')
                if ($candidateAapt) { $aapt = $candidateAapt; $sources.aapt = 'build-tools'; break }
            }
        }
        if (-not $apksigner) {
            foreach ($folder in $folders) {
                $candidateSigner = Find-Alpha15ToolInFolder $folder.Directory.FullName @('apksigner.bat', 'apksigner.exe', 'apksigner.cmd', 'apksigner')
                if ($candidateSigner) { $apksigner = $candidateSigner; $sources.apksigner = 'build-tools'; break }
            }
        }
    }
    if (-not $aapt) { Throw-Alpha15Failure 3 'aapt_not_found' 'Neither aapt nor aapt2 was found in valid build-tools.' }
    if (-not $apksigner) { Throw-Alpha15Failure 3 'apksigner_not_found' 'apksigner was not found in valid build-tools.' }
    if (-not $aaptKind) { $aaptKind = $(if ((Split-Path -Leaf $aapt) -match '^aapt2') { 'aapt2' } else { 'aapt' }) }
    if (-not $selectedBuildTools) {
        $toolVersions = @(@($aapt, $apksigner) | ForEach-Object {
            $parent = Split-Path -Parent $_
            if ((Split-Path -Leaf (Split-Path -Parent $parent)) -eq 'build-tools') { Split-Path -Leaf $parent }
        } | Where-Object { $_ } | Select-Object -Unique)
        if ($toolVersions.Count -eq 1) { $selectedBuildTools = $toolVersions[0] }
    }

    if (-not $sdkRoot) {
        $inferredRoots = @(@($adb, $aapt, $apksigner) | ForEach-Object { Get-Alpha15SdkRootFromToolPath $_ } | Where-Object { $_ } | Select-Object -Unique)
        if ($inferredRoots.Count -eq 1) { $sdkRoot = $inferredRoots[0]; $sdkSource = 'tool_paths' }
    }
    if (-not $sdkRoot -and (-not $AdbPath -or -not $AaptPath -or -not $ApksignerPath)) {
        Throw-Alpha15Failure 3 'sdk_root_not_found' 'An Android SDK root could not be resolved safely.'
    }

    $internal = [pscustomobject]@{
        SdkRoot = $sdkRoot
        Adb = $adb
        Aapt = $aapt
        AaptKind = $aaptKind
        Apksigner = $apksigner
        BuildToolsVersion = $selectedBuildTools
        Sources = $sources
    }
    $report = [pscustomobject][ordered]@{
        PSTypeName = 'AndroidToolchainInfo'
        sdk_root = $(if ($ShowSensitiveIdentifiers) { $sdkRoot } else { '<ANDROID_SDK>' })
        sdk_source = $sdkSource
        adb = ConvertTo-Alpha15ReportedToolPath $adb $sdkRoot -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
        adb_source = $sources.adb
        aapt = ConvertTo-Alpha15ReportedToolPath $aapt $sdkRoot -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
        aapt_kind = $aaptKind
        aapt_source = $sources.aapt
        apksigner = ConvertTo-Alpha15ReportedToolPath $apksigner $sdkRoot -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
        apksigner_source = $sources.apksigner
        build_tools_version = $selectedBuildTools
        versions = [ordered]@{
            adb = Get-Alpha15ToolVersion $adb @('version')
            aapt = Get-Alpha15ToolVersion $aapt @('version')
            apksigner = Get-Alpha15ToolVersion $apksigner @('version')
        }
    }
    return [pscustomobject]@{ Internal = $internal; Report = $report }
}

function Get-Alpha15CertificateDigest {
    param([string[]]$Lines)
    $text = $Lines -join "`n"
    $match = [regex]::Match($text, '(?im)certificate SHA-256 digest:\s*([0-9a-f:]{32,})')
    if (-not $match.Success) { return $null }
    $digest = ($match.Groups[1].Value -replace '[^0-9a-fA-F]', '').ToLowerInvariant()
    if ($digest.Length -lt 32) { return $null }
    return $digest
}

function Get-Alpha15ApkInfo {
    [CmdletBinding()]
    param(
        [string]$ApkPath,
        [Parameter(Mandatory = $true)]$Toolchain,
        [switch]$AllowDifferentAlphaVersion,
        [switch]$ShowSensitiveIdentifiers
    )
    Assert-Alpha15SafeText $ApkPath 'ApkPath'
    try { $resolvedApk = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path } catch {
        Throw-Alpha15Failure 4 'apk_not_found' 'The APK was not found.'
    }
    $item = Get-Item -LiteralPath $resolvedApk
    if ($item.Length -le 0) { Throw-Alpha15Failure 4 'apk_empty' 'The APK is empty.' }

    $badgingResult = Invoke-Alpha15External $Toolchain.Aapt @('dump', 'badging', $resolvedApk)
    if ($badgingResult.ExitCode -ne 0) { Throw-Alpha15Failure 4 'apk_badging_failed' 'APK metadata could not be inspected.' }
    $badging = $badgingResult.Lines -join "`n"
    $packageMatch = [regex]::Match($badging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
    $minMatch = [regex]::Match($badging, "sdkVersion:'([^']+)'")
    $targetMatch = [regex]::Match($badging, "targetSdkVersion:'([^']+)'")
    if (-not $packageMatch.Success -or -not $minMatch.Success -or -not $targetMatch.Success) {
        Throw-Alpha15Failure 4 'apk_metadata_incomplete' 'Required APK metadata is missing.'
    }

    $signatureResult = Invoke-Alpha15External $Toolchain.Apksigner @('verify', '--verbose', '--print-certs', $resolvedApk)
    if ($signatureResult.ExitCode -ne 0) { Throw-Alpha15Failure 4 'apk_signature_invalid' 'APK signature verification failed.' }
    $digest = Get-Alpha15CertificateDigest $signatureResult.Lines
    if (-not $digest) { Throw-Alpha15Failure 4 'apk_certificate_unreadable' 'APK certificate could not be read.' }

    $packageName = $packageMatch.Groups[1].Value
    $versionCode = [long]$packageMatch.Groups[2].Value
    $versionName = $packageMatch.Groups[3].Value
    if ($packageName -ne 'io.healthtracker.companion.debug') {
        Throw-Alpha15Failure 4 'unexpected_application_id' 'APK applicationId is not the Alpha 1.5 debug package.'
    }
    if (-not $AllowDifferentAlphaVersion -and ($versionCode -ne 15 -or $versionName -ne '1.5.0-alpha01-debug')) {
        Throw-Alpha15Failure 4 'unexpected_alpha_version' 'APK version is not Alpha 1.5 RC1.'
    }

    $nativeCodeMatch = [regex]::Match($badging, "native-code:\s*(.+)")
    $nativeCodes = @()
    if ($nativeCodeMatch.Success) { $nativeCodes = @([regex]::Matches($nativeCodeMatch.Groups[1].Value, "'([^']+)'") | ForEach-Object { $_.Groups[1].Value }) }
    $report = [pscustomobject][ordered]@{
        file = $(if ($ShowSensitiveIdentifiers) { $resolvedApk } else { $item.Name })
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $resolvedApk -Algorithm SHA256).Hash.ToLowerInvariant()
        package = $packageName
        version_code = $versionCode
        version_name = $versionName
        min_sdk = [int]$minMatch.Groups[1].Value
        target_sdk = [int]$targetMatch.Groups[1].Value
        debuggable = [bool]($badging -match '(?m)^application-debuggable')
        signature_valid = $true
        certificate_fingerprint = $digest.Substring(0, 12)
        native_code = $nativeCodes
    }
    return [pscustomobject]@{ Internal = [pscustomobject]@{ Path = $resolvedApk; CertificateDigest = $digest }; Report = $report }
}

function Invoke-Alpha15Adb {
    param([string]$Adb, [AllowNull()][string]$Serial, [string[]]$Arguments)
    $allArguments = @()
    if ($Serial) { $allArguments += @('-s', $Serial) }
    $allArguments += $Arguments
    return Invoke-Alpha15External $Adb $allArguments
}

function Get-Alpha15ConnectedDevices {
    param([string]$Adb)
    $result = Invoke-Alpha15Adb $Adb $null @('devices', '-l')
    if ($result.ExitCode -ne 0) { Throw-Alpha15Failure 5 'adb_devices_failed' 'adb could not enumerate devices.' }
    $devices = @()
    foreach ($line in @($result.Lines | Select-Object -Skip 1)) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\*') { continue }
        $parts = @($line.Trim() -split '\s+')
        if ($parts.Count -lt 2) { continue }
        $devices += [pscustomobject]@{
            Serial = $parts[0]
            State = $parts[1].ToLowerInvariant()
            Fingerprint = Get-Alpha15ShortFingerprint $parts[0]
        }
    }
    return $devices
}

function Select-Alpha15Device {
    param([object[]]$Devices, [AllowNull()][string]$Serial)
    Assert-Alpha15SafeText $Serial 'Serial'
    if ($Serial) {
        $selected = @($Devices | Where-Object { $_.Serial -ceq $Serial })
        if ($selected.Count -ne 1) { Throw-Alpha15Failure 5 'serial_not_found' 'The selected serial is not connected.' }
        if ($selected[0].State -eq 'unauthorized') { Throw-Alpha15Failure 9 'device_unauthorized' 'The selected device is unauthorized.' }
        if ($selected[0].State -ne 'device') { Throw-Alpha15Failure 5 ('device_' + $selected[0].State) 'The selected device is not in the authorized device state.' }
        return $selected[0]
    }
    if ($Devices.Count -eq 0) { Throw-Alpha15Failure 5 'device_missing' 'No Android device was detected.' }
    if ($Devices.Count -gt 1) { Throw-Alpha15Failure 5 'multiple_devices' 'Multiple Android devices were detected; use -Serial.' }
    if ($Devices[0].State -eq 'unauthorized') { Throw-Alpha15Failure 9 'device_unauthorized' 'The connected device is unauthorized.' }
    if ($Devices[0].State -ne 'device') { Throw-Alpha15Failure 5 ('device_' + $Devices[0].State) 'The connected device is not ready.' }
    return $Devices[0]
}

function Get-Alpha15AdbText {
    param([string]$Adb, [string]$Serial, [string[]]$Arguments, [switch]$AllowFailure)
    $result = Invoke-Alpha15Adb $Adb $Serial $Arguments
    if ($result.ExitCode -ne 0 -and -not $AllowFailure) { Throw-Alpha15Failure 5 'device_query_failed' 'A read-only device query failed.' }
    return (($result.Lines -join "`n").Trim())
}

function Get-Alpha15DeviceInfo {
    param([string]$Adb, $SelectedDevice, [long]$ApkSizeBytes)
    $serial = $SelectedDevice.Serial
    $prop = @{}
    foreach ($entry in @(
        @('manufacturer', 'ro.product.manufacturer'), @('model', 'ro.product.model'), @('api', 'ro.build.version.sdk'),
        @('android_version', 'ro.build.version.release'), @('abi', 'ro.product.cpu.abi'), @('boot_completed', 'sys.boot_completed')
    )) { $prop[$entry[0]] = Get-Alpha15AdbText $Adb $serial @('shell', 'getprop', $entry[1]) }

    $spaceText = Get-Alpha15AdbText $Adb $serial @('shell', 'df', '-k', '/sdcard') -AllowFailure
    $availableKb = $null
    $spaceLine = @($spaceText -split "`r?`n" | Where-Object { $_ -and $_ -notmatch '^Filesystem' } | Select-Object -Last 1)
    if ($spaceLine.Count -eq 1) {
        $columns = @($spaceLine[0].Trim() -split '\s+')
        if ($columns.Count -ge 4 -and $columns[3] -match '^\d+$') { $availableKb = [long]$columns[3] }
    }
    $requiredKb = [long][Math]::Ceiling(($ApkSizeBytes * 3 + 100MB) / 1KB)
    $batteryText = Get-Alpha15AdbText $Adb $serial @('shell', 'dumpsys', 'battery') -AllowFailure
    $batteryMatch = [regex]::Match($batteryText, '(?m)^\s*level:\s*(\d+)')
    $battery = $(if ($batteryMatch.Success) { [int]$batteryMatch.Groups[1].Value } else { $null })
    return [pscustomobject][ordered]@{
        serial_fingerprint = $SelectedDevice.Fingerprint
        state = $SelectedDevice.State
        manufacturer = (ConvertTo-Alpha15SafeLine $prop.manufacturer)
        model = (ConvertTo-Alpha15SafeLine $prop.model)
        android_api = $(if ($prop.api -match '^\d+$') { [int]$prop.api } else { $null })
        android_version = (ConvertTo-Alpha15SafeLine $prop.android_version)
        abi = (ConvertTo-Alpha15SafeLine $prop.abi)
        boot_completed = $prop.boot_completed -eq '1'
        available_space_kb = $availableKb
        required_space_kb = $requiredKb
        space_sufficient = $null -ne $availableKb -and $availableKb -ge $requiredKb
        battery_percent = $battery
    }
}

function Get-Alpha15InstalledPackageInfo {
    param([string]$Adb, [string]$Serial, [string]$PackageName)
    $dumpResult = Invoke-Alpha15Adb $Adb $Serial @('shell', 'dumpsys', 'package', $PackageName)
    if ($dumpResult.ExitCode -ne 0) { Throw-Alpha15Failure 5 'package_query_failed' 'Package manager query failed.' }
    $dump = $dumpResult.Lines -join "`n"
    if ($dump -match '(?i)Unable to find package|Unknown package' -or $dump -notmatch '(?m)versionCode=') {
        return [pscustomobject]@{ Present = $false; Report = [pscustomobject][ordered]@{ present = $false }; Dump = $dump }
    }
    $code = [regex]::Match($dump, '(?m)versionCode=(\d+)')
    $name = [regex]::Match($dump, '(?m)\s*versionName=([^\r\n]+)')
    $first = [regex]::Match($dump, '(?m)\s*firstInstallTime=([^\r\n]+)')
    $last = [regex]::Match($dump, '(?m)\s*lastUpdateTime=([^\r\n]+)')
    $installer = [regex]::Match($dump, '(?m)\s*installerPackageName=([^\r\n]+)')
    $report = [pscustomobject][ordered]@{
        present = $true
        version_code = $(if ($code.Success) { [long]$code.Groups[1].Value } else { $null })
        version_name = $(if ($name.Success) { $name.Groups[1].Value.Trim() } else { $null })
        first_install_time = $(if ($first.Success) { $first.Groups[1].Value.Trim() } else { $null })
        last_update_time = $(if ($last.Success) { $last.Groups[1].Value.Trim() } else { $null })
        installer = $(if ($installer.Success) { ConvertTo-Alpha15SafeLine $installer.Groups[1].Value } else { $null })
        data_directory_reported = [bool]($dump -match '(?m)\s*dataDir=')
    }
    return [pscustomobject]@{ Present = $true; Report = $report; Dump = $dump }
}

function New-Alpha15TemporaryDirectory {
    param([string]$Prefix = 'health-tracker-alpha15')
    $root = [IO.Path]::GetTempPath()
    $path = Join-Path $root ($Prefix + '-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($path)
    return $path
}

function Remove-Alpha15TemporaryDirectory {
    param([AllowNull()][string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return }
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Throw-Alpha15Failure 10 'unsafe_temp_cleanup' 'Temporary cleanup target was outside the system temporary directory.'
    }
    [IO.Directory]::Delete($fullPath, $true)
}

function Get-Alpha15InstalledCertificate {
    param([string]$Adb, [string]$Serial, [string]$PackageName, [string]$Apksigner)
    $temporary = New-Alpha15TemporaryDirectory 'health-tracker-alpha15-installed-apk'
    $removed = $false
    try {
        $pathResult = Invoke-Alpha15Adb $Adb $Serial @('shell', 'pm', 'path', $PackageName)
        if ($pathResult.ExitCode -ne 0) { return [pscustomobject]@{ Status = 'unable_to_verify'; Digest = $null; TempRemoved = $false } }
        $remotePaths = @($pathResult.Lines | ForEach-Object { if ($_ -match '^package:(.+)$') { $Matches[1].Trim() } } | Where-Object { $_ })
        if ($remotePaths.Count -eq 0) { return [pscustomobject]@{ Status = 'unable_to_verify'; Digest = $null; TempRemoved = $false } }
        $basePath = @($remotePaths | Where-Object { $_ -match '/base\.apk$' } | Select-Object -First 1)
        if ($basePath.Count -eq 0) { $basePath = @($remotePaths[0]) }
        $localApk = Join-Path $temporary 'installed-base.apk'
        $pull = Invoke-Alpha15Adb $Adb $Serial @('pull', $basePath[0], $localApk)
        if ($pull.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $localApk -PathType Leaf)) {
            return [pscustomobject]@{ Status = 'unable_to_verify'; Digest = $null; TempRemoved = $false }
        }
        $verify = Invoke-Alpha15External $Apksigner @('verify', '--verbose', '--print-certs', $localApk)
        $digest = $(if ($verify.ExitCode -eq 0) { Get-Alpha15CertificateDigest $verify.Lines } else { $null })
        if (-not $digest) { return [pscustomobject]@{ Status = 'unable_to_verify'; Digest = $null; TempRemoved = $false } }
        return [pscustomobject]@{ Status = 'verified'; Digest = $digest; TempRemoved = $false }
    } finally {
        Remove-Alpha15TemporaryDirectory $temporary
        $removed = -not (Test-Path -LiteralPath $temporary)
    }
}

function Compare-Alpha15InstalledPackage {
    param($Installed, $ApkInfo, [string]$Adb, [string]$Serial, [string]$Apksigner, [string]$PackageName)
    if (-not $Installed.Present) {
        return [pscustomobject][ordered]@{
            status = 'package_not_installed'; signature = 'not_applicable'; installed_certificate_fingerprint = $null
            version_relation = 'not_installed'; installation_allowed = $true; temporary_apk_removed = $true
        }
    }
    $installedCert = Get-Alpha15InstalledCertificate $Adb $Serial $PackageName $Apksigner
    if ($installedCert.Status -ne 'verified') {
        return [pscustomobject][ordered]@{
            status = 'unable_to_verify'; signature = 'unable_to_verify'; installed_certificate_fingerprint = $null
            version_relation = 'unknown'; installation_allowed = $false; temporary_apk_removed = $true
        }
    }
    $sameSignature = $installedCert.Digest -eq $ApkInfo.Internal.CertificateDigest
    $candidateCode = [long]$ApkInfo.Report.version_code
    $installedCode = [long]$Installed.Report.version_code
    $relation = $(if ($candidateCode -gt $installedCode) { 'candidate_newer' } elseif ($candidateCode -lt $installedCode) { 'candidate_older' } else { 'same_version' })
    $status = $(if (-not $sameSignature) { 'signature_mismatch' } else { $relation })
    return [pscustomobject][ordered]@{
        status = $status
        signature = $(if ($sameSignature) { 'compatible_upgrade' } else { 'signature_mismatch' })
        installed_certificate_fingerprint = $installedCert.Digest.Substring(0, 12)
        version_relation = $relation
        installation_allowed = $sameSignature -and $candidateCode -ge $installedCode
        temporary_apk_removed = $true
    }
}

function Get-Alpha15ExitFromException {
    param([Management.Automation.ErrorRecord]$ErrorRecord)
    $exception = $ErrorRecord.Exception
    if ($exception.Data.Contains('Alpha15ExitCode')) {
        return [pscustomobject]@{ ExitCode = [int]$exception.Data['Alpha15ExitCode']; Reason = [string]$exception.Data['Alpha15Reason']; Message = $exception.Message }
    }
    return [pscustomobject]@{ ExitCode = 10; Reason = 'unexpected_error'; Message = 'Unexpected error; details were sanitized.' }
}

function Invoke-Alpha15PreflightCore {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ApkPath,
        [string]$Serial,
        [string]$AndroidSdkRoot,
        [string]$AdbPath,
        [string]$AaptPath,
        [string]$ApksignerPath,
        [string]$BuildToolsVersion,
        [switch]$AllowPreviewBuildTools,
        [switch]$AllowDifferentAlphaVersion,
        [switch]$ShowSensitiveIdentifiers
    )
    $report = [ordered]@{
        schema = 'health-tracker-alpha15-phone-preflight-v2'
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        status = 'error'
        exit_code = 10
        reason = 'unexpected_error'
        read_only = $true
    }
    $context = $null
    try {
        $toolchain = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $AndroidSdkRoot -AdbPath $AdbPath -AaptPath $AaptPath -ApksignerPath $ApksignerPath -BuildToolsVersion $BuildToolsVersion -AllowPreviewBuildTools:$AllowPreviewBuildTools -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
        $report.toolchain = $toolchain.Report
        $apk = Get-Alpha15ApkInfo -ApkPath $ApkPath -Toolchain $toolchain.Internal -AllowDifferentAlphaVersion:$AllowDifferentAlphaVersion -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
        $report.apk = $apk.Report

        $devices = @(Get-Alpha15ConnectedDevices $toolchain.Internal.Adb)
        $report.detected_devices = @($devices | ForEach-Object { [pscustomobject]@{ serial_fingerprint = $_.Fingerprint; state = $_.State } })
        $selected = Select-Alpha15Device $devices $Serial
        $device = Get-Alpha15DeviceInfo $toolchain.Internal.Adb $selected $apk.Report.size_bytes
        if (-not $ShowSensitiveIdentifiers) { $report.selected_device = $selected.Fingerprint } else { $report.selected_device = $selected.Serial }
        $report.device = $device
        if (-not $device.boot_completed) { Throw-Alpha15Failure 5 'boot_incomplete' 'Android boot has not completed.' }
        if ($null -eq $device.android_api -or $device.android_api -lt $apk.Report.min_sdk) { Throw-Alpha15Failure 5 'device_sdk_incompatible' 'Device API is lower than the APK minSdk.' }
        if ($apk.Report.native_code.Count -gt 0 -and $device.abi -notin $apk.Report.native_code) { Throw-Alpha15Failure 5 'device_abi_incompatible' 'Device ABI is not supported by the APK.' }
        if (-not $device.space_sufficient) { Throw-Alpha15Failure 8 'insufficient_space' 'Available storage is insufficient or could not be verified.' }

        $installed = Get-Alpha15InstalledPackageInfo $toolchain.Internal.Adb $selected.Serial $apk.Report.package
        $report.installed = $installed.Report
        $comparison = Compare-Alpha15InstalledPackage $installed $apk $toolchain.Internal.Adb $selected.Serial $toolchain.Internal.Apksigner $apk.Report.package
        $report.comparison = $comparison
        if ($comparison.status -eq 'signature_mismatch' -or $comparison.status -eq 'unable_to_verify') {
            Throw-Alpha15Failure 6 $comparison.status 'Installed signature compatibility could not be established.'
        }
        if ($comparison.version_relation -eq 'candidate_older') { Throw-Alpha15Failure 7 'candidate_older' 'Candidate versionCode is lower than the installed package.' }

        $report.status = 'ready'
        $report.exit_code = 0
        $report.reason = 'ready'
        $context = [pscustomobject]@{
            Toolchain = $toolchain.Internal
            Apk = $apk.Internal
            ApkReport = $apk.Report
            Serial = $selected.Serial
            SerialFingerprint = $selected.Fingerprint
            PackageName = $apk.Report.package
            InstalledBefore = $installed
        }
        return [pscustomobject]@{ ExitCode = 0; Report = [pscustomobject]$report; Context = $context }
    } catch {
        $failure = Get-Alpha15ExitFromException $_
        $report.status = 'blocked'
        $report.exit_code = $failure.ExitCode
        $report.reason = $failure.Reason
        $report.message = ConvertTo-Alpha15SafeLine $failure.Message
        return [pscustomobject]@{ ExitCode = $failure.ExitCode; Report = [pscustomobject]$report; Context = $context }
    }
}

function Invoke-Alpha15InstallCore {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ApkPath,
        [string]$Serial,
        [string]$AndroidSdkRoot,
        [string]$AdbPath,
        [string]$AaptPath,
        [string]$ApksignerPath,
        [string]$ConfirmInstall,
        [switch]$Launch
    )
    $installReport = [ordered]@{
        schema = 'health-tracker-alpha15-phone-install-v1'
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        status = 'blocked'
        exit_code = 2
        install_attempted = $false
        launch_requested = [bool]$Launch
    }
    try {
        if ([string]::IsNullOrWhiteSpace($ApkPath)) { Throw-Alpha15Failure 2 'apk_path_required' 'ApkPath is required.' }
        $preflight = Invoke-Alpha15PreflightCore -ApkPath $ApkPath -Serial $Serial -AndroidSdkRoot $AndroidSdkRoot `
            -AdbPath $AdbPath -AaptPath $AaptPath -ApksignerPath $ApksignerPath
        $installReport.preflight = $preflight.Report
        if ($preflight.ExitCode -ne 0) {
            $installReport.exit_code = $preflight.ExitCode
            $installReport.reason = 'preflight_blocked'
        } elseif ($ConfirmInstall -cne 'ALPHA15-INSTALL') {
            $installReport.exit_code = 2
            $installReport.reason = 'install_confirmation_required'
            $installReport.message = 'Pass -ConfirmInstall ALPHA15-INSTALL after reviewing preflight.'
        } else {
            $context = $preflight.Context
            $installReport.install_attempted = $true
            $install = Invoke-Alpha15Adb $context.Toolchain.Adb $context.Serial @('install', '-r', $context.Apk.Path)
            if ($install.ExitCode -ne 0 -or ($install.Lines -join "`n") -notmatch '(?i)Success') {
                Throw-Alpha15Failure 10 'adb_install_failed' 'adb install -r failed; no uninstall or retry was attempted.'
            }

            $installedAfter = Get-Alpha15InstalledPackageInfo $context.Toolchain.Adb $context.Serial $context.PackageName
            if (-not $installedAfter.Present) { Throw-Alpha15Failure 10 'post_install_package_missing' 'Package was not visible after installation.' }
            if ([long]$installedAfter.Report.version_code -ne [long]$context.ApkReport.version_code -or $installedAfter.Report.version_name -ne $context.ApkReport.version_name) {
                Throw-Alpha15Failure 10 'post_install_version_mismatch' 'Installed version did not match the candidate APK.'
            }
            $certificate = Get-Alpha15InstalledCertificate $context.Toolchain.Adb $context.Serial $context.PackageName $context.Toolchain.Apksigner
            if ($certificate.Status -ne 'verified' -or $certificate.Digest -ne $context.Apk.CertificateDigest) {
                Throw-Alpha15Failure 10 'post_install_signature_mismatch' 'Installed certificate did not match the candidate APK.'
            }

            $launchResult = 'not_requested'
            if ($Launch) {
                $component = Get-Alpha15LauncherComponent $context.Toolchain.Adb $context.Serial $context.PackageName
                if (-not $component) { Throw-Alpha15Failure 10 'launcher_activity_missing' 'Launcher activity could not be resolved.' }
                $launchCall = Invoke-Alpha15Adb $context.Toolchain.Adb $context.Serial @('shell', 'am', 'start', '-n', $component)
                if ($launchCall.ExitCode -ne 0) { Throw-Alpha15Failure 10 'launch_failed' 'Launcher activity failed to start.' }
                Start-Sleep -Seconds 2
                $launchResult = 'requested'
            }
            $process = Get-Alpha15ProcessState $context.Toolchain.Adb $context.Serial $context.PackageName
            $installReport.status = 'installed'
            $installReport.exit_code = 0
            $installReport.reason = 'installed_and_verified'
            $installReport.command_policy = 'adb install -r; no -d, -t, uninstall, pm clear, or grant-all'
            $installReport.installed = $installedAfter.Report
            $installReport.certificate_fingerprint = $certificate.Digest.Substring(0, 12)
            $installReport.process = $process
            $installReport.launch = $launchResult
        }
    } catch {
        $failure = Get-Alpha15ExitFromException $_
        $installReport.status = 'failed'
        $installReport.exit_code = $failure.ExitCode
        $installReport.reason = $failure.Reason
        $installReport.message = ConvertTo-Alpha15SafeLine $failure.Message
    }
    return [pscustomobject]@{ ExitCode = [int]$installReport.exit_code; Report = [pscustomobject]$installReport }
}

function Write-Alpha15Utf8Json {
    param([Parameter(Mandatory = $true)]$Value, [Parameter(Mandatory = $true)][string]$OutputPath)
    Assert-Alpha15SafeText $OutputPath 'OutputPath'
    $fullPath = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { [void][IO.Directory]::CreateDirectory($parent) }
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($fullPath, $json, (New-Object Text.UTF8Encoding($false)))
    return $fullPath
}

function Write-Alpha15TextFile {
    param([string]$Text, [string]$OutputPath)
    Assert-Alpha15SafeText $OutputPath 'OutputPath'
    $fullPath = [IO.Path]::GetFullPath($OutputPath)
    $parent = Split-Path -Parent $fullPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { [void][IO.Directory]::CreateDirectory($parent) }
    [IO.File]::WriteAllText($fullPath, $Text, (New-Object Text.UTF8Encoding($false)))
    return $fullPath
}

function Get-Alpha15LauncherComponent {
    param([string]$Adb, [string]$Serial, [string]$PackageName)
    $result = Invoke-Alpha15Adb $Adb $Serial @('shell', 'cmd', 'package', 'resolve-activity', '--brief', '-c', 'android.intent.category.LAUNCHER', $PackageName)
    if ($result.ExitCode -ne 0) { return $null }
    $component = @($result.Lines | Where-Object { $_ -match '^[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+$' } | Select-Object -Last 1)
    return $(if ($component.Count -eq 1) { $component[0].Trim() } else { $null })
}

function Get-Alpha15ProcessState {
    param([string]$Adb, [string]$Serial, [string]$PackageName)
    $result = Invoke-Alpha15Adb $Adb $Serial @('shell', 'pidof', $PackageName)
    $pidText = ($result.Lines -join '').Trim()
    return [pscustomobject]@{ running = $result.ExitCode -eq 0 -and $pidText -match '^\d+(\s+\d+)*$'; pid_available = $pidText -match '^\d+' }
}
