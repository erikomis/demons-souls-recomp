# cmake -DSRC=<built launcher> -DDST=<folder with PLAY.bat> -P copy_to_root.cmake
file(COPY_FILE "${SRC}" "${DST}/DemonsSoulsLauncher.exe" RESULT r ONLY_IF_DIFFERENT)
if(r)
    message(WARNING "DemonsSoulsLauncher.exe was not copied next to PLAY.bat (${r}); close the launcher and build again.")
endif()
