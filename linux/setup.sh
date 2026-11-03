#!/bin/sh
# Demon's Souls (BLUS-30443) PC port -- setup on Linux / Steam Deck from a git checkout or ZIP.
# Same six steps as SETUP.bat (docs/LINUX.md): your disc image -> extracted game files -> EBOOT
# decrypted by RPCS3 -> recompiled code -> DemonsSoulsRecomp.exe, cross-compiled with clang-cl and
# a Microsoft CRT/SDK that xwin fetches to this PC. linux/play.sh then runs it through Proton.
# The AppImage (linux/appimage) runs this same code with its own Python, LLVM, xwin and git.
#   linux/setup.sh [image.iso | image.zip | dumped disc folder] [--key HEX | --key file.dkey]
#                  [--rpcs3 path/to/rpcs3.AppImage] [--jobs N]
# Safe to run again: finished steps are skipped.
set -eu
D=$(cd "$(dirname "$0")/.." && pwd)
cd "$D"

PY=${PYTHON:-python3}
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "Python 3.10 or newer is needed (python3). Or use the AppImage, which brings its own."
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git is needed (Debian/Ubuntu: sudo apt install git). Or use the AppImage, which brings its own."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment in .venv ..."
  "$PY" -m venv .venv || { echo "python3 -m venv failed (Debian/Ubuntu: sudo apt install python3-venv)"; exit 1; }
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r setup/requirements.txt
export DS_SETUP_NAME="${DS_SETUP_NAME:-linux/setup.sh}"
export DS_PLAY_HINT="${DS_PLAY_HINT:-Run linux/play.sh to play.}"
exec .venv/bin/python setup/setup.py "$@"
