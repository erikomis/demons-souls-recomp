#!/bin/bash
# Cross-builds the game as an arm64-v8a Android shared library (libmain.so) with the NDK: the same cmake
# line as linux/native/build.sh's build step, plus the NDK toolchain. Needs the game lifted first
# (linux/native/build.sh venv game decrypt toolkit lift) and SDL2 + glslang built for arm64-v8a into
# one prefix (android/build_deps.sh).
#
#   android/build_so.sh            configure + build -> port/build_android/libmain.so
#
# Environment:
#   ANDROID_NDK   the NDK (default: the newest under $ANDROID_HOME/ndk, else ~/Android/sdk/ndk)
#   DES_ANDROID_PREFIX   the SDL2 + glslang prefix (default ~/Android/prefix-arm64)
#   DES_BUILD     the build folder (default port/build_android)
#   JOBS          parallel compile jobs (ninja's -j)
set -eo pipefail
here=$(cd "$(dirname "$0")" && pwd)
DES_ROOT=$(cd "$here/.." && pwd)
SDK=${ANDROID_HOME:-$HOME/Android/sdk}
NDK=${ANDROID_NDK:-$(ls -d "$SDK"/ndk/* 2>/dev/null | sort -V | tail -n 1)}
PREFIX=${DES_ANDROID_PREFIX:-$HOME/Android/prefix-arm64}
DES_BUILD=${DES_BUILD:-$DES_ROOT/port/build_android}
fail() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$NDK/build/cmake/android.toolchain.cmake" ] || fail "no NDK at '$NDK' (ANDROID_NDK)"
[ -f "$PREFIX/lib/libSDL2.so" ] || fail "no SDL2 for arm64 in $PREFIX: run android/build_deps.sh"
[ -f "$DES_ROOT/port/.lifted" ] || fail "nothing lifted yet: linux/native/build.sh venv game decrypt toolkit lift"

# No -march, no AVX2, no LTO. -ffp-contract=off: arm64 would fuse a multiply and an add the game does
# separately (the lifted PPU code has it already; this covers the SPU code and the runtime too).
flags="-ffp-contract=off"
cmake -S "$DES_ROOT/project" -B "$DES_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Fast \
      -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
      -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=29 \
      -DCMAKE_PREFIX_PATH="$PREFIX" -DCMAKE_FIND_ROOT_PATH="$PREFIX" \
      -DCMAKE_C_FLAGS="$flags" -DCMAKE_CXX_FLAGS="$flags" \
      -DDS_AVX2=OFF -DDS_BOOT_HARNESS=ON -DPS3RECOMP_BUILD_TESTS=OFF \
      -DPS3RECOMP_FFMPEG_RUNTIME=OFF -DPS3RECOMP_RSX_VULKAN=ON \
      -DPS3RECOMP_DIR="$DES_ROOT/deps/ps3recomp" -DRECOMP_DIR="$DES_ROOT/port/recompiled" \
      -DSPU_DIR="$DES_ROOT/port/spu" ||
  fail "cmake could not configure the Android build (see the lines above)"
jobs=; [ -n "${JOBS:-}" ] && jobs="-j $JOBS"
# shellcheck disable=SC2086
ninja -C "$DES_BUILD" $jobs DemonsSoulsRecomp || fail "the build failed (see the lines above)"
[ -f "$DES_BUILD/libmain.so" ] || fail "the build ended without $DES_BUILD/libmain.so"
echo "built: $DES_BUILD/libmain.so ($(du -h "$DES_BUILD/libmain.so" | cut -f1))"
