[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$OutputPath,
    [string]$AndroidSdkRoot,
    [string]$AaptPath,
    [string]$ApksignerPath,
    [string]$BuildToolsVersion,
    [switch]$AllowPreviewBuildTools,
    [switch]$AllowDifferentAlphaVersion,
    [switch]$ShowSensitiveIdentifiers,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage:
  alpha15_apk_manifest.ps1 -ApkPath <apk> [-OutputPath <json>]
    [-AndroidSdkRoot <sdk>] [-AaptPath <file>] [-ApksignerPath <file>]
    [-BuildToolsVersion <version>] [-AllowPreviewBuildTools]
    [-AllowDifferentAlphaVersion] [-ShowSensitiveIdentifiers] [-Help]

Default output is a unique directory under the system temporary directory,
never android/app/build. RC1 mode requires package io.healthtracker.companion.debug,
versionCode 15, versionName 1.5.0-alpha01-debug, and a readable signature.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')

try {
    if ([string]::IsNullOrWhiteSpace($ApkPath)) { Throw-Alpha15Failure 2 'apk_path_required' 'ApkPath is required.' }
    $toolchain = Resolve-Alpha15AndroidToolchain -AndroidSdkRoot $AndroidSdkRoot -AaptPath $AaptPath `
        -ApksignerPath $ApksignerPath -BuildToolsVersion $BuildToolsVersion -AllowPreviewBuildTools:$AllowPreviewBuildTools
    $apk = Get-Alpha15ApkInfo -ApkPath $ApkPath -Toolchain $toolchain.Internal -AllowDifferentAlphaVersion:$AllowDifferentAlphaVersion

    $commitResult = Invoke-Alpha15External 'git' @('-C', $script:Alpha15RepositoryRoot, 'rev-parse', 'HEAD')
    $branchResult = Invoke-Alpha15External 'git' @('-C', $script:Alpha15RepositoryRoot, 'branch', '--show-current')
    $statusResult = Invoke-Alpha15External 'git' @('-C', $script:Alpha15RepositoryRoot, 'status', '--porcelain=v1', '-uno')
    if ($commitResult.ExitCode -ne 0 -or $branchResult.ExitCode -ne 0 -or $statusResult.ExitCode -ne 0) {
        Throw-Alpha15Failure 10 'git_state_unavailable' 'Git state could not be read.'
    }
    $manifest = [pscustomobject][ordered]@{
        schema = 'health-tracker-alpha15-apk-manifest-v2'
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        apk_file = $apk.Report.file
        sha256 = $apk.Report.sha256
        size_bytes = $apk.Report.size_bytes
        package = $apk.Report.package
        version_code = $apk.Report.version_code
        version_name = $apk.Report.version_name
        min_sdk = $apk.Report.min_sdk
        target_sdk = $apk.Report.target_sdk
        debuggable = $apk.Report.debuggable
        signature_valid = $apk.Report.signature_valid
        certificate_fingerprint = $apk.Report.certificate_fingerprint
        git_commit = ($commitResult.Lines -join '').Trim()
        git_branch = ($branchResult.Lines -join '').Trim()
        working_tree = $(if ($statusResult.Lines.Count -gt 0) { 'dirty' } else { 'clean' })
        alpha15_rc1_strict = -not [bool]$AllowDifferentAlphaVersion
        toolchain = $toolchain.Report
    }
    if (-not $OutputPath) {
        $directory = New-Alpha15TemporaryDirectory 'health-tracker-alpha15-apk-manifest'
        $OutputPath = Join-Path $directory 'apk-manifest.json'
    }
    $written = Write-Alpha15Utf8Json -Value $manifest -OutputPath $OutputPath
    Write-Output (ConvertTo-Alpha15ReportedFilePath $written -ShowSensitiveIdentifiers:$ShowSensitiveIdentifiers)
    exit 0
} catch {
    $failure = Get-Alpha15ExitFromException $_
    Write-Error ($failure.Reason + ': ' + (ConvertTo-Alpha15SafeLine $failure.Message))
    exit $failure.ExitCode
}
