# Android (arm64) — experimental, not playable yet

The game built as an arm64-v8a Android shared library (`libmain.so`) and run by SDL2's `SDLActivity`,
drawn by the same Vulkan backend as the native Linux build ([LINUX_NATIVE.md](LINUX_NATIVE.md)). Built
on a Linux PC with the NDK; the APK is made from your own disc and stays on your machines, debug-signed.
**Never publish the APK**: it contains the game's lifted code.

**Status (2026-11-16):** builds and packs (M0); runs in game on a Pixel 10 Pro XL at 30 fps (M1/M2 and past).

## First device run: Pixel 10 Pro XL

Tensor G5, Android 17 (API 37), 16 GB, 4 KB pages. PowerVR D-Series DXT-48-1536 MC1, Vulkan 1.4.317,
driver "PowerVR D-Series Vulkan Driver" 25.3@6908880 (conformance 1.4.5.0).

- Boots to the title screen ("PRESS START BUTTON", textures and fonts right) at a steady 30.0 fps, game
  time 1.000 s per real second; sound at its rate, no underruns. No driver crash, no signal trouble.
- `[vm] guest memory at 0x7a20000000` (the 3.5 GB MAP_NORESERVE reservation works under bionic).
- Peak memory at the title screen: VmHWM 604-609 MB. (Native Linux x86-64, same settings, RTX 3070: about
  1,970 MB at the title and 2,280 MB at most in game -- a save loaded, warps to Boletaria, Latria and the
  Valley -- figures that include what the NVIDIA driver maps into the process.)
- `textureCompressionBC` is false, BC1/2/3 are sampleable per format: DXT textures on. No depthBounds.
- In game (a save pushed from the PC, loaded through the menus; the Tutorial, Boletaria's tunnel, standing):
  29.2-30.0 fps over 2 minutes, 240-290 draws a frame, game time 0.97-1.00 s per real second; VmHWM 712 MB
  (733 MB in an earlier run). Every hitch of 100 ms or more was a one-draw loading-screen frame. Thermal
  status 0, battery 27 C, no fan.
- Background and back (home key, 20 s, back): the same process carries on, the surface and swapchain made
  again, sound back at its normal queue (~31 ms), 30 fps.
- Keys work (SDL's keyboard -> the pad, `input.toml`): `adb shell input keyevent --longpress KEYCODE_ENTER`
  is START (a plain keyevent is down and up within one event pump: the game never sees it), KEYCODE_E
  cross, KEYCODE_DPAD_* the D-pad.
- The game folder pushed by adb: 7.9 GB in 2 min 47 s (USB, ~49 MB/s).
- Found and fixed on the device: files adb pushes are the shell user's (folders drwxrws---), which the app
  cannot open (push_game.sh now opens them up); SDL asked for any orientation (the window is resizable;
  now landscape only, SDL_HINT_ORIENTATIONS); the picture came out turned 90 degrees with preTransform =
  currentTransform (now IDENTITY on Android, the compositor rotates; VK_SUBOPTIMAL_KHR at present is
  expected then and no longer rebuilds the swapchain every frame); the app's own folders were its uid's
  alone, so adb could neither push a save in nor read the logs (android_main.cpp now opens them up).
- Added after the first run: a letterbox (on by default on Android, `PS3RECOMP_VK_LETTERBOX=0` stretches;
  `=1` turns it on elsewhere), and background / foreground handling: an SDL event watch releases the
  swapchain and VkSurface on SDL_APP_WILLENTERBACKGROUND and makes them again on DIDENTERFOREGROUND, and
  cellAudio drops what it mixes meanwhile and clears SDL's queue on the way back.

## Build

Needs: a checkout that went through `linux/native/build.sh venv game decrypt toolkit lift`, the Android
SDK in `~/Android/sdk` (cmdline-tools, `ndk;28.2.13676358`, `platform-tools`, `build-tools;35.0.0`,
`platforms;android-35`), a JDK 17, and:

```sh
android/build_deps.sh          # SDL2 2.30.12 + glslang 15.4.0 for arm64 -> ~/Android/prefix-arm64
android/build_so.sh            # the game -> port/build_android/libmain.so
android/build_apk.sh install   # the APK (debug-signed), adb install on the connected phone
android/push_game.sh           # game/ -> /sdcard/Android/data/io.github.timboat.desrecomp/files/game
```

M0, measured on a Ryzen 7 5800X (16 threads, 32 GB), NDK r28c, `CMAKE_BUILD_TYPE=Fast`, no LTO:

| | |
|---|---|
| Full compile + link | 10 min 41 s wall (8,294 s CPU); largest compiler process 2.0 GB |
| Link alone (ld.lld) | 3.2 s, 6.6 GB peak RSS |
| `libmain.so` | 2.12 GB with the NDK's default `-g`; 330 MB with the debug info stripped (`.text` 302 MB) |
| APK | 323 MB; both libraries stored uncompressed, 16 KB aligned (`zipalign -c -P 16`) |

`libmain.so` exports one symbol, `SDL_main`; its LOAD segments are 16 KB aligned (`-z max-page-size=16384`).

## Run

Saves: `files/gamedata/dev_hdd0/home/00000001/savedata/BLUS30443DEMONSS005`. To bring one from the PC:
`adb push <gamedata>/dev_hdd0/home/00000001/savedata/BLUS30443DEMONSS005 <files>/gamedata/dev_hdd0/home/00000001/savedata/`
with the game stopped (`adb shell am force-stop io.github.timboat.desrecomp`).

`android/android_main.cpp` does what `linux/native/play.sh` does: the environment (the drives under the
app's external files folder, the HDD1 cache wiped, the Vulkan renderer's settings), the logs in
`files/logs/last_run_out.txt` / `last_run_err.txt` (unbuffered), then the boot harness on
`files/game/PS3_GAME/USRDIR/EBOOT.elf`. Defaults: 30 fps, no movies (`PS3_NO_SAIL=1`: no FFmpeg on Android
yet), straight to the title screen (`DES_SKIP_INTRO=1`), full screen. `files/des.ini` (KEY=VALUE lines,
pushed by `push_game.sh` from `android/des.ini`) overrides any of them; `KEY=` with nothing unsets one.
Every 10 s the game log and logcat (tag `DeS`) get the process's peak and current memory (`[mem] VmHWM`).

```sh
adb logcat -s DeS
adb shell cat /sdcard/Android/data/io.github.timboat.desrecomp/files/logs/last_run_err.txt
```

## What differs from the Linux build

- `project/CMakeLists.txt`: on `ANDROID`, a shared library named `main` (what SDLActivity loads) with
  `android/android_main.cpp`; the boot harness's `main` is compiled as `ds_boot_main`; hidden visibility;
  SDL2, libandroid and liblog; `-z max-page-size=16384`. The 64-byte code alignment applies as on Linux.
- `patches/ps3recomp-local.patch` (all `__ANDROID__`-guarded):
  - `boot_main.cpp`: the main guest thread gets its own 256 MB stack (as on macOS, without the run loop):
    SDL_main runs on a Java thread with a small stack.
  - `win32_compat.c`: thread affinity through `sched_setaffinity(pthread_gettid_np())` (bionic has
    `pthread_setaffinity_np` only from API 36).
  - `cellFiber.c`: no fibers (bionic has no ucontext routines); CreateFiber fails. Demon's Souls does not
    use libfiber.
  - `rsx_vulkan_backend.c`: BC1-3 (DXT) textures when the device can sample those three formats, even if
    it reports `textureCompressionBC` false (PowerVR); a Vulkan 1.1 instance on Android, and the device's
    vendor / device id and driver name / version string in the log (the driver line on Android only).
  - The toolkit's CMake stops when glslang is missing on Android (the game would draw black).
- `timespec_get` needs API 29, the minimum here (`ANDROID_PLATFORM=29`).

## Known open points

- The aarch64 Linux signal / context code in `win32_compat.c` has never run; on Android its handlers sit
  behind ART's libsigchain, and the thread-park signal (`SIGRTMIN + 4`) may clash with one ART uses.
- SDL's window and event pump run on the vblank ticker thread, not SDL_main's.
- In the background the game waits (SDL blocks the thread that pumps its events) but its other threads
  keep their state; Android may still end the process if it needs the memory.
- The letterbox does not move the image overlay (the boss rush timer): it is placed over the whole screen.
- The compositor rotates every frame (preTransform IDENTITY); pre-rotating in the backend would save that.
- Touch has no mapping: a controller (USB / Bluetooth, through SDL) or a keyboard is needed. Controller untried.
- After SDL_main returns, the app's process stays (SDLActivity); `adb shell am force-stop` before a new run.
