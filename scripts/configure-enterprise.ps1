param([string]$CaCertificatePath='')
$ErrorActionPreference='Stop'
$rootPath=Split-Path $PSScriptRoot -Parent
if(-not $CaCertificatePath){$CaCertificatePath=Read-Host 'Path to the verified ChulaWiFi CA certificate (.pem or .crt)'}
if(-not(Test-Path -LiteralPath $CaCertificatePath)){throw 'CA file not found. Obtain the official certificate from university IT before entering credentials.'}
$pem=Get-Content -LiteralPath $CaCertificatePath -Raw
if(-not $pem.Contains('-----BEGIN CERTIFICATE-----')){
    $certificate=New-Object Security.Cryptography.X509Certificates.X509Certificate2($CaCertificatePath)
    $pem="-----BEGIN CERTIFICATE-----`n"+[Convert]::ToBase64String($certificate.RawData,[Base64FormattingOptions]::InsertLineBreaks)+"`n-----END CERTIFICATE-----"
}
$serverName=Read-Host 'University IT authentication server name [wifi.it.chula.ac.th]'
if(-not $serverName){$serverName='wifi.it.chula.ac.th'}
$username=Read-Host 'CUNET username'
$securePassword=Read-Host 'CUNET password (hidden; never sent to chat)' -AsSecureString
$values=@{}
Get-Content (Join-Path $rootPath '.env') | ForEach-Object {if($_ -match '^([^#=]+)=(.*)$'){$values[$Matches[1]]=$Matches[2]}}
function Quote-Cpp([string]$value){return '"'+$value.Replace('\','\\').Replace('"','\"').Replace("`r",'\r').Replace("`n",'\n')+'"'}
$pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try{
    $password=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $header=@('#pragma once','#define WIFI_ENTERPRISE 1','const char WIFI_SSID[] = "ChulaWiFi";',
        ('const char WIFI_EAP_USERNAME[] = '+(Quote-Cpp $username)+';'),
        ('const char WIFI_PASSWORD[] = '+(Quote-Cpp $password)+';'),
        ('const char WIFI_EAP_SERVER_NAME[] = '+(Quote-Cpp $serverName)+';'),
        ('const unsigned long WIFI_BOOTSTRAP_EPOCH = '+[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+'UL;'),
        ('const char WIFI_CA_CERT[] = R"PARKING_CA('+ $pem +')PARKING_CA";'),
        ('const char MQTT_HOST[] = '+(Quote-Cpp $values.MQTT_BIND_IP)+';'),
        'const uint16_t MQTT_PORT = 1883;',
        ('const char MQTT_USERNAME[] = '+(Quote-Cpp $values.MQTT_USERNAME)+';'),
        ('const char MQTT_PASSWORD[] = '+(Quote-Cpp $values.MQTT_PASSWORD)+';'))
    [IO.File]::WriteAllLines((Join-Path $rootPath 'firmware/esp32_gateway/secrets.h'),$header,(New-Object Text.UTF8Encoding($false)))
    Write-Host 'Saved enterprise secrets.h locally. No credentials printed. Compile and upload soon so the initial UTC clock is current.'
}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer);$password=$null}
