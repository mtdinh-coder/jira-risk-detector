# Register a Windows Scheduled Task to run scripts/run.ps1 daily at 9:00 AM.
# Run once from PowerShell — does NOT require admin (uses current-user scope).
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runPs1 = Join-Path $PSScriptRoot "run.ps1"

if (-not (Test-Path $runPs1)) {
    throw "run.ps1 not found at $runPs1"
}

$taskName = "JiraRiskDetector"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runPs1`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am

# StartWhenAvailable = if the laptop was off at 9 AM, run on next wake.
# RestartCount/Interval = retry transient network/API failures.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily Jira risk detector — DMs TPM and tags Dev/QA on Slack at 9 AM" `
    -Force | Out-Null

Write-Host "Registered scheduled task '$taskName' for 9:00 AM daily." -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Test now:  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  Inspect:   Get-ScheduledTask -TaskName '$taskName' | Get-ScheduledTaskInfo"
Write-Host "  Remove:    Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
