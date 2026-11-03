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
rem The Python that made .venv may have been removed or upgraded since ("No Python at ..."): then make
rem .venv again with the Python installed now.
".venv\Scripts\python.exe" -c "" >nul 2>nul || call :remake_venv || exit /b 1
".venv\Scripts\python.exe" setup\build.py %*
exit /b %errorlevel%

:remake_venv
echo The Python that SETUP.bat used is no longer installed: making the Python environment again ...
set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto :no_python
rmdir /s /q ".venv"
%PY% -m venv .venv || goto :venv_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r setup\requirements.txt || goto :venv_failed
exit /b 0
:no_python
echo Python 3.10 or newer is needed: run SETUP.bat, it can install it.
pause
exit /b 1
:venv_failed
echo Making the Python environment failed: run SETUP.bat.
pause
exit /b 1
