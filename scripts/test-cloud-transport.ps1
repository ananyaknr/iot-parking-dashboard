# Controlled backend HTTPS failure only; not physical internet-disconnection acceptance.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$taskOldProxy = $env:HTTPS_PROXY
$taskOldNoProxy = $env:NO_PROXY
$taskProbe = New-Object Net.Sockets.TcpClient
try { $taskProbe.Connect('127.0.0.1',9); throw 'Port 9 is in use; refusing controlled failure' }
catch [Net.Sockets.SocketException] { }
finally { $taskProbe.Dispose() }
function Wait-TransportStage([string]$taskPhase) {
    for ($taskAttempt=0; $taskAttempt -lt 15; $taskAttempt++) {
        & "$taskRoot\.venv\Scripts\python.exe" "$taskRoot\scripts\verify-cloud-outage.py" $taskPhase --controlled-https-failure
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 2
    }
    throw "Controlled transport stage did not pass: $taskPhase"
}
& "$taskRoot\.venv\Scripts\python.exe" "$taskRoot\scripts\verify-cloud-outage.py" baseline --controlled-https-failure
if ($LASTEXITCODE -ne 0) { throw 'Actual hardware online baseline did not pass; no transport changed' }
try {
    $env:HTTPS_PROXY = 'http://127.0.0.1:9'
    $env:NO_PROXY = '127.0.0.1,localhost'
    & "$taskRoot\scripts\restart-native-backend.ps1"
    Wait-TransportStage 'offline-before-restart'
    & "$taskRoot\scripts\restart-native-backend.ps1"
    Wait-TransportStage 'offline-after-restart'
}
finally {
    $env:HTTPS_PROXY = $taskOldProxy
    $env:NO_PROXY = $taskOldNoProxy
    Write-Host 'Restoring normal backend HTTPS transport.'
    & "$taskRoot\scripts\restart-native-backend.ps1"
}
Wait-TransportStage 'recovered'
