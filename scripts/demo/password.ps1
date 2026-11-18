param([switch]$CopyToClipboard, [switch]$RequireExisting)
$ErrorActionPreference = 'Stop'
$demoCredentialDirectory = Join-Path $env:LOCALAPPDATA 'HealthTrackerDemo'
$demoCredentialPath = Join-Path $demoCredentialDirectory 'password.dpapi'
if (-not (Test-Path -LiteralPath $demoCredentialPath)) {
    if ($RequireExisting) { throw 'Falta la credencial DEMO existente; no se generó otra contraseña.' }
    New-Item -ItemType Directory -Path $demoCredentialDirectory -Force | Out-Null
    $demoIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $demoCredentialDirectory /inheritance:r /grant:r "${demoIdentity}:(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo restringir el archivo de credenciales.' }
    $demoRandomBytes = [byte[]]::new(32)
    $demoRandomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $demoRandomGenerator.GetBytes($demoRandomBytes)
    $demoRandomGenerator.Dispose()
    $demoPlaintext = [Convert]::ToBase64String($demoRandomBytes)
    $demoSecurePassword = ConvertTo-SecureString $demoPlaintext -AsPlainText -Force
    $demoSecurePassword | ConvertFrom-SecureString | Set-Content -LiteralPath $demoCredentialPath
    $demoPlaintext = $null
    [Array]::Clear($demoRandomBytes, 0, $demoRandomBytes.Length)
}
$demoSecurePassword = Get-Content -LiteralPath $demoCredentialPath | ConvertTo-SecureString
if ($CopyToClipboard) {
    $demoCredential = [pscredential]::new('demo@healthtracker.test', $demoSecurePassword)
    Set-Clipboard -Value $demoCredential.GetNetworkCredential().Password
    Write-Output 'Contraseña DEMO copiada al portapapeles.'
} else {
    # Dot-source this script to use the SecureString without printing the secret.
    Write-Output 'Credencial DEMO disponible con protección DPAPI del usuario Windows.'
}
