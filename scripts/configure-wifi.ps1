param([string]$Ssid='')
$ErrorActionPreference = 'Stop'
$rootPath = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $rootPath '.env'
if (-not (Test-Path $envFile)) { throw 'Run setup-local.py first.' }
$values = @{}
Get-Content $envFile | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { $values[$Matches[1]]=$Matches[2] } }
Write-Host 'Enter Wi-Fi credentials locally. Nothing is sent to chat.'
if(-not $Ssid){$Ssid = Read-Host '2.4 GHz Wi-Fi SSID'}
Write-Host "Configuring ESP32 for network: $Ssid"
$securePassword = Read-Host 'Wi-Fi password (hidden)' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $wifiPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    function Quote-Cpp([string]$value) { return '"' + $value.Replace('\','\\').Replace('"','\"').Replace("`r",'\r').Replace("`n",'\n') + '"' }
    $header = @(
        '#pragma once','#define WIFI_ENTERPRISE 0',
        ('const char WIFI_SSID[] = ' + (Quote-Cpp $ssid) + ';'),
        ('const char WIFI_PASSWORD[] = ' + (Quote-Cpp $wifiPassword) + ';'),
        ('const char MQTT_HOST[] = ' + (Quote-Cpp $values.MQTT_BIND_IP) + ';'),
        'const uint16_t MQTT_PORT = 1883;',
        ('const char MQTT_USERNAME[] = ' + (Quote-Cpp $values.MQTT_USERNAME) + ';'),
        ('const char MQTT_PASSWORD[] = ' + (Quote-Cpp $values.MQTT_PASSWORD) + ';')
    )
    [IO.File]::WriteAllLines((Join-Path $rootPath 'firmware/esp32_gateway/secrets.h'), $header, (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Saved ignored secrets.h. Credentials were not printed.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $wifiPassword = $null
}
