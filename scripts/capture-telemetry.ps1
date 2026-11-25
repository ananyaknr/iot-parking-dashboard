param(
    [Parameter(Mandatory=$true)][string]$Port,
    [ValidateRange(5,3600)][int]$Seconds = 60,
    [string]$OutputDirectory = 'docs/serial-logs',
    [string]$StopFile = ''
)
# Captures actual USB telemetry only; physical state must be supplied by the user.
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$rawPath = Join-Path $OutputDirectory "$stamp-raw.jsonl"
$eventPath = Join-Path $OutputDirectory "$stamp-events.jsonl"
$summaryPath = Join-Path $OutputDirectory "$stamp-summary.json"
$serial = New-Object System.IO.Ports.SerialPort $Port,9600,None,8,one
$serial.ReadTimeout = 1500
$serial.NewLine = "`n"
$required = @('node','a1_distance_cm','m1_distance_cm','a1_occupied','m1_occupied','vibration','vibration_count','vibration_status')
$count = 0
$valid = 0
$failures = @()
$startupDiscard = $null
$times = @()
$partial = ''
try {
    $serial.Open()
    Start-Sleep -Seconds 2 # allow UNO auto-reset; excluded from capture window
    $serial.DiscardInBuffer()
    # Flush through the next newline to establish a complete-message boundary.
    try { $startupDiscard = $serial.ReadLine().TrimEnd("`r") } catch [TimeoutException] {}
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds -and
           (-not $StopFile -or -not (Test-Path -LiteralPath $StopFile))) {
        try { $chunk = $serial.ReadExisting() } catch { throw }
        if ($chunk.Length -eq 0) { Start-Sleep -Milliseconds 20; continue }
        $partial += $chunk
        while ($partial.Contains("`n")) {
            $end = $partial.IndexOf("`n")
            $line = $partial.Substring(0, $end).TrimEnd("`r")
            $partial = $partial.Substring($end + 1)
            $count++
            $elapsed = $timer.Elapsed.TotalSeconds
            $times += $elapsed
            Add-Content -LiteralPath $rawPath -Value $line -Encoding UTF8
            $errorText = $null
            try {
                if (-not $line.StartsWith('{') -or -not $line.EndsWith('}')) { throw 'Expected a JSON object' }
                $msg = $line | ConvertFrom-Json -ErrorAction Stop
                $names = @($msg.PSObject.Properties.Name)
                if (@(Compare-Object $required $names).Count -ne 0) { throw 'Schema keys differ' }
                if ($msg.node -cne 'uno') { throw 'Invalid node' }
                foreach ($key in @('m1_distance_cm','m1_occupied','vibration','vibration_count')) {
                    if ($null -ne $msg.$key) { throw "Expected null: $key" }
                }
                if ($msg.vibration_status -cne 'not_installed') { throw 'Invalid vibration status' }
                $distance = $msg.a1_distance_cm
                if ($null -ne $distance) {
                    if (($distance -isnot [ValueType]) -or ($distance -is [bool]) -or $distance -lt 2 -or $distance -gt 400) { throw 'Invalid A1 distance' }
                }
                if ($null -ne $msg.a1_occupied -and $msg.a1_occupied -isnot [bool]) { throw 'Invalid A1 occupancy type' }
                if ($null -eq $distance -and $null -ne $msg.a1_occupied) { throw 'No echo must have unknown occupancy' }
                if ($null -ne $distance -and $distance -lt 15 -and $msg.a1_occupied -ne $true) { throw 'Occupied threshold mismatch' }
                if ($null -ne $distance -and $distance -gt 18 -and $msg.a1_occupied -ne $false) { throw 'Vacant threshold mismatch' }
                $valid++
            } catch { $errorText = $_.Exception.Message; $failures += "Line ${count}: $errorText" }
            [ordered]@{ utc = [DateTime]::UtcNow.ToString('o'); elapsed_seconds = $elapsed; raw = $line; error = $errorText } |
                ConvertTo-Json -Compress | Add-Content -LiteralPath $eventPath -Encoding UTF8
            Write-Host $line
        }
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}
$intervals = @()
for ($i = 1; $i -lt $times.Count; $i++) { $intervals += $times[$i] - $times[$i-1] }
$summary = [ordered]@{
    port = $Port; baud = 9600; requested_seconds = $Seconds
    actual_seconds = $timer.Elapsed.TotalSeconds
    complete_messages = $count; valid_messages = $valid; errors = $failures
    startup_line_discarded = $startupDiscard; trailing_partial_line = $partial
    mean_interval_seconds = if ($intervals.Count) { ($intervals | Measure-Object -Average).Average } else { $null }
    minimum_messages = [Math]::Floor($timer.Elapsed.TotalSeconds * 55 / 60)
    telemetry_pass = ($count -ge [Math]::Floor($timer.Elapsed.TotalSeconds * 55 / 60) -and $failures.Count -eq 0)
    physical_acceptance = 'Not determined by this capture; correlate with user actions'
    raw_log = $rawPath; event_log = $eventPath
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$summary | ConvertTo-Json -Depth 5
if (-not $summary.telemetry_pass) { exit 1 }

