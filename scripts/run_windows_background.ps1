$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = "1"

$logDir = Join-Path $root "output\windows"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logPath = Join-Path $logDir "server.log"

& (Join-Path $root ".venv\Scripts\python.exe") -m flask --app app run --host 127.0.0.1 --port 5000 *> $logPath
