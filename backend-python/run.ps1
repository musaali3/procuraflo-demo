$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = Join-Path $PSScriptRoot '..\..\venv\Scripts\python.exe'
}
if (-not (Test-Path $python)) { throw 'Python environment missing. Create backend-python\.venv or the workspace root venv, then install backend-python\requirements.txt.' }
$serverPort = if ($env:PORT) { $env:PORT } else { '8001' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $python -m uvicorn app.main:app --app-dir $PSScriptRoot --host 0.0.0.0 --port $serverPort --reload --reload-dir $PSScriptRoot
} finally {
    Pop-Location
}
