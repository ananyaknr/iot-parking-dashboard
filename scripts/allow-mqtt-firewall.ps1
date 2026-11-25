# Run locally as Administrator. Restricts inbound access to this executable and local subnet.
$ErrorActionPreference='Stop'
$rootPath=Split-Path $PSScriptRoot -Parent
$values=@{}
Get-Content (Join-Path $rootPath '.env') | ForEach-Object {if($_ -match '^([^#=]+)=(.*)$'){$values[$Matches[1]]=$Matches[2]}}
$exe=Join-Path $rootPath '.tools/native/mosquitto/mosquitto.exe'
$existing=Get-NetFirewallRule -DisplayName 'Parking MQTT local subnet' -ErrorAction SilentlyContinue
if($existing){
    $program=($existing | Get-NetFirewallApplicationFilter).Program
    if($program -ne $exe){throw 'Refusing to change a firewall rule for a different executable'}
    $existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $values.MQTT_BIND_IP -RemoteAddress LocalSubnet
    Write-Host 'Updated scoped MQTT firewall rule to the current LAN address.';return
}
New-NetFirewallRule -DisplayName 'Parking MQTT local subnet' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1883 -LocalAddress $values.MQTT_BIND_IP -RemoteAddress LocalSubnet -Program $exe -Profile Any | Out-Null
Write-Host 'Allowed local-subnet clients to this project Mosquitto executable on TCP 1883.'
