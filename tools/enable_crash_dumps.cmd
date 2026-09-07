@echo off
REM ---------------------------------------------------------------------------
REM  Ask Windows to keep a crash dump when El Fager dies.
REM
REM  El Fager crashed after 23 hours with STATUS_HEAP_CORRUPTION (0xC0000374)
REM  and left nothing behind to look at: the fault is in a native library, so
REM  Python never sees it, and under pythonw there is no console for a stack to
REM  reach. WER can capture the process image instead, which turns the next one
REM  from a mystery into something diagnosable.
REM
REM  The setting lives under HKLM and needs administrator rights, which is the
REM  only reason this is a separate file. Double-click it and accept the prompt.
REM
REM  Costs nothing until a crash happens. To undo:
REM    reg delete "HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\pythonw.exe" /f
REM ---------------------------------------------------------------------------

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Asking for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "KEY=HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\pythonw.exe"
set "DUMPS=%~dp0..\data\crashdumps"

if not exist "%DUMPS%" mkdir "%DUMPS%"

reg add "%KEY%" /v DumpFolder /t REG_EXPAND_SZ /d "%DUMPS%" /f  >nul
reg add "%KEY%" /v DumpType   /t REG_DWORD     /d 2            /f  >nul
reg add "%KEY%" /v DumpCount  /t REG_DWORD     /d 5            /f  >nul

echo.
echo   Crash dumps enabled for pythonw.exe
echo   Dumps will be written to: %DUMPS%
echo   DumpType 2 = full memory, DumpCount 5 = keep the last five.
echo.
reg query "%KEY%"
echo.
pause
