@echo off
rem Plays Demon's Souls exactly like PLAY.bat, and records frame timing to
rem analyse (docs\NOTES.md fix 46). While playing, press F8 right after you see a stutter or
rem hitch: the window title shows [RECORDING - F8 = stutter, N marked]. Each run is saved to
rem perf\<date_time>\perf.txt (about 25 MB an hour). Afterwards
rem ".venv\Scripts\python tools\perf_report.py" summarises the newest one. Works with the other modes: "set DES_FPS=60" (or 30 / unlimited) or
rem "set DES_GAME=game_remaster" before running this, as with the other bats.
setlocal
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%T"
set "PD=%~dp0perf\%TS%"
if not exist "%PD%" mkdir "%PD%"
for /f %%R in ('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Where-Object CurrentRefreshRate | Select-Object -First 1).CurrentRefreshRate"') do set "DES_REFRESH=%%R"
set "DES_PERF=1"
set "LD_PRESENT_LOG=%PD%\perf.txt"
set "LD_PRESENT_LOG_FROM=0"
set "LD_PRESENT_LOG_SECS=0"
echo Recording frame timing to %PD%
echo Press F8 in the game window right after each stutter you see.
call "%~dp0PLAY.bat"
echo.
echo Recording saved to %PD%
echo Summary: .venv\Scripts\python tools\perf_report.py
pause
