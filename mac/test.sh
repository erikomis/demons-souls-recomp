#!/bin/sh
# Native regressions, with synthetic inputs only; no game files or saves required.
# PS3RECOMP_DIR chooses an already patched SDK (default deps/ps3recomp).
# DES_TEST_BUILD chooses a separate test build. DES_TEST_SANITIZERS=ON enables ASan/UBSan.
# Additional arguments go to CTest, e.g. mac/test.sh -R 'spu_elf|spu_job'.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SDK=${PS3RECOMP_DIR:-$ROOT/deps/ps3recomp}
BUILD=${DES_TEST_BUILD:-$ROOT/port/build_mac_tests}
case "$SDK" in /*) ;; *) SDK="$ROOT/$SDK" ;; esac
case "$BUILD" in /*) ;; *) BUILD="$ROOT/$BUILD" ;; esac
if [ ! -f "$SDK/runtime/spu/spu_helpers.h" ]; then
    echo "error: no SDK in $SDK. Run mac/rebuild.sh toolkit or set PS3RECOMP_DIR to a patched SDK." >&2
    exit 1
fi
if ! git -c core.autocrlf=input -C "$SDK" apply --reverse --check --whitespace=nowarn \
    "$ROOT/patches/ps3recomp-local.patch"; then
    echo "error: the SDK does not match this checkout's runtime patch. Update it with mac/rebuild.sh toolkit." >&2
    exit 1
fi
cmake -S "$ROOT/mac/tests" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DPS3RECOMP_DIR="$SDK" -DDES_TEST_SANITIZERS="${DES_TEST_SANITIZERS:-OFF}"
cmake --build "$BUILD" --parallel "${JOBS:-6}"
ctest --test-dir "$BUILD" --output-on-failure "$@"
