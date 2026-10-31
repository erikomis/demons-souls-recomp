@echo off
rem Demon's Souls at the original 30 fps (the game's own frame rate; no 60 fps patch).
rem Same as PLAY.bat in every other way (saves, controls, logs).
set "DES_FPS=30"
call "%~dp0PLAY.bat"
