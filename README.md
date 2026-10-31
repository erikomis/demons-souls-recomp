# Demon's Souls — native PC port (ps3recomp)

A native Windows build of **Demon's Souls** (PS3, USA, **BLUS-30443**), made by statically
recompiling the game's PowerPC (PPU) and SPU code to C/C++ with
[ps3recomp](https://github.com/sp00nznet/ps3recomp), plus a PS3 runtime and a Direct3D 12 renderer.
It is not an emulator: the game's code runs as a normal x64 program.

> **No game files are included.** This repo holds only the tools, patches and build scripts. You
> need your own copy of the game, dumped from your own disc. The setup reads your disc image and
> builds everything on your PC.

## Status

**The entire game seems playable.** It runs with sound and music at 60 fps (or 50 on a 100 Hz
screen, 30, or uncapped), with keyboard + mouse or an Xbox controller. Intro movies are skipped and
there is no online play.

I'm currently playing through the whole game to find and fix any spots that still run slower
than they should (stutters, frame drops in heavy scenes). Boletarian Palace, the heaviest area
tested so far, is already smooth. Expect more performance fixes as the playthrough goes on; see
[docs/NOTES.md](docs/NOTES.md) for the full development log (50 fixes and counting).

If you hit a stutter, run `PLAY_RECORD.bat`, press **F8** right after it happens, and open an
issue with the `perf\<date>\perf.txt` it saves.

## What you need

- **Windows 10/11 x64**, a CPU with **AVX2** (Intel Haswell / AMD Ryzen or newer), a **Direct3D 12** GPU.
- About **12 GB** free disk space (8 GB game files + build).
- **Your disc image** of Demon's Souls USA (BLUS-30443): a `.iso` (a Redump `.zip` works as is), or a
  dumped disc folder with `PS3_GAME` in it. A Redump-style encrypted image also needs its
  **disc key** (the `.dkey` file that comes with the dump, or the "Disc Key" on its Redump page).
- **[RPCS3](https://rpcs3.net/download)**, used once to decrypt the game's `EBOOT.BIN`. Unzip it anywhere.
- **Python 3.10+** and **Git**. If they are missing, SETUP.bat offers to install them with winget.
- **Visual Studio 2022** (Community or the free **Build Tools**) with *Desktop development with C++*,
  and **LLVM** (clang-cl) 17 or newer. If they are missing, setup offers to install them with winget.

## Build it (one time)

1. Download this repo (green **Code** button → *Download ZIP*, or `git clone`) and unpack it
   somewhere with enough space, ideally a path without unusual characters.
2. **Drag your disc image onto `SETUP.bat`**, or double-click `SETUP.bat` and it asks for it.
3. Answer its questions: the disc key if the image is encrypted, and where `rpcs3.exe` is.

That's it. SETUP.bat then:

| step | what happens | time* |
|---|---|---|
| 1 | extracts all game files from the image (and decrypts them) into `game/` | 2–5 min |
| 2 | decrypts `EBOOT.BIN` → `EBOOT.elf` with RPCS3 and checks it is the tested version | < 1 min |
| 3 | downloads ps3recomp at the tested commit and applies this port's runtime patch | < 1 min |
| 4 | recompiles the game: ~94,000 PPU functions + 12 SPU programs → C/C++ in `port/` | 2–4 min |
| 5 | applies this port's edits to the recompiled code (`patches/lifted-code.patch`) | seconds |
| 6 | compiles everything with clang-cl into `port/build_opt/DemonsSoulsRecomp.exe` | 10–30 min |

\* on a fast 16-core PC; the first compile is the long part. If anything fails, fix what it says
and run SETUP.bat again: finished steps are skipped.

## Play

Double-click **`PLAY.bat`**. The logos and first load take about a minute.

| launcher | what it does |
|---|---|
| `PLAY.bat` | 60 fps (50 fps automatically on a ~100 Hz monitor, every frame shown exactly 2 refreshes) |
| `PLAY_30FPS.bat` | the original 30 fps |
| `PLAY_50FPS.bat` | 50 fps locked to a 100 Hz screen |
| `PLAY_UNLIMITED.bat` | uncapped (up to 240 fps), no vsync, game speed stays correct |
| `PLAY_RECORD.bat` | plays normally and records frame timing; press **F8** at a stutter (see `tools/perf_report.py`) |
| `PLAY_REMASTER.bat` | runs with the *PC Remaster* mod installed (see below) |

**Controls.** An Xbox (XInput) controller works when plugged in (A = Cross, B = Circle, X = Square,
Y = Triangle, LB/RB = L1/R1, LT/RT = L2/R2, Back = Select). A DualShock/DualSense needs Steam Input or
DS4Windows. Keyboard + mouse:

| | |
|---|---|
| WASD | move |
| mouse (or IJKL) | camera |
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
| F1 | capture / release the mouse |
| F9 | god mode on/off (no death, HP/MP/stamina stay full) |

At *Create Profile* a text box opens for the character name. Saves go to `gamedata/`. Each run
writes logs to `logs/` (they grow by ~600 MB an hour; the previous run is kept as `*_prev.txt`).

## Optional: PC Remaster mod

The *Demon's Souls PC Remaster* mod by fromsoftserve (Nexus Mods, Demon's Souls mod 106)
(made for RPCS3) works with this port. Download the mod's zip yourself, then:

```bat
.venv\Scripts\python tools\install_remaster.py "path\to\the mod.zip" --apply
```

That builds `game_remaster/` as a hard-linked copy of `game/` (no extra disk space) with the mod's
files swapped in. Your normal `game/` is not changed. Play with `PLAY_REMASTER.bat`.

## Repo layout

```
SETUP.bat / BUILD.bat        one-time setup / rebuild after code changes
PLAY*.bat                    launchers (environment switches documented inside PLAY.bat)
setup/setup.py, build.py     the setup pipeline and the toolchain finder + build
project/                     CMake project: CMakeLists.txt, main.cpp, stubs.cpp
patches/ps3recomp-local.patch   this port's changes to the ps3recomp runtime/renderer (applied to
                                ps3recomp @ 4e8f3ca, v0.18.0)
patches/lifted-code.patch    this port's edits to the recompiled game code (frame pacing, 60 fps
                             step, god mode, test hooks)
tools/                       disc extraction, UDF names, SPURS job lifting, perf report, mod installer
docs/NOTES.md                development log: every fix, why, and how it was measured
```

Everything SETUP.bat produces (`game/`, `port/`, `deps/`, `.venv/`, saves, logs) is in `.gitignore`.
**Never commit or share those**: they are the game.

## Troubleshooting

- **"RPCS3 did not write EBOOT.elf"**: close any open RPCS3 window and run SETUP.bat again, or decrypt
  by hand: RPCS3 → *Utilities* → *Decrypt PS3 Binaries* → `game\PS3_GAME\USRDIR\EBOOT.BIN`.
  If RPCS3 itself complains, install the PS3 firmware in RPCS3 first (*File → Install Firmware*).
- **"EBOOT.BIN is not the tested one"**: only the USA disc (BLUS-30443, version as on the disc) is
  supported. Other regions or updated EBOOTs need different patches.
- **Build tools not found**: install Visual Studio 2022 Build Tools with *Desktop development with C++*
  and LLVM (`winget install LLVM.LLVM`), or set `LLVM_DIR` to an LLVM folder, then run BUILD.bat.
- **The game window stays black / closes**: look at the end of `logs\last_run_err.txt`.
- **"needs AVX2"** message box: your CPU is too old for the SPU code as built.

## Credits and license

- [ps3recomp](https://github.com/sp00nznet/ps3recomp) by Ned Heller / sp00nznet (MIT): the recompiler
  and runtime this port is built on.
- [RPCS3](https://rpcs3.net): used to decrypt the EBOOT, and as the reference for how the PS3 behaves.
- The *PC Remaster* mod is by fromsoftserve.

This repo's own code and patches are under the MIT license (see [LICENSE](LICENSE)). Demon's Souls is
© Sony Interactive Entertainment / FromSoftware. This project is not affiliated with or endorsed by
them, and contains none of their files. Buy the game and dump your own disc.
