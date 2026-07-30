Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command Invoke-Alpha15Adb -ErrorAction SilentlyContinue)) {
    . (Join-Path $PSScriptRoot 'alpha15_phone_common.ps1')
}

function Get-Alpha15LogTimestamp {
    param([string]$Line)
    $match = [regex]::Match($Line, '^(\d{2}-\d{2}\s+\d{2}:\d{2})')
    return $(if ($match.Success) { $match.Groups[1].Value } else { 'unknown' })
}

function Get-Alpha15SecretClassification {
    param([string]$Line)
    if ($Line -match '(?i)fixture|mock|example|test[_ -]?token|\[REDACTED\]') { return 'test_fixture' }
    if ($Line -match '(?i)(Authorization|Bearer|access[_ -]?token|refresh[_ -]?token|SECRET_KEY|API_TOKEN_SIGNING_KEY|cookie)\s*[:=]\s*\S{4,}') {
        return 'real_candidate'
    }
    if ($Line -match '(?i)Authorization|Bearer|access[_ -]?token|refresh[_ -]?token|SECRET_KEY|API_TOKEN_SIGNING_KEY|cookie') {
        return 'generic_identifier'
    }
    return 'unknown'
}

function Find-Alpha15SanitizedLogFindings {
    param([string[]]$Lines)
    $rules = @(
        [pscustomobject]@{ Code = 'fatal_exception'; Category = 'crash'; Pattern = '(?i)FATAL EXCEPTION' },
        [pscustomobject]@{ Code = 'android_runtime'; Category = 'crash'; Pattern = '(?i)AndroidRuntime' },
        [pscustomobject]@{ Code = 'anr'; Category = 'anr'; Pattern = '(?i)ANR in' },
        [pscustomobject]@{ Code = 'process_died'; Category = 'crash'; Pattern = '(?i)Process .* has died' },
        [pscustomobject]@{ Code = 'sqlite_exception'; Category = 'persistence'; Pattern = '(?i)SQLiteException' },
        [pscustomobject]@{ Code = 'room'; Category = 'persistence'; Pattern = '(?i)\bRoom\b' },
        [pscustomobject]@{ Code = 'migration'; Category = 'persistence'; Pattern = '(?i)\bmigration\b' },
        [pscustomobject]@{ Code = 'draft_payload_hash_mismatch'; Category = 'persistence'; Pattern = 'draft_payload_hash_mismatch' },
        [pscustomobject]@{ Code = 'draft_package_missing'; Category = 'persistence'; Pattern = 'draft_package_missing' },
        [pscustomobject]@{ Code = 'schema_incompatible'; Category = 'persistence'; Pattern = 'SCHEMA_INCOMPATIBLE' },
        [pscustomobject]@{ Code = 'unknown_host'; Category = 'network'; Pattern = '(?i)UnknownHostException' },
        [pscustomobject]@{ Code = 'connect_exception'; Category = 'network'; Pattern = '(?i)ConnectException' },
        [pscustomobject]@{ Code = 'socket_timeout'; Category = 'network'; Pattern = '(?i)SocketTimeoutException' },
        [pscustomobject]@{ Code = 'tls_handshake'; Category = 'network'; Pattern = '(?i)SSLHandshakeException' },
        [pscustomobject]@{ Code = 'certificate_exception'; Category = 'network'; Pattern = '(?i)CertificateException' },
        [pscustomobject]@{ Code = 'http_error'; Category = 'network'; Pattern = '(?i)HTTP\s+[45]\d\d' },
        [pscustomobject]@{ Code = 'provider_unavailable'; Category = 'health_connect'; Pattern = '(?i)provider unavailable' },
        [pscustomobject]@{ Code = 'permission_revoked'; Category = 'health_connect'; Pattern = '(?i)permission revoked' },
        [pscustomobject]@{ Code = 'changes_token'; Category = 'health_connect'; Pattern = '(?i)changes token' },
        [pscustomobject]@{ Code = 'recoverable_sync'; Category = 'health_connect'; Pattern = '(?i)recoverable sync' },
        [pscustomobject]@{ Code = 'sensitive_identifier'; Category = 'secret'; Pattern = '(?i)Authorization|Bearer|access[_ -]?token|refresh[_ -]?token|SECRET_KEY|API_TOKEN_SIGNING_KEY|cookie' }
    )
    $findings = New-Object System.Collections.ArrayList
    foreach ($line in $Lines) {
        foreach ($rule in $rules) {
            if ($line -notmatch $rule.Pattern) { continue }
            $classification = $(if ($rule.Category -eq 'secret') { Get-Alpha15SecretClassification $line } else { 'not_applicable' })
            [void]$findings.Add([pscustomobject][ordered]@{
                category = $rule.Category
                pattern = $rule.Code
                timestamp = Get-Alpha15LogTimestamp $line
                origin = 'logcat'
                classification = $classification
                content = '[REDACTED]'
            })
        }
    }
    return @($findings)
}

function Get-Alpha15SanitizedLogs {
    [CmdletBinding()]
    param(
        [string]$Adb,
        [string]$Serial,
        [string]$PackageName,
        [ValidateRange(20, 5000)][int]$LastLines = 500,
        [string]$Since,
        [string[]]$Buffers = @('main', 'system', 'crash'),
        [string]$RawOutputPath
    )
    Assert-Alpha15SafeText $Since 'Since'
    foreach ($buffer in $Buffers) {
        if ($buffer -notin @('main', 'system', 'crash')) { Throw-Alpha15Failure 2 'invalid_log_buffer' 'Unsupported logcat buffer.' }
    }
    $arguments = @('logcat', '-d')
    foreach ($buffer in $Buffers) { $arguments += @('-b', $buffer) }
    if ($Since) { $arguments += @('-T', $Since) } else { $arguments += @('-t', $LastLines.ToString()) }

    $process = Get-Alpha15ProcessState $Adb $Serial $PackageName
    if ($process.running) {
        $pidResult = Invoke-Alpha15Adb $Adb $Serial @('shell', 'pidof', $PackageName)
        $pid = ($pidResult.Lines -join '').Trim().Split(' ')[0]
        if ($pid -match '^\d+$') { $arguments += @('--pid', $pid) }
    }
    $result = Invoke-Alpha15Adb $Adb $Serial $arguments
    if ($result.ExitCode -ne 0) { Throw-Alpha15Failure 5 'logcat_query_failed' 'Bounded logcat query failed.' }
    $lines = @($result.Lines | Select-Object -Last $LastLines)
    if ($RawOutputPath) {
        $fullRaw = [IO.Path]::GetFullPath($RawOutputPath)
        if (Test-Alpha15PathUnderRoot $fullRaw $script:Alpha15RepositoryRoot) {
            Throw-Alpha15Failure 2 'raw_logs_inside_repository' 'Raw logcat must be written outside the repository.'
        }
        [void](Write-Alpha15TextFile -Text (($lines -join "`r`n") + "`r`n") -OutputPath $fullRaw)
    }
    $findings = @(Find-Alpha15SanitizedLogFindings $lines)
    return [pscustomobject][ordered]@{
        requested_line_limit = $LastLines
        buffers = @($Buffers)
        since = $(if ($Since) { $Since } else { $null })
        pid_filter_applied = $process.running
        raw_log_saved = [bool]$RawOutputPath
        raw_log_warning = $(if ($RawOutputPath) { 'Raw logcat may contain sensitive data; keep it outside the repository and delete it after review.' } else { $null })
        finding_count = $findings.Count
        findings = $findings
        crash_detected = [bool]@($findings | Where-Object { $_.category -eq 'crash' }).Count
        anr_detected = [bool]@($findings | Where-Object { $_.category -eq 'anr' }).Count
        sensitive_log_candidate = [bool]@($findings | Where-Object { $_.category -eq 'secret' -and $_.classification -in @('real_candidate', 'unknown') }).Count
    }
}
