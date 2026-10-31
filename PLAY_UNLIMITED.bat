@echo off
rem Demon's Souls at uncapped frame rate, up to 240 fps, no vsync; game speed stays real (NOTES fix 43).
rem Same as PLAY.bat in every other way (saves, controls, logs).
set "DES_FPS=unlimited"
call "%~dp0PLAY.bat"
