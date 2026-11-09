param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalInstance = Join-Path $ProjectRoot 'instance\local-play'
if (-not (Test-Path -LiteralPath (Join-Path $LocalInstance 'sync-report.json'))) {
    throw 'Initialize local testing first: .venv\Scripts\python.exe tools\sync_local_content.py'
}
$env:GAME_ENV = 'development'
$env:GAME_INSTANCE_PATH = $LocalInstance
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $LocalInstance 'math_game.db').Replace('\', '/')
$env:GAME_MEDIA_ROOT = Join-Path $LocalInstance 'media'
$env:GAME_IDENTITY_URL = ''
$env:GAME_IDENTITY_TOKEN = ''
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonExe = 'python'
}

function Get-LoginUrl {
    param([int]$Port)
    return "http://127.0.0.1:$Port/login"
}

function Test-MathGameReady {
    param([int]$Port)

    try {
        $markerPath = Join-Path $LocalInstance 'server.json'
        if (-not (Test-Path -LiteralPath $markerPath)) { return $false }
        $server = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($server.port -ne $Port) { return $false }
        $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.pid)"
        if (-not $processInfo -or $processInfo.CommandLine -notlike '*local_play_server.py*') { return $false }
        $response = Invoke-WebRequest -UseBasicParsing -Uri (Get-LoginUrl $Port) -TimeoutSec 2
        return ($response.StatusCode -eq 200 -and $response.Content -like '*Math Game*')
    }
    catch {
        return $false
    }
}

function Test-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $listener)
}

$Port = $null
foreach ($candidatePort in 5001..5010) {
    if (Test-MathGameReady $candidatePort) {
        $Port = $candidatePort
        break
    }
}

$StartedServer = $false
if ($null -eq $Port) {
    foreach ($candidatePort in 5001..5010) {
        if (Test-PortAvailable $candidatePort) {
            $Port = $candidatePort
            break
        }
    }
}

if ($null -eq $Port) {
    throw 'No available port found from 5000 through 5010.'
}

if (-not (Test-MathGameReady $Port)) {
    $runner = Join-Path $ProjectRoot 'tools\local_play_server.py'
    Start-Process -FilePath $PythonExe -ArgumentList @("`"$runner`"", '--port', "$Port") -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LocalInstance 'server-out.log') -RedirectStandardError (Join-Path $LocalInstance 'server-error.log')
    $StartedServer = $true
}

$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
    if (Test-MathGameReady $Port) {
        $LoginUrl = Get-LoginUrl $Port
        if (-not $NoBrowser) {
            Start-Process $LoginUrl
        }
        if ($StartedServer) {
            Write-Host "Started Math Game on port $Port."
        }
        Write-Host "Opened admin login page: $LoginUrl"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

$LoginUrl = Get-LoginUrl $Port
if (-not $NoBrowser) {
    Start-Process $LoginUrl
}

Write-Host "Math Game did not confirm readiness within 25 seconds."
Write-Host "Tried admin login page: $LoginUrl"
