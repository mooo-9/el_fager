# One-time setup: register the El Fager watchdog to start at logon.
# Run:  .\setup_watchdog.ps1
$pyw = "C:\Users\Mohab1\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "pythonw.exe not found at $pyw - edit this script with your Python path."
    exit 1
}
# schtasks /TR mangles paths with spaces; use the native cmdlets instead.
$action  = New-ScheduledTaskAction -Execute $pyw -Argument '"C:\claude proj\el_fager\watchdog.py"' -WorkingDirectory "C:\claude proj\el_fager"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "El Fager Watchdog" -Action $action -Trigger $trigger `
    -Description "Keeps El Fager running; auto-restarts on crash" -Force | Out-Null
Write-Host "Done. Watchdog starts El Fager at every logon and auto-restarts it on crash."
Write-Host "Start it now:  Start-ScheduledTask -TaskName 'El Fager Watchdog'"
Write-Host "Remove:        Unregister-ScheduledTask -TaskName 'El Fager Watchdog' -Confirm:`$false"
