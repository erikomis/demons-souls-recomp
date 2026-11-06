@echo off
rem The rebuild after an update, in a window of its own (PLAY.bat runs it when started by the launcher, which
rem has no console for PLAY.bat itself). When the build does not finish, it asks whether to play the build
rem that is already there anyway; a yes leaves logs\play_old_build.flag for PLAY.bat. Exit code 0 = built
rem or play the old build, 1 = stop.
setlocal
set "R=%~dp0.."
call "%R%\BUILD.bat"
if not errorlevel 1 exit /b 0
echo.
echo The rebuild did not finish: the messages above say why (logs\build_last.txt has the compiler's full
echo output). The build you already have is still there. It was made before this update, so the update's
echo fixes are not in it, and an old build with new files can misbehave (turn movies off if it stays black).
echo.
choice /c YN /m "Play the build you already have anyway"
if errorlevel 2 exit /b 1
if not exist "%R%\logs" mkdir "%R%\logs"
echo yes> "%R%\logs\play_old_build.flag"
exit /b 0
