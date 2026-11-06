# Shared settings for mac/install.sh and mac/rebuild.sh. Sourced, not run (zsh).
# Every value can be overridden from the environment.
#
#   DES_ROOT    this repository (default: the parent of mac/)
#   DES_VENV    the Python environment the setup's tools run in (default: $DES_ROOT/.venv)
#   DES_BUILD   the native build (default: $DES_ROOT/port/build_mac):
#               DemonsSoulsRecomp (the game) and DemonsSoulsRecomp_window (its window)
#   DES_KEYS    the key file mac/rebuild.sh decrypt writes with tools/fetch_keys.py and hands to
#               tools/decrypt_self.py (default: ~/Library/Application Support/demons-souls-recomp/
#               keys/self_keys.txt, outside the repository, mode 600)
#   DES_ISO     your disc image (.iso, or a Redump .zip), or a dumped disc folder holding PS3_GAME/;
#               needed only until game/ is extracted
#   DES_KEY     the disc key of an encrypted (Redump) image: 32 hex digits or a .dkey file. Without it
#               a .dkey next to the image is used, as SETUP.bat does
#   JOBS        parallel compile jobs (ninja's -j; default: ninja's own)
#   PY          the Python 3.10+ the venv is made from (default: the newest python3.1x on PATH)

DES_ROOT=${DES_ROOT:-${here:h}}
DES_VENV=${DES_VENV:-$DES_ROOT/.venv}
DES_BUILD=${DES_BUILD:-$DES_ROOT/port/build_mac}
DES_KEYS=${DES_KEYS:-$HOME/Library/Application Support/demons-souls-recomp/keys/self_keys.txt}
DES_GAME_DIR=$DES_ROOT/game
DES_USRDIR=$DES_GAME_DIR/PS3_GAME/USRDIR
DES_ELF=$DES_USRDIR/EBOOT.elf
DES_EXE=$DES_BUILD/DemonsSoulsRecomp
DES_WIN=$DES_BUILD/DemonsSoulsRecomp_window
VPY=$DES_VENV/bin/python

# A GUI app (the launcher) starts with a bare PATH: Homebrew's folders go first.
for p in /usr/local/bin /opt/homebrew/bin; do
    [ -d "$p" ] && path=("$p" ${path:#$p})
done
export PATH

if [ -z "$PY" ]; then
    for c in python3.14 python3.13 python3.12 python3.11 python3.10; do
        command -v $c >/dev/null && { PY=$(command -v $c); break; }
    done
fi

# Homebrew's prefix (for SDL2 and the FFmpeg the movies use at run time).
DES_BREW=${HOMEBREW_PREFIX:-$(brew --prefix 2>/dev/null)}
DES_BREW=${DES_BREW:-/opt/homebrew}
