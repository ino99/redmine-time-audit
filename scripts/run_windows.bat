@echo off
setlocal

cd /d "%~dp0\.."
set PYTHONDONTWRITEBYTECODE=1

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b %errorlevel%

if not exist ".env" copy ".env.example" ".env"

if "%~1"=="--setup-only" exit /b 0

".venv\Scripts\python.exe" -m flask --app app run --debug
