package io.github.timboat.desrecomp;

import org.libsdl.app.SDLActivity;

/** SDL's activity, unchanged for now: it loads libSDL2.so and libmain.so and runs SDL_main
 *  (android/android_main.cpp) on its own thread. */
public class DeSActivity extends SDLActivity {
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL2", "main" };
    }
}
