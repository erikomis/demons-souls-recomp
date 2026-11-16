#!/bin/bash
# Packs port/build_android/libmain.so (android/build_so.sh) and the arm64 SDL2 into a debug-signed APK:
# android/app/build/outputs/apk/debug/app-debug.apk. The APK holds code lifted from your own disc: it stays
# on your machine and your devices (never publish it).
#
#   android/build_apk.sh [install]     install: also adb install -r it on the connected device
set -eo pipefail
here=$(cd "$(dirname "$0")" && pwd)
DES_ROOT=$(cd "$here/.." && pwd)
export ANDROID_HOME=${ANDROID_HOME:-$HOME/Android/sdk}
PREFIX=${DES_ANDROID_PREFIX:-$HOME/Android/prefix-arm64}
DES_BUILD=${DES_BUILD:-$DES_ROOT/port/build_android}
fail() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$DES_BUILD/libmain.so" ] || fail "no $DES_BUILD/libmain.so: run android/build_so.sh first"
J=$here/app/jniLibs/arm64-v8a
mkdir -p "$J"
# The NDK toolchain builds with -g: libmain.so is ~2.1 GB with its debug info, ~330 MB without. The APK gets
# it without (the symbol table stays, so a tombstone still names the functions); the full one stays in
# $DES_BUILD for ndk-stack / llvm-symbolizer.
NDK=${ANDROID_NDK:-$(ls -d "$ANDROID_HOME"/ndk/* 2>/dev/null | sort -V | tail -n 1)}
STRIP=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip
[ -x "$STRIP" ] || fail "no llvm-strip in the NDK ($NDK)"
if [ ! -f "$J/libmain.so" ] || [ "$DES_BUILD/libmain.so" -nt "$J/libmain.so" ]; then
  "$STRIP" --strip-debug -o "$J/libmain.so" "$DES_BUILD/libmain.so"
fi
cp -f "$PREFIX/lib/libSDL2.so" "$J/"
cd "$here"
APK=$here/app/build/outputs/apk/debug/app-debug.apk
# Gradle updates an APK in place, and a replaced 330 MB library leaves its old copy as dead space: start anew.
rm -f "$APK"
./gradlew --no-daemon -q assembleDebug
BT=$(ls -d "$ANDROID_HOME"/build-tools/* | sort -V | tail -n 1)
"$BT/zipalign" -c -P 16 4 "$APK" || fail "the APK's native libraries are not 16 KB aligned"
echo "built: $APK ($(du -h "$APK" | cut -f1)), native libraries 16 KB aligned"
if [ "${1:-}" = install ]; then
  "$ANDROID_HOME/platform-tools/adb" install -r "$APK"
fi
