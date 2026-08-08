[CmdletBinding()]
param(
    [string]$SessionId,
    [string]$ProjectRoot,
    [string]$ReportRoot,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: run_beta1_mariadb.ps1 [-SessionId <id>] [-ProjectRoot <repo>] [-ReportRoot <path>] [-Help]
Builds a disposable QA image, runs migration cycles and the full backend suite
against MariaDB 11.4 on tmpfs, then removes only the resources it created.
It never invokes Docker Compose or creates a Docker volume.
'@
    exit 0
}

. (Join-Path $PSScriptRoot 'alpha20_beta1_common.ps1')
if (-not $ProjectRoot) { $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path }
else { $ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path }
$SessionId = Get-Beta1SessionId $SessionId
$sessionRoot = Get-Beta1SessionRoot $SessionId $ReportRoot
$reportPath = Join-Path $sessionRoot 'mariadb-isolated.json'
$logPath = Join-Path $sessionRoot 'mariadb-isolated.log'
$resourceSuffix = (Get-Beta1TextFingerprint $SessionId)
$networkName = "ht-beta1-net-$resourceSuffix"
$dbContainer = "ht-beta1-db-$resourceSuffix"
$imageName = "health-tracker-beta1-qa:$resourceSuffix"
$storageParent = Join-Path ([IO.Path]::GetTempPath()) 'health-tracker-beta1-storage'
$storageRoot = Join-Path $storageParent $SessionId
$dbSchema = 'health_tracker_beta1_qa'
$dbUser = 'beta1_qa'
$dbPassword = 'qa-' + [Guid]::NewGuid().ToString('N')
$rootPassword = 'root-qa-' + [Guid]::NewGuid().ToString('N')
$secretKey = 'web-qa-' + [Guid]::NewGuid().ToString('N')
$tokenKey = 'token-qa-' + [Guid]::NewGuid().ToString('N')
$createdNetwork = $false
$createdContainer = $false
$createdImage = $false
$createdStorage = $false
$zeroToHeadPassed = $false
$cycleCount = 0
$testsPassed = $false
$cleanupPassed = $false
$failure = $null
$started = [DateTime]::UtcNow

function Invoke-DockerChecked {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($output.Count -gt 0) {
        $output | Tee-Object -FilePath $logPath -Append | Write-Output
    }
    if ($exitCode -ne 0) { throw "docker_command_failed_exit_$exitCode" }
}

function Invoke-AppChecked {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $dockerArguments = @(
        'run', '--rm', '--network', $networkName,
        '-e', "DB_HOST=$dbContainer", '-e', 'DB_PORT=3306',
        '-e', "DB_NAME=$dbSchema", '-e', "DB_USER=$dbUser", '-e', "DB_PASSWORD=$dbPassword",
        '-e', "SECRET_KEY=$secretKey", '-e', "API_TOKEN_SIGNING_KEY=$tokenKey",
        '-e', 'DATA_ROOT=/tmp/health-tracker-beta1-data', '-e', 'SCHEMA_ROOT=/app/schemas',
        '-e', 'APP_TIMEZONE=UTC', '-e', 'GUNICORN_TIMEOUT=60', '-e', 'GUNICORN_KEEP_ALIVE=5',
        '--entrypoint', 'python', $imageName
    ) + $Arguments
    Invoke-DockerChecked $dockerArguments
}

function Test-DockerObjectExists {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @Arguments 2>$null | Out-Null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    return ($exitCode -eq 0)
}

try {
    New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null
    if (Test-DockerObjectExists @('container', 'inspect', $dbContainer)) { throw 'qa_container_name_already_exists' }
    if (Test-DockerObjectExists @('network', 'inspect', $networkName)) { throw 'qa_network_name_already_exists' }
    if (Test-DockerObjectExists @('image', 'inspect', $imageName)) { throw 'qa_image_name_already_exists' }
    if (Test-Path -LiteralPath $storageRoot) { throw 'qa_storage_path_already_exists' }

    $dailyBefore = @(& docker ps --format '{{.Names}}|{{.ID}}' --filter 'name=^/health-tracker-' | Sort-Object)
    if ($LASTEXITCODE -ne 0) { throw 'docker_daily_inventory_failed' }
    $volumesBefore = @(& docker volume ls --format '{{.Name}}' | Sort-Object)
    if ($LASTEXITCODE -ne 0) { throw 'docker_volume_inventory_failed' }
    New-Item -ItemType Directory -Path $storageRoot -Force | Out-Null
    $createdStorage = $true

    $dockerfile = @'
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FLASK_APP=app:create_app
WORKDIR /app
COPY backend/requirements-dev.txt ./requirements-dev.txt
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY backend/ ./
COPY schemas/ /app/schemas/
COPY schemas/ /schemas/
COPY examples/ /examples/
COPY scripts/release/ /app/scripts/release/
COPY scripts/portability/ /app/scripts/portability/
RUN addgroup --system app && adduser --system --ingroup app app && mkdir -p /tmp/health-tracker-beta1-data && chown -R app:app /app /tmp/health-tracker-beta1-data
USER app
'@
    'Building disposable QA image.' | Set-Content -LiteralPath $logPath -Encoding UTF8
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $buildOutput = @($dockerfile | docker build --tag $imageName --file - $ProjectRoot 2>&1)
        $buildExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $buildOutput | Tee-Object -FilePath $logPath -Append | Write-Output
    $createdImage = Test-DockerObjectExists @('image', 'inspect', $imageName)
    if ($buildExitCode -ne 0 -or -not $createdImage) { throw "docker_build_failed_exit_$buildExitCode" }

    Invoke-DockerChecked @('network', 'create', '--label', 'io.healthtracker.qa=beta1', $networkName)
    $createdNetwork = $true
    Invoke-DockerChecked @(
        'run', '--detach', '--name', $dbContainer, '--network', $networkName,
        '--label', 'io.healthtracker.qa=beta1',
        '--tmpfs', '/var/lib/mysql:rw,noexec,nosuid,size=512m',
        '--health-cmd', 'healthcheck.sh --connect --innodb_initialized',
        '--health-interval', '2s', '--health-timeout', '5s', '--health-retries', '60',
        '-e', "MARIADB_DATABASE=$dbSchema", '-e', "MARIADB_USER=$dbUser",
        '-e', "MARIADB_PASSWORD=$dbPassword", '-e', "MARIADB_ROOT_PASSWORD=$rootPassword",
        'mariadb:11.4'
    )
    $createdContainer = $true

    $healthy = $false
    foreach ($attempt in 1..90) {
        $state = (& docker inspect --format '{{.State.Health.Status}}' $dbContainer 2>$null)
        if ($LASTEXITCODE -eq 0 -and $state -eq 'healthy') { $healthy = $true; break }
        if ($state -eq 'unhealthy') { throw 'mariadb_became_unhealthy' }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { throw 'mariadb_health_timeout' }
    'MariaDB healthy on isolated tmpfs.' | Add-Content -LiteralPath $logPath -Encoding UTF8

    Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade', 'head')
    Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'check')
    Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'current')
    $zeroToHeadPassed = $true
    foreach ($cycle in 1..2) {
        "Migration cycle ${cycle}: head -> 0035 -> head." | Add-Content -LiteralPath $logPath -Encoding UTF8
        Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'downgrade', '20260731_0035')
        Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'upgrade', 'head')
        Invoke-AppChecked @('-m', 'flask', '--app', 'app:create_app', 'db', 'check')
        $cycleCount++
    }

    'Running full pytest suite in isolated Docker/MariaDB environment.' |
        Add-Content -LiteralPath $logPath -Encoding UTF8
    Invoke-AppChecked @('-m', 'pytest', '-q')
    $testsPassed = $true
} catch {
    $failure = $_.Exception.Message
    if (Test-Path -LiteralPath $sessionRoot) {
        ('FAILURE: ' + $failure) | Add-Content -LiteralPath $logPath -Encoding UTF8
    }
} finally {
    if ($createdContainer) { & docker rm --force $dbContainer 2>$null | Out-Null }
    if ($createdNetwork) { & docker network rm $networkName 2>$null | Out-Null }
    if ($createdImage) { & docker image rm --force $imageName 2>$null | Out-Null }
    if ($createdStorage -and (Test-Path -LiteralPath $storageRoot)) {
        $resolvedStorage = [IO.Path]::GetFullPath($storageRoot)
        $resolvedParent = [IO.Path]::GetFullPath($storageParent).TrimEnd('\', '/')
        if (-not $resolvedStorage.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'qa_storage_cleanup_target_outside_temp_root'
        }
        Remove-Item -LiteralPath $resolvedStorage -Recurse -Force
    }

    $containerGone = -not (Test-DockerObjectExists @('container', 'inspect', $dbContainer))
    $networkGone = -not (Test-DockerObjectExists @('network', 'inspect', $networkName))
    $imageGone = -not (Test-DockerObjectExists @('image', 'inspect', $imageName))
    $storageGone = -not (Test-Path -LiteralPath $storageRoot)
    $dailyAfter = @(& docker ps --format '{{.Names}}|{{.ID}}' --filter 'name=^/health-tracker-' | Sort-Object)
    $volumesAfter = @(& docker volume ls --format '{{.Name}}' | Sort-Object)
    $dailyUnchanged = ((@($dailyBefore) -join "`n") -eq (@($dailyAfter) -join "`n"))
    $volumesUnchanged = ((@($volumesBefore) -join "`n") -eq (@($volumesAfter) -join "`n"))
    $cleanupPassed = $containerGone -and $networkGone -and $imageGone -and $storageGone -and $dailyUnchanged -and $volumesUnchanged
    $report = [ordered]@{
        schema = 'health-tracker-beta1-mariadb-qa-v1'
        session_id = $SessionId
        started_at_utc = $started.ToString('o')
        finished_at_utc = [DateTime]::UtcNow.ToString('o')
        isolation = [ordered]@{
            database_engine = 'mariadb:11.4'
            database_storage = 'tmpfs'
            named_volumes_created = 0
            docker_compose_used = $false
            persistent_data_used = $false
        }
        migration_head = '20260731_0036'
        migration_zero_to_head_passed = $zeroToHeadPassed
        migration_head_0035_head_cycles_passed = $cycleCount
        full_pytest_passed = $testsPassed
        cleanup_passed = $cleanupPassed
        daily_containers_unchanged = $dailyUnchanged
        docker_volumes_unchanged = $volumesUnchanged
        failure = $failure
    }
    Write-Beta1Json $report $reportPath 8
}

if ($failure -or -not $zeroToHeadPassed -or $cycleCount -ne 2 -or -not $testsPassed -or -not $cleanupPassed) {
    [Console]::Error.WriteLine("Beta 1 MariaDB QA failed; report: $reportPath")
    exit 4
}
Write-Output "Beta 1 MariaDB QA passed; report: $reportPath"
exit 0
