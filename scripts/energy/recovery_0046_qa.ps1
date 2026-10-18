param(
    [Parameter(Mandatory)][ValidateSet('clone-baseline','interrupt','upgrade','roundtrip','postwrite','clone-post','verify-post','freeze','retain-image')][string]$Phase,
    [Parameter(Mandatory)][string]$QaEnvFile,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$PytestWheels,
    [string]$Image = 'health-tracker-energy18:recovery-0046-3ffeba6'
)
# Existing LOCAL Docker only. No Compose operation, host port or persistent volume.
# Credentials are passed through --env-file, never opened or printed here.
$ErrorActionPreference = 'Stop'
$scriptRoot = $PSScriptRoot
$prefix = 'energy18_recovery_qa_20261018_'
foreach ($requiredPath in @($QaEnvFile, $EvidenceRoot, $PytestWheels)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw 'Missing private QA prerequisite' }
}
function Assert-QA-Schema([string]$schema) {
    if ($schema -notin @(($prefix+'a'), ($prefix+'b'), ($prefix+'c'))) { throw 'Refusing non-QA schema' }
}
function Storage-Name([string]$schema) {
    if ($schema.EndsWith('_a')) { return 'recovery-qa-files' }
    return 'recovery-qa-files-' + $schema.Substring($schema.Length-1)
}
function Run-QA([string]$schema, [string]$action) {
    Assert-QA-Schema $schema
    $storageName = Storage-Name $schema
    docker --context desktop-linux run --rm --network health-tracker_default `
        --env-file $QaEnvFile --env "DB_NAME=$schema" --env "DATA_ROOT=/evidence/$storageName" --env PYTHONPATH=/app `
        --mount "type=bind,source=$EvidenceRoot,target=/evidence" `
        --mount "type=bind,source=$scriptRoot,target=/qa-scripts,readonly" `
        --mount "type=bind,source=$PytestWheels,target=/qa-wheels,readonly" `
        --entrypoint sh $Image -c 'python -m venv --system-site-packages /tmp/qa-venv && /tmp/qa-venv/bin/pip install --no-index --find-links=/qa-wheels pytest >/tmp/qa-pip.log && exec /tmp/qa-venv/bin/python /qa-scripts/recovery_0046_qa.py "$1" --schema "$2"' sh $action $schema
    if ($LASTEXITCODE -ne 0) { throw "QA phase failed: $action" }
}
function Clone-QA([string]$source, [string]$target, [string]$label) {
    Assert-QA-Schema $source; Assert-QA-Schema $target
    if ($source -eq $target) { throw 'Restore requires a different empty schema' }
    $targetCount = docker --context desktop-linux exec health-tracker-db-1 sh -c 'export MYSQL_PWD="$MARIADB_ROOT_PASSWORD"; exec mariadb --user=root --batch --skip-column-names -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=\"$1\""' sh $target
    if ($LASTEXITCODE -ne 0 -or $targetCount.Trim() -ne '0') { throw 'Restore target is not empty' }
    $sqlPath = Join-Path $EvidenceRoot "$label.sql"
    $containerPath = "/tmp/energy18-recovery-$label.sql"
    if (Test-Path -LiteralPath $sqlPath) { throw 'Retain prior backup; choose a new reviewed run' }
    docker --context desktop-linux exec health-tracker-db-1 sh -c 'export MYSQL_PWD="$MARIADB_ROOT_PASSWORD"; exec mariadb-dump --user=root --single-transaction --quick --skip-lock-tables --skip-add-locks --skip-add-drop-table --skip-comments "$1" > "$2"' sh $source $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Consistent dump failed' }
    docker --context desktop-linux cp "health-tracker-db-1:$containerPath" $sqlPath
    if ($LASTEXITCODE -ne 0) { throw 'QA dump copy failed' }
    $hostHash = (Get-FileHash -LiteralPath $sqlPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $containerHash = docker --context desktop-linux exec health-tracker-db-1 sha256sum $containerPath
    if ($LASTEXITCODE -ne 0 -or $containerHash.Split(' ')[0] -ne $hostHash) { throw 'Backup checksum mismatch' }
    # The source has no running writers. Raw storage stays frozen until clone validation.
    $archivePath = Join-Path $EvidenceRoot "$label-files.tar.gz"
    $sourceFiles = Join-Path $EvidenceRoot (Storage-Name $source)
    $targetFiles = Join-Path $EvidenceRoot (Storage-Name $target)
    if (Test-Path -LiteralPath $targetFiles) { throw 'Restore requires fresh file storage' }
    tar -czf $archivePath -C $sourceFiles .
    if ($LASTEXITCODE -ne 0) { throw 'QA raw archive failed' }
    $rawHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    New-Item -ItemType Directory -Path $targetFiles | Out-Null
    tar -xzf $archivePath -C $targetFiles
    if ($LASTEXITCODE -ne 0) { throw 'QA raw restore failed' }
    @{sql_sha256=$hostHash;files_sha256=$rawHash;consistent='InnoDB single-transaction; all QA writers stopped';target='fresh empty isolated QA schema'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceRoot "$label-checksums.json") -Encoding utf8
    docker --context desktop-linux exec health-tracker-db-1 sh -c 'export MYSQL_PWD="$MARIADB_ROOT_PASSWORD"; exec mariadb --user=root --database="$1" < "$2"' sh $target $containerPath
    if ($LASTEXITCODE -ne 0) { throw 'Isolated restore failed; retain target for diagnosis' }
}
switch ($Phase) {
    'clone-baseline' { Clone-QA ($prefix+'a') ($prefix+'b') 'pre-ddl'; Run-QA ($prefix+'b') 'verify-baseline' }
    'interrupt' { Run-QA ($prefix+'a') 'interrupt' }
    'upgrade' { Run-QA ($prefix+'b') 'upgrade' }
    'roundtrip' { Run-QA ($prefix+'b') 'roundtrip' }
    'postwrite' { Run-QA ($prefix+'b') 'postwrite' }
    'clone-post' { Clone-QA ($prefix+'b') ($prefix+'c') 'post-writes' }
    'verify-post' { Run-QA ($prefix+'c') 'verify-post' }
    'freeze' {
        # Only this disposable QA schema; never global or production grants.
        @'
REVOKE INSERT, UPDATE, DELETE ON energy18_recovery_qa_20261018_b.* FROM 'progression_qa'@'172.18.%';
'@ | docker --context desktop-linux exec -i health-tracker-db-1 sh -c 'export MYSQL_PWD="$MARIADB_ROOT_PASSWORD"; exec mariadb --user=root --batch'
        if ($LASTEXITCODE -ne 0) { throw 'QA write freeze failed' }
        Run-QA ($prefix+'b') 'freeze'
    }
    'retain-image' {
        $archivePath = Join-Path $EvidenceRoot 'recovery-0046-image.tar'
        if (Test-Path -LiteralPath $archivePath) { throw 'Retain existing image archive' }
        $imageId = docker --context desktop-linux image inspect $Image --format '{{.Id}}'
        if ($LASTEXITCODE -ne 0) { throw 'Compatible image missing' }
        docker --context desktop-linux image save --output $archivePath $Image
        if ($LASTEXITCODE -ne 0) { throw 'Image archive failed' }
        @{image_id=$imageId;archive_sha256=(Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'recovery-image.json') -Encoding utf8
    }
}
