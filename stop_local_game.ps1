$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$markerPath = Join-Path $ProjectRoot 'instance\local-play\server.json'
if (Test-Path -LiteralPath $markerPath) {
    $server = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.pid)"
    $runner = Join-Path $ProjectRoot 'tools\local_play_server.py'
    if ($processInfo -and $processInfo.CommandLine.Contains($runner)) {
        Stop-Process -Id $server.pid
        Write-Host 'Local game stopped. Progress is saved.'
    }
    Remove-Item -LiteralPath $markerPath
}
