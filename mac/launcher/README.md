# Demon's Souls Launcher (macOS)

A desktop app (Tauri 2) for the native macOS build of this port (Apple silicon, Metal): it takes the
player from their own Demon's Souls disc image (USA, BLUS-30443) to "Play" without a terminal,
keeps the game's settings, manages the saves, edits the controls, shows the log and the trophies,
and rebuilds the port. It ships no game code or files: the cover art on Home is read from the
player's own extracted game files (`game/PS3_GAME/ICON0.PNG`, `PIC1.PNG`), and the app icon is a
plain flame drawn by `scripts/make_icon.py`.

It is the Resistance 2 port's launcher adapted to this game, by way of the PES 2013 one (its in-app
install flow, trophy list and picture controls). The UI is in Brazilian Portuguese by default, with
English in the sidebar. The Windows build has its own launcher (`project/launcher/`); this one is
macOS only.

Everything it runs is the repository's own scripts (see `docs/MACOS.md`):

| | |
| --- | --- |
| `mac/install.sh` | the whole install, resumable: checks the disk, then every `mac/rebuild.sh` step |
| `mac/rebuild.sh [step ...]` | `deps venv game decrypt toolkit lift build`, each announced as `==> <step>` |
| `mac/setup_steps.py` | the steps that reuse `setup/setup.py` (game files, ELF check, toolkit, lift) |
| `mac/env.sh` | the folders and tools the two shell scripts share |
| `mac/play.sh` | the one way the game runs; Play sets its variables and calls it |
| `tools/decrypt_self.py`, `tools/fetch_keys.py` | EBOOT.BIN -> EBOOT.elf without RPCS3 (from resistance-recomp) |

## Building

Needs Node 20+, Rust (stable) and the Xcode Command Line Tools.

```sh
cd mac/launcher
npm ci
npx tsc --noEmit                 # the frontend's types
(cd src-tauri && cargo test)     # the backend's tests
npm run tauri build              # .app and .dmg in src-tauri/target/release/bundle/
npm run release                  # the same, then scripts/check_bundle.py on both
npm run tauri dev                # the app with the frontend hot-reloaded
```

`scripts/check_bundle.py <.app|.dmg>` fails when a bundle carries anything from the game (names, PS3
file headers, PowerPC/SPU ELFs, files over 16 MB). The builds are unsigned: right-click the app and
choose Open the first time (Gatekeeper). `cargo test -- --ignored real_build --nocapture` lists which
of the launcher's variables the real build in `port/build_mac` contains.

## Install the game

Home shows the **Install the game** card while nothing is built. The player chooses the disc image
(a decrypted `.iso`, a Redump `.iso` or `.zip`, or a dumped disc folder holding `PS3_GAME/`) and, for
an encrypted Redump image, its disc key (32 hex digits, or the `.dkey`; one next to the image is
found on its own). Then:

1. **Prerequisites** (before anything runs): Apple's Command Line Tools (their installer, waited for)
   and Homebrew's `cmake ninja sdl2 glslang spirv-cross ffmpeg python@3.12`, installed only after the
   player says yes to the `brew install` line shown. The free space (14 GB) is checked.
2. **sources** (`src-tauri/src/install.zsh`): when the launcher found no checkout of the port, it
   clones `SOURCES_URL` at `SOURCES_BRANCH` (lib.rs: `github.com/erikomis/demons-souls-recomp`,
   branch `macos-native`, where the Mac support lives; `DES_SOURCES_URL` / `DES_SOURCES_BRANCH`
   override them) into `~/Library/Application Support/demons-souls-recomp/src`. A checkout the
   launcher already uses (the folder it was built from, for example) is installed into in place.
3. Then the repository's `mac/install.sh`, whose steps the progress bar follows: **deps**, **venv**
   (`.venv` with `setup/requirements.txt` and `pycryptodome`), **game** (`tools/iso_extract.py --all`,
   `tools/udf_rename.py`, `game/.extracted`), **decrypt** (`tools/fetch_keys.py` downloads RPCS3's
   public key table once into `<data>/keys/self_keys.txt`, mode 600, checked by its SHA-256;
   `tools/decrypt_self.py` writes `EBOOT.elf`, checked against `setup.py`'s `EBOOT_ELF_SHA256`),
   **toolkit** (`setup.step_ps3recomp()`), **lift** (`setup.step_lift()`) and **build** (the cmake +
   ninja line of `docs/MACOS.md`, with `-DPS3RECOMP_FFMPEG_RUNTIME=ON`).

The install runs in its own process group under `nice`; **Cancel** and quitting the app stop it, and
pressing Install again continues where it stopped (every step skips what is done; the build is
incremental). Its output is also in `<data>/install.log`. On a failure the card gives a reason by
stage (no internet, a full disk, a missing disc key, an EBOOT that is not the tested one, the
compile...) with **Copy log** and **Show the log file**.

**Why a clone and not sources in the bundle:** the repository is public, `setup/patch_sync.py`
re-applies the patches from the checkout's git history after an update, and the Updates tab can then
`git pull` it. A staged copy would need its own update path. The catch: until the Mac scripts are on
that branch, the app's install stops at "the sources have no mac/install.sh yet"; a developer's
checkout works today.

## Pages

- **Home / Início**: the art from the player's game files, "BLUS30443 · version 01.00", the build
  date and the frame rate, **Play** / Stop (**Capture this frame** in debug mode), a bar for whatever
  blocks Play, the install card, a bar when Updates has news. Cards: quick settings (frame rate,
  window size, fps counter, keep the Mac awake), the last save, the status (state, game files,
  movies, port folder) with the log, Updates, **Play shortcut on the Desktop** and **Add to Steam**.
- **Graphics / Gráficos**: window size (`DES_SIZE`, the window host's `--size`; the picture stays
  1280×720 at 16:9 inside it), the Dock / Finder icon from the player's ICON0.PNG; image quality: a
  profile, anti-aliasing (`PS3_AA` off / fxaa / smaa), sharpening (`PS3_SHARPEN`), anisotropic
  filtering (`PS3_ANISO`, off by default), a gamma override (`PS3_DISPLAY_GAMMA`); filters: vibrance
  (`PS3_VIBRANCE`) and contrast (`PS3_CONTRAST`).
- **Performance / Desempenho**: the frame rate (`DES_FPS`: 60, mac/play.sh's default, or the
  console's 30), the fps counter (`PS3RECOMP_METAL_FPS=1`), keep the Mac awake (`caffeinate -i`), and
  the translated shaders on disk (`PS3RECOMP_MSL_CACHE`, mac/play.sh's `cache/msl`: size and
  **Clear**).
- **Game / Jogo**: the game files (`game/`, the image they came from), the character name
  (`DES_NAME`: the Mac build has no on-screen keyboard text box), skip the intro (`DES_SKIP_INTRO=1`,
  marked untested on the Mac), the console language (`PS3_LANG`), the movies (`DES_MOVIES=0` when off;
  the FFmpeg found, and `PS3RECOMP_FFMPEG_AVCODEC` / `_AVUTIL` overrides), mute (`AUDIO_MUTE=1`), the
  trophies (names and icons from `game/PS3_GAME/TROPDIR/NPWR00881_00/TROPHY.TRP`, unlocks from
  `gamedata/trophies/`), the saves manager and its backups (below).
- **Controls / Controles**: the bindings table (keyboard, mouse buttons, controller) with what each
  PS3 control does in Demon's Souls (R1 attack, R2 strong attack, L1 block, L2 parry, ○ roll, ✕
  interact, △ two-hand, □ use item, R3 lock on, the D-pad switches equipment, START the menu). It
  starts from the port's `mac/input.toml`; the first change copies it, with the change, to
  `<data>/input.toml` (the toolkit's `libs/input/pad_input_map.h` format; `[mouse]` and any other
  section kept), which Play then passes as `PS3_INPUT_MAP`. **Restore defaults** moves that copy to
  `input.toml.bak`, so mac/play.sh uses `mac/input.toml` again. The controller test, what drives the
  game (`PS3_INPUT_MODE`), the mouse (`PS3_MOUSE`, `_SENS`, `_INVERT_Y`, `_INVERT_X`, `_DEADZONE`,
  `_CAPTURE`; all passed when the file has a `[mouse]` section, so the launcher's settings win) and
  vibration (`PS3_RUMBLE`, `PS3_RUMBLE_STRENGTH`, with a test pulse).
- **Advanced / Avançado**: **Install / rebuild** (what the Mac has, the port folder, `mac/rebuild.sh
  deps venv` + the chosen steps of `decrypt toolkit lift build`, JOBS for ninja, progress from the
  `==> step` and ninja's `[k/n]` lines), **Updates** (the checkout's branch and commit, `git fetch`,
  commits behind, **Get the new sources** = `git pull --ff-only`, refused with local changes; "the
  sources changed after the build"), **Game log** (the end of `logs/last_run_err.txt`, followed every
  2 s, filter, warnings and errors only; the previous session is `last_run_err_prev.txt`), **Debug
  mode** (below), **Environment** (extra variables, passed last; the controller log `PS3_PAD_LOG=1`,
  the stall report `PS3_STALL_SAMPLE=<ms>`, the verbose log `DES_LOG=1`; the equivalent command line;
  Restore defaults).

Settings are saved the moment they change (`~/Library/Application Support/demons-souls-recomp/
launcher.json`) and apply on the next Play. A control whose variable the build does not contain (the
executable is searched for the name, `FEATURE_MARKERS` in lib.rs) is greyed out and not passed.

## What Play does

```sh
cd <port> && [caffeinate -i] /bin/sh mac/play.sh   # play.sh's own lines in <data>/play.log
```

with only the settings that differ from mac/play.sh's defaults in the environment (with the defaults,
nothing at all: a test checks this), then the extra variables. mac/play.sh sets everything else
(`PS3_HDD0_ROOT`, `PS3_INPUT_MAP` = `mac/input.toml` unless the launcher passes its copy,
`PS3RECOMP_MSL_CACHE`, the FFmpeg it finds, the 60/30 fps switches) and starts
`port/build_mac/DemonsSoulsRecomp_window --title … --size … -- port/build_mac/DemonsSoulsRecomp
game/PS3_GAME/USRDIR/EBOOT.elf`, writing `logs/last_run_out.txt` and `logs/last_run_err.txt`.

- **Stop** sends SIGTERM to that process group (play.sh, the window host and the game), and SIGKILL
  8 s later if it is still there. Never by name.
- Play is refused while another `DemonsSoulsRecomp` runs (a terminal, another session) and while an
  install or a rebuild runs.
- `--play` on the command line starts the game once the window is up (the Desktop shortcut and the
  Steam entry use it; Steam's adds `--exit-with-game`). `--view <page>[:<tab>]` opens a page.

## Saves

`src-tauri/src/saves.rs`. The game's characters are cellSaveData folders `BLUS30443DEMONSS<n>`
under `<port>/gamedata/dev_hdd0/home/00000001/savedata` (`PS3_GAMEDATA_ROOT` in the extra variables
moves it, as it moves the game's), listed next to RPCS3's (`~/Library/Application Support/rpcs3/
dev_hdd0/home/<user>/savedata`, read-only: a save can be copied from RPCS3 into the port, with the
PARAM.SFO / PARAM.PFD metadata converted, never the other way). Back up one or all, restore, delete,
export to `.zip`, import a `.zip`. Backups go to `<data>/save-backups/`; one is made before every Play
(the newest 10 kept; 0 turns it off) and before every restore, copy, import and delete. Everything
refuses while the game runs.

## Debug mode

`src-tauri/src/report.rs`. **Play in debug mode** starts the game as Play does, with its log in a new
folder `<data>/reports/<UTC time>/` (`DES_LOG_DIR`, which mac/play.sh honours) and
`PS3RECOMP_METAL_FRAME_DUMP` (the whole frame every 120 presents), `LV2_ERRDBG=1`, `PS3_VERBOSE=1` and
the fps counter. **Capture this frame** keeps the latest whole frame; the per-pass capture on request
needs `RSX_ENGINE_PASS_DUMP_TRIGGER`, which this runtime does not have, so it stays off. `events.tsv`
indexes the session, `system.txt` has the Mac, the GPU, the game files, the build and the command;
after a crash macOS's crash report is copied as `crash.ips`. **Analyse** groups the log's error and
warning lines; **Create .zip** packs the folder (frames as PNG, the home folder's path as `~`).

## Removed from the other launchers, and why

- **Disc mounting** (hdiutil, mount on Play, eject): the port reads the files extracted into `game/`,
  so the image is only needed once, by the install.
- **Window mode, screen, vsync, MetalFX, internal resolution, aspect, tone curve, clarity, LUTs,
  vignette, grain, texture packs and dumps, volume and output device**: the Mac runtime has none of
  them (the port's D3D12 renderer, where resolution scale, texture packs and frame pacing live, is
  Windows only). **Frame rates other than 60 and 30**: they need that renderer's present pacing.
- **The draw-engine, vertex-cache, frame-clock, vblank, QoS and shader-async switches** of the
  Resistance 2 and PES launchers: that toolkit's, not this one's.
- **The Option File profiles, the Data Pack and the savedata keys** (PES), **the play folder and its
  first-boot HDD install** (Resistance 2): this game has no counterpart.
- **The PC Remaster mod** (`DES_GAME=game_remaster`): its shaders are the D3D12 renderer's. It can
  still be passed as an extra variable.
- **A launcher self-update**: there is no release page for it yet (`update.rs` `REPO` is `None`).

## Not tested

The install from an empty data folder end to end (the clone needs the Mac scripts on the
`macos-native` branch), skip the intro on the Mac, Add to Steam with Steam installed, and keyboard
and mouse in the game beyond the menus.
