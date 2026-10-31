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
rem set DES_FPS=30 for the original 30.
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
rem The SPU code is built for AVX2 (fix 36); this makes a CPU without it stop with a message box.
set "PS3_REQUIRE_AVX2=1"
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
rem ("set DES_FPS=unlimited" = uncapped). PLAY_DEMONS_SOULS_30FPS.bat / _50FPS.bat / _UNLIMITED.bat
rem next to this file just set DES_FPS and call it.
if "%DES_FPS%"=="" (
  set "DES_FPS=60"
  for /f %%R in ('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Where-Object CurrentRefreshRate | Select-Object -First 1).CurrentRefreshRate"') do (
    if %%R GEQ 95 if %%R LEQ 105 set "DES_FPS=50"
  )
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
echo Running at %DES_FPS% fps.
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
  pause
)
exit /b %CODE%
