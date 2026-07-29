[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ApkPath,
    [string]$Serial,
    [switch]$Json,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
if ($Help) {
    @'
Usage: alpha15_phone_preflight.ps1 [-ApkPath <apk>] [-Serial <exact-serial>] [-Json] [-Help]
Read-only checks only. It never installs, uninstalls, clears app data, or reads /data.
Exit 0=ready, 2=device selection, 3=tool/APK issue, 4=compatibility issue.
'@
    exit 0
}

if (-not $ApkPath) {
    $ApkPath = Join-Path $PSScriptRoot '..\..\android\app\build\outputs\apk\debug\app-debug.apk'
}

function Fail([string]$Message, [int]$Code) { Write-Error $Message; exit $Code }
function Mask-Serial([string]$Value) {
    if ($Value.Length -le 4) { return ('*' * $Value.Length) }
    return ('*' * ($Value.Length - 4)) + $Value.Substring($Value.Length - 4)
}
function Find-Tool([string]$Name, [string]$Area) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $roots = @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME, (Join-Path $env:LOCALAPPDATA 'Android\Sdk')) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } | Select-Object -Unique
    foreach ($root in $roots) {
        $base = if ($Area -eq 'platform-tools') { Join-Path $root $Area } else {
            Get-ChildItem -LiteralPath (Join-Path $root $Area) -Directory -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
        if ($base) {
            $candidate = Join-Path $base "$Name.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }
    return $null
}

$adb = Find-Tool 'adb' 'platform-tools'
$aapt = Find-Tool 'aapt' 'build-tools'
$apksigner = Find-Tool 'apksigner' 'build-tools'
if (-not $adb -or -not $aapt -or -not $apksigner) { Fail 'adb, aapt, and apksigner are required.' 3 }
try { $resolvedApk = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path } catch { Fail 'APK not found.' 3 }

$adbVersion = ((& $adb version 2>&1) | Select-Object -First 1).ToString().Trim()
$deviceLines = & $adb devices 2>&1
if ($LASTEXITCODE -ne 0) { Fail 'adb could not list devices.' 3 }
$devices = @($deviceLines | Select-Object -Skip 1 | ForEach-Object {
    $parts = ($_ -split "\s+")
    if ($parts.Count -ge 2 -and $parts[1] -eq 'device') { $parts[0] }
} | Where-Object { $_ })
if ($Serial) {
    if ($Serial -notin $devices) { Fail 'The selected device is not connected and authorized.' 2 }
    $selected = $Serial
} elseif ($devices.Count -eq 1) {
    $selected = $devices[0]
} else {
    Fail "Expected one authorized device; found $($devices.Count). Use -Serial for an exact selection." 2
}

$badging = (& $aapt dump badging $resolvedApk 2>&1) -join "`n"
$packageMatch = [regex]::Match($badging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
if ($LASTEXITCODE -ne 0 -or -not $packageMatch.Success) { Fail 'Unable to inspect APK metadata.' 3 }
$signatureOutput = & $apksigner verify --verbose $resolvedApk 2>&1
if ($LASTEXITCODE -ne 0) { Fail 'APK signature verification failed.' 3 }

function Device-Prop([string]$Name) {
    ((& $adb -s $selected shell getprop $Name 2>$null) -join '').Trim()
}
$packageName = $packageMatch.Groups[1].Value
$installedDump = (& $adb -s $selected shell dumpsys package $packageName 2>$null) -join "`n"
$installed = $installedDump -match "Package \[$([regex]::Escape($packageName))\]"
$installedCode = $null
$installedName = $null
if ($installed) {
    $codeMatch = [regex]::Match($installedDump, 'versionCode=(\d+)')
    $nameMatch = [regex]::Match($installedDump, 'versionName=([^\r\n]+)')
    if ($codeMatch.Success) { $installedCode = [long]$codeMatch.Groups[1].Value }
    if ($nameMatch.Success) { $installedName = $nameMatch.Groups[1].Value.Trim() }
}
$apkCode = [long]$packageMatch.Groups[2].Value
$versionCompatible = -not $installed -or $installedCode -eq $null -or $apkCode -ge $installedCode
$spaceLine = ((& $adb -s $selected shell df -k /sdcard 2>$null) | Select-Object -Last 1).ToString().Trim()
$result = [ordered]@{
    ready_for_manual_install_r = $versionCompatible
    adb_version = $adbVersion
    connected_devices = @($devices | ForEach-Object { Mask-Serial $_ })
    selected_device = Mask-Serial $selected
    manufacturer = Device-Prop 'ro.product.manufacturer'
    model = Device-Prop 'ro.product.model'
    android_api = Device-Prop 'ro.build.version.sdk'
    android_version = Device-Prop 'ro.build.version.release'
    sdcard_space_kb = $spaceLine
    apk = [ordered]@{
        file = (Get-Item -LiteralPath $resolvedApk).Name
        sha256 = (Get-FileHash -LiteralPath $resolvedApk -Algorithm SHA256).Hash.ToLowerInvariant()
        package = $packageName
        version_code = $apkCode
        version_name = $packageMatch.Groups[3].Value
        signature_valid = $true
    }
    installed = [ordered]@{
        present = $installed
        version_code = $installedCode
        version_name = $installedName
    }
    compatibility_note = $(if ($versionCompatible) {
        'Package and version permit a manual adb install -r check; installed-signature equality is verified by Android at install time.'
    } else { 'APK versionCode is lower than the installed package; install -r would require a forbidden downgrade.' })
}
if ($Json) { $result | ConvertTo-Json -Depth 5 } else { $result | Format-List | Out-String | Write-Output }
if (-not $versionCompatible) { exit 4 }
exit 0
