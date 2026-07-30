[CmdletBinding()]
param(
    [string]$ApkPath,
    [string]$Serial,
    [string]$AndroidSdkRoot,
    [switch]$Preflight,
    [switch]$Install,
    [switch]$BasicSmoke,
    [switch]$Collect,
    [switch]$Report,
    [switch]$All,
    [string]$ConfirmInstall,
    [string]$ConfirmQa,
    [switch]$Launch,
    [switch]$Restart,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage:
  alpha15_phone_qa.ps1 -ApkPath <apk> [-Serial <exact-serial>]
    [-AndroidSdkRoot <sdk>] [-Preflight|-Install|-BasicSmoke|-Collect|-Report|-All]
    [-ConfirmInstall ALPHA15-INSTALL] [-ConfirmQa ALPHA15-QA]
    [-Launch] [-Restart] [-Help]

Default mode is -Preflight. Every invocation creates a unique session under:
  %TEMP%\health-tracker-alpha15-qa\<session-id>

-All requires both literal confirmations before any installation or QA action.
It never automates login/forms, stores credentials, changes networking or Health
Connect, grants permissions, clears app data, uninstalls, or reads private data.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')

function Get-Alpha15PowerShellExecutable {
    foreach ($name in @('powershell.exe', 'pwsh.exe')) {
        $candidate = Join-Path $PSHOME $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    $command = Get-Command powershell.exe, pwsh.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    Throw-Alpha15Failure 3 'powershell_not_found' 'A PowerShell executable could not be resolved.'
}

function Invoke-Alpha15ChildScript {
    param([string]$ScriptPath, [string[]]$Arguments)
    $hostExecutable = Get-Alpha15PowerShellExecutable
    return Invoke-Alpha15External $hostExecutable (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $Arguments)
}

function New-Alpha15QaChecklist {
    $items = @(
        'Login', 'Cold start', 'Hoy', 'Entrenamiento descargado', 'Start offline', 'Autosave', 'Process death',
        'Continue', 'Complete', 'Autosync', 'Plan', 'Programación', 'Historial', 'Progreso', 'Peso', 'Nutrición',
        'Pasos', 'Health Connect', 'Permisos parciales', 'Revocación parcial', 'Servidor offline', 'Reconexión',
        'Pendientes 0', 'Conflictos 0', 'Sin duplicados', 'Sin crash', 'Sin logout inesperado', 'Sin secretos'
    )
    $lines = New-Object System.Collections.ArrayList
    [void]$lines.Add('# Sesión QA manual Alpha 1.5')
    [void]$lines.Add('')
    [void]$lines.Add('Este checklist requiere observación humana y datos ficticios. Ninguna casilla se aprueba por scripts o fakes.')
    [void]$lines.Add('')
    foreach ($item in $items) { [void]$lines.Add("- [ ] $item") }
    [void]$lines.Add('')
    [void]$lines.Add('## Conservación pre/post actualización')
    [void]$lines.Add('')
    foreach ($item in @('Package presente antes y después', 'Login conservado', 'Servidor conservado', 'Room/Historial conservados', 'DataStore/preferencias conservados', 'Keystore/sesión conservados', 'Draft activo conservado', 'Planes conservados', 'Health cache/ledger conservados', 'Operaciones pendientes conservadas')) {
        [void]$lines.Add("- [ ] $item")
    }
    [void]$lines.Add('')
    [void]$lines.Add('No declarar preservación aprobada hasta completar este bloque en teléfono físico.')
    return (($lines -join "`r`n") + "`r`n")
}

$selectedModes = @(@($Preflight, $Install, $BasicSmoke, $Collect, $Report, $All) | Where-Object { $_ }).Count
if ($selectedModes -eq 0) { $Preflight = $true; $selectedModes = 1 }
if ($selectedModes -gt 1) {
    Write-Error 'Select exactly one mode.'
    exit 2
}
if ($All -and ($ConfirmInstall -cne 'ALPHA15-INSTALL' -or $ConfirmQa -cne 'ALPHA15-QA')) {
    Write-Error 'All mode requires -ConfirmInstall ALPHA15-INSTALL and -ConfirmQa ALPHA15-QA.'
    exit 2
}
if (($Preflight -or $Install -or $All) -and [string]::IsNullOrWhiteSpace($ApkPath)) {
    Write-Error 'ApkPath is required for preflight/install/all.'
    exit 2
}

$sessionRoot = Join-Path ([IO.Path]::GetTempPath()) 'health-tracker-alpha15-qa'
[void][IO.Directory]::CreateDirectory($sessionRoot)
$sessionId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$sessionDirectory = Join-Path $sessionRoot $sessionId
[void][IO.Directory]::CreateDirectory($sessionDirectory)

$summary = [ordered]@{
    schema = 'health-tracker-alpha15-phone-qa-session-v1'
    session_id = $sessionId
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    mode = $(if ($All) { 'all' } elseif ($Install) { 'install' } elseif ($BasicSmoke) { 'basic_smoke' } elseif ($Collect) { 'collect' } elseif ($Report) { 'report' } else { 'preflight' })
    session_directory = '<TEMP>\health-tracker-alpha15-qa\' + $sessionId
    status = 'created'
    phone_mutation = 'none'
}
$exitCode = 0

try {
    [void](Write-Alpha15TextFile -Text (New-Alpha15QaChecklist) -OutputPath (Join-Path $sessionDirectory 'qa-checklist.md'))

    if ($Preflight -or $Install -or $All) {
        $preflightPath = Join-Path $sessionDirectory 'preflight.json'
        $preflight = Invoke-Alpha15PreflightCore -ApkPath $ApkPath -Serial $Serial -AndroidSdkRoot $AndroidSdkRoot
        [void](Write-Alpha15Utf8Json -Value $preflight.Report -OutputPath $preflightPath)
        $summary.preflight_exit_code = $preflight.ExitCode
        if ($preflight.Report.PSObject.Properties.Name -contains 'installed') {
            [void](Write-Alpha15Utf8Json -Value $preflight.Report.installed -OutputPath (Join-Path $sessionDirectory 'package-before.json'))
        }
        if ($preflight.ExitCode -ne 0) { $exitCode = $preflight.ExitCode; $summary.status = 'preflight_blocked' }
    }

    if (($Install -or $All) -and $exitCode -eq 0) {
        $installPath = Join-Path $sessionDirectory 'install.json'
        $arguments = @('-ApkPath', $ApkPath, '-ConfirmInstall', $ConfirmInstall, '-OutputPath', $installPath)
        if ($Serial) { $arguments += @('-Serial', $Serial) }
        if ($AndroidSdkRoot) { $arguments += @('-AndroidSdkRoot', $AndroidSdkRoot) }
        if ($Launch -or $All) { $arguments += '-Launch' }
        $child = Invoke-Alpha15ChildScript (Join-Path $PSScriptRoot 'alpha15_phone_install.ps1') $arguments
        $exitCode = $child.ExitCode
        $summary.install_exit_code = $exitCode
        if (Test-Path -LiteralPath $installPath) {
            $installJson = Get-Content -Raw -LiteralPath $installPath | ConvertFrom-Json
            if ($installJson.install_attempted -eq $true) { $summary.phone_mutation = 'adb_install_r_confirmed' }
            if ($installJson.PSObject.Properties.Name -contains 'installed') {
                [void](Write-Alpha15Utf8Json -Value $installJson.installed -OutputPath (Join-Path $sessionDirectory 'package-after.json'))
            }
        }
        if ($exitCode -ne 0) { $summary.status = 'install_failed' }
    }

    if (($BasicSmoke -or $Collect -or $All) -and $exitCode -eq 0) {
        $smokePath = Join-Path $sessionDirectory 'smoke.json'
        $arguments = @('-OutputPath', $smokePath, '-Json')
        if ($Serial) { $arguments += @('-Serial', $Serial) }
        if ($AndroidSdkRoot) { $arguments += @('-AndroidSdkRoot', $AndroidSdkRoot) }
        if ($Launch -or $All) { $arguments += '-Launch' }
        if ($Restart -or $All) { $arguments += '-Restart' }
        if ($Collect -or $All) { $arguments += '-CollectLogs' }
        $child = Invoke-Alpha15ChildScript (Join-Path $PSScriptRoot 'alpha15_phone_smoke.ps1') $arguments
        $exitCode = $child.ExitCode
        $summary.smoke_exit_code = $exitCode
        if ($Launch -or $Restart -or $All) { $summary.phone_mutation = $(if ($summary.phone_mutation -eq 'none') { 'explicit_launch_or_restart' } else { $summary.phone_mutation + '_and_launch_restart' }) }
        if (Test-Path -LiteralPath $smokePath) {
            $smokeJson = Get-Content -Raw -LiteralPath $smokePath | ConvertFrom-Json
            if ($smokeJson.PSObject.Properties.Name -contains 'logs') {
                [void](Write-Alpha15Utf8Json -Value $smokeJson.logs -OutputPath (Join-Path $sessionDirectory 'sanitized-log-findings.json'))
            }
        }
        if ($exitCode -ne 0) { $summary.status = 'smoke_attention_required' }
    }

    if ($exitCode -eq 0) { $summary.status = $(if ($Report) { 'manual_report_ready' } else { 'automated_scope_complete' }) }
} catch {
    $failure = Get-Alpha15ExitFromException $_
    $exitCode = $failure.ExitCode
    $summary.status = 'failed'
    $summary.reason = $failure.Reason
    $summary.message = ConvertTo-Alpha15SafeLine $failure.Message
} finally {
    $summary.exit_code = $exitCode
    [void](Write-Alpha15Utf8Json -Value ([pscustomobject]$summary) -OutputPath (Join-Path $sessionDirectory 'summary.json'))
}

Write-Output ('Session: ' + $summary.session_directory)
Write-Output ('Status: ' + $summary.status)
exit $exitCode
