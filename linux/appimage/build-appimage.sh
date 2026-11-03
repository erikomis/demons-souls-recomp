#!/bin/bash
# Builds DemonsSoulsRecomp-Setup-x86_64.AppImage, the Linux / Steam Deck setup + play kit (docs/LINUX.md).
#
# TOOLS ONLY. It holds a relocatable Python (python-appimage) with cryptography/CMake/Ninja, clang-cl +
# lld-link + llvm-lib + llvm-rc from LLVM's own Linux release, xwin, a fallback git, and this repo's
# setup/, tools/, patches/, project/, linux/ and docs/. Never game files, the EBOOT, recompiled code,
# keys, firmware, saves, shader caches, RPCS3, Proton or Microsoft's CRT/SDK: the player's PC gets those
# itself (docs/LINUX.md). check_payload below refuses to package anything that looks like them.
#
# The git copy and the libraries it needs are GPL/LGPL: their Debian/Ubuntu source packages are
# collected into DemonsSoulsRecomp-Setup-sources.tar, which must be published in the same place as the
# AppImage (the workflow uploads both). Everything else in it is under permissive licenses.
#
# Run on Linux x86_64 (the GitHub Actions job: Ubuntu 22.04, .github/workflows/linux-appimage.yml).
# Needs curl, tar, zstd, patchelf, git, python3, and deb-src entries for apt-get source (the workflow
# adds them). SKIP_SOURCES=1 skips the sources: for a local test build only, never to hand out.
# Downloads are cached in $CACHE.
#   linux/appimage/build-appimage.sh [output.AppImage [sources.tar]]
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:-$REPO/DemonsSoulsRecomp-Setup-x86_64.AppImage}
SRC_OUT=${2:-$(dirname "$OUT")/DemonsSoulsRecomp-Setup-sources.tar}
WORK=${WORK:-$REPO/build-appimage}
CACHE=${CACHE:-$WORK/cache}
APPDIR=$WORK/AppDir
LLVM_VERSION=${LLVM_VERSION:-23.1.3}         # the tested Windows build's clang
PY_SERIES=python3.12
APPIMAGETOOL_VERSION=1.9.1
XWIN_VERSION=$(sed -n "s/^XWIN_VERSION = '\(.*\)'/\1/p" "$REPO/setup/build.py")
SHARE=$APPDIR/usr/share/demons-souls-recomp
ORIGINS=$WORK/origins.txt   # every system file copied into the AppImage, for collect_sources

say() { printf '\n== %s\n' "$*"; }
fetch() {   # fetch <url> <file in $CACHE>
  [ -s "$CACHE/$2" ] || { echo "  downloading $1"; curl -fL --retry 3 -o "$CACHE/$2.part" "$1"; mv "$CACHE/$2.part" "$CACHE/$2"; }
}
gh_asset() {  # gh_asset <owner/repo> <tag> <name regex>: download URL of a release asset
  curl -fsSL ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
    "https://api.github.com/repos/$1/releases/tags/$2" |
    python3 -c 'import json, re, sys
for a in json.load(sys.stdin)["assets"]:
    if re.search(sys.argv[1], a["name"]): print(a["browser_download_url"]); break' "$3"
}

# Libraries every Linux has (glibc and the C++ runtime): never bundled. Everything else an ELF needs
# is copied next to it and found through its RPATH.
SYSTEM_LIBS='^(linux-vdso|ld-linux|libc|libm|libdl|libpthread|librt|libresolv|libutil|libstdc\+\+|libgcc_s|libz)\.so'
bundle_libs() {   # bundle_libs <libdir> <elf>...
  local dir=$1; shift
  mkdir -p "$dir"
  for elf in "$@"; do
    ldd "$elf" 2>/dev/null | awk '/=> \// {print $1, $3}' | while read -r name path; do
      echo "$name" | grep -Eq "$SYSTEM_LIBS" && continue
      [ -e "$dir/$name" ] || { cp -L "$path" "$dir/$name"; echo "$path" >> "$ORIGINS"; bundle_libs "$dir" "$dir/$name"; }
    done
  done
}
set_rpath() {   # set_rpath <rpath> <elf>...
  local r=$1; shift
  for elf in "$@"; do
    [ -L "$elf" ] && continue
    file -b "$elf" | grep -q ELF && patchelf --set-rpath "$r" "$elf"
  done
}

rm -rf "$APPDIR"
mkdir -p "$CACHE" "$WORK"
: > "$ORIGINS"

say "Python ($PY_SERIES, python-appimage)"
url=$(gh_asset niess/python-appimage "$PY_SERIES" 'cp312-manylinux2014_x86_64\.AppImage$')
[ -n "$url" ] || { echo "no $PY_SERIES AppImage found"; exit 1; }
fetch "$url" "$(basename "$url")"
chmod +x "$CACHE/$(basename "$url")"
rm -rf "$WORK/squashfs-root"
(cd "$WORK" && "$CACHE/$(basename "$url")" --appimage-extract >/dev/null)
mv "$WORK/squashfs-root" "$APPDIR"
rm -f "$APPDIR"/AppRun "$APPDIR"/*.desktop "$APPDIR"/*.png "$APPDIR"/*.svg "$APPDIR"/.DirIcon
rm -rf "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo" "$APPDIR/usr/share/icons"
PYHOME=$(ls -d "$APPDIR"/opt/python3.*)
PY="$PYHOME/bin/$(basename "$PYHOME")"
"$PY" -m pip install --no-cache-dir --disable-pip-version-check -q -r "$REPO/setup/requirements.txt" certifi
# Python modules the kit never uses whose libraries are GPL/LGPL (readline and gdbm GPL-3, libcrypt
# and libnsl LGPL): out, so the only copyleft parts left are git and its libraries, whose sources ship
# next to the AppImage (collect_sources below). check_links makes sure nothing still needs them.
rm -f "$PYHOME"/lib/python3.*/lib-dynload/{readline,_gdbm,_dbm,_crypt,nis}.cpython-*.so
rm -f "$APPDIR"/usr/lib/{libreadline,libgdbm,libgdbm_compat,libcrypt,libnsl}.so*

say "LLVM $LLVM_VERSION (clang-cl, lld-link, llvm-lib, llvm-rc, llvm-mt + clang's headers)"
LLVM_TAR=LLVM-$LLVM_VERSION-Linux-X64.tar.zst
fetch "https://github.com/llvm/llvm-project/releases/download/llvmorg-$LLVM_VERSION/$LLVM_TAR" "$LLVM_TAR"
rm -rf "$WORK/llvm" && mkdir -p "$WORK/llvm"
# LLVM packs it with zstd's long mode (a 2 GB window), which zstd only decodes when told so; plain
# "tar --zstd" cannot read it
zstd -dc --long=31 "$CACHE/$LLVM_TAR" | tar -xf - -C "$WORK/llvm" --strip-components=1 --wildcards \
  '*/bin/clang' '*/bin/clang-[0-9]*' '*/bin/clang-cl' '*/bin/lld' '*/bin/lld-link' '*/bin/llvm-ar' \
  '*/bin/llvm-lib' '*/bin/llvm-rc' '*/bin/llvm-mt' '*/lib/clang/*/include/*'
L=$APPDIR/usr/lib/llvm
mkdir -p "$L"
cp -a "$WORK/llvm/bin" "$WORK/llvm/lib" "$L/"
for t in clang-cl lld-link llvm-lib llvm-rc; do
  [ -e "$L/bin/$t" ] || { echo "LLVM tarball has no bin/$t"; exit 1; }
done
bundle_libs "$L/lib" $(find "$L/bin" -type f)
set_rpath '$ORIGIN/../lib' $(find "$L/bin" -type f)
set_rpath '$ORIGIN' $(find "$L/lib" -maxdepth 1 -name '*.so*' -type f)
mkdir -p "$APPDIR/usr/share/licenses/llvm"
curl -fsSL -o "$APPDIR/usr/share/licenses/llvm/LICENSE.TXT" \
  "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-$LLVM_VERSION/llvm/LICENSE.TXT"

say "xwin $XWIN_VERSION"
XT=xwin-$XWIN_VERSION-x86_64-unknown-linux-musl.tar.gz
fetch "https://github.com/Jake-Shadle/xwin/releases/download/$XWIN_VERSION/$XT" "$XT"
fetch "https://github.com/Jake-Shadle/xwin/releases/download/$XWIN_VERSION/$XT.sha256" "$XT.sha256"
(cd "$CACHE" && echo "$(cut -d' ' -f1 "$XT.sha256")  $XT" | sha256sum -c -)
rm -rf "$WORK/xwin" && mkdir -p "$WORK/xwin" "$APPDIR/usr/lib/xwin" "$APPDIR/usr/share/licenses/xwin"
tar -xzf "$CACHE/$XT" -C "$WORK/xwin" --strip-components=1
cp "$WORK/xwin/xwin" "$APPDIR/usr/lib/xwin/"
cp "$WORK/xwin"/LICENSE-* "$APPDIR/usr/share/licenses/xwin/"

say "git (used only where the system has none)"
G=$APPDIR/usr/lib/git
mkdir -p "$G/bin" "$G/libexec/git-core" "$G/share" "$APPDIR/usr/share/licenses/git"
cp -L "$(command -v git)" "$G/bin/git"
command -v git >> "$ORIGINS"
for h in git-remote-http git-remote-https; do
  if [ -e "/usr/lib/git-core/$h" ]; then
    cp -L "/usr/lib/git-core/$h" "$G/libexec/git-core/$h"
    echo "/usr/lib/git-core/$h" >> "$ORIGINS"
  fi
done
cp -r /usr/share/git-core/templates "$G/share/templates" 2>/dev/null || mkdir -p "$G/share/templates"
bundle_libs "$G/lib" "$G/bin/git" "$G"/libexec/git-core/*
set_rpath '$ORIGIN/../lib' "$G/bin/git"
set_rpath '$ORIGIN/../../lib' "$G"/libexec/git-core/*
set_rpath '$ORIGIN' $(find "$G/lib" -name '*.so*' -type f)

# The Debian package that installed a file. dpkg knows some files only by their /lib or /usr/lib path.
owner() {
  local f=$1 r o p
  r=$(readlink -f "$f")
  for p in "$f" "$r" "${r#/usr}" "/usr$r"; do
    o=$(dpkg -S "$p" 2>/dev/null | head -n 1) || true
    [ -n "$o" ] && { echo "${o%%:*}" | sed 's/,.*//'; return 0; }
  done
  echo "no Debian package owns $f" >&2
  return 1
}
say "sources of the bundled GPL/LGPL parts (git and its libraries) -> $(basename "$SRC_OUT")"
SRC=$WORK/sources
rm -rf "$SRC" && mkdir -p "$SRC/packages"
LIC=$APPDIR/usr/share/licenses
sort -u "$ORIGINS" | while read -r f; do pkg=$(owner "$f") || exit 1; echo "$pkg $f"; done > "$WORK/owners.txt"
{
  echo "Source code of the programs and libraries DemonsSoulsRecomp-Setup-x86_64.AppImage copies from"
  echo "Ubuntu 22.04 / the git-core PPA: git (GPL-2.0) and the libraries it needs (several LGPL; all are"
  echo "included here, whatever their license)."
  echo "The source packages are in DemonsSoulsRecomp-Setup-sources.tar, published next to the AppImage."
  echo "The only change made to these binaries: their RPATH (patchelf, linux/appimage/build-appimage.sh)."
  echo
  printf '%-34s %-40s %s\n' "binary package" "source package=version" "bundled file"
} > "$SRC/SOURCES.txt"
while read -r pkg f; do
  spec=$(dpkg-query -W -f='${source:Package}=${source:Version}' "$pkg")
  printf '%-34s %-40s %s\n' "$pkg" "$spec" "$f" >> "$SRC/SOURCES.txt"
  echo "$spec" >> "$WORK/specs.txt"
  mkdir -p "$LIC/$pkg"
  cp -L "/usr/share/doc/$pkg/copyright" "$LIC/$pkg/copyright" 2>/dev/null ||
    { echo "no copyright file for $pkg"; exit 1; }
done < "$WORK/owners.txt"
if [ "${SKIP_SOURCES:-}" = 1 ]; then
  echo "  SKIP_SOURCES=1: no source packages collected -- do not hand this AppImage out"
else
  sort -u "$WORK/specs.txt" | while read -r spec; do
    (cd "$SRC/packages" && apt-get source --download-only -q "$spec" >/dev/null) ||
      { echo "apt-get source $spec failed (deb-src entries missing?)"; exit 1; }
  done
  tar -cf "$SRC_OUT" -C "$SRC" .
  echo "  $(sort -u "$WORK/specs.txt" | wc -l) source packages, $(du -h "$SRC_OUT" | cut -f1)"
fi
rm -f "$WORK/specs.txt"
cp "$SRC/SOURCES.txt" "$LIC/SOURCES.txt"

say "this repo's scripts and patches"
mkdir -p "$SHARE"
(cd "$REPO" && git ls-files -z --cached --others --exclude-standard -- \
    setup tools patches project linux docs README.md LICENSE .gitattributes) |
  while IFS= read -r -d '' f; do
    [ -f "$REPO/$f" ] || continue
    mkdir -p "$SHARE/$(dirname "$f")"
    cp "$REPO/$f" "$SHARE/$f"
  done
find "$SHARE" -name '__pycache__' -prune -exec rm -rf {} +
rm -f "$SHARE/setup/local_config.json"
chmod +x "$SHARE"/linux/*.sh
cp "$REPO/LICENSE" "$APPDIR/usr/share/licenses/demons-souls-recomp-LICENSE"
cat > "$APPDIR/usr/share/licenses/README.txt" <<EOF
Demon's Souls PC port -- Linux setup + play kit. Tools only: no game data, no recompiled code.
Contents and their licenses:
  usr/share/demons-souls-recomp  this repo's scripts and patches (../demons-souls-recomp-LICENSE)
  opt/python3.*                  CPython from python-appimage (PSF license, lib/python3.*/LICENSE.txt),
                                 with cryptography, cmake, ninja, certifi (licenses in site-packages/*.dist-info)
  usr/lib/llvm                   LLVM $LLVM_VERSION release binaries (llvm/LICENSE.TXT, Apache-2.0 WITH LLVM-exception)
  usr/lib/xwin                   xwin $XWIN_VERSION (xwin/LICENSE-MIT, xwin/LICENSE-APACHE)
  usr/lib/git                    git (GPL-2.0) and the libraries it needs (several LGPL), from Ubuntu;
                                 copyright files in <package>/copyright, SOURCES.txt lists each one, and
                                 their source packages are in DemonsSoulsRecomp-Setup-sources.tar,
                                 published next to this AppImage
  usr/lib/*.so*                  libraries of that Python build (OpenSSL, libffi, ncurses, Tcl/Tk, Xft,
                                 bzip2, xz, SQLite: permissive licenses). Its GPL/LGPL modules (readline,
                                 gdbm, crypt, nis) are removed.
Downloaded on the player's PC, never part of this file: RPCS3 (GPL-2.0), ps3recomp (its repository's
license), the Microsoft CRT + Windows SDK via xwin (Microsoft's license, accepted by the player),
umu-launcher / Proton (their licenses).
EOF

say "launcher, desktop entry, icon"
cp "$REPO/linux/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cat > "$APPDIR/demons-souls-recomp.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Demon's Souls PC port (setup + play)
Comment=Builds the Demon's Souls PC port from your own disc image and plays it through Proton
Exec=AppRun
Icon=demons-souls-recomp
Terminal=true
Categories=Game;
EOF
"$PY" - "$APPDIR/demons-souls-recomp.png" <<'EOF'
# a plain 256x256 icon (dark red with a lighter frame); no game artwork
import struct, sys, zlib
W = 256
rows = []
for y in range(W):
    row = bytearray([0])
    for x in range(W):
        edge = min(x, y, W - 1 - x, W - 1 - y)
        row += bytes((150, 40, 30, 255) if 18 <= edge < 30 else (40, 12, 10, 255))
    rows.append(bytes(row))
def chunk(t, d):
    return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, W, 8, 6, 0, 0, 0)) + \
      chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b'')
open(sys.argv[1], 'wb').write(png)
EOF
ln -sf demons-souls-recomp.png "$APPDIR/.DirIcon"

say "checking nothing needs a removed library"
find "$APPDIR" -type f \( -name '*.so*' -o -perm -u+x \) | while read -r f; do
  file -b "$f" | grep -q ELF || continue
  if patchelf --print-needed "$f" 2>/dev/null | grep -Eq '^(libreadline|libgdbm|libgdbm_compat|libcrypt|libnsl)\.'; then
    echo "$f still needs a removed GPL/LGPL library"; exit 1
  fi
done
echo "  ok"

say "checking the payload holds no game data"
check_payload() {
  local bad
  bad=$(find "$APPDIR" \( -iname '*.iso' -o -iname '*.dkey' -o -iname 'EBOOT*' -o -iname '*.self' \
        -o -iname '*.sprx' -o -iname '*.sdat' -o -iname '*.edat' -o -iname '*.pup' -o -iname 'PARAM.SFO' \
        -o -iname '*.pkg' -o -iname '*.rap' -o -iname '*.bnd' -o -iname '*.bhd5' -o -iname '*.bdt' \
        -o -iname '*.dcx' -o -iname '*.flver' -o -iname '*.tpf' -o -iname 'ppu_recomp*' -o -iname 'spu_recomp*' \
        -o -iname 'PS3_GAME' -o -iname 'dev_hdd0' -o -iname 'savedata' -o -iname 'DemonsSoulsRecomp.exe' \) -print)
  if [ -n "$bad" ]; then echo "REFUSING to package (looks like game data or recompiled code):"; echo "$bad"; exit 1; fi
  echo "  ok: no game-like files; $(find "$SHARE" -type f | wc -l) repo files (git ls-files only)"
}
check_payload

say "AppImage"
TOOL=appimagetool-x86_64.AppImage
fetch "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/$TOOL" "$TOOL"
chmod +x "$CACHE/$TOOL"
rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$CACHE/$TOOL" --no-appstream "$APPDIR" "$OUT"
ls -la "$OUT"
