[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$Serial,
    [string]$AndroidSdkRoot,
    [string]$AdbPath,
    [string]$AaptPath,
    [string]$ApksignerPath,
    [string]$BuildToolsVersion,
    [switch]$AllowPreviewBuildTools,
    [switch]$Json,
    [string]$OutputPath,
    [switch]$ShowSensitiveIdentifiers,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage:
  alpha15_phone_preflight.ps1 -ApkPath <apk> [-Serial <exact-serial>]
    [-AndroidSdkRoot <sdk>] [-AdbPath <file>] [-AaptPath <file>]
    [-ApksignerPath <file>] [-BuildToolsVersion <version>]
    [-AllowPreviewBuildTools] [-Json] [-OutputPath <json>]
    [-ShowSensitiveIdentifiers] [-Help]

Read-only by default and always: no install, launch, logcat clear, permission,
connectivity, app-data, /data, Room, DataStore, or Keystore mutation.

Exit codes:
  0 ready                 2 invalid arguments
  3 toolchain             4 APK validation
  5 device selection      6 signature incompatible/unverifiable
  7 candidate downgrade   8 insufficient/unverifiable storage
  9 unauthorized          10 unexpected sanitized error
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')

if ([string]::IsNullOrWhiteSpace($ApkPath)) {
    $result = [pscustomobject]@{
        ExitCode = 2
        Report = [pscustomobject][ordered]@{
            schema = 'health-tracker-alpha15-phone-preflight-v2'
            generated_at_utc = [DateTime]::UtcNow.ToString('o')
            status = 'blocked'
            exit_code = 2
            reason = 'apk_path_required'
            message = 'ApkPath is required.'
            read_only = $true
        }
    }
} else {
    $result = Invoke-Alpha15PreflightCore -ApkPath $ApkPath -Serial $Serial -AndroidSdkRoot $AndroidSdkRoot `
        -AdbPath $AdbPath -AaptPath $AaptPath -ApksignerPath $ApksignerPath `
        -BuildToolsVersion $BuildToolsVersion -AllowPreviewBuildTools:$AllowPreviewBuildTools `
        -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers
}

if ($OutputPath) { [void](Write-Alpha15Utf8Json -Value $result.Report -OutputPath $OutputPath) }
if ($Json) {
    $result.Report | ConvertTo-Json -Depth 12
} else {
    $result.Report | Format-List | Out-String | Write-Output
}
exit $result.ExitCode
