@echo off
rem Demon's Souls with the "Demon's Souls PC Remaster" mod by fromsoftserve (Nexus Mods, mod 106):
rem relit models, normal / specular maps, cubemap armour, better shadows. Runs the modded copy
rem game_remaster (hard links to the normal game + the mod's files, made by
rem tools\install_remaster.py; docs\NOTES.md fix 45).
rem Same saves, controls, frame-rate choice (auto 50/60) and F9 god mode as PLAY.bat.
set "DES_GAME=game_remaster"
call "%~dp0PLAY.bat"
