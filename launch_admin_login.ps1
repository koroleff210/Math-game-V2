param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
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
foreach ($candidatePort in 5000..5010) {
    if (Test-MathGameReady $candidatePort) {
        $Port = $candidatePort
        break
    }
}

$StartedServer = $false
if ($null -eq $Port) {
    foreach ($candidatePort in 5000..5010) {
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
    $serverCommand = "Set-Location -LiteralPath '$ProjectRoot'; `$env:PORT='$Port'; & '$PythonExe' run.py"
    Start-Process powershell.exe -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy', 'Bypass',
        '-Command', $serverCommand
    ) -WindowStyle Minimized
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
