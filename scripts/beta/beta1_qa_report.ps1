[CmdletBinding()]
param(
    [string]$SessionId,
    [string]$ProjectRoot,
    [string]$ReportRoot,
    [int]$BackendPassed = 0,
    [int]$BackendSkipped = 0,
    [int]$AndroidJvmPassed = 0,
    [int]$AndroidJvmSkipped = 0,
    [string[]]$BlockedGate = @(),
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: beta1_qa_report.ps1 [-SessionId <id>] [-ProjectRoot <repo>] [-ReportRoot <path>]
       [-BackendPassed N] [-BackendSkipped N] [-AndroidJvmPassed N] [-AndroidJvmSkipped N]
       [-BlockedGate <code...>] [-Help]
Combines Beta 1 JSON artifacts with a read-only Git/repository summary. It never stages files.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
if (-not $ProjectRoot) { $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path }
else { $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path }
$SessionId = Get-Beta1SessionId $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$reportPath = Join-Path $sessionRoot 'beta1-qa-report.json'

function Invoke-GitText {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $value = (& git -C $ProjectRoot @Arguments 2>$null) -join "`n"
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw ('git_read_failed:' + ($Arguments -join '_')) }
    return $value.Trim()
}

function Read-OptionalJson {
    param([Parameter(Mandatory = $true)][string]$Name)
    $path = Join-Path $sessionRoot $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    return (Get-Content -Raw -Encoding UTF8 -LiteralPath $path | ConvertFrom-Json)
}

try {
    $branch = Invoke-GitText @('branch', '--show-current')
    $head = Invoke-GitText @('rev-parse', 'HEAD')
    $status = Invoke-GitText @('status', '--porcelain=v1')
    $staged = Invoke-GitText @('diff', '--cached', '--name-only')
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $diffCheck = (& git -C $ProjectRoot diff --check 2>$null) -join "`n"
        $diffCheckCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $nameStatus = Invoke-GitText @('diff', '--name-status')
    $diffStat = Invoke-GitText @('diff', '--stat')

    $suspicious = @(Get-ChildItem -LiteralPath $ProjectRoot -File -Force | Where-Object {
        $_.Name -match '^(status|tatus|branch|commit|diff|powershell|gradlew|adb)'
    } | ForEach-Object {
        [ordered]@{
            name_fingerprint = Get-Beta1TextFingerprint $_.Name
            size_bytes = $_.Length
            created_at_utc = $_.CreationTimeUtc.ToString('o')
            modified_at_utc = $_.LastWriteTimeUtc.ToString('o')
        }
    })

    $avd = Read-OptionalJson 'avd.json'
    $instrumentation = Read-OptionalJson 'instrumentation.json'
    $apk = Read-OptionalJson 'apk-audit.json'
    $cleanup = Read-OptionalJson 'avd-cleanup.json'
    $report = [ordered]@{
        schema = 'health-tracker-beta1-qa-report-v1'
        session_id = $SessionId
        branch = $branch
        head = $head
        expected_initial_head = '1093d4d14c7aa52f180ed7d1ba17cea5437dc896'
        freeze = 'android-2.0-beta1-stabilization-no-new-product-features'
        backend = [ordered]@{ passed = $BackendPassed; skipped = $BackendSkipped }
        android_jvm = [ordered]@{ passed = $AndroidJvmPassed; skipped = $AndroidJvmSkipped }
        avd = $avd
        instrumentation = $instrumentation
        apk = $apk
        avd_cleanup = $cleanup
        blocked_gates = @($BlockedGate)
        repository = [ordered]@{
            status_porcelain = @($status -split "`n" | Where-Object { $_ })
            changed_name_status = @($nameStatus -split "`n" | Where-Object { $_ })
            diff_stat = $diffStat
            diff_check_exit_code = $diffCheckCode
            diff_check_output = $diffCheck.Trim()
            staging_empty = [string]::IsNullOrWhiteSpace($staged)
            suspicious_root_artifacts = $suspicious
        }
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    Write-Beta1Json $report $reportPath 14
    if ($branch -ne 'beta/android-1.0-stabilization' -or $head -ne $report.expected_initial_head -or
        $diffCheckCode -ne 0 -or -not $report.repository.staging_empty) {
        throw 'repository_gate_failed'
    }
    Write-Output "Beta 1 QA report written outside the repository: $reportPath"
    exit 0
} catch {
    [Console]::Error.WriteLine("Beta 1 QA report failed: " + $_.Exception.Message)
    exit 4
}
