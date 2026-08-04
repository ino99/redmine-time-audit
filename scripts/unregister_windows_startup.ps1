$ErrorActionPreference = "Stop"

$taskName = "Redmine Time Audit"
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Removed: $taskName"
