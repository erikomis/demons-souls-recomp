@echo off
rem Launches the native PC build of Demon's Souls (BLUS-30443, ps3recomp static recompilation).
rem Run SETUP.bat once first. Game files: game\   Saves: gamedata\dev_hdd0\home\00000001\savedata
rem
rem Controls: an Xbox (XInput) controller is used when one is plugged in (A = Cross, B = Circle, X = Square,
rem Y = Triangle, LB/RB = L1/R1, LT/RT = L2/R2, Back = Select). A DualShock/DualSense needs Steam Input or
rem DS4Windows to show up as an Xbox pad. Without a controller, keyboard + mouse:
rem   WASD move   mouse camera (IJKL also)   LMB attack (R1)   Shift strong attack (R2)
rem   RMB block (L1)   Ctrl parry (L2)   Space roll/dash/back (Circle)   E interact/confirm (Cross)
rem   F two-hand (Triangle)   R use item (Square)   Tab or middle mouse lock on (R3)   C (L3)
rem   arrows d-pad (switch items)   Enter Start   Backspace Select   F1 capture/release the mouse
rem Keys only count while the game window is in front. At Create Profile a text box opens for the
rem character name: type it, Enter = OK, Esc = Cancel (the game ignores keys while it is open).
rem "set DES_NAME=<name>" before launching skips the box and uses that name.
rem God mode (fix 44): F9 in the game window turns it on / off (the window title says [GOD MODE - F9]):
rem you cannot die and HP, MP and stamina stay full. "set DES_GOD=1" before launching starts with it on.
rem
rem Every run is logged to logs\last_run_out.txt / last_run_err.txt (previous run kept as *_prev.txt).
rem They grow by roughly 600 MB an hour. Attach the end of last_run_err.txt when you report a crash.
rem Runs at up to 60 fps by default (docs\NOTES.md fix 28), 50 on a 100 Hz monitor (fix 42);
rem set DES_FPS=30 for the original 30, or any whole number 31-240 (PLAY_CHOOSE_FPS.bat asks).
rem Frame timing is recorded on every run: press F8 in the game right after a stutter, then run
rem REPORT.bat to pack it up for a GitHub issue (see README.md).
rem Where the PC cannot hold 60 (Boletarian Palace: ~58 since fix 36) the game step stretches to match,
rem so the game still runs at real speed instead of in slow motion (fix 33; DES_ADAPTIVE_STEP=0 = fixed 1/60).
rem Sound and music work (fix 29). Known gaps: intro movies are skipped.
rem Uses the build SETUP.bat / BUILD.bat make (port\build_opt).
setlocal
set "D=%~dp0"
if "%D:~-1%"=="\" set "D=%D:~0,-1%"
set "PS3_TITLE=Demon's Souls (ps3recomp)"
rem DES_GAME=<folder next to this file> picks the game files (default "game"); the PC Remaster mod copy
rem is "game_remaster" (PLAY_DEMONS_SOULS_REMASTER.bat, NOTES fix 45). Saves are shared.
if "%DES_GAME%"=="" set "DES_GAME=game"
if /i "%DES_GAME%"=="game_remaster" set "PS3_TITLE=Demon's Souls (ps3recomp) - PC Remaster mod"
set "PS3_HDD0_ROOT=%D%\hdd0"
set "PS3_HDD1_ROOT=%D%\hdd1"
set "RSX_LIVE_DRAW=1"
set "GCM_NO_TITLE_RECYCLE=1"
set "PS3_NP_STRICT_OFFLINE=1"
set "SPU_INTERP_UNLIFTED=1"
set "PS3_DEV_FLASH=%D%\no_flash"
set "SPURS_JC_EVENTS=0"
set "PS3_NO_SAIL=1"
set "PAD_KEYMAP=souls"
set "OSK_TEXT=%DES_NAME%"
set "PAD_SCRIPT="
rem Sound: threads start in PS3 priority order. Without it the audio notify queue (created by a
rem higher-priority thread) is read before it exists and the game stays silent (NOTES fix 29).
set "PS3_PRIO_START=1"
rem Even frame pacing (fix 37): when the game falls behind it renders two frames back to back;
rem this spaces their presents out instead of showing them a millisecond apart (judder).
set "LD_PRESENT_PACE=0.85"
rem The SPU code is built for AVX2 when the building CPU has it (fix 36); then a CPU without it
rem stops with a message box instead of crashing. BUILD.bat leaves no_avx2.txt for a build without.
set "PS3_REQUIRE_AVX2="
if not exist "%D%\port\build_opt\no_avx2.txt" set "PS3_REQUIRE_AVX2=1"
rem F12 while the game window is in front records that frame for debugging (every draw as an
rem image + the draw log) into captures\f<frame>. About 1 GB and a few seconds per press.
set "LD_F12_CAPTURE=%D%\captures"
rem 60 fps mode (default): the game steps a fixed 1/30 s per frame and its frame loop takes two
rem vblanks, so 60 fps = a 1/60 s step (DES_60FPS) + 120 Hz vblanks + guest clock at 200% (so the
rem game's own frame skip still keeps the speed right when a frame runs long) -- the same recipe
rem as RPCS3's 60 FPS patch. "set DES_FPS=30" before launching gives the original 30 fps.
rem 50 fps mode (NOTES fix 42): on a ~100 Hz monitor 60 fps cannot be even (frames stay up 1, 2 or 3
rem refreshes -- judder when the camera turns), so there the default is 50 fps with every frame shown for
rem exactly 2 refreshes: 100 Hz vblanks, guest clock 167%, present on every 2nd refresh. The adaptive step
rem keeps game speed right. "set DES_FPS=60" (or 30 / 50) before launching picks the mode by hand
rem ("set DES_FPS=unlimited" = uncapped, a number 31-240 = custom). PLAY_30FPS.bat / _50FPS.bat /
rem _UNLIMITED.bat / PLAY_CHOOSE_FPS.bat next to this file just set DES_FPS and call it.
set "DES_REFRESH="
for /f %%R in ('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Where-Object CurrentRefreshRate | Select-Object -First 1).CurrentRefreshRate"') do set "DES_REFRESH=%%R"
if "%DES_REFRESH%"=="" set "DES_REFRESH=60"
if "%DES_FPS%"=="" (
  set "DES_FPS=60"
  if %DES_REFRESH% GEQ 95 if %DES_REFRESH% LEQ 105 set "DES_FPS=50"
)
if "%DES_FPS%"=="60" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=120"
  set "PS3_CLOCK_SCALE=200"
)
if "%DES_FPS%"=="50" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=100"
  set "PS3_CLOCK_SCALE=167"
  set "LD_PRESENT_INTERVAL=2"
  set "LD_PRESENT_PACE=0"
)
rem Uncapped (fix 43): 480 Hz vblanks (game loop up to 240 fps), shortest step 1/240 s so the adaptive
rem step keeps real speed, no vsync. Boletarian Palace ~68 fps; frames are not evenly paced.
if "%DES_FPS%"=="unlimited" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=480"
  set "PS3_CLOCK_SCALE=200"
  set "DES_MAX_FPS=240"
  set "LD_PRESENT_INTERVAL=0"
  set "LD_PRESENT_PACE=0"
)
set "FPS_NOTE="
set "DES_CUSTOM=1"
for %%F in (30 50 60 unlimited) do if /i "%DES_FPS%"=="%%F" set "DES_CUSTOM="
if defined DES_CUSTOM call :custom_fps || exit /b 1
echo Running at %DES_FPS% fps%FPS_NOTE%.
rem Frame-timing recording (NOTES fix 46), on for every run (~25 MB an hour, no visible cost): press
rem F8 in the game window right after you see a stutter -- the window title counts the marks. Saved to
rem perf\<date_time>\perf.txt; REPORT.bat packs the newest one (+ a short summary, your PC's specs and
rem the end of the log) into a zip to attach to a GitHub issue. Only the newest 10 recordings are
rem kept. "set DES_RECORD=0" before launching turns recording off.
set "PD="
if "%DES_RECORD%"=="0" goto :no_record
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%T"
set "PD=%D%\perf\%TS%"
if not exist "%PD%" mkdir "%PD%"
for /f "skip=10 delims=" %%P in ('dir /b /ad /o-n "%D%\perf" 2^>nul') do rmdir /s /q "%D%\perf\%%P"
set "DES_PERF=1"
set "LD_PRESENT_LOG=%PD%\perf.txt"
set "LD_PRESENT_LOG_FROM=0"
set "LD_PRESENT_LOG_SECS=0"
rem When a game step runs 28 ms or more, a few stack samples of the main thread and HighGraphics go in the
rem recording too, so a freeze says what the game was doing (docs/NOTES.md fix 59). Costs nothing otherwise.
if not defined DES_PERF_STACKS set "DES_PERF_STACKS=1"
if not defined DES_PERF_STACK_THREADS set "DES_PERF_STACK_THREADS=HighGraphics"
echo Recording frame timing: press F8 in the game right after any stutter you see.
:no_record
set "EXE=%D%\port\build_opt\DemonsSoulsRecomp.exe"
if not exist "%EXE%" (
  echo DemonsSoulsRecomp.exe is not built yet. Run SETUP.bat first.
  pause
  exit /b 1
)
rem A killed run can leave truncated files in the HDD1 cache that the next run trusts.
if exist "%D%\hdd1\cache" rmdir /s /q "%D%\hdd1\cache"
if not exist "%D%\logs" mkdir "%D%\logs"
if exist "%D%\logs\last_run_out.txt" move /y "%D%\logs\last_run_out.txt" "%D%\logs\last_run_out_prev.txt" >nul
if exist "%D%\logs\last_run_err.txt" move /y "%D%\logs\last_run_err.txt" "%D%\logs\last_run_err_prev.txt" >nul
echo Starting Demon's Souls (the logos and loading take about a minute)...
cd /d "%D%"
"%EXE%" "%D%\%DES_GAME%\PS3_GAME\USRDIR\EBOOT.elf" > "%D%\logs\last_run_out.txt" 2> "%D%\logs\last_run_err.txt"
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
  echo.
  echo Demon's Souls exited with code %CODE%. The logs are in logs\last_run_*.txt.
  echo To report the crash, run REPORT.bat and attach the zip it makes to a GitHub issue.
  pause
)
exit /b %CODE%

rem Custom frame rate N (31-240): 2 vblanks per game frame, guest clock N/30 (at most 200%, as the
rem 60 fps and uncapped modes), shortest adaptive step 1/N above 60. When the monitor's refresh is a
rem whole multiple of N every frame stays up the same number of refreshes (vsync, even pacing);
rem otherwise vsync is off, which is smooth on a G-Sync / FreeSync screen and may tear on others.
:custom_fps
set "N="
set /a "N=%DES_FPS%" 2>nul
if not "%N%"=="%DES_FPS%" goto :bad_fps
if %N% LSS 31 goto :bad_fps
if %N% GTR 240 goto :bad_fps
set "DES_60FPS=1"
set /a "PS3_VBLANK_HZ=N*2"
set /a "PS3_CLOCK_SCALE=(N*100+15)/30"
if %PS3_CLOCK_SCALE% GTR 200 set "PS3_CLOCK_SCALE=200"
if %N% GTR 60 set "DES_MAX_FPS=%N%"
set "LD_PRESENT_PACE=0"
set "LD_PRESENT_INTERVAL=0"
set "FPS_NOTE= (vsync off: %DES_REFRESH% Hz is not a multiple of %N%)"
rem Windows reports fractional refresh rates rounded down (99.98 Hz -> 99), so try one higher too.
set /a "K=DES_REFRESH/N, RMD=DES_REFRESH %% N, K2=(DES_REFRESH+1)/N, RMD2=(DES_REFRESH+1) %% N"
if %K2% GEQ 1 if %RMD2% EQU 0 set "LD_PRESENT_INTERVAL=%K2%"
if %K% GEQ 1 if %RMD% EQU 0 set "LD_PRESENT_INTERVAL=%K%"
if not "%LD_PRESENT_INTERVAL%"=="0" set "K=%LD_PRESENT_INTERVAL%"
if not "%LD_PRESENT_INTERVAL%"=="0" set "FPS_NOTE= (vsync on: every frame shown %K% of your monitor's %DES_REFRESH% Hz refreshes)"
exit /b 0
:bad_fps
echo DES_FPS=%DES_FPS% is not a frame rate this port can run: use 30, 50, 60, unlimited, or a whole
echo number from 31 to 240.
pause
exit /b 1
