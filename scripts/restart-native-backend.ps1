$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskLedger = Get-Content -LiteralPath (Join-Path $taskRoot '.runtime/processes.json') -Raw | ConvertFrom-Json
$taskEntry = $taskLedger.backend
if ($taskEntry) {
    $taskProcess = Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
    if ($taskProcess) {
        if ($taskProcess.Path -ne $taskEntry.path -or $taskProcess.StartTime.ToUniversalTime().ToString('o') -ne $taskEntry.started) {
            throw 'Backend identity changed; refusing to stop it'
        }
        Set-Content -LiteralPath (Join-Path $taskRoot '.runtime/backend.stop') 'Requested cloud configuration reload'
        for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
            if (-not (Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Seconds 1
        }
        $taskProcess = Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
        if ($taskProcess) {
            if ($taskProcess.Path -ne $taskEntry.path -or $taskProcess.StartTime.ToUniversalTime().ToString('o') -ne $taskEntry.started) {
                throw 'Backend identity changed during shutdown'
            }
            Stop-Process -Id $taskEntry.id
        }
    }
}
& (Join-Path $taskRoot 'scripts/start-native.ps1')
