#!/bin/bash
# Builds SDL2 2.30.12 and glslang 15.4.0 for arm64-v8a (Android API 29) into one prefix, for
# android/build_so.sh. glslang without SPIRV-Tools (ENABLE_OPT=OFF): the Vulkan backend's shaders do not
# need its optimizer (rsx_shader_spirv.cpp). Sources are downloaded once into ~/Android/src.
#
#   android/build_deps.sh
#
# Environment: ANDROID_NDK (default: the newest NDK under $ANDROID_HOME/ndk), DES_ANDROID_PREFIX (default
# ~/Android/prefix-arm64).
set -eo pipefail
SDK=${ANDROID_HOME:-$HOME/Android/sdk}
NDK=${ANDROID_NDK:-$(ls -d "$SDK"/ndk/* 2>/dev/null | sort -V | tail -n 1)}
PREFIX=${DES_ANDROID_PREFIX:-$HOME/Android/prefix-arm64}
SRC=${DES_ANDROID_SRC:-$HOME/Android/src}
SDL_V=2.30.12
GLSLANG_V=15.4.0
[ -f "$NDK/build/cmake/android.toolchain.cmake" ] || { echo "ERROR: no NDK at '$NDK' (ANDROID_NDK)" >&2; exit 1; }
mkdir -p "$SRC"
cd "$SRC"
[ -d SDL2-$SDL_V ] || curl -fsSL https://github.com/libsdl-org/SDL/releases/download/release-$SDL_V/SDL2-$SDL_V.tar.gz | tar xz
[ -d glslang-$GLSLANG_V ] || curl -fsSL https://github.com/KhronosGroup/glslang/archive/refs/tags/$GLSLANG_V.tar.gz | tar xz
X=(-G Ninja -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" -DANDROID_ABI=arm64-v8a
   -DANDROID_PLATFORM=29 -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX")
cmake -S SDL2-$SDL_V -B build-sdl "${X[@]}" -DSDL_SHARED=ON -DSDL_STATIC=OFF -DSDL_TEST=OFF
ninja -C build-sdl install
cmake -S glslang-$GLSLANG_V -B build-glslang "${X[@]}" -DENABLE_OPT=OFF -DGLSLANG_TESTS=OFF \
      -DENABLE_GLSLANG_BINARIES=OFF -DBUILD_SHARED_LIBS=OFF -DCMAKE_POSITION_INDEPENDENT_CODE=ON
ninja -C build-glslang install
echo "SDL2 $SDL_V + glslang $GLSLANG_V for arm64-v8a in $PREFIX"
# The Java side of SDL (org.libsdl.app) in android/app/src/main/java is SDL2-$SDL_V/android-project's, unchanged.
