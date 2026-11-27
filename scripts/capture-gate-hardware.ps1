param([ValidatePattern('^COM[0-9]+$')][string]$Port='COM9')
$ErrorActionPreference='Stop'
$rootPath=Split-Path $PSScriptRoot -Parent
$cliPath=Join-Path $rootPath '.tools/arduino-cli/arduino-cli.exe'
$configPath=Join-Path $rootPath '.tools/arduino-cli.yaml'
$logPath=Join-Path $rootPath ('.runtime/gate-native-'+$Port+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
Write-Host ('Native serial capture: '+$logPath)
# Run in an interactive terminal; newline commands are passed to the board.
# Use Ctrl+C to release the port. No .NET SerialPort reader or firmware change.
# Default asserted DTR/RTS selected download mode on the CH9102 ESP32 adapter.
& $cliPath --config-file $configPath monitor -p $Port --config baudrate=115200,dtr=off,rts=off --quiet --raw --timestamp 2>&1 | Tee-Object -FilePath $logPath
exit $LASTEXITCODE
