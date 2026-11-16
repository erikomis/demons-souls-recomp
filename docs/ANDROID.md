# Android (arm64) — experimental, not playable yet

The game built as an arm64-v8a Android shared library (`libmain.so`) and run by SDL2's `SDLActivity`,
drawn by the same Vulkan backend as the native Linux build ([LINUX_NATIVE.md](LINUX_NATIVE.md)). Built
on a Linux PC with the NDK; the APK is made from your own disc and stays on your machines, debug-signed.
**Never publish the APK**: it contains the game's lifted code.

**Status (2026-11-16):** builds and packs (M0). Not yet run on a device.

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

## Known open points (not tried on a device yet)

- The aarch64 Linux signal / context code in `win32_compat.c` has never run; on Android its handlers sit
  behind ART's libsigchain, and the thread-park signal (`SIGRTMIN + 4`) may clash with one ART uses.
- SDL's window and event pump run on the vblank ticker thread, not SDL_main's.
- The window's surface goes away when the app goes to the background (SDL_APP_WILLENTERBACKGROUND /
  DIDENTERFOREGROUND are not handled yet); the swapchain's `preTransform = currentTransform` may show a
  rotated picture; no letterbox.
