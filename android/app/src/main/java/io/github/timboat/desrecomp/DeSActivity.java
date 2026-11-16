package io.github.timboat.desrecomp;

import android.os.Bundle;
import android.view.ViewGroup;

import org.libsdl.app.SDLActivity;

/** SDL's activity (it loads libSDL2.so and libmain.so and runs SDL_main, android/android_main.cpp, on its
 *  own thread) with the on-screen controls (TouchControls) laid over SDL's surface. */
public class DeSActivity extends SDLActivity {
    @Override
    protected String[] getLibraries() {
        return new String[] { "SDL2", "main" };
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (mLayout != null && !mBrokenLibraries)
            mLayout.addView(new TouchControls(this),
                    new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }
}
