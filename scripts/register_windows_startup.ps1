$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$taskName = "Redmine Time Audit"
$pythonPath = Join-Path $root ".venv\Scripts\pythonw.exe"

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_windows.ps1") -SetupOnly
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-m flask --app app run --host 127.0.0.1 --port 5000" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances Ignore

Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Starts the Redmine Time Audit Flask server in the background." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "Registered and started: $taskName"
Write-Host "Open http://127.0.0.1:5000 manually in your browser."
