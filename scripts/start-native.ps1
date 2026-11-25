param([switch]$SkipBackend)
$ErrorActionPreference = 'Stop'
$rootPath = Split-Path $PSScriptRoot -Parent
Set-Location $rootPath
$runtime = Join-Path $rootPath '.runtime'
$logDir = Join-Path $rootPath 'docs/runtime-logs'
New-Item -ItemType Directory -Force $runtime,$logDir,(Join-Path $runtime 'mqtt'),(Join-Path $runtime 'influxdb') | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)
function Import-LocalEnvironment {
    Get-Content (Join-Path $rootPath '.env') | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process') }
    }
}
Import-LocalEnvironment
$python = Join-Path $rootPath '.venv/Scripts/python.exe'
$mosquitto = Join-Path $rootPath '.tools/native/mosquitto/mosquitto.exe'
$influxd = (Get-ChildItem (Join-Path $rootPath '.tools/native/influxdb') -Filter influxd.exe -Recurse | Select-Object -First 1).FullName
if (-not $influxd -or -not (Test-Path $mosquitto) -or -not (Test-Path $python)) { throw 'Native dependencies are missing. See README installation instructions.' }
$ledgerPath = Join-Path $runtime 'processes.json'
$ledger = @{}
if (Test-Path $ledgerPath) { $obj=Get-Content $ledgerPath -Raw | ConvertFrom-Json; $obj.PSObject.Properties | ForEach-Object {$ledger[$_.Name]=$_.Value} }
function Start-Owned([string]$name,[string]$exe,[string[]]$arguments,[int]$port) {
    if ($ledger.ContainsKey($name)) {
        $entry=$ledger[$name]
        $existing=Get-Process -Id $entry.id -ErrorAction SilentlyContinue
        if ($existing -and $existing.Path -eq $entry.path -and $existing.StartTime.ToUniversalTime().ToString('o') -eq $entry.started) { return }
    }
    $socket = New-Object Net.Sockets.TcpClient
    $probeAddress=if($name -eq 'mosquitto'){$env:MQTT_BIND_IP}else{'127.0.0.1'}
    try { $socket.Connect($probeAddress,$port); throw "Port $port already used by an unowned process" }
    catch [Net.Sockets.SocketException] {} finally {$socket.Dispose()}
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $rootPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir "$name.stdout.log") -RedirectStandardError (Join-Path $logDir "$name.stderr.log")
    $ledger[$name]=@{id=$process.Id;path=[IO.Path]::GetFullPath($exe);started=$process.StartTime.ToUniversalTime().ToString('o')}
    $ledger | ConvertTo-Json -Depth 4 | Set-Content $ledgerPath -Encoding UTF8
}
# Listen on the selected LAN address, not all interfaces. Backend connects to that same address.
$pathPrefix = $rootPath.Replace('\','/')
$conf = @(
    "listener 1883 $env:MQTT_BIND_IP",'allow_anonymous false',
    "password_file $pathPrefix/.secrets/mosquitto.passwd", "acl_file $pathPrefix/infra/mosquitto/acl",
    'persistence true',"persistence_location $pathPrefix/.runtime/mqtt/",'log_dest stdout','max_packet_size 2048'
)
$confPath=Join-Path $runtime 'mosquitto.conf'
[IO.File]::WriteAllLines($confPath,$conf,$utf8)
$passwdPath=Join-Path $rootPath '.secrets/mosquitto.passwd'
if (-not ((Get-Content $passwdPath -Raw) -match '\$[67]\$')) {
    & (Join-Path $rootPath '.tools/native/mosquitto/mosquitto_passwd.exe') -U $passwdPath
    if ($LASTEXITCODE) { throw 'MQTT password hashing failed' }
}
Start-Owned 'mosquitto' $mosquitto @('-c',('"'+$confPath+'"')) 1883
Start-Owned 'influxdb' $influxd @('--http-bind-address=127.0.0.1:8086',('--bolt-path='+$pathPrefix+'/.runtime/influxdb/influxd.bolt'),('--engine-path='+$pathPrefix+'/.runtime/influxdb/engine'),'--reporting-disabled','--storage-cache-max-memory-size=33554432','--storage-cache-snapshot-memory-size=8388608') 8086
$ready=$false
for($i=0;$i -lt 45;$i++) {
    try { $health=Invoke-RestMethod 'http://127.0.0.1:8086/health' -TimeoutSec 2; if($health.status -eq 'pass'){$ready=$true;break} } catch {}
    Start-Sleep -Seconds 1
}
if(-not $ready){throw 'InfluxDB did not become ready; inspect runtime logs'}
& $python (Join-Path $PSScriptRoot 'bootstrap-native.py')
if($LASTEXITCODE){throw 'InfluxDB bootstrap failed'}
Import-LocalEnvironment
if(-not $SkipBackend){
    $env:MQTT_HOST=$env:MQTT_BIND_IP
    $env:INFLUX_URL='http://127.0.0.1:8086'
    $env:INFLUX_ORG='parking';$env:INFLUX_BUCKET='sensor_data'
    $env:INFLUX_TOKEN=$env:INFLUX_RUNTIME_TOKEN
    $env:DASHBOARD_PORT='5000'
    $env:BACKEND_STOP_FILE=Join-Path $runtime 'backend.stop'
    if(Test-Path $env:BACKEND_STOP_FILE){Remove-Item -LiteralPath $env:BACKEND_STOP_FILE}
    Start-Owned 'backend' $python @('"'+(Join-Path $rootPath 'backend/main.py')+'"') 5000
    $backendReady=$false
    for($i=0;$i -lt 20;$i++){
        try{Invoke-RestMethod 'http://127.0.0.1:5000/health' -TimeoutSec 2 | Out-Null;$backendReady=$true;break}catch{}
        Start-Sleep -Seconds 1
    }
    if(-not $backendReady){throw 'Backend did not become ready; inspect backend.stderr.log'}
}
Write-Host 'Native services started. Dashboard: http://127.0.0.1:5000'
Write-Host 'Login: parking-admin. Password is stored locally in .env (GRAFANA_PASSWORD); never paste it into chat.'
