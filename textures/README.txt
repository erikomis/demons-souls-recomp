Texture packs (docs/NOTES.md fix 60)
============================

dump\     The launcher's "Dump textures" saves every texture the game draws here, once, as it
          looks in game:  <KEY>_<width>x<height>_<format>.png   (index.csv lists them all).
          KEY is 16 characters (0-9, A-F) computed from the texture's contents, so the same
          texture gets the same KEY every run and on every PC.

replace\  Any .png or .dds here whose file name STARTS WITH a KEY is drawn instead of that
          texture, however the game is started. Sub folders are fine; anything after the KEY in the name is
          ignored (e.g. 0123456789ABCDEF_knight_armour_4k.png).
          - Any size works (a 512x512 texture can be replaced by a 2048x2048 one).
          - .png: 8-bit RGBA or RGB. Mipmaps are made automatically.
          - .dds: DXT1/DXT3/DXT5, BC7, BC4 (greyscale) or 32-bit RGBA, 2D only (no cubemaps), with or
            without mipmaps. DDS loads faster and uses less video memory than PNG -- best for big
            packs. BC5 is not accepted (it has no blue or alpha channel).
          - Edit the DUMPED png: its colours are exactly what the game samples, including textures
            whose channels look odd (normal maps etc.); keep the same channel meaning.
          - If both a .png and a .dds have the same KEY, the .dds is used.
          Restart the game to pick up new or changed files.

kbm\      Keyboard / mouse button icons (docs/NOTES.md fix 91): files named like replace\ ones, drawn instead
          of their texture only while the keyboard / mouse was used last (the controller brings the PS3 art
          back). BUILD.bat makes them from your copy of the game (tools\kbm_icons.py); edit them like any
          replacement, or delete version.txt to have BUILD.bat draw them again.

Settings (environment variables, set before starting the launcher or PLAY.bat; or in the launcher's
Extra settings box):
  LD_TEX_REPLACE=0       ignore the replace folder
  LD_TEX_DIR=<folder>    use another folder instead of this one
  LD_TEX_REPLACE_MB=4096 video memory kept for loaded replacements not drawn right now
  LD_TEX_THREADS=2       background threads loading / saving textures
  LD_TEX_LOG=1           log every replacement as it loads (default: the first 32)
  LD_TEX_KBM=0 / 1       never / always use the kbm folder (default: follow the keyboard / controller)

What is not covered: cubemaps (reflections) and 1-pixel-high colour ramps. Textures the game
rewrites constantly (movies, render copies) are only dumped for their first few versions.
Models are not part of this; model mods are file mods (see the PC Remaster section of README.md).
Messages go to logs\last_run_err.txt, lines starting with [texpack].
