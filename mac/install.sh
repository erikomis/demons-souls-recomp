#!/bin/zsh
# Install Demon's Souls (BLUS-30443) natively on macOS from your own disc image, in one go, the way the
# launcher's "Install the game" button does (mac/launcher):
#
#   DES_ISO="/path/to/Demon's Souls (USA).iso" mac/install.sh            # a decrypted image
#   DES_ISO=<Redump .iso or .zip> DES_KEY=<32 hex digits or .dkey> mac/install.sh
#
# It checks the free disk space, then runs every step of mac/rebuild.sh (deps venv game decrypt toolkit
# lift build). Run it again after a failure or a quit and it continues: each step skips what is already
# done (the venv, the extracted game, EBOOT.elf, the toolkit, the lift), and the build is incremental.
# One install at a time in this folder. Then: mac/play.sh.
set -e
setopt pipefail
here=${0:A:h}
source "$here/env.sh"

# What a full install leaves on the disk: the game files about 8 GB, port/ (lift + build) about 1.2 GB,
# deps/ and the venv about 0.3 GB; asked for with room for the build on the way.
NEED_GB=${DES_NEED_GB:-14}
if [ ! -x "$DES_EXE" ]; then
    have=$(( $(df -k "$DES_ROOT" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
    [ -f "$DES_GAME_DIR/.extracted" ] && NEED_GB=$(( NEED_GB > 8 ? NEED_GB - 8 : 2 ))
    if (( have < NEED_GB )); then
        print -r -- "ERROR: not enough free disk space: $have GB free, about $NEED_GB GB are needed. Free some space and run this again."
        exit 1
    fi
fi

mkdir -p "$DES_ROOT/logs"
lock=$DES_ROOT/logs/install.pid
if [ -f "$lock" ] && kill -0 "$(cat "$lock")" 2>/dev/null; then
    print -r -- "ERROR: another install is already running in $DES_ROOT (process $(cat "$lock")). Wait for it, or stop it, and run this again."
    exit 1
fi
print -r -- $$ >"$lock"
trap 'rm -f "$lock"' EXIT

"$here/rebuild.sh"
print -r -- "Installed. Play with mac/play.sh (or the launcher's Play)."
