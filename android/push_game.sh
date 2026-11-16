#!/bin/bash
# Copies your game files (game/, from linux/native/build.sh game decrypt) to the phone over adb, into the
# app's own external folder: /sdcard/Android/data/io.github.timboat.desrecomp/files/game (~8 GB; no
# storage permission needed). Run it with the APK installed (android/build_apk.sh install). Files already
# there and current are skipped (adb push --sync), so it can be run again after an interruption.
#
#   android/push_game.sh [game folder]       default: game/ beside this checkout's android/
#
# Also pushes linux/native/input.toml (the controller map) and, if present, android/des.ini (your
# KEY=VALUE overrides of android_main.cpp's settings; not in git).
set -eo pipefail
here=$(cd "$(dirname "$0")" && pwd)
DES_ROOT=$(cd "$here/.." && pwd)
ADB=${ADB:-${ANDROID_HOME:-$HOME/Android/sdk}/platform-tools/adb}
PKG=io.github.timboat.desrecomp
DST=/sdcard/Android/data/$PKG/files
SRC=$(cd "${1:-$DES_ROOT/game}" && pwd)
fail() { echo "ERROR: $*" >&2; exit 1; }
[ -f "$SRC/PS3_GAME/USRDIR/EBOOT.elf" ] || fail "no $SRC/PS3_GAME/USRDIR/EBOOT.elf (linux/native/build.sh game decrypt)"
"$ADB" get-state >/dev/null 2>&1 || fail "no device (adb devices; accept the USB debugging prompt on the phone)"
"$ADB" shell mkdir -p "$DST/game"

echo "copying $SRC -> $DST/game (about 8 GB: 5-15 minutes over USB 3)"
# --sync: only files that are newer here than on the phone, so a second run continues an interrupted one.
"$ADB" push --sync "$SRC/." "$DST/game/"
"$ADB" push -q "$DES_ROOT/linux/native/input.toml" "$DST/input.toml"
[ -f "$here/des.ini" ] && "$ADB" push -q "$here/des.ini" "$DST/des.ini"
# adb creates what it pushes as the shell user, folders drwxrws--- (group ext_data_rw): the app's own uid is
# neither, and reads its folder straight from the disk (not through the FUSE layer), so it could not open
# them (Permission denied on EBOOT.elf; Pixel 10, Android 17). Open them to everyone: only the app and adb
# can reach this folder anyway.
"$ADB" shell chmod -R a+rwX "$DST/game" "$DST/input.toml"
[ -f "$here/des.ini" ] && "$ADB" shell chmod a+rw "$DST/des.ini"
echo "done: $DST"
