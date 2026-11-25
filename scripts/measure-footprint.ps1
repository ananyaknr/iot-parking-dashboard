$rootPath=Split-Path $PSScriptRoot -Parent
$paths=@('.tools/native','.tools/native-downloads','.venv','.runtime','backend','dashboard','scripts')
$items=foreach($relative in $paths){
    $path=Join-Path $rootPath $relative
    $bytes=if(Test-Path $path){(Get-ChildItem $path -Recurse -File -Force | Measure-Object Length -Sum).Sum}else{0}
    [pscustomobject]@{path=$relative;bytes=[long]$bytes;MiB=[Math]::Round($bytes/1MB,2)}
}
$baseline=Get-Content (Join-Path $rootPath '.runtime/native-baseline.json') -Raw | ConvertFrom-Json
$workspaceBytes=(Get-ChildItem $rootPath -Recurse -File -Force | Measure-Object Length -Sum).Sum
$report=[ordered]@{utc=[DateTime]::UtcNow.ToString('o');components=$items;native_total_bytes=($items|Measure-Object bytes -Sum).Sum;workspace_growth_since_baseline=$workspaceBytes-$baseline.workspace_bytes;free_drive_bytes=[System.IO.DriveInfo]::new('C:/').AvailableFreeSpace;note='Includes retained native download archives and the small extraction helper. Excludes pre-existing Arduino toolchains. Database growth is ongoing; seven-day retention is not a disk quota.'}
$report | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $rootPath 'docs/runtime-logs/footprint.json') -Encoding UTF8
$report | ConvertTo-Json -Depth 5
