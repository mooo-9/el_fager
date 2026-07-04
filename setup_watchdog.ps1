# One-time setup: register the El Fager watchdog to start at logon.
# Run this yourself in PowerShell:  .\setup_watchdog.ps1
$pyw = "C:\Users\Mohab1\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "pythonw.exe not found at $pyw - edit this script with your Python path."
    exit 1
}
schtasks /Create /SC ONLOGON /TN "El Fager Watchdog" /TR "`"$pyw`" `"C:\claude proj\el_fager\watchdog.py`"" /F
Write-Host ""
Write-Host "Done. The watchdog will start El Fager at every logon and auto-restart it on crash."
Write-Host "To start it right now without logging out:"
Write-Host "  Start-Process `"$pyw`" -ArgumentList `"C:\claude proj\el_fager\watchdog.py`""
Write-Host "To remove:  schtasks /Delete /TN `"El Fager Watchdog`" /F"
