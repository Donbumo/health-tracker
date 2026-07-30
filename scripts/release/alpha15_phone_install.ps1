[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$Serial,
    [string]$AndroidSdkRoot,
    [string]$AdbPath,
    [string]$AaptPath,
    [string]$ApksignerPath,
    [string]$ConfirmInstall,
    [switch]$Launch,
    [string]$OutputPath,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage:
  alpha15_phone_install.ps1 -ApkPath <apk> [-Serial <exact-serial>]
    [-AndroidSdkRoot <sdk>] [-ConfirmInstall ALPHA15-INSTALL]
    [-Launch] [-OutputPath <json>] [-Help]

Runs the full read-only preflight first. Installation is allowed only with the
literal confirmation ALPHA15-INSTALL and uses exactly: adb install -r <apk>.
It never uses -d, uninstall, pm clear, grant-all, run-as, or permission changes.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')

$result = Invoke-Alpha15InstallCore -ApkPath $ApkPath -Serial $Serial -AndroidSdkRoot $AndroidSdkRoot `
    -AdbPath $AdbPath -AaptPath $AaptPath -ApksignerPath $ApksignerPath `
    -ConfirmInstall $ConfirmInstall -Launch:$Launch

if ($OutputPath) { [void](Write-Alpha15Utf8Json -Value $result.Report -OutputPath $OutputPath) }
$result.Report | ConvertTo-Json -Depth 12
exit $result.ExitCode
