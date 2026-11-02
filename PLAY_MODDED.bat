@echo off
rem Demon's Souls with your imported models: runs the modded copy game_mod that
rem tools\flver_tool.py import writes (hard links to the normal game + your model files;
rem docs\NOTES.md fix 61). The normal game\ is never changed. Same saves, controls, frame-rate
rem choice and F9 god mode as PLAY.bat. Delete game_mod to undo every import.
if not exist "%~dp0game_mod\PS3_GAME\USRDIR\EBOOT.elf" (
  echo No models imported yet. See models\README.txt.
  pause
  exit /b 1
)
set "DES_GAME=game_mod"
call "%~dp0PLAY.bat"
