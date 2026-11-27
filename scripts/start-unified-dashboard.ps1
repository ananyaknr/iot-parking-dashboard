param(
    [string]$CameraRoot = (Join-Path (Split-Path $PSScriptRoot -Parent) '../intelligence-parking-lot'),
    [int]$Port = 8081
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$CameraRoot = (Resolve-Path -LiteralPath $CameraRoot).Path
$taskRuntime = Join-Path $taskRoot '.runtime'
New-Item -ItemType Directory -Force -Path $taskRuntime | Out-Null
$taskCameraPython = Join-Path $CameraRoot '.venv/Scripts/python.exe'
$taskSensorPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskCameraPython)) { throw 'Camera .venv missing; install its existing requirements first.' }
# All connections in this launcher are local. Never send them to a system proxy.
$env:NO_PROXY = '127.0.0.1,localhost'
& (Join-Path $PSScriptRoot 'start-native.ps1')
if ($LASTEXITCODE) { throw 'Native startup failed' }

$taskLedgerPath = Join-Path $taskRuntime 'unified-processes.json'
$taskLedger = @{}
if (Test-Path -LiteralPath $taskLedgerPath) {
    $taskSaved = Get-Content -LiteralPath $taskLedgerPath -Raw | ConvertFrom-Json
    $taskSaved.PSObject.Properties | ForEach-Object { $taskLedger[$_.Name] = $_.Value }
}
function Test-LocalPort([int]$Number) {
    $taskSocket = New-Object Net.Sockets.TcpClient
    try { $taskSocket.Connect('127.0.0.1', $Number); return $true }
    catch [Net.Sockets.SocketException] { return $false }
    finally { $taskSocket.Dispose() }
}
function Start-UnifiedProcess([string]$Name, [string]$Exe, [string[]]$Arguments, [string]$Directory) {
    $taskProcess = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskRuntime "$Name.stdout.log") -RedirectStandardError (Join-Path $taskRuntime "$Name.stderr.log")
    # Process.Path can be temporarily null immediately after Windows CreateProcess.
    $taskLedger[$Name] = @{id=$taskProcess.Id;path=[IO.Path]::GetFullPath($Exe);started=$taskProcess.StartTime.ToUniversalTime().ToString('o')}
    $taskLedger | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $taskLedgerPath -Encoding UTF8
}
function Wait-LocalPort([int]$Number, [string]$Name) {
    for ($taskAttempt=0; $taskAttempt -lt 20; $taskAttempt++) {
        if (Test-LocalPort $Number) { return }
        Start-Sleep -Seconds 1
    }
    throw "$Name did not start within 20 seconds; inspect .runtime/$Name.stderr.log"
}

if (-not (Test-LocalPort 8001)) {
    $taskOldEnv = @{}
    $taskIsolatedEnv = @{
        PARKING_BACKEND='local'; PARKING_REQUIRE_FRESH_SENSORS='false'
        PARKING_DATABASE_PATH=(Join-Path $CameraRoot 'data/runtime/windows-joint-test/parking.sqlite3')
        PARKING_STORAGE_PATH=(Join-Path $CameraRoot 'data/runtime/windows-joint-test/photos')
    }
    try {
        foreach ($taskKey in $taskIsolatedEnv.Keys) {
            $taskOldEnv[$taskKey] = [Environment]::GetEnvironmentVariable($taskKey, 'Process')
            [Environment]::SetEnvironmentVariable($taskKey, $taskIsolatedEnv[$taskKey], 'Process')
        }
        Start-UnifiedProcess 'unified-parking-api' $taskCameraPython @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001') $CameraRoot
    } finally {
        foreach ($taskKey in $taskOldEnv.Keys) { [Environment]::SetEnvironmentVariable($taskKey, $taskOldEnv[$taskKey], 'Process') }
    }
    Wait-LocalPort 8001 'unified-parking-api'
}
$taskParking = Invoke-RestMethod 'http://127.0.0.1:8001/parking/status' -TimeoutSec 5
if ($taskParking.storage -ne 'local' -or $taskParking.gate_mode -ne 'simulation') {
    throw 'Port 8001 is not the isolated local simulation API. Refusing to connect.'
}
if (-not (Test-LocalPort 5001)) {
    if (Test-Path -LiteralPath (Join-Path $taskRuntime 'gate-demo.stop')) {
        throw 'gate-demo.stop exists; inspect why the previous simulation stopped before removing it.'
    }
    Start-UnifiedProcess 'unified-sensors' $taskSensorPython @(('"'+(Join-Path $taskRoot 'scripts/run-gate-demo.py')+'"')) $taskRoot
    Wait-LocalPort 5001 'unified-sensors'
}
$taskUser = if($env:DASHBOARD_USERNAME){$env:DASHBOARD_USERNAME}elseif($env:GRAFANA_USERNAME){$env:GRAFANA_USERNAME}else{'parking-admin'}
$taskPassword = if($env:DASHBOARD_PASSWORD){$env:DASHBOARD_PASSWORD}else{$env:GRAFANA_PASSWORD}
$taskAuth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($taskUser+':'+$taskPassword))
$taskSensor = Invoke-RestMethod 'http://127.0.0.1:5001/api/latest' -Headers @{Authorization=('Basic '+$taskAuth)} -TimeoutSec 5
if ($taskSensor.data_origin -ne 'hardware_gate_sim' -or -not $taskSensor.parking3.enabled) {
    throw 'Port 5001 is not the existing isolated G3 backend. Refusing to connect.'
}
if (-not (Test-LocalPort $Port)) {
    Start-UnifiedProcess 'unified-gateway' $taskCameraPython @(('"'+(Join-Path $taskRoot 'scripts/run-unified-dashboard.py')+'"'),'--port',"$Port") $taskRoot
    Wait-LocalPort $Port 'unified-gateway'
} else {
    $taskEntry = $taskLedger['unified-gateway']
    $taskExisting = if ($taskEntry) { Get-Process -Id $taskEntry.id -ErrorAction SilentlyContinue } else { $null }
    if (-not $taskExisting -or $taskExisting.Path -ne $taskEntry.path -or $taskExisting.StartTime.ToUniversalTime().ToString('o') -ne $taskEntry.started) {
        throw "Port $Port is occupied; refusing to replace an unrelated application. Choose -Port."
    }
}
Write-Host "Unified read-only dashboard: http://127.0.0.1:$Port"
Write-Host "Readiness: http://127.0.0.1:$Port/api/integration/readiness"
Write-Host 'Camera API and isolated G3 sensor backend stay separate. No parking writer or physical servo is enabled.'
