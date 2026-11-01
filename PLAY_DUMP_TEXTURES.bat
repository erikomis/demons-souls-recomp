@echo off
rem Demon's Souls with texture dumping on (docs/NOTES.md fix 60): every texture the game draws is saved
rem once, as it looks in game, to textures\dump\<KEY>_<width>x<height>_<format>.png (plus index.csv).
rem To replace one: put an edited .png (any size) or a .dds (DXT1/3/5, BC4, BC7 or 32-bit RGBA) whose
rem name starts with the same 16-character KEY in textures\replace (sub folders are fine).
rem Replacements load in every launcher; this one only adds the dumping. Walking into a new area may
rem stutter a little while the PNGs are written. Same saves, controls and frame rate as PLAY.bat.
set "LD_TEX_DUMP=1"
call "%~dp0PLAY.bat"
