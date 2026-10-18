@echo off
rem Double-click to run the Stage 1 sequential benchmark on Windows (extract the zip first).
set /p MEMBER=Type your name (English) and press Enter:
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\run-stage1.ps1" -Name "%MEMBER%"
echo.
pause
