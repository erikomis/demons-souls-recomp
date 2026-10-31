@echo off
rem Demon's Souls (BLUS-30443) PC port -- one-click setup.
rem Drag your disc image (.iso, Redump .zip, or dumped disc folder) onto this file, or double-click
rem it and it will ask. It extracts the game, recompiles it and builds DemonsSoulsRecomp.exe.
rem Safe to run again: finished steps are skipped.
setlocal EnableExtensions
cd /d "%~dp0"
title Demon's Souls PC port - setup

set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto :need_python
where git >nul 2>nul || goto :need_git

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment in .venv ...
  %PY% -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r setup\requirements.txt || goto :failed
".venv\Scripts\python.exe" setup\setup.py %*
if errorlevel 1 goto :failed
echo.
pause
exit /b 0

:need_python
echo Python 3.10 or newer is needed (https://www.python.org/downloads/ - tick "Add python.exe to PATH").
call :offer Python.Python.3.12
goto :reopen

:need_git
echo Git is needed (https://git-scm.com/download/win).
call :offer Git.Git
goto :reopen

:offer
where winget >nul 2>nul || exit /b 1
set "ANS="
set /p "ANS=Install it now with winget? [Y/n] "
if /i "%ANS%"=="n" exit /b 1
winget install -e --id %1 --accept-package-agreements --accept-source-agreements
exit /b %errorlevel%

:reopen
echo.
echo When it is installed, close this window and run SETUP.bat again.
pause
exit /b 1

:failed
echo.
echo Setup stopped. Fix the problem above and run SETUP.bat again - finished steps are skipped.
pause
exit /b 1
