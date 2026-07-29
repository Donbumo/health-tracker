[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$OutputPath,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: alpha15_apk_manifest.ps1 [-ApkPath <apk>] [-OutputPath <json>] [-Help]
Creates a local, secret-free JSON manifest next to the APK unless OutputPath is supplied.
'@
    exit 0
}

if (-not $ApkPath) {
    $ApkPath = Join-Path $PSScriptRoot '..\..\android\app\build\outputs\apk\debug\app-debug.apk'
}

function Find-AndroidTool([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $sdkRoots = @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME, (Join-Path $env:LOCALAPPDATA 'Android\Sdk')) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique
    foreach ($root in $sdkRoots) {
        $candidate = Get-ChildItem -LiteralPath (Join-Path $root 'build-tools') -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName "$Name.exe" } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    throw "Android tool not found: $Name"
}

$resolvedApk = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path
$aapt = Find-AndroidTool 'aapt'
$badging = (& $aapt dump badging $resolvedApk 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'aapt could not inspect the APK.' }

$packageMatch = [regex]::Match($badging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
$sdkMatch = [regex]::Match($badging, "sdkVersion:'([^']+)'"
)
$targetMatch = [regex]::Match($badging, "targetSdkVersion:'([^']+)'"
)
if (-not $packageMatch.Success -or -not $sdkMatch.Success -or -not $targetMatch.Success) {
    throw 'Required APK manifest fields were not found.'
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$commit = (& git -C $repoRoot rev-parse HEAD 2>$null).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Unable to read the Git commit.' }
$dirty = [bool]((& git -C $repoRoot status --porcelain=v1 -uno 2>$null) -join '')
$item = Get-Item -LiteralPath $resolvedApk
$manifest = [ordered]@{
    schema = 'health-tracker-alpha15-apk-manifest-v1'
    apk_file = $item.Name
    sha256 = (Get-FileHash -LiteralPath $resolvedApk -Algorithm SHA256).Hash.ToLowerInvariant()
    size_bytes = $item.Length
    package = $packageMatch.Groups[1].Value
    version_code = $packageMatch.Groups[2].Value
    version_name = $packageMatch.Groups[3].Value
    min_sdk = $sdkMatch.Groups[1].Value
    target_sdk = $targetMatch.Groups[1].Value
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    git_commit = $commit
    working_tree = $(if ($dirty) { 'dirty' } else { 'clean' })
}

if (-not $OutputPath) { $OutputPath = "$resolvedApk.alpha15-manifest.json" }
$parent = Split-Path -Parent $OutputPath
if ($parent -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw 'Output directory does not exist.'
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output (Resolve-Path -LiteralPath $OutputPath).Path
