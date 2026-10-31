@echo off
rem Packs your last play session (its frame-timing recording with your F8 marks, a summary, your PC's
rem specs and the end of the log) into one zip, shows it in Explorer and opens the GitHub "new issue"
rem page so you can attach it. Your Windows user name is removed from everything in the zip.
rem   REPORT.bat [perf\<date_time> folder]   (default: the newest recording)
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\make_report.py %*
echo.
pause
