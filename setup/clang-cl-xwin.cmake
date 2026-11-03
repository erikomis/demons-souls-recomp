# CMake toolchain: build the Windows exe with clang-cl + lld-link and a Microsoft CRT/SDK that xwin
# fetched on this PC (deps/xwin), without Visual Studio. This is how Linux builds it (docs/LINUX.md);
# on Windows "set DS_XWIN=1" before BUILD.bat tests the same path. setup/build.py passes DS_LLVM_BIN
# and puts the SDK's include and library folders in the INCLUDE and LIB environment variables, which
# clang-cl and lld-link read the way cl.exe and link.exe do (no paths in the flags, so a data folder
# with spaces or quotes in its name still builds).
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_VERSION 10.0)
set(CMAKE_SYSTEM_PROCESSOR AMD64)

# try_compile projects re-read this file without the -D values of the main configure
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES DS_LLVM_BIN DS_MSVC_COMPAT)
if(NOT DS_LLVM_BIN)
    message(FATAL_ERROR "DS_LLVM_BIN (the LLVM bin folder with clang-cl and lld-link) is not set; build with setup/build.py")
endif()
if(CMAKE_HOST_WIN32)
    set(_ds_exe ".exe")
else()
    set(_ds_exe "")
endif()

set(CMAKE_C_COMPILER "${DS_LLVM_BIN}/clang-cl${_ds_exe}")
set(CMAKE_CXX_COMPILER "${DS_LLVM_BIN}/clang-cl${_ds_exe}")
set(CMAKE_LINKER "${DS_LLVM_BIN}/lld-link${_ds_exe}")
set(CMAKE_AR "${DS_LLVM_BIN}/llvm-lib${_ds_exe}")
set(CMAKE_RC_COMPILER "${DS_LLVM_BIN}/llvm-rc${_ds_exe}")
set(CMAKE_MT "${DS_LLVM_BIN}/llvm-mt${_ds_exe}")

# Without Visual Studio clang-cl cannot tell which MSVC to imitate: the CRT's (build.py reads it from
# the folder name, 14.44 -> 19.44 = Visual Studio 2022 17.14).
if(NOT DS_MSVC_COMPAT)
    set(DS_MSVC_COMPAT 19.40)
endif()
string(APPEND CMAKE_C_FLAGS_INIT " --target=x86_64-pc-windows-msvc -fms-compatibility-version=${DS_MSVC_COMPAT}")
string(APPEND CMAKE_CXX_FLAGS_INIT " --target=x86_64-pc-windows-msvc -fms-compatibility-version=${DS_MSVC_COMPAT}")
# No manifest step: it needs llvm-mt built with libxml2, which LLVM's Linux release builds lack, and
# the default manifest (asInvoker) changes nothing for this exe.
string(APPEND CMAKE_EXE_LINKER_FLAGS_INIT " /manifest:no")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
