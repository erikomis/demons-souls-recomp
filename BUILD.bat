@echo off
rem Rebuilds DemonsSoulsRecomp.exe after you change code (incremental; SETUP.bat must have run once).
rem   BUILD.bat [--jobs N] [ninja targets...]
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup\build.py %*
exit /b %errorlevel%
