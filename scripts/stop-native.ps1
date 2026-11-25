$ErrorActionPreference='Stop'
$rootPath=Split-Path $PSScriptRoot -Parent
$ledgerPath=Join-Path $rootPath '.runtime/processes.json'
if(-not(Test-Path $ledgerPath)){Write-Host 'No project-owned processes recorded.';return}
$ledger=Get-Content $ledgerPath -Raw | ConvertFrom-Json
Set-Content (Join-Path $rootPath '.runtime/backend.stop') 'Requested native shutdown'
foreach($name in @('backend','influxdb','mosquitto')){
    $entry=$ledger.$name
    if(-not $entry){continue}
    $process=Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    if(-not $process){continue}
    if($process.Path -ne $entry.path -or $process.StartTime.ToUniversalTime().ToString('o') -ne $entry.started){
        Write-Warning "PID changed; refusing to stop $name";continue
    }
    if($name -eq 'backend'){
        for($i=0;$i -lt 10 -and (Get-Process -Id $entry.id -ErrorAction SilentlyContinue);$i++){Start-Sleep -Seconds 1}
    }
    if(Get-Process -Id $entry.id -ErrorAction SilentlyContinue){Stop-Process -Id $entry.id}
    Write-Host "Stopped project-owned $name"
}
