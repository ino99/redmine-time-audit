param(
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$env:PYTHONDONTWRITEBYTECODE = "1"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
}

if ($SetupOnly) {
    exit 0
}

& .\.venv\Scripts\python.exe -m flask --app app run --debug
