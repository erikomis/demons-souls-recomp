@echo off
rem Demon's Souls at 50 fps locked to a 100 Hz monitor - every frame shown for exactly 2 refreshes (NOTES fix 42).
rem Same as PLAY.bat in every other way (saves, controls, logs).
set "DES_FPS=50"
call "%~dp0PLAY.bat"
