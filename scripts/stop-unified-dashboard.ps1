$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskLedgerPath = Join-Path $taskRoot '.runtime/unified-processes.json'
if (-not (Test-Path -LiteralPath $taskLedgerPath)) { return }
$taskLedger = Get-Content -LiteralPath $taskLedgerPath -Raw | ConvertFrom-Json
foreach ($taskName in @('unified-gateway','unified-sensors','unified-parking-api')) {
    $taskEntry = $taskLedger.$taskName
    if (-not $taskEntry) { continue }
    $taskProcess = Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue
    if (-not $taskProcess) { continue }
    if ($taskProcess.Path -ne $taskEntry.path -or $taskProcess.StartTime.ToUniversalTime().ToString('o') -ne $taskEntry.started) {
        throw "$taskName process identity changed; refusing to stop it."
    }
    if ($taskName -eq 'unified-sensors') {
        $taskStopFile = Join-Path $taskRoot '.runtime/gate-demo.stop'
        Set-Content -LiteralPath $taskStopFile 'Requested unified dashboard shutdown'
        try { Wait-Process -Id $taskProcess.Id -Timeout 15 -ErrorAction Stop }
        catch { throw 'Sensor shutdown not confirmed; inspect its log. Stop file retained.' }
        Remove-Item -LiteralPath $taskStopFile
    } else {
        # Windows venv Python uses a redirector process; stop its verified tree.
        & taskkill.exe /PID $taskProcess.Id /T /F | Out-Null
        if ($LASTEXITCODE) { throw "$taskName shutdown failed; process ledger retained." }
    }
}
Remove-Item -LiteralPath $taskLedgerPath
Write-Host 'Stopped migration processes owned by this launcher. Existing native services and data retained.'
