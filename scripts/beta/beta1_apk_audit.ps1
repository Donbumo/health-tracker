[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$SessionId,
    [string]$SdkRoot,
    [string]$ProjectRoot,
    [string]$ReportRoot,
    [switch]$AllowNonBetaVersion,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: beta1_apk_audit.ps1 [-ApkPath <apk>] [-SessionId <id>] [-SdkRoot <path>]
       [-ProjectRoot <repo>] [-ReportRoot <path>] [-AllowNonBetaVersion] [-Help]
Inspects package/version/SDK/debuggable/signature/permissions/ZIP entries and reports only
sensitive-pattern names and counts. The JSON report is written outside the repository.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
if (-not $ProjectRoot) { $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path }
else { $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path }
if (-not $ApkPath) { $ApkPath = Join-Path $ProjectRoot 'android\app\build\outputs\apk\debug\app-debug.apk' }
$resolvedApk = (Resolve-Path -LiteralPath $ApkPath -ErrorAction Stop).Path
$SessionId = Get-Beta1SessionId $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$reportPath = Join-Path $sessionRoot 'apk-audit.json'

try {
    $resolvedSdk = Resolve-Beta1SdkRoot $SdkRoot $ProjectRoot
    try { $aapt = Find-Beta1AndroidTool $resolvedSdk 'build-tools' 'aapt' }
    catch { $aapt = Find-Beta1AndroidTool $resolvedSdk 'build-tools' 'aapt2' }
    $apksigner = Find-Beta1AndroidTool $resolvedSdk 'build-tools' 'apksigner'
    $badging = (& $aapt dump badging $resolvedApk 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'aapt_badging_failed' }
    $packageMatch = [regex]::Match($badging, "package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'")
    $minMatch = [regex]::Match($badging, "sdkVersion:'([^']+)'")
    $targetMatch = [regex]::Match($badging, "targetSdkVersion:'([^']+)'")
    if (-not $packageMatch.Success -or -not $minMatch.Success -or -not $targetMatch.Success) { throw 'apk_metadata_missing' }
    if (-not $AllowNonBetaVersion) {
        Test-Beta1ApkIdentity $packageMatch.Groups[1].Value ([long]$packageMatch.Groups[2].Value)
        if ($packageMatch.Groups[3].Value -ne '2.0.0-beta01-debug') { throw 'apk_version_name_mismatch' }
    }

    $signature = (& $apksigner verify --verbose $resolvedApk 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'apk_signature_invalid' }
    $v2 = $signature -match '(?im)Verified using v2 scheme.*:\s*true'
    $v3 = $signature -match '(?im)Verified using v3 scheme.*:\s*true'
    if (-not $v2 -and -not $v3) { throw 'apk_modern_signature_missing' }

    $permissions = @([regex]::Matches($badging, "uses-permission(?:-sdk-\d+)?: name='([^']+)'" ) |
        ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($resolvedApk)
    try {
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName })
    } finally {
        $archive.Dispose()
    }
    $forbiddenEntryPatterns = @(
        [ordered]@{ name = 'dotenv'; regex = '(^|/)\.env($|\.)'; classification = 'blocking' },
        [ordered]@{ name = 'local_properties'; regex = '(^|/)local\.properties$'; classification = 'blocking' },
        [ordered]@{ name = 'keystore'; regex = '\.(?:jks|keystore|p12|pfx)$'; classification = 'blocking' },
        [ordered]@{ name = 'database_or_dump'; regex = '\.(?:db|sqlite|sqlite3|dump|sql)$'; classification = 'blocking' },
        [ordered]@{ name = 'personal_activity'; regex = '\.(?:fit|gpx|tcx)$'; classification = 'blocking_review' },
        [ordered]@{ name = 'embedded_private_payload'; regex = '^(?:assets|res/raw)/.*\.(?:pdf|jpe?g|png|zip|htpack)$'; classification = 'blocking_review' },
        [ordered]@{ name = 'logs_or_screenshots'; regex = '\.(?:log|trace)$|(^|/)screenshots?/'; classification = 'blocking_review' }
    )
    $entryFindings = @()
    foreach ($pattern in $forbiddenEntryPatterns) {
        $count = @($entryNames | Where-Object { $_ -match $pattern.regex }).Count
        $entryFindings += [ordered]@{ pattern = $pattern.name; count = $count; classification = $pattern.classification }
    }

    $ascii = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($resolvedApk))
    $contentPatterns = @(
        [ordered]@{ name = 'private_key_pem'; regex = '-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'; classification = 'blocking' },
        [ordered]@{ name = 'bearer_literal'; regex = 'Bearer\s+[A-Za-z0-9._~+/-]{20,}'; classification = 'blocking' },
        [ordered]@{ name = 'authorization_label'; regex = 'Authorization'; classification = 'expected_protocol_label' },
        [ordered]@{ name = 'password_label'; regex = 'password|contrase(?:n|ñ)a'; classification = 'expected_login_label' },
        [ordered]@{ name = 'emulator_loopback'; regex = '10\.0\.2\.2'; classification = 'debug_review' },
        [ordered]@{ name = 'private_ipv4'; regex = '(?<!\d)(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}(?!\d)'; classification = 'blocking_review' },
        [ordered]@{ name = 'nas_hostname_label'; regex = '(?i)(?:nas|synology)\.[a-z0-9.-]+'; classification = 'blocking_review' }
    )
    $contentFindings = @()
    foreach ($pattern in $contentPatterns) {
        $count = [regex]::Matches($ascii, $pattern.regex, [Text.RegularExpressions.RegexOptions]::IgnoreCase).Count
        $contentFindings += [ordered]@{ pattern = $pattern.name; count = $count; classification = $pattern.classification }
    }
    $blockingEntries = @($entryFindings | Where-Object { $_.classification -eq 'blocking' -and $_.count -gt 0 }).Count
    $blockingContent = @($contentFindings | Where-Object { $_.classification -eq 'blocking' -and $_.count -gt 0 }).Count
    $item = Get-Item -LiteralPath $resolvedApk
    $report = [ordered]@{
        schema = 'health-tracker-beta1-apk-audit-v1'
        session_id = $SessionId
        apk_file = $item.Name
        size_bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $resolvedApk -Algorithm SHA256).Hash.ToLowerInvariant()
        package = $packageMatch.Groups[1].Value
        version_code = [long]$packageMatch.Groups[2].Value
        version_name = $packageMatch.Groups[3].Value
        min_sdk = [int]$minMatch.Groups[1].Value
        target_sdk = [int]$targetMatch.Groups[1].Value
        debuggable = ($badging -match '(?m)^application-debuggable')
        signature_v2 = $v2
        signature_v3 = $v3
        permissions = $permissions
        entry_count = $entryNames.Count
        entry_pattern_findings = $entryFindings
        content_pattern_findings = $contentFindings
        blocking_findings = $blockingEntries + $blockingContent
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Beta1Json $report $reportPath 10
    if ($report.blocking_findings -gt 0) { throw 'apk_sensitive_pattern_blocking_finding' }
    Write-Output "APK audit passed; report: $reportPath"
    exit 0
} catch {
    if (-not (Test-Path -LiteralPath $reportPath)) {
        Write-Beta1Json ([ordered]@{
            schema = 'health-tracker-beta1-apk-audit-v1'
            session_id = $SessionId
            status = 'failed'
            error_code = $_.Exception.Message
            generated_at_utc = [DateTime]::UtcNow.ToString('o')
        }) $reportPath
    }
    [Console]::Error.WriteLine("Beta 1 APK audit failed: " + $_.Exception.Message)
    exit 4
}
