# DemonsSoulsLauncher.exe: the settings window that starts the game through PLAY.bat (launcher.cpp).
# Plain Win32 + GDI+, nothing to install. Built with the game and copied next to PLAY.bat, where it
# finds the game and keeps launcher.ini. Also builds on its own (a quick test of the window):
#   cmake -S project/launcher -B <dir> -G Ninja && ninja -C <dir>
cmake_minimum_required(VERSION 3.21)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(DemonsSoulsLauncher LANGUAGES CXX)
endif()

add_executable(DemonsSoulsLauncher WIN32 launcher.cpp launcher.rc)
set_target_properties(DemonsSoulsLauncher PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
target_compile_definitions(DemonsSoulsLauncher PRIVATE UNICODE _UNICODE _CRT_SECURE_NO_WARNINGS)
target_compile_options(DemonsSoulsLauncher PRIVATE /O2)
target_link_libraries(DemonsSoulsLauncher PRIVATE comctl32 gdiplus shell32 user32 gdi32)
# launcher.rc carries the manifest (modern controls, DPI awareness); no second one from the linker.
target_link_options(DemonsSoulsLauncher PRIVATE /MANIFEST:NO)

# Next to PLAY.bat, on every build. An open launcher locks its exe: then this says so and the build
# goes on (the next one copies it).
set(DS_LAUNCHER_DEST "${CMAKE_CURRENT_SOURCE_DIR}/../.." CACHE PATH "Where the launcher is copied (next to PLAY.bat)")
add_custom_target(DemonsSoulsLauncher_copy ALL
    COMMAND "${CMAKE_COMMAND}" "-DSRC=$<TARGET_FILE:DemonsSoulsLauncher>" "-DDST=${DS_LAUNCHER_DEST}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/copy_to_root.cmake"
    DEPENDS DemonsSoulsLauncher
    VERBATIM)
