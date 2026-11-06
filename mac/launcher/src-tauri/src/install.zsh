#!/bin/zsh
# "Install the game": from the player's own disc image to a build Play can run. The launcher runs
# this (src-tauri/src/lib.rs, start_install) in its own process group and reads the "==> <step>"
# lines for its progress bar. The work is the repository's own mac/install.sh; this only gets the
# sources first when there is no checkout yet. Pressing Install again after a failure or a Cancel
# continues where it stopped (mac/install.sh skips what is done).
#
# Inputs, all from the environment:
#   DES_SRC             the port folder: a checkout of the sources (cloned here when missing)
#   DES_SOURCES_URL     the repository to clone, and its branch (lib.rs SOURCES_URL / SOURCES_BRANCH)
#   DES_SOURCES_BRANCH
#   DES_ISO, DES_KEY    the disc image (or dumped folder) and its disc key, for mac/install.sh
#   JOBS                parallel compile jobs
set -e
: ${DES_SRC:?} ${DES_SOURCES_URL:?} ${DES_SOURCES_BRANCH:?}
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
say() { print -r -- "==> $*"; }
fail() { print -r -- "ERROR: $*"; exit 1; }

say "sources (the port's sources)"
if [ ! -f "$DES_SRC/mac/install.sh" ]; then
    command -v git >/dev/null || fail "git is missing (Apple's command-line tools have it)"
    if [ -d "$DES_SRC/.git" ]; then
        # a checkout from before the macOS install existed
        git -C "$DES_SRC" pull --ff-only || fail "could not update the sources in $DES_SRC (git pull)"
    elif [ -e "$DES_SRC" ] && [ -n "$(ls -A "$DES_SRC" 2>/dev/null)" ]; then
        fail "$DES_SRC is there but is not a checkout of the sources: move it away and press Install again"
    else
        mkdir -p "${DES_SRC:h}"
        rm -rf "$DES_SRC.partial"
        print -r -- "  git clone --branch $DES_SOURCES_BRANCH $DES_SOURCES_URL"
        git clone --branch "$DES_SOURCES_BRANCH" "$DES_SOURCES_URL" "$DES_SRC.partial" ||
            fail "could not download the sources from $DES_SOURCES_URL (no internet?)"
        rm -rf "$DES_SRC"
        mv "$DES_SRC.partial" "$DES_SRC"
    fi
    [ -f "$DES_SRC/mac/install.sh" ] ||
        fail "the sources ($DES_SOURCES_URL, branch $DES_SOURCES_BRANCH) have no mac/install.sh yet"
fi
print -r -- "  $DES_SRC ($(git -C "$DES_SRC" rev-parse --short HEAD 2>/dev/null || echo 'not a git checkout'))"
exec /bin/zsh "$DES_SRC/mac/install.sh"
