// Android entry point: SDLActivity loads libmain.so and calls SDL_main on its "SDLThread". This does what
// linux/native/play.sh does before it starts the game -- the environment, the HDD1 cache wipe, the log
// files -- and then runs the boot harness's main (runtime/ppu/tests/boot_main.cpp, compiled with
// main=ds_boot_main for this build) on the EBOOT.
//
// Everything lives in the app's external files folder, /sdcard/Android/data/<package>/files (no storage
// permission needed; adb push puts the game there):
//
//   files/game/PS3_GAME/USRDIR/EBOOT.elf   the game, from your own disc (linux/native/build.sh game decrypt)
//   files/hdd0 hdd1 gamedata no_flash      the console's drives and the saves (made here when missing)
//   files/logs/last_run_out.txt, last_run_err.txt   stdout / stderr of the run (the previous run: *_prev.txt)
//   files/des.ini                          optional KEY=VALUE lines that override the settings below
//                                          (lines starting with # are comments; KEY= with nothing unsets)
//
// Settings: as play.sh with DES_FPS=30, DES_MOVIES=0 (PS3_NO_SAIL: no FFmpeg on Android yet), full screen,
// DES_SKIP_INTRO=1. A thread logs the process's peak and current resident memory (VmHWM / VmRSS) every
// 10 s to the game log and to logcat (tag "DeS").
#include <android/log.h>
#include <SDL.h>

#include <dirent.h>
#include <errno.h>
#include <ftw.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <string>

int ds_boot_main(int argc, char** argv);   // boot_main.cpp's main (C++ linkage: main=ds_boot_main)

#define TAG "DeS"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

namespace {

int rm_entry(const char* path, const struct stat*, int, struct FTW*) { return remove(path); }

void rm_rf(const std::string& dir) { nftw(dir.c_str(), rm_entry, 16, FTW_DEPTH | FTW_PHYS); }

void mkdirs(const std::string& dir) {
    for (size_t i = 1; i <= dir.size(); i++)
        if (i == dir.size() || dir[i] == '/') mkdir(dir.substr(0, i).c_str(), 0775);
}

bool exists(const std::string& p) { struct stat st; return stat(p.c_str(), &st) == 0; }

// des.ini: KEY=VALUE per line, applied before the defaults (which never overwrite what it set).
void apply_ini(const std::string& path) {
    FILE* f = fopen(path.c_str(), "r");
    if (!f) return;
    char line[1024];
    while (fgets(line, sizeof line, f)) {
        char* s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (*s == '#' || *s == ';' || *s == '\n' || *s == '\r' || !*s) continue;
        s[strcspn(s, "\r\n")] = 0;
        char* eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        char* k = s; char* e = eq; while (e > k && (e[-1] == ' ' || e[-1] == '\t')) *--e = 0;
        const char* v = eq + 1; while (*v == ' ' || *v == '\t') v++;
        setenv(k, *v ? v : "\x01", 1);   // "\x01": unset, and the default stays off (clear_unset_markers)
        LOGI("des.ini: %s=%s", k, v);
    }
    fclose(f);
}

// A default: only when des.ini did not set (or unset) the variable.
void def(const char* k, const char* v) { setenv(k, v, 0); }

// Drops the des.ini "unset" markers once the defaults are in.
void clear_unset_markers() {
    std::string drop;
    for (char** e = environ; *e; e++) {
        const char* eq = strchr(*e, '=');
        if (eq && eq[1] == '\x01' && !eq[2]) drop.append(*e, eq - *e).push_back('\n');
    }
    size_t a = 0, b;
    while ((b = drop.find('\n', a)) != std::string::npos) { unsetenv(drop.substr(a, b - a).c_str()); a = b + 1; }
}

// Peak / current resident set, from /proc/self/status.
void rss_kb(long* hwm, long* rss) {
    *hwm = *rss = -1;
    FILE* f = fopen("/proc/self/status", "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        if (!strncmp(line, "VmHWM:", 6)) *hwm = atol(line + 6);
        else if (!strncmp(line, "VmRSS:", 6)) *rss = atol(line + 6);
    }
    fclose(f);
}

void* rss_thread(void*) {
    for (;;) {
        sleep(10);
        long hwm, rss;
        rss_kb(&hwm, &rss);
        fprintf(stderr, "[mem] VmHWM %ld MB, VmRSS %ld MB\n", hwm / 1024, rss / 1024);
        LOGI("[mem] VmHWM %ld MB, VmRSS %ld MB", hwm / 1024, rss / 1024);
    }
    return nullptr;
}

}  // namespace

extern "C" __attribute__((visibility("default"))) int SDL_main(int, char**) {
    const char* ext = SDL_AndroidGetExternalStoragePath();
    if (!ext) { LOGE("no external files folder: %s", SDL_GetError()); return 1; }
    const std::string F = ext;
    if (chdir(F.c_str()) != 0) { LOGE("chdir %s: %s", F.c_str(), strerror(errno)); return 1; }

    // The logs first, unbuffered, so a crash loses nothing (play.sh's > last_run_*.txt).
    const std::string logs = F + "/logs";
    mkdirs(logs);
    for (const char* n : {"out", "err"}) {
        const std::string cur = logs + "/last_run_" + n + ".txt";
        if (exists(cur)) rename(cur.c_str(), (logs + "/last_run_" + n + "_prev.txt").c_str());
    }
    if (!freopen((logs + "/last_run_out.txt").c_str(), "w", stdout)) LOGE("stdout log: %s", strerror(errno));
    if (!freopen((logs + "/last_run_err.txt").c_str(), "w", stderr)) LOGE("stderr log: %s", strerror(errno));
    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);
    LOGI("files: %s; game log: %s/last_run_err.txt", F.c_str(), logs.c_str());

    apply_ini(F + "/des.ini");

    const std::string eboot = F + "/game/PS3_GAME/USRDIR/EBOOT.elf";
    if (!exists(eboot)) {
        fprintf(stderr, "no %s: adb push your game/ folder (from linux/native/build.sh) there first\n", eboot.c_str());
        LOGE("no %s", eboot.c_str());
        return 1;
    }

    // The drives (play.sh: PS3_HDD0_ROOT / PS3_HDD1_ROOT / PS3_DEV_FLASH) and the saves (PS3_GAMEDATA_ROOT;
    // the desktop builds use ./gamedata, which is the same folder here).
    def("PS3_HDD0_ROOT", (F + "/hdd0").c_str());
    def("PS3_HDD1_ROOT", (F + "/hdd1").c_str());
    def("PS3_DEV_FLASH", (F + "/no_flash").c_str());
    def("PS3_GAMEDATA_ROOT", (F + "/gamedata").c_str());
    // The HDD1 cache goes before every run, as in play.sh (a killed run leaves truncated files there).
    for (const char* k : {"PS3_HDD0_ROOT", "PS3_HDD1_ROOT", "PS3_DEV_FLASH", "PS3_GAMEDATA_ROOT"}) {
        const char* d = getenv(k);
        if (!d || *d == '\x01') continue;
        if (!strcmp(k, "PS3_HDD1_ROOT")) rm_rf(std::string(d) + "/cache");
        mkdirs(d);
    }

    def("PS3_TITLE", "Demon's Souls (ps3recomp)");
    def("GCM_NO_TITLE_RECYCLE", "1");
    def("PS3_NP_STRICT_OFFLINE", "1");
    def("SPU_INTERP_UNLIFTED", "1");
    def("SPURS_JC_EVENTS", "0");
    def("PAD_KEYMAP", "souls");
    def("OSK_TEXT", "Slayer");
    def("PS3_PRIO_START", "1");
    if (exists(F + "/input.toml")) def("PS3_INPUT_MAP", (F + "/input.toml").c_str());
    // The Vulkan renderer: guest programs, batched draws, a full-screen window.
    def("PS3RECOMP_VK_GUEST_PROGRAMS", "1");
    def("PS3RECOMP_VK_WINDOW", "1");
    def("VK_DRAW_BATCH", "1");
    def("PS3RECOMP_VK_FULLSCREEN", "1");
    def("RSX_VK_ASYNC_SHADERS", "1");
    def("PS3RECOMP_SPIRV_CACHE", (F + "/cache/spirv").c_str());
    // The SPU command dispatcher (NOTES fixes 145, 150).
    def("DES_DISPQ_BATCH", "1");
    def("SPU_DISPQ_WAIT", "1");
    // The cheap report lines (play.sh).
    def("AUDIO_RATE", "1");
    def("DES_STEP_STATS", "1");
    def("EVT_BACKLOG", "1");
    def("HITCH_MS", "100");
    // No movies (no FFmpeg in this build), the console's 30 fps, straight to the title screen.
    def("PS3_NO_SAIL", "1");
    def("DES_FPS", "30");
    def("DES_SKIP_INTRO", "1");
    def("PS3_VERBOSE", "0");
    clear_unset_markers();
    if (const char* fps = getenv("DES_FPS")) {
        if (!strcmp(fps, "60")) { def("DES_60FPS", "1"); def("PS3_VBLANK_HZ", "120"); def("PS3_CLOCK_SCALE", "200"); }
        else if (!strcmp(fps, "unlimited")) {
            def("DES_60FPS", "1"); def("PS3_VBLANK_HZ", "480"); def("PS3_CLOCK_SCALE", "200"); def("DES_MAX_FPS", "240");
        }
    }
    if (getenv("PS3RECOMP_SPIRV_CACHE")) mkdirs(getenv("PS3RECOMP_SPIRV_CACHE"));

    fprintf(stderr, "[android] files %s, DES_FPS=%s\n", F.c_str(), getenv("DES_FPS") ? getenv("DES_FPS") : "30");
    pthread_t th;
    if (pthread_create(&th, nullptr, rss_thread, nullptr) == 0) pthread_detach(th);

    char arg0[] = "DemonsSoulsRecomp";
    std::string a1 = eboot;
    char* argv[] = {arg0, a1.data(), nullptr};
    const int rc = ds_boot_main(2, argv);

    long hwm, rss;
    rss_kb(&hwm, &rss);
    fprintf(stderr, "[mem] at exit: VmHWM %ld MB, VmRSS %ld MB\n", hwm / 1024, rss / 1024);
    LOGI("game exited with %d (VmHWM %ld MB)", rc, hwm / 1024);
    return rc;
}
