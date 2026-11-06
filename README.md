# Demon's Souls — native PC port (ps3recomp)

A native Windows build of **Demon's Souls** (PS3, USA, **BLUS-30443**), made by statically
recompiling the game's PowerPC (PPU) and SPU code to C/C++ with
[ps3recomp](https://github.com/sp00nznet/ps3recomp), plus a PS3 runtime and a Direct3D 12 renderer.
It is not an emulator: the game's code runs as a normal x64 program.

> **No game files are included.** This repo holds only the tools, patches and build scripts. You
> need your own copy of the game, dumped from your own disc. The setup reads your disc image and
> builds everything on your PC.

**Community Discord:** [discord.gg/gTvrZZ75G](https://discord.gg/gTvrZZ75G) (questions, help with setup,
bug reports and screenshots). Bug reports with a REPORT.bat zip are still best as a GitHub issue.

## Status

**The entire game seems playable.** It runs with sound and music at 60 fps (or 50 on a 100 Hz
screen, 30, uncapped, or any frame rate you pick), with keyboard + mouse or an Xbox controller. The game's movies play (title screen, intro,
story and endings; `set DES_MOVIES=0` skips them). The in-engine cutscenes are smooth at 60 fps and above too:
their camera is blended between its 30 fps keys (`set DES_CUT_BLEND=0` for the original nearest-key camera).

**Above 60 fps there are known bugs**, such as the sound drifting out of sync with the picture. (The dash
slowing to half speed above 150 fps is fixed.) 60 fps (or 50 on a 100 Hz screen) is the recommended setting;
higher frame rates are still being worked on.

**There is no online play yet.** Multiplayer will be added once the game is optimised.

**Performance:** on high-end hardware the game is mostly smooth. Optimisations for lower-end PCs
(fewer cores, older CPUs, Steam Deck) are happening now.

I'm currently playing through the whole game to find and fix any spots that still run slower
than they should (stutters, frame drops in heavy scenes). Boletarian Palace, the heaviest area
tested so far, is already smooth on a fast PC. Expect more performance fixes as the playthrough goes on; see
[docs/NOTES.md](docs/NOTES.md) for the full development log (50 fixes and counting).

If you hit a stutter or a crash, please report it: see
[Reporting stutters and crashes](#reporting-stutters-and-crashes). Every run is recorded, so all it
takes is pressing **F8** when it happens and running `REPORT.bat` afterwards.

## What you need

- **Windows 10/11 x64** and a **Direct3D 12** GPU. AVX2 (Intel Haswell / AMD Ryzen or newer) is used
  when your CPU has it; on older CPUs BUILD.bat builds without it (a couple of fps slower in the
  heaviest areas).
- About **14 GB** free disk space (8 GB game files + build + tools).
- **Your disc image** of Demon's Souls USA (BLUS-30443): a `.iso` (a Redump `.zip` works as is), or a
  dumped disc folder with `PS3_GAME` in it. A Redump-style encrypted image also needs its
  **disc key** (the `.dkey` file that comes with the dump). No `.dkey`? The key is public: it is the
  "Disc Key" line on [Redump's page for this disc](http://redump.org/disc/16199/) (Demon's Souls, USA, BLUS-30443, version
  01.00). SETUP opens that page for you when it needs the key.
- **Nothing else to install.** SETUP downloads what it needs into the folder (`deps\`), with no
  installer and no administrator rights: a portable **Python** and **Git** when you have none,
  **[RPCS3](https://rpcs3.net)** (used once to decrypt the game's `EBOOT.BIN`), and, without Visual
  Studio, a portable compiler (**LLVM** + Microsoft's C runtime and Windows SDK, about 1.3 GB, fetched
  by [xwin](https://github.com/Jake-Shadle/xwin); Microsoft's license applies). The Python, Git, LLVM,
  RPCS3 and xwin downloads are checked against pinned or published checksums. Already have Python 3.10+, Git, RPCS3
  (`SETUP.bat --rpcs3 path\to\rpcs3.exe`) or **Visual Studio 2022** with *Desktop development with
  C++* + **LLVM** 17 or newer? Then those are used instead. RPCS3 needs the Microsoft Visual C++
  runtime, which most PCs already have; SETUP offers Microsoft's installer if yours does not. (Installed
  Visual Studio later and want it used? Delete `deps\.portable_compiler`.) Keep the folder's path plain:
  no `[ ]` or `&` in it (the build tools cannot handle them; SETUP says so).

**macOS (Apple Silicon):** a native arm64 build that draws through Metal, contributed by erikomis (PR #30).
It plays through the menus, character creation and into the Tutorial so far; build steps, controls and known
gaps are in [docs/MACOS.md](docs/MACOS.md). It is experimental, and the Windows build is unchanged.

**Linux / Steam Deck:** a setup + play kit (an AppImage) builds the same port from your own disc
image on Linux and runs it through Proton. See [docs/LINUX.md](docs/LINUX.md).
**It works on Linux:** set up and played on Ubuntu 24.04 (Intel i7-4770K + NVIDIA GTX 980). On that
4-core CPU it is still choppier than on Windows (Linux performance work is under way). A Steam Deck is
not confirmed yet; please report how it goes.

## Build it (one time)

The setup below has been tested on a clean Windows install (Windows Sandbox: no
Python, Git, Visual Studio, RPCS3 or Visual C++ runtime) and on a normal gaming PC.

1. Download the newest release: **[Releases](https://github.com/timboat/demons-souls-recomp/releases/latest)** → `DemonsSoulsRecomp-<version>.zip` (or the
   green **Code** button → *Download ZIP*, or `git clone`), and unpack it somewhere with enough
   space, for example `C:\Games\DemonsSouls`. Keep the path plain (no `[ ]` or `&`). There is no
   ready-to-play download: the game is built on your PC from your own disc.
2. Double-click **`DemonsSoulsLauncher.exe`** (it is in the release ZIP) and press **PLAY**. It sees
   that the game is not built yet and offers to run `SETUP.bat`: answer **Yes**. (Or drag your disc
   image onto `SETUP.bat`, or double-click `SETUP.bat`; same thing.)
3. Answer SETUP's questions. Pressing **Enter** takes the suggested answer, which is right almost always:
   - **your disc image**: drag the `.iso` / `.zip` / disc folder into the window (or paste its path) and
     press Enter;
   - **the disc key**, only for an encrypted image without a `.dkey` file: SETUP opens
     [Redump's page](http://redump.org/disc/16199/) in your browser; copy the long code on its
     "Disc Key" line and paste it with **Ctrl+V**;
   - whether it may **download** RPCS3, a portable Python / Git and the portable compiler (say yes);
   - the **Microsoft Visual C++ runtime** for RPCS3, if your PC has none: Windows asks you to allow
     Microsoft's installer;
   - **xwin** asks you to accept Microsoft's license for the C runtime / Windows SDK it downloads.
4. Wait for **All done**, then press **PLAY** in the launcher.

SETUP.bat then:

| step | what happens | time* |
|---|---|---|
| 1 | extracts all game files from the image (and decrypts them) into `game/` | 2–5 min |
| 2 | decrypts `EBOOT.BIN` → `EBOOT.elf` with RPCS3 and checks it is the tested version | < 1 min |
| 3 | downloads ps3recomp at the tested commit and applies this port's runtime patch | < 1 min |
| 4 | recompiles the game: ~94,000 PPU functions + 12 SPU programs → C/C++ in `port/` | 2–4 min |
| 5 | applies this port's edits to the recompiled code (`patches/lifted-code.patch`) | seconds |
| 6 | compiles everything with clang-cl into `port/build_opt/DemonsSoulsRecomp.exe` (plus `DemonsSoulsLauncher.exe`, next to `PLAY.bat`) | 10–30 min |

\* on a fast 16-core PC; the first compile is the long part. The compile shows one progress line
(`compiling 47/322 (15%)`); the compiler's full output goes to `logs\build_last.txt`. If anything fails, fix
what it says and run SETUP.bat again: finished steps are skipped.

## Updating

Press **Check for updates** in the launcher: it asks GitHub, lists what is new and, if you say yes,
downloads it, puts it in the folder and rebuilds the game; the launcher then opens again. **No Git
needed:** a copy from a release ZIP (or the Code ZIP) gets the newest release (checked against the
checksum GitHub publishes for it; your game files, build, saves and settings are not touched), a
`git clone` gets `git pull`. The launcher's status line shows which release you have.
Copies from before release v2026.11.03.7 need this once by hand: download the newest
[release](https://github.com/timboat/demons-souls-recomp/releases/latest) ZIP and copy everything inside its folder over your old folder,
replacing files (`game/`, `port/`, `deps/` and your saves are not in the ZIP, so they stay), then
press Play (or run **`BUILD.bat`**). It re-applies
the patches that changed since your last setup and recompiles only the files they touch. If it
says so, run `SETUP.bat` instead: that also works, keeps the game files and skips what is done.
If you forget, Play notices that the folder was updated but not rebuilt and runs BUILD.bat first
(an old build with new files can stay on a black screen). To play the build you already have instead, tick
**Keep my build after updates** in the launcher (or `set DES_NO_REBUILD=1`); the update's fixes then wait until
you run BUILD.bat. And if a rebuild does not finish, Play asks whether to start the build you already have.
Setups made before 2026-11-03 could not take updates (the patches were applied once and never
again); the first `BUILD.bat` or `SETUP.bat` with this version brings them up to date.

## Play

Double-click **`DemonsSoulsLauncher.exe`** (SETUP.bat / BUILD.bat build it next to `PLAY.bat`) and
press **PLAY**. The logos and first load take about a minute.

The launcher is one window for every option below: frame rate (Auto, 30, 50, 60, unlimited or any
number, with a line saying how it will look on your screen), internal resolution, Normal / PC Remaster
mod / your imported models, fullscreen, movies, god mode, frame-timing recording, texture dumping,
keys by letter and CPU core pinning. It remembers them in `launcher.ini`. Its buttons: **Check for
updates** (shows what is new on GitHub; on yes `git pull` + `BUILD.bat`, then it opens again), **Report a problem** (`REPORT.bat`), **Controls** and
**Folders** (saves, logs, recordings, texture and model folders). If the game crashes it offers to
make the report. *Extra settings* takes any `NAME=value` switch from this README or from an issue
(e.g. `LD_PSO_ASYNC=0`). `DemonsSoulsLauncher.exe --play` starts the game straight away with the
saved settings, for a desktop shortcut.

The launcher runs `PLAY.bat` with your choices. `PLAY.bat` on its own starts the game at 60 fps (50 fps
automatically on a ~100 Hz monitor, every frame shown exactly 2 refreshes), and the `set X=...` switches
in this README work in front of it too. The separate `PLAY_30FPS.bat`, `PLAY_REMASTER.bat` etc. are gone:
those are all launcher options now.

| launcher option | what it does |
|---|---|
| *Frame rate*: Auto / 30 / 50 / 60 / Unlimited / Custom... | Auto = 60, or 50 on a ~100 Hz screen; 30 = the original; Unlimited = up to 240 fps, no vsync, game speed stays correct; Custom = **any frame rate you type in** (31–240) |
| *Game*: Normal / PC Remaster mod / My models | your game as on the disc, with the *PC Remaster* mod installed, or with your imported models (see below) |
| *Dump textures* | saves every texture the game draws, for texture packs (see below) |
| *Skip the intro (straight to PRESS START)* | the logos and the opening movie are skipped (the window stays black for a few seconds, then the title screen); the story movies still play |
| *Keep my build after updates* | after an update, plays the build you already have instead of rebuilding first |

Without the launcher (Linux, or `PLAY.bat` by hand) the same choices are switches: `DES_FPS=30|50|60|unlimited|31-240`,
`DES_GAME=game_remaster` (PC Remaster) or `DES_GAME=game_mod` (your models), `LD_TEX_DUMP=1` (dump textures),
`DES_SKIP_INTRO=1` (skip the intro), `DES_NO_REBUILD=1` (keep my build).
In the launcher, any other folder made by `tools\flver_tool.py import --mod <folder>` goes in *Extra settings*
as `DES_GAME=<folder>`.

**Custom frame rate.** In the launcher pick *Custom...* and type a
number, e.g. 45, 72, 120 or 144. The game
runs at real speed at any of them. If your monitor's refresh rate is a whole multiple of the number
(72 or 144 on a 144 Hz screen, 40 or 120 on 120 Hz), every frame is shown for the same number of
refreshes and motion is perfectly even. Otherwise vsync is turned off, which looks fine on a
G-Sync / FreeSync screen but can tear on others. The launcher says which one you got. You can also
`set DES_FPS=<number>` before running `PLAY.bat`.

**Higher resolution.** *Resolution* in the launcher, or `set DES_RES_SCALE=2` (up to 4) before running
`PLAY.bat`, renders the game at
2x its 1280x720 (2560x1440), much sharper, at no cost on the CPU side; a mid-range GPU handles 2x easily.
The window and borderless fullscreen show the picture at the window's own size, at the game's 16:9
with black bars on other screens (`set LD_SWAP_RESIZE=0` = the old stretched picture).
*Sharper shadows too* (`set LD_RES_SCALE_SHADOW=1`) also renders the 2048x2048 shadow map at the
higher resolution.

**Controls.** An Xbox (XInput) controller works when plugged in (A = Cross, B = Circle, X = Square,
Y = Triangle, LB/RB = L1/R1, LT/RT = L2/R2, Back = Select). A DualShock/DualSense needs Steam Input or
DS4Windows. Keyboard + mouse work too, also with a controller connected (the mouse takes over the
camera once you press a key or mouse button, and the controller takes it back when you use it):

| | |
|---|---|
| WASD | move |
| mouse (or IJKL) | camera (click into the game to capture the mouse) |
| left mouse | attack (R1) |
| Shift | strong attack (R2) |
| right mouse | block (L1) |
| Ctrl | parry (L2) |
| Space | roll / dash / back (Circle) |
| E | interact / confirm (Cross) |
| F | two-hand (Triangle) |
| R | use item (Square) |
| Tab / middle mouse | lock on (R3) |
| arrows | d-pad (switch items) |
| Enter / Backspace | Start / Select |
| Esc or F1 | release the mouse (F1 also captures it again; leaving the window or using a controller also releases it). Esc no longer closes the game: use the X or Alt+F4 |
| Alt+Enter / F11 | borderless fullscreen on/off (`set DES_FULLSCREEN=1` starts in it) |
| F9 | god mode on/off (no death, HP/MP/stamina stay full) |

**In menus** (title screen, Start menu, inventory, shops, level-up, ...) the mouse is a pointer: the Windows arrow
appears, **moving it over an item selects it** (with the game's own cursor sound and help text), **left click on an
item confirms it** (on another item it selects it first, on empty space it does nothing), **right click = back**,
the **wheel** moves the cursor up and down, and the mouse's side buttons or **PageUp / PageDown** are L1 / R1. Keys
and the controller take over as soon as you use them; the mouse only takes over again once it moves. When the menu
closes the mouse goes back to the camera. Pointing works in the title, profile select, Start menu tabs, inventory,
equipment, item commands, shops, talk choices, level-up, the archstone list, the System menu and yes / no boxes; the
Options rows still use keys / wheel (a click there confirms as before). `set DES_POINT=0` turns pointing off (the
mouse then only clicks / scrolls in menus), `set PAD_MENU_MOUSE=0` turns the mouse in menus off altogether. Outside
menus the mouse buttons attack and block as before.

**Button icons follow what you play with:** while the keyboard / mouse is what you used last, the game's button
icons (key guides, "Pick up" prompts, the HUD's equipment boxes, the Start menu tabs) show the keys and mouse
buttons instead of the PS3 buttons; touch the controller and they are PS3 buttons again. BUILD.bat draws them
once from your own copy of the game into `textures\kbm` (the letters are the game's own font). `set LD_TEX_KBM=0`
always shows the PS3 buttons, `set LD_TEX_KBM=1` always the keyboard ones. The title screen says "PRESS ENTER
BUTTON" instead of "PRESS START BUTTON" the same way.

The mouse turns the camera directly (no stick dead zone or speed limit) and follows the game's invert-camera
options. `set PAD_MOUSE_LOOK_SENS=0.0012` sets the sensitivity (radians per mouse count), `set PAD_MOUSE_LOOK=0`
goes back to the old stick-style mouse.

Keys go by position, not by letter: on an AZERTY or QWERTZ keyboard you move with the keys where
WASD would be (ZQSD on AZERTY), and the others follow the same way. `set PAD_KEYS_BY_LETTER=1` = by letter.

At *Create Profile* a text box opens for the character name. Saves go to `gamedata/`. Each run
writes logs to `logs/` (they grow by ~600 MB an hour; the previous run is kept as `*_prev.txt`).

## Reporting stutters and crashes

The game records frame timing while you play (*Record frame timing (F8)* in the launcher, on by default) (about 25 MB an hour, no visible cost; the newest
10 sessions are kept in `perf\`). The window title shows `[RECORDING - F8 = stutter, N marked]`.

1. **Press F8** in the game right after you see a stutter, hitch or slowdown. Each press puts a mark
   in the recording at that moment, so the exact frames can be found later. Press it as often as you
   like.
2. **After you quit** (or right after a crash), press **Report a problem** in the launcher (or
   double-click **`REPORT.bat`**). It packs the last
   session into one zip, shows it in Explorer and opens the GitHub *New issue* page.
3. **Open an issue** with the *Stutter / slowdown* or *Crash / bug* template, **drag the zip into
   it**, and say where you were in the game and what you saw at each F8 press.

What the zip contains (nothing else, and your Windows user name is removed from all of it):

| file | what it is |
|---|---|
| `report.txt` | the summary from `tools/perf_report.py`: frame pacing, every hitch with its likely cause (a slow game step, shader compile, slow file read, the renderer, the GPU), and what happened just before each F8 mark |
| `perf.txt` | the recording itself, so we can dig into the exact frames (trimmed to the minutes around your F8 marks if the session is too long for GitHub's 25 MB limit) |
| `system.txt` | Windows version, CPU, RAM, GPU + driver, monitor resolution / refresh, the frame-rate setting and which version of this port you built |
| `log_tail.txt` | the last 400 lines of the game's log, from the same session (shows what it was doing if it crashed) |

Curious yourself? `.venv\Scripts\python tools\perf_report.py` prints the same summary for your newest
recording. To play without recording, untick *Record frame timing (F8)* in the launcher (or `set DES_RECORD=0`
before running `PLAY.bat`).

## Optional: PC Remaster mod

The *Demon's Souls PC Remaster* mod by fromsoftserve (Nexus Mods, Demon's Souls mod 106)
(made for RPCS3) works with this port. Download the mod's zip yourself, then:

```bat
.venv\Scripts\python tools\install_remaster.py "path\to\the mod.zip" --apply
```

That builds `game_remaster/` as a hard-linked copy of `game/` (no extra disk space) with the mod's
files swapped in. Your normal `game/` is not changed. Play it with *Game: PC Remaster mod* in the launcher.

## Optional: texture packs

Textures can be replaced without unpacking any game files, at any resolution:

1. Tick *Dump textures* in the launcher and play through the part you want to change. Every texture the game
   draws is saved once to `textures\dump\` as `<KEY>_<width>x<height>_<format>.png`, exactly as it
   looks in game. The 16-character KEY comes from the texture's contents, so it is the same on every PC.
2. Edit a PNG (or make a bigger one) and put it in `textures\replace\` with a name that starts with
   the same KEY, e.g. `0123456789ABCDEF_armour_4k.png`. Sub folders are fine.
3. Play as usual (untick *Dump textures*). Replacements load in the background; `.dds` files (DXT1/3/5, BC7, BC4 or 32-bit
   RGBA, with or without mipmaps) load faster and use less video memory than PNG.

Details and settings: `textures\README.txt`. Cubemaps (reflections) are not covered; for models see
the next section. Packs are made from the game's art -- share them only where that is allowed.

## Optional: model import/export

Armour, weapons, characters, objects and map pieces can be exported to glTF, edited in Blender (or
anything that reads and writes glTF 2.0) and imported back:

```
.venv\Scripts\python tools\flver_tool.py export game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
  -> models\BD_F_5010\BD_F_5010.gltf (+ .bin and the textures as PNG)
  ... Blender: File > Import > glTF 2.0, edit, File > Export > glTF 2.0 (.glb is fine) ...
.venv\Scripts\python tools\flver_tool.py import models\BD_F_5010\edited.glb game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
```

Import writes `game_mod\`, a copy of `game\` made of hard links (no extra disk space); `game\` is
never changed. Play it with *Game: My models* in the launcher; delete `game_mod\` to undo everything. Shape, UVs,
vertex colours and bone weights come from your file; materials, textures, skeleton, collision and
animations stay the game's (change textures with texture packs). Edit the `_l` low-detail copy too,
or the old shape shows from far away. Which file holds what and the rules: `models\README.txt`.
`flver_tool.py selftest` checks every model in your game reads and writes back byte for byte.
Exported models are the game's art -- share them only where that is allowed.

## Repo layout

```
SETUP.bat / BUILD.bat        one-time setup / rebuild after code changes
DemonsSoulsLauncher.exe      the settings window (built by SETUP/BUILD from project/launcher/)
PLAY.bat                     starts the game; the launcher runs it (environment switches documented inside)
REPORT.bat                   packs the last session into a zip for a GitHub issue
setup/setup.py, build.py     the setup pipeline and the toolchain finder + build
project/                     CMake project: CMakeLists.txt, main.cpp, stubs.cpp
patches/ps3recomp-local.patch   this port's changes to the ps3recomp runtime/renderer (applied to
                                ps3recomp @ 4e8f3ca, v0.18.0)
patches/lifted-code.patch    this port's edits to the recompiled game code (frame pacing, 60 fps
                             step, god mode, test hooks)
tools/                       disc extraction, UDF names, SPURS job lifting, perf report + issue zip, mod installer,
                             model export/import (flver_tool.py, souls_formats.py)
docs/NOTES.md                development log: every fix, why, and how it was measured
linux/, docs/LINUX.md        Linux / Steam Deck kit: setup.sh, play.sh, the AppImage (linux/appimage)
mac/, docs/MACOS.md          native macOS (Apple Silicon, Metal) build: install.sh, rebuild.sh, play.sh, the launcher app
setup/clang-cl-xwin.cmake    the cross toolchain Linux builds with (clang-cl + an SDK fetched by xwin)
```

Everything SETUP.bat produces (`game/`, `port/`, `deps/`, `.venv/`, saves, logs) is in `.gitignore`.
**Never commit or share those**: they are the game.

## Troubleshooting

- **No online play yet.** Demon's Souls' servers closed in 2018; multiplayer will be added once the game is
  optimised. For now the game goes straight into offline play
  without the "Cannot connect (009)" and "Offline Mode" boxes (`set DES_AUTO_OFFLINE=0` shows them again).

- **"RPCS3 did not write EBOOT.elf"**: close any open RPCS3 window and run SETUP.bat again, or decrypt
  by hand: RPCS3 → *Utilities* → *Decrypt PS3 Binaries* → `game\PS3_GAME\USRDIR\EBOOT.BIN`.
  If RPCS3 itself complains, install the PS3 firmware in RPCS3 first (*File → Install Firmware*).
  SETUP tries three times and shows RPCS3's exit code and log. In **Windows Sandbox or a virtual
  machine** RPCS3 can crash inside the virtual GPU's driver before it decrypts anything (it starts
  Vulkan even just to decrypt, and as administrator Vulkan cannot be told to skip the driver): decrypt
  `EBOOT.BIN` on another PC with RPCS3 and copy the `EBOOT.elf` into `game\PS3_GAME\USRDIR\`, then
  run SETUP.bat again.
- **"EBOOT.BIN is not the tested one"**: only the USA disc (BLUS-30443, version as on the disc) is
  supported. Other regions or updated EBOOTs need different patches.
- **Build tools not found**: run SETUP.bat or BUILD.bat again and let it download the portable
  compiler (answer yes). Or install Visual Studio 2022 Build Tools with *Desktop development with C++*
  and LLVM (`winget install LLVM.LLVM`), or set `LLVM_DIR` to an LLVM folder, then run BUILD.bat.
- **The setup window seems stuck**: the compile shows one progress line and can sit on one file for
  a minute; its full output is in `logs\build_last.txt`. If nothing moves for many minutes, press
  Enter once in the window.
- **The game window stays black / closes**: look at the end of `logs\last_run_err.txt`.
- **Uneven frames at 100+ fps in busy areas** (e.g. the Valley of Defilement swamp): the game's own
  frame work can need more than 10 ms there; the 50 fps mode is even everywhere. On CPUs with two
  core complexes the game pins itself to the one with the biggest L3 (docs/NOTES.md fix 65);
  `set DES_AFFINITY=0` turns that off.
- **A character or object is black, or missing, for a moment the first time you see it**: its shaders
  are being compiled in the background (instead of freezing the game; docs/NOTES.md fix 62). It only
  happens the first time a shader is ever seen. `set LD_PSO_ASYNC=0` before PLAY.bat = wait instead.
- **"needs AVX2"** message box: this build was made on a PC with AVX2 and yours has none. Run
  BUILD.bat on this PC (it picks the right setting), or `set DS_AVX2=0` before BUILD.bat on the other one.

## Credits and license

- [ps3recomp](https://github.com/sp00nznet/ps3recomp) by Ned Heller / sp00nznet (MIT): the recompiler
  and runtime this port is built on.
- [RPCS3](https://rpcs3.net): used to decrypt the EBOOT, and as the reference for how the PS3 behaves.
- The *PC Remaster* mod is by fromsoftserve.

This repo's own code and patches are under the MIT license (see [LICENSE](LICENSE)). Demon's Souls is
© Sony Interactive Entertainment / FromSoftware. This project is not affiliated with or endorsed by
them, and contains none of their files. Buy the game and dump your own disc.
