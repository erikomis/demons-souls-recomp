@echo off
rem Demon's Souls with a frame rate you pick from a menu, including any number you type in (31-240).
rem Same as PLAY.bat in every other way (saves, controls, recording, logs).
setlocal
echo Demon's Souls - choose a frame rate
echo.
echo   1  Auto: 60 fps, or 50 on a 100 Hz monitor (same as PLAY.bat)
echo   2  30 fps (the original game)
echo   3  50 fps (for 100 Hz monitors)
echo   4  60 fps
echo   5  Unlimited (up to 240, no vsync)
echo   6  Custom: type your own number
echo.
set "C="
set /p "C=Choice [1-6, Enter = 1]: "
set "DES_FPS="
if "%C%"=="2" set "DES_FPS=30"
if "%C%"=="3" set "DES_FPS=50"
if "%C%"=="4" set "DES_FPS=60"
if "%C%"=="5" set "DES_FPS=unlimited"
if not "%C%"=="6" goto :run
echo.
echo Any whole number from 31 to 240. Smoothest when your monitor's refresh rate is a multiple of it
echo (for example 72 or 144 on a 144 Hz screen, 40 or 120 on 120 Hz); otherwise vsync is turned off,
echo which is fine on a G-Sync / FreeSync screen but may tear on others. Game speed stays correct.
set /p "DES_FPS=Frame rate: "
:run
call "%~dp0PLAY.bat"
