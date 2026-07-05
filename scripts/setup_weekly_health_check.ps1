# One-time setup: register the weekly health check (Friday 5:57 PM).
# Run:  .\scripts\setup_weekly_health_check.ps1
$pyw = "C:\Users\Mohab1\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "pythonw.exe not found at $pyw - edit this script with your Python path."
    exit 1
}
# schtasks /TR mangles paths with spaces; use the native cmdlets instead.
$action  = New-ScheduledTaskAction -Execute $pyw -Argument '-X utf8 "C:\claude proj\el_fager\scripts\weekly_health_check.py"' -WorkingDirectory "C:\claude proj\el_fager"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 5:57PM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "El Fager Weekly Health Check" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Weekly pytest + usage audit + backtest drift report" -Force | Out-Null
Write-Host "Done. Health check runs every Friday at 5:57 PM (or next boot if missed)."
Write-Host "Run it now:  Start-ScheduledTask -TaskName 'El Fager Weekly Health Check'"
Write-Host "Remove:      Unregister-ScheduledTask -TaskName 'El Fager Weekly Health Check' -Confirm:`$false"
