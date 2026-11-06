//! Launcher core for the Demon's Souls (BLUS-30443) port on macOS: the settings, the game files
//! extracted from the player's disc image, the builds of the port folder, the install and the
//! rebuild (mac/install.sh, mac/rebuild.sh) as child processes whose output is streamed to the
//! window, and "Play", which runs mac/play.sh with the settings mapped onto its environment
//! variables. mac/play.sh sets the port's own defaults and starts the window host
//! (DemonsSoulsRecomp_window) with the game under it; its own `${VAR:-default}`s let what the
//! launcher sets win. No game code or data is part of the app: everything it shows or starts comes
//! from the player's own copy and build folder.
//!
//! A variable is passed only when the build reads it (`FEATURE_MARKERS`: the executable is searched
//! for the name) or mac/play.sh does, and only when it differs from play.sh's default. With the
//! default settings Play's environment is exactly what `mac/play.sh` alone would do.

mod app_icon;
mod input_map;
mod install;
mod mods;
mod play_shortcut;
mod report;
mod saves;
mod steam;
mod steam_art;
mod trophies;
mod update;
mod vdf;
mod zipfile;

use input_map::{Bindings, InputEnv};
use saves::{read_sfo, BackupMeta, Side, Slot};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::UNIX_EPOCH;
use tauri::{AppHandle, Emitter, Manager, State};

const TITLE_ID: &str = "BLUS30443";
/// The game and its window host, under the port folder.
const GAME_EXE: &str = "DemonsSoulsRecomp";
const WINDOW_EXE: &str = "DemonsSoulsRecomp_window";
const BUILD_DIR: &str = "port/build_mac";
/// The decrypted executable the game runs.
const ELF_REL: &str = "game/PS3_GAME/USRDIR/EBOOT.elf";
/// What Play starts, under the port folder.
const PLAY_SH: &str = "mac/play.sh";
const REBUILD_SH: &str = "mac/rebuild.sh";
const INSTALL_SH: &str = "mac/install.sh";
/// The repository "Install the game" clones when there is no checkout yet: the port's own repository,
/// whose main branch has the Mac support since PR #30 (DES_SOURCES_URL / DES_SOURCES_BRANCH override both).
const SOURCES_URL: &str = "https://github.com/timboat/demons-souls-recomp.git";
const SOURCES_BRANCH: &str = "main";

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

/// What the player can change. Each field maps onto one of the environment variables mac/play.sh
/// or the game reads (see `launch_env`), or onto how Play starts it.
#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(rename_all = "camelCase", default)]
pub struct Settings {
    /// Launcher UI language: "pt-BR" or "en".
    pub ui_lang: String,
    /// The port folder: a checkout with port/build_mac and game/. Empty = found on its own.
    pub port_dir: String,
    /// PS3_LANG; empty = the Mac's language.
    pub game_lang: String,
    /// DES_FPS: "60" (play.sh's default) or "30" (the console's own rate).
    pub fps: String,
    /// DES_MOVIES=0 when off; on, play.sh plays them whenever FFmpeg is found.
    pub movies: bool,
    /// DES_NAME: the character name the game's on-screen keyboard gets (empty = play.sh's "Slayer").
    pub char_name: String,
    /// DES_SKIP_INTRO=1: the logos and the opening movie are skipped, straight to PRESS START.
    pub skip_intro: bool,
    /// DES_SIZE: "<w>x<h>"; empty = play.sh's 1280x720 (the window host's --size).
    pub window_size: String,
    /// PS3_WINDOW_MODE: "windowed" (the default), "fullscreen" (macOS's own) or "borderless".
    pub window_mode: String,
    /// PS3_DISPLAY: the screen's name (or its 1-based number); empty = the main screen.
    pub display: String,
    /// PS3_VSYNC=0 when off.
    pub vsync: bool,
    /// PS3_RES_SCALE: the internal resolution as a multiple of 1280x720: "" (native), "1.5"
    /// (1080p), "2" (1440p), "3" (4K).
    pub res_scale: String,
    /// PS3_UPSCALE: "" (a plain scale) or "metalfx" (macOS 13+).
    pub upscale: String,
    /// PS3_WINDOW_ICON=<game/PS3_GAME/ICON0.PNG>: the game's own window shows the player's icon
    /// in the Dock instead of a generic one.
    pub game_window_icon: bool,
    /// The player's own ICON0.PNG in the Dock instead of the placeholder.
    pub game_icon: bool,
    /// PS3_AA: "" (off), "fxaa" or "smaa".
    pub aa: String,
    /// PS3_SHARPEN: 0 (off) to 1.
    pub sharpen: f32,
    /// PS3_ANISO: 0 (off, the runtime's default), 2, 4, 8 or 16.
    pub aniso: u32,
    /// PS3_DISPLAY_GAMMA when set; otherwise the game's own brightness.
    pub gamma_override: bool,
    pub gamma: f32,
    /// PS3_VIBRANCE: -1 (muted) .. 0 (off) .. 1 (vivid).
    pub vibrance: f32,
    /// PS3_CONTRAST: 0.5 .. 1 (off) .. 1.5.
    pub contrast: f32,
    /// PS3_VIGNETTE and PS3_GRAIN: 0 (off) .. 1.
    pub vignette: f32,
    pub grain: f32,
    /// PS3_LUT: the player's colour LUT (ReShade's PNG strip), and how much of it
    /// (PS3_LUT_STRENGTH, 0..1).
    pub lut_path: String,
    pub lut_strength: f32,
    /// PS3_LUT_PRESET: a built-in LUT ("warm", "cool", "film", "vivid"; empty = none).
    pub lut_preset: String,
    /// PS3_MODS: the texture packs in use (folders in <data>/mods, PS3_MODS_DIR), first wins.
    pub mods: Vec<String>,
    /// PS3_MODS_DUMP=<data>/texture-dump: the game writes every texture it uploads there.
    pub mods_dump: bool,
    /// PS3_INPUT_MODE: "both" (the default), "controller" or "keyboard".
    pub input_mode: String,
    /// PS3_MOUSE, PS3_MOUSE_SENS, PS3_MOUSE_INVERT_Y, PS3_MOUSE_INVERT_X, PS3_MOUSE_DEADZONE
    /// (mac/input.toml's: on, 1.0, off, off, 30).
    pub mouse: bool,
    pub mouse_sens: f32,
    pub mouse_invert_y: bool,
    pub mouse_invert_x: bool,
    pub mouse_deadzone: u32,
    /// PS3_MOUSE_CAPTURE: a click captures the cursor (Esc/Cmd releases it).
    pub mouse_capture: bool,
    /// PS3_RUMBLE=0 when off; PS3_RUMBLE_STRENGTH in percent (0-200).
    pub rumble: bool,
    pub rumble_strength: u32,
    /// AUDIO_MUTE=1: the device gets silence; the game's sound runs as always.
    pub audio_mute: bool,
    /// PS3RECOMP_METAL_FPS=1: frame rate and frame times in the window title.
    pub show_fps: bool,
    /// Run under `caffeinate -i` so the Mac does not sleep mid-game.
    pub keep_awake: bool,
    /// PS3RECOMP_FFMPEG_AVCODEC / _AVUTIL; empty = play.sh finds Homebrew's.
    pub ffmpeg_avcodec: String,
    pub ffmpeg_avutil: String,
    /// DES_LOG=1: the runtime's per-event lines in the log (play.sh keeps them out: they cost frames).
    pub verbose_log: bool,
    /// PS3_PAD_LOG=1: the controller's buttons in the log.
    pub pad_log: bool,
    /// PS3_STALL_SAMPLE=<ms>: every thread's stacks after this long without a frame; 0 = off.
    pub stall_sample_ms: u32,
    /// Extra KEY=VALUE lines (diagnostics), one per line; '#' starts a comment.
    pub extra_env: String,
    /// The rebuild's steps and JOBS (Advanced > Install / rebuild).
    pub rebuild_steps: Vec<String>,
    pub jobs: u32,
    /// Automatic backups of the saves made before each "Play" that are kept (0 = off).
    pub save_backups_keep: u32,
    /// Look for new port sources on start (when the folder is a git checkout).
    pub auto_update_check: bool,
    /// What the Install card was given last (install.rs), so a second press continues with it.
    pub install: install::Inputs,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            ui_lang: "pt-BR".into(),
            port_dir: String::new(),
            game_lang: String::new(),
            fps: "60".into(),
            movies: true,
            char_name: String::new(),
            skip_intro: false,
            window_size: String::new(),
            window_mode: "windowed".into(),
            display: String::new(),
            vsync: true,
            res_scale: String::new(),
            upscale: String::new(),
            game_window_icon: true,
            game_icon: false,
            aa: String::new(),
            sharpen: 0.0,
            aniso: 0,
            gamma_override: false,
            gamma: 1.0,
            vibrance: 0.0,
            contrast: 1.0,
            vignette: 0.0,
            grain: 0.0,
            lut_path: String::new(),
            lut_strength: 1.0,
            lut_preset: String::new(),
            mods: Vec::new(),
            mods_dump: false,
            input_mode: "both".into(),
            mouse: true,
            mouse_sens: 1.0,
            mouse_invert_y: false,
            mouse_invert_x: false,
            mouse_deadzone: 30,
            mouse_capture: true,
            rumble: true,
            rumble_strength: 100,
            audio_mute: false,
            show_fps: false,
            keep_awake: true,
            ffmpeg_avcodec: String::new(),
            ffmpeg_avutil: String::new(),
            verbose_log: false,
            pad_log: false,
            stall_sample_ms: 0,
            extra_env: String::new(),
            rebuild_steps: Vec::new(),
            jobs: 0,
            save_backups_keep: 10,
            auto_update_check: true,
            install: install::Inputs::default(),
        }
    }
}

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

/// The launcher's own folder: launcher.json, the controls file, backups, reports, the sources an
/// install clones. The key file tools/fetch_keys.py writes is in its `keys/`, which the launcher
/// never reads.
fn data_root() -> PathBuf {
    if cfg!(target_os = "macos") {
        home().join("Library/Application Support/demons-souls-recomp")
    } else {
        std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).unwrap_or_else(|| home().join(".local/share")).join("demons-souls-recomp")
    }
}

fn settings_path() -> PathBuf {
    data_root().join("launcher.json")
}

fn reports_dir() -> PathBuf {
    data_root().join("reports")
}

/// The sources "Install the game" clones when the launcher finds no checkout.
fn cloned_sources() -> PathBuf {
    data_root().join("src")
}

/// The controls file the Controls page writes (PS3_INPUT_MAP), next to launcher.json: a copy of
/// the port's mac/input.toml with the player's changes. Until a binding changes there is none and
/// play.sh uses mac/input.toml.
fn input_map_path() -> PathBuf {
    data_root().join("input.toml")
}

/// The port's own layout, which play.sh uses when the launcher passes no PS3_INPUT_MAP.
fn base_input_map(port: Option<&Path>) -> Option<PathBuf> {
    port.map(|p| p.join("mac/input.toml")).filter(|p| p.is_file())
}

/// The controls file as Play passes it (see `launch_env`): the launcher's when there is one. The
/// mouse settings are passed whenever the file the game reads has a [mouse] section (mac/input.toml
/// has one), so the launcher's stand.
fn input_env(port: Option<&Path>) -> InputEnv {
    let own = input_map_path();
    if let Ok(text) = fs::read_to_string(&own) {
        return InputEnv { path: Some(s(&own)), has_mouse_section: input_map::parse(&text).has_mouse_section };
    }
    let base = base_input_map(port).and_then(|p| fs::read_to_string(p).ok());
    InputEnv { path: None, has_mouse_section: base.is_some_and(|t| input_map::parse(&t).has_mouse_section) }
}

/// Where texture packs live (PS3_MODS_DIR): <data>/mods.
fn mods_dir() -> PathBuf {
    data_root().join("mods")
}

/// Where "Dump the game's textures" makes the game write them (PS3_MODS_DUMP).
fn mods_dump_dir() -> PathBuf {
    data_root().join("texture-dump")
}

fn rpcs3_dir() -> PathBuf {
    if cfg!(target_os = "macos") {
        home().join("Library/Application Support/rpcs3")
    } else {
        std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from).unwrap_or_else(|| home().join(".config")).join("rpcs3")
    }
}

fn load_settings_file() -> Settings {
    fs::read_to_string(settings_path()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default()
}

fn write_settings(s: &Settings) -> Result<(), String> {
    let p = settings_path();
    if let Some(d) = p.parent() {
        fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    let tmp = p.with_extension("json.tmp");
    fs::write(&tmp, serde_json::to_string_pretty(s).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    fs::rename(&tmp, &p).map_err(|e| e.to_string())
}

fn parse_env_lines(text: &str) -> Vec<(String, String)> {
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .filter_map(|l| {
            let l = l.strip_prefix("export ").unwrap_or(l);
            let (k, v) = l.split_once('=')?;
            let k = k.trim();
            if k.is_empty() || !k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
                return None;
            }
            Some((k.to_string(), v.trim().trim_matches('"').to_string()))
        })
        .collect()
}

fn extra_var(s: &Settings, key: &str) -> Option<String> {
    parse_env_lines(&s.extra_env).into_iter().rev().find(|(k, _)| k == key).map(|(_, v)| v)
}

fn now_secs() -> u64 {
    std::time::SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn now_ms() -> u64 {
    std::time::SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0)
}

fn mtime(p: &Path) -> u64 {
    fs::metadata(p).and_then(|m| m.modified()).ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map_or(0, |d| d.as_secs())
}

fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut s = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        s.push(T[(n >> 18) as usize & 63] as char);
        s.push(T[(n >> 12) as usize & 63] as char);
        s.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        s.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    s
}

fn data_url(path: &Path, mime: &str) -> Option<String> {
    let mut buf = Vec::new();
    fs::File::open(path).ok()?.read_to_end(&mut buf).ok()?;
    Some(format!("data:{mime};base64,{}", base64(&buf)))
}

fn s(p: &Path) -> String {
    p.to_string_lossy().into_owned()
}

// ---------------------------------------------------------------------------
// The game files (extracted from the player's disc image into <port>/game)
// ---------------------------------------------------------------------------

/// The folder holding the game's PS3_GAME/: `<port>/game`.
fn game_root(port: &Path) -> PathBuf {
    port.join("game")
}

#[derive(Serialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
pub struct GameInfo {
    /// `<port>/game`, when it holds PS3_GAME/PARAM.SFO.
    root: Option<String>,
    title: String,
    title_id: String,
    app_ver: String,
    /// The image it was extracted from (game/.extracted).
    image: Option<String>,
    /// The files are this game (BLUS30443).
    ours: bool,
    /// The extraction finished (game/.extracted is there).
    extracted: bool,
}

fn game_info(port: Option<&Path>) -> GameInfo {
    let Some(port) = port else { return GameInfo::default() };
    let g = game_root(port);
    let mark = g.join(".extracted");
    let mut d = GameInfo {
        extracted: mark.is_file(),
        image: fs::read_to_string(&mark).ok().map(|t| t.trim().to_string()).filter(|t| !t.is_empty()),
        ..Default::default()
    };
    if let Some(v) = read_sfo(&g.join("PS3_GAME/PARAM.SFO")) {
        d.title = v.get("TITLE").cloned().unwrap_or_default();
        d.title_id = v.get("TITLE_ID").cloned().unwrap_or_default();
        d.app_ver = v.get("APP_VER").or(v.get("VERSION")).cloned().unwrap_or_default();
        d.ours = d.title_id == TITLE_ID;
        d.root = Some(s(&g));
    }
    d
}

/// The game's ICON0.PNG and PIC1.PNG (the player's own; nothing ships).
fn game_art(port: Option<&Path>) -> (Option<PathBuf>, Option<PathBuf>) {
    match port {
        Some(p) => {
            let g = game_root(p).join("PS3_GAME");
            (Some(g.join("ICON0.PNG")).filter(|p| p.is_file()), Some(g.join("PIC1.PNG")).filter(|p| p.is_file()))
        }
        None => (None, None),
    }
}

fn game_art_of(st: &Settings) -> (Option<PathBuf>, Option<PathBuf>) {
    game_art(port_root(st).as_deref())
}

// ---------------------------------------------------------------------------
// The builds
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct Builds {
    root: String,
    /// port/build_mac/DemonsSoulsRecomp, the game.
    eboot: Option<String>,
    /// port/build_mac/DemonsSoulsRecomp_window, its window.
    window: Option<String>,
    /// game/PS3_GAME/USRDIR/EBOOT.elf, the decrypted executable.
    eboot_elf: Option<String>,
    /// mac/play.sh, which Play starts.
    play_sh: Option<String>,
    /// Everything Play needs is there.
    ok: bool,
    missing: Vec<String>,
    /// mac/rebuild.sh, when this folder can rebuild.
    rebuild_sh: Option<String>,
    /// When the game was built (its mtime).
    built_at: u64,
}

fn resolve_builds(root: &Path) -> Builds {
    let file = |p: PathBuf| Some(p).filter(|p| p.is_file());
    let eboot = file(root.join(BUILD_DIR).join(GAME_EXE));
    let window = file(root.join(BUILD_DIR).join(WINDOW_EXE));
    let eboot_elf = file(root.join(ELF_REL));
    let play_sh = file(root.join(PLAY_SH));
    let mut missing = Vec::new();
    for (what, v) in [
        (format!("{BUILD_DIR}/{GAME_EXE}"), eboot.is_some()),
        (format!("{BUILD_DIR}/{WINDOW_EXE}"), window.is_some()),
        (ELF_REL.to_string(), eboot_elf.is_some()),
        (PLAY_SH.to_string(), play_sh.is_some()),
    ] {
        if !v {
            missing.push(what);
        }
    }
    let rebuild_sh = file(root.join(REBUILD_SH));
    let o = |p: &Option<PathBuf>| p.as_deref().map(s);
    Builds {
        root: s(root),
        built_at: eboot.as_deref().map(mtime).unwrap_or(0),
        ok: missing.is_empty(),
        eboot: o(&eboot),
        window: o(&window),
        eboot_elf: o(&eboot_elf),
        play_sh: o(&play_sh),
        missing,
        rebuild_sh: o(&rebuild_sh),
    }
}

/// A checkout of this port: mac/play.sh starts DemonsSoulsRecomp, and the setup is there.
fn is_port_checkout(p: &Path) -> bool {
    p.join("setup/setup.py").is_file() && fs::read_to_string(p.join(PLAY_SH)).is_ok_and(|t| t.contains(GAME_EXE))
}

/// The repository this launcher was built from: mac/launcher/src-tauri/../../.. .
fn own_repo() -> Option<PathBuf> {
    let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    is_port_checkout(&p).then(|| p.canonicalize().unwrap_or(p))
}

/// Port folders found on this Mac: DES_ROOT, the folder the launcher comes from, the sources an
/// install cloned, then a folder one level under the usual places that is a checkout of this
/// port. Complete builds first, the newest build first.
fn find_port_dirs_now() -> Vec<Builds> {
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Some(r) = std::env::var_os("DES_ROOT") {
        cands.push(PathBuf::from(r));
    }
    cands.extend(own_repo());
    cands.push(cloned_sources());
    for base in ["Desktop", "Developer", "Documents", "Projects", "src", "code", "git", "Games", ""] {
        let dir = home().join(base);
        let Ok(it) = fs::read_dir(&dir) else { continue };
        for e in it.flatten() {
            if !e.file_name().to_string_lossy().starts_with('.') {
                cands.push(e.path());
            }
        }
    }
    let mut seen = std::collections::HashSet::new();
    let mut v: Vec<Builds> = cands
        .into_iter()
        .filter(|p| p.is_dir() && is_port_checkout(p))
        .map(|p| p.canonicalize().unwrap_or(p))
        .filter(|p| seen.insert(p.clone()))
        .map(|p| resolve_builds(&p))
        .collect();
    v.sort_by(|a, b| b.ok.cmp(&a.ok).then(b.built_at.cmp(&a.built_at)));
    v
}

/// The port folder in use: the setting, else the best one found.
fn port_root(s: &Settings) -> Option<PathBuf> {
    let p = s.port_dir.trim();
    if !p.is_empty() {
        return Some(PathBuf::from(p));
    }
    find_port_dirs_now().into_iter().next().map(|b| PathBuf::from(b.root))
}

/// Where "Install the game" works: the port folder in use when it has mac/install.sh, else the
/// sources it clones into the data folder.
fn install_target(s: &Settings) -> PathBuf {
    port_root(s).filter(|r| r.join(INSTALL_SH).is_file()).unwrap_or_else(cloned_sources)
}

// ---------------------------------------------------------------------------
// The saves, the logs, the shader cache
// ---------------------------------------------------------------------------

/// The saves' root: PS3_GAMEDATA_ROOT from the extra variables, else `<port>/gamedata` (the
/// runtime's "./gamedata", play.sh running in the port folder).
fn gamedata_root(st: &Settings, port: &Path) -> PathBuf {
    extra_var(st, "PS3_GAMEDATA_ROOT").filter(|v| !v.trim().is_empty()).map(PathBuf::from).unwrap_or_else(|| port.join("gamedata"))
}

fn locations(st: &Settings) -> Result<saves::Locations, String> {
    let port = port_root(st).ok_or("no port folder yet")?;
    Ok(saves::Locations {
        port_savedata: gamedata_root(st, &port).join("dev_hdd0/home").join(saves::PORT_USER).join("savedata"),
        rpcs3_hdd0: rpcs3_dir().join("dev_hdd0"),
        backups: data_root().join("save-backups"),
    })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SaveInfo {
    name: String,
    title: String,
    subtitle: String,
    modified: u64,
    folder: String,
}

fn last_save(st: &Settings) -> Option<SaveInfo> {
    let loc = locations(st).ok()?;
    saves::newest_slot(&loc.port_savedata).map(|x| SaveInfo { name: x.name, title: x.title, subtitle: x.subtitle, modified: x.modified, folder: x.path })
}

/// The translated shaders on disk: PS3RECOMP_MSL_CACHE, play.sh's `cache/msl` unless the extra
/// variables move it.
fn msl_cache_dir(s: &Settings) -> Option<PathBuf> {
    extra_var(s, "PS3RECOMP_MSL_CACHE").filter(|v| !v.is_empty()).map(PathBuf::from).or_else(|| port_root(s).map(|r| r.join("cache/msl")))
}

/// The folder play.sh writes last_run_out.txt / last_run_err.txt into (and their _prev).
fn logs_dir(port: &Path) -> PathBuf {
    port.join("logs")
}

/// The game's log: what the game writes to stderr (play.sh: "game log in logs/last_run_err.txt").
const GAME_LOG: &str = "last_run_err.txt";
/// play.sh's own few lines (and why it refused, when it did).
const PLAY_LOG: &str = "play.log";

// ---------------------------------------------------------------------------
// Processes
// ---------------------------------------------------------------------------

#[derive(Default)]
pub struct AppState {
    rebuild: Mutex<Option<u32>>,
    /// `brew install` of what the build needs.
    setup: Mutex<Option<u32>>,
    game: Mutex<Option<u32>>,
    /// The report folder of the game started in debug mode, and whether that game is still running.
    report: Mutex<Option<(PathBuf, bool)>>,
    /// Where the last game this launcher started writes its log.
    last_log: Mutex<Option<PathBuf>>,
    /// The launcher's Dock icon as last set (app_icon::key; "" = the bundle's).
    dock_icon: Mutex<String>,
    play_request: Mutex<bool>,
    exit_with_game: Mutex<bool>,
    /// `--view <page>`: the page to open on (play_shortcut::start_view).
    start_view: Mutex<Option<String>>,
    /// build_features' cache.
    features: Mutex<FeatureCache>,
}

/// A GUI app on macOS starts with a bare PATH; Homebrew's and the usual install places are added
/// in front (the build needs cmake, ninja, glslang and spirv-cross).
fn tool_path() -> std::ffi::OsString {
    let mut parts: Vec<PathBuf> = Vec::new();
    if cfg!(target_os = "macos") {
        parts.extend(["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin"].map(PathBuf::from));
    }
    if let Some(p) = std::env::var_os("PATH") {
        parts.extend(std::env::split_paths(&p));
    }
    parts.extend(["/usr/bin", "/bin", "/usr/sbin", "/sbin"].map(PathBuf::from));
    let mut seen = std::collections::HashSet::new();
    parts.retain(|p| seen.insert(p.clone()));
    std::env::join_paths(parts).unwrap_or_else(|_| std::env::var_os("PATH").unwrap_or_default())
}

/// The native build runs on macOS (Metal) only.
fn host_supported() -> bool {
    cfg!(target_os = "macos") || std::env::var_os("DES_ANY_HOST").is_some_and(|v| !v.is_empty())
}

fn require_supported_host() -> Result<(), String> {
    if host_supported() {
        Ok(())
    } else {
        Err(format!("this launcher is for the macOS build; this is {}", std::env::consts::OS))
    }
}

/// No console window for a child of this GUI app (Windows).
#[cfg(windows)]
pub(crate) fn no_console(cmd: &mut Command) -> &mut Command {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW)
}
#[cfg(not(windows))]
pub(crate) fn no_console(cmd: &mut Command) -> &mut Command {
    cmd
}

fn clt_installed() -> bool {
    if !cfg!(target_os = "macos") {
        return true;
    }
    Command::new("xcode-select")
        .arg("-p")
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map(|o| o.status.success() && Path::new(String::from_utf8_lossy(&o.stdout).trim()).is_dir())
        .unwrap_or(false)
}

fn find_brew() -> Option<PathBuf> {
    ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"].iter().map(PathBuf::from).find(|p| p.is_file())
}

fn brew_prefix() -> PathBuf {
    match find_brew() {
        Some(b) => b.parent().and_then(Path::parent).map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("/opt/homebrew")),
        None => PathBuf::from("/opt/homebrew"),
    }
}

/// libavcodec as play.sh finds it (the versioned Homebrew one), for the Game page; the settings'
/// paths win.
fn ffmpeg_found(s: &Settings) -> Option<PathBuf> {
    if !s.ffmpeg_avcodec.trim().is_empty() {
        return Some(PathBuf::from(s.ffmpeg_avcodec.trim())).filter(|p| p.is_file());
    }
    for lib in [brew_prefix().join("lib"), PathBuf::from("/usr/local/lib")] {
        let mut v: Vec<PathBuf> = fs::read_dir(&lib)
            .into_iter()
            .flatten()
            .flatten()
            .map(|e| e.path())
            .filter(|p| {
                let n = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
                n.strip_prefix("libavcodec.").and_then(|r| r.strip_suffix(".dylib")).is_some_and(|v| !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit()))
            })
            .collect();
        v.sort();
        if let Some(p) = v.pop() {
            return Some(p);
        }
    }
    None
}

#[cfg(unix)]
fn own_process_group(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    cmd.process_group(0); // so a stop reaches what it started too
}
#[cfg(not(unix))]
fn own_process_group(cmd: &mut Command) {
    no_console(cmd);
}

/// Stop what this launcher started, with what it started in turn: SIGTERM (SIGKILL when `force`)
/// to the process group `pid` leads.
fn kill_tree(pid: u32, force: bool) {
    #[cfg(unix)]
    {
        let _ = Command::new("kill").arg(if force { "-KILL" } else { "-TERM" }).arg(format!("-{pid}")).status();
    }
    #[cfg(windows)]
    {
        let mut cmd = Command::new("taskkill");
        cmd.args(["/PID", &pid.to_string(), "/T"]);
        if force {
            cmd.arg("/F");
        }
        let _ = no_console(&mut cmd).stdout(Stdio::null()).stderr(Stdio::null()).status();
    }
    #[cfg(not(any(unix, windows)))]
    let _ = (pid, force);
}

fn command_stdout(cmd: &mut Command) -> Option<String> {
    let out = cmd.stderr(Stdio::null()).output().ok()?;
    if !out.status.success() {
        return None;
    }
    String::from_utf8(out.stdout).ok()
}

/// A process with this exact name is running (the game started from a terminal). Only looked at,
/// never signalled.
#[cfg(not(windows))]
fn process_running(name: &str) -> bool {
    Command::new("pgrep").args(["-x", name]).stdout(Stdio::null()).stderr(Stdio::null()).status().is_ok_and(|s| s.success())
}
#[cfg(windows)]
fn process_running(name: &str) -> bool {
    let _ = name;
    false
}

fn shell_quote(v: &str) -> String {
    if !v.is_empty() && v.chars().all(|c| c.is_ascii_alphanumeric() || "-_./:,=+@".contains(c)) {
        v.to_string()
    } else {
        format!("'{}'", v.replace('\'', "'\\''"))
    }
}

// ---------------------------------------------------------------------------
// Launch
// ---------------------------------------------------------------------------

/// "<w>x<h>", as the window host's --size takes it.
fn valid_window_size(v: &str) -> bool {
    let mut it = v.splitn(2, 'x').map(|n| n.parse::<u32>().ok());
    matches!((it.next(), it.next()), (Some(Some(w)), Some(Some(h))) if (320..=8192).contains(&w) && (180..=8192).contains(&h))
}

/// PS3_RES_SCALE for the `res_scale` setting: a multiple above 1 and up to 4 (the runtime's
/// range, in quarter steps), or None for native (also for anything unparsable).
fn res_scale_value(v: &str) -> Option<String> {
    let x: f32 = v.trim().parse().ok()?;
    (x > 1.0 && x <= 4.0).then(|| format!("{}", (x * 4.0).round() / 4.0))
}

/// The built-in LUTs the runtime has.
fn valid_lut_preset(v: &str) -> Option<&'static str> {
    ["warm", "cool", "film", "vivid"].into_iter().find(|p| *p == v.trim())
}

/// The character name for DES_NAME: 1 to 16 printable characters (the game's own limit), no
/// control characters; None when empty or not usable.
fn valid_name(v: &str) -> Option<String> {
    let n = v.trim();
    (!n.is_empty() && n.chars().count() <= 16 && !n.chars().any(char::is_control)).then(|| n.to_string())
}

/// The environment Play gives mac/play.sh, on top of the launcher's own. Only what the build or
/// play.sh reads (`features` for the build's), and only what differs from play.sh's and the
/// runtime's defaults; the extra variables last (they win). `input`: the controls file, when the
/// Controls page has written one. `port`: the port folder (the game's ICON0.PNG for its window).
fn launch_env(s: &Settings, port: Option<&Path>, input: &InputEnv, features: &Features) -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = Vec::new();
    // mac/play.sh's own settings
    if s.fps == "30" {
        env.push(("DES_FPS".into(), "30".into()));
    }
    if !s.movies {
        env.push(("DES_MOVIES".into(), "0".into()));
    }
    if let Some(n) = valid_name(&s.char_name) {
        env.push(("DES_NAME".into(), n));
    }
    if valid_window_size(&s.window_size) && s.window_size != "1280x720" {
        env.push(("DES_SIZE".into(), s.window_size.clone()));
    }
    if s.verbose_log {
        env.push(("DES_LOG".into(), "1".into()));
    }
    let mut set = |k: &str, v: String| {
        if features.contains(k) {
            env.push((k.to_string(), v));
        }
    };
    if s.skip_intro {
        set("DES_SKIP_INTRO", "1".into());
    }
    if s.movies {
        for (k, v) in [("PS3RECOMP_FFMPEG_AVCODEC", &s.ffmpeg_avcodec), ("PS3RECOMP_FFMPEG_AVUTIL", &s.ffmpeg_avutil)] {
            if !v.trim().is_empty() {
                set(k, v.trim().to_string());
            }
        }
    }
    let lang = s.game_lang.trim();
    if !lang.is_empty() && lang.len() <= 8 && lang.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
        set("PS3_LANG", lang.to_string());
    }
    if s.aa == "fxaa" || (s.aa == "smaa" && features.contains("smaa")) {
        set("PS3_AA", s.aa.clone());
    }
    if s.sharpen >= 0.005 {
        set("PS3_SHARPEN", format!("{:.2}", s.sharpen.min(1.0)));
    }
    if s.aniso > 1 {
        set("PS3_ANISO", s.aniso.min(16).to_string());
    }
    if s.gamma_override {
        set("PS3_DISPLAY_GAMMA", format!("{:.2}", s.gamma.clamp(0.5, 1.5)));
    }
    // the present pass's filters: only what differs from the game's picture
    if s.vibrance.abs() >= 0.005 {
        set("PS3_VIBRANCE", format!("{:.2}", s.vibrance.clamp(-1.0, 1.0)));
    }
    if (s.contrast - 1.0).abs() >= 0.005 && s.contrast > 0.0 {
        set("PS3_CONTRAST", format!("{:.2}", s.contrast.clamp(0.5, 1.5)));
    }
    if s.vignette >= 0.005 {
        set("PS3_VIGNETTE", format!("{:.2}", s.vignette.min(1.0)));
    }
    if s.grain >= 0.005 {
        set("PS3_GRAIN", format!("{:.2}", s.grain.min(1.0)));
    }
    let lut = s.lut_path.trim();
    let preset = valid_lut_preset(&s.lut_preset);
    if !lut.is_empty() {
        set("PS3_LUT", lut.to_string());
    }
    if let Some(p) = preset {
        set("PS3_LUT_PRESET", p.into());
    }
    if (preset.is_some() || !lut.is_empty()) && s.lut_strength < 0.995 {
        set("PS3_LUT_STRENGTH", format!("{:.2}", s.lut_strength.clamp(0.0, 1.0)));
    }
    // the internal resolution and how it reaches the window
    if let Some(k) = res_scale_value(&s.res_scale) {
        set("PS3_RES_SCALE", k);
    }
    if s.upscale == "metalfx" {
        set("PS3_UPSCALE", "metalfx".into());
    }
    // the window (its size is DES_SIZE above, mac/play.sh's --size)
    if matches!(s.window_mode.as_str(), "fullscreen" | "borderless") {
        set("PS3_WINDOW_MODE", s.window_mode.clone());
    }
    let display = s.display.trim();
    if !display.is_empty() && !display.contains(['\n', '\r']) {
        set("PS3_DISPLAY", display.to_string());
    }
    if !s.vsync {
        set("PS3_VSYNC", "0".into());
    }
    // play.sh sets no PS3_VFS_ROOT, so the runtime's "game" would not find the icon: the file
    if s.game_window_icon {
        if let Some(icon) = port.map(|p| game_root(p).join("PS3_GAME/ICON0.PNG")).filter(|p| p.is_file()) {
            set("PS3_WINDOW_ICON", self::s(&icon));
        }
    }
    // texture packs: the folder and the enabled ones, first wins; the dump
    if let Some(list) = mods::env_list(&s.mods) {
        set("PS3_MODS_DIR", self::s(&mods_dir()));
        set("PS3_MODS", list);
    }
    if s.mods_dump {
        set("PS3_MODS_DUMP", self::s(&mods_dump_dir()));
    }
    // Input: the controls file, then the mouse and rumble settings. The variables win over the
    // file's [mouse]; when the file the game reads has one, every mouse setting is passed so the
    // launcher's stand.
    if let Some(p) = &input.path {
        set("PS3_INPUT_MAP", p.clone());
    }
    if matches!(s.input_mode.as_str(), "controller" | "keyboard") {
        set("PS3_INPUT_MODE", s.input_mode.clone());
    }
    let all = input.has_mouse_section;
    if !s.mouse {
        set("PS3_MOUSE", "0".into());
    } else {
        if all {
            set("PS3_MOUSE", "1".into());
        }
        if all || (s.mouse_sens - 1.0).abs() > 1e-3 {
            set("PS3_MOUSE_SENS", format!("{:.2}", s.mouse_sens.clamp(0.05, 10.0)));
        }
        if all || s.mouse_invert_y {
            set("PS3_MOUSE_INVERT_Y", if s.mouse_invert_y { "1" } else { "0" }.into());
        }
        if all || s.mouse_invert_x {
            set("PS3_MOUSE_INVERT_X", if s.mouse_invert_x { "1" } else { "0" }.into());
        }
        if all || s.mouse_deadzone != 30 {
            set("PS3_MOUSE_DEADZONE", s.mouse_deadzone.min(120).to_string());
        }
        if all || !s.mouse_capture {
            set("PS3_MOUSE_CAPTURE", if s.mouse_capture { "1" } else { "0" }.into());
        }
    }
    if !s.rumble {
        set("PS3_RUMBLE", "0".into());
    } else if s.rumble_strength != 100 {
        set("PS3_RUMBLE_STRENGTH", s.rumble_strength.min(200).to_string());
    }
    // any value turns these on, so they are passed only when on
    if s.audio_mute {
        set("AUDIO_MUTE", "1".into());
    }
    if s.show_fps {
        set("PS3RECOMP_METAL_FPS", "1".into()); // exactly "1"
    }
    if s.pad_log {
        set("PS3_PAD_LOG", "1".into());
    }
    if s.stall_sample_ms > 0 {
        set("PS3_STALL_SAMPLE", s.stall_sample_ms.clamp(50, 10_000).to_string());
    }
    env.extend(parse_env_lines(&s.extra_env));
    env
}

/// The program and arguments: [caffeinate -i] /bin/sh mac/play.sh.
fn launch_argv(s: &Settings, b: &Builds) -> Result<Vec<String>, String> {
    let play = b.play_sh.clone().ok_or_else(|| format!("{PLAY_SH} is missing in {}", b.root))?;
    let mut argv = Vec::new();
    if s.keep_awake && Path::new("/usr/bin/caffeinate").is_file() {
        argv.extend(["/usr/bin/caffeinate".to_string(), "-i".to_string()]);
    }
    argv.extend(["/bin/sh".to_string(), play]);
    Ok(argv)
}

/// The equivalent command line, shown in Advanced > Environment.
#[tauri::command]
fn launch_preview(state: State<'_, AppState>, settings: Settings) -> Result<String, String> {
    let root = port_root(&settings).ok_or("no port folder yet (Advanced > Install / rebuild)")?;
    let b = resolve_builds(&root);
    let features = feature_set(&b, &state.features);
    let env = launch_env(&settings, Some(&root), &input_env(Some(&root)), &features);
    let mut out = vec![format!("cd {} &&", shell_quote(&s(&root)))];
    out.extend(env.into_iter().map(|(k, v)| format!("{k}={}", shell_quote(&v))));
    out.extend(launch_argv(&settings, &b).unwrap_or_else(|e| vec![format!("# {e}")]).iter().map(|a| shell_quote(a)));
    Ok(out.join(" "))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayStarted {
    log: String,
    backup: Option<String>,
    backup_error: Option<String>,
    report: Option<String>,
}

/// Start the game. `diagnostic`: debug mode (report.rs), with its log and dumps in a new report
/// folder. A refusal is also written to stderr.
#[tauri::command]
fn play(app: AppHandle, state: State<'_, AppState>, diagnostic: Option<bool>) -> Result<PlayStarted, String> {
    let r = start_game(app, state, diagnostic);
    match &r {
        Ok(p) => eprintln!("[launcher] Play: started, log {}", p.log),
        Err(e) => eprintln!("[launcher] Play refused: {e}"),
    }
    r
}

fn start_game(app: AppHandle, state: State<'_, AppState>, diagnostic: Option<bool>) -> Result<PlayStarted, String> {
    require_supported_host()?;
    let mut slot = state.game.lock().unwrap();
    if slot.is_some() {
        return Err("the game is already running".into());
    }
    // one game at a time, on this Mac: a terminal or another session may own it
    if process_running(GAME_EXE) {
        return Err("other-running".into());
    }
    if state.rebuild.lock().unwrap().is_some() {
        return Err("an install or a rebuild is running".into());
    }
    let s = load_settings_file();
    let root = port_root(&s).ok_or("no port folder: pick it in Advanced > Install / rebuild")?;
    let b = resolve_builds(&root);
    if !b.ok {
        return Err(format!("missing in {}: {}", b.root, b.missing.join(", ")));
    }
    let g = game_info(Some(&root));
    if g.root.is_some() && !g.ours {
        return Err(format!("{}: not {TITLE_ID} ({})", game_root(&root).display(), g.title_id));
    }
    let data = data_root();
    fs::create_dir_all(&data).map_err(|e| format!("{}: {e}", data.display()))?;
    let features = feature_set(&b, &state.features);
    let report_dir = if diagnostic.unwrap_or(false) { Some(report::create(&reports_dir(), &saves::stamp(now_secs()))?) } else { None };
    // play.sh writes the game's log into logs/ (a debug session: its own folder)
    let log_dir = report_dir.clone().unwrap_or_else(|| extra_var(&s, "DES_LOG_DIR").filter(|v| !v.is_empty()).map(PathBuf::from).unwrap_or_else(|| logs_dir(&root)));
    let log_path = log_dir.join(GAME_LOG);
    let out = fs::File::create(data.join(PLAY_LOG)).map_err(|e| format!("{}: {e}", data.join(PLAY_LOG).display()))?;
    let out2 = out.try_clone().map_err(|e| e.to_string())?;

    // the saves as they are now, before the game can touch them
    let (backup, backup_error) = match locations(&s).and_then(|l| saves::backup_before_play(&l, s.save_backups_keep, now_secs())) {
        Ok(b) => (b.map(|b| b.id), None),
        Err(e) => (None, Some(e)),
    };

    let argv = launch_argv(&s, &b)?;
    let mut env = launch_env(&s, Some(&root), &input_env(Some(&root)), &features);
    if let Some(d) = &report_dir {
        // after the extra variables: the report's paths win
        env.extend(report::env(d, features.contains("RSX_ENGINE_PASS_DUMP_TRIGGER")));
        env.push(("DES_LOG_DIR".into(), self::s(d)));
    }
    let mut cmd = Command::new(&argv[0]);
    cmd.args(&argv[1..])
        .current_dir(&root)
        .env("PATH", tool_path())
        .env_remove("PS3RECOMP_METAL_HEADLESS")
        .env_remove("PS3RECOMP_HOST_SURFACES")
        .env_remove("PS3RECOMP_WINDOW_STATE")
        .env_remove("PS3_ARGV")
        .stdin(Stdio::null())
        .stdout(out)
        .stderr(out2);
    for (k, v) in &env {
        cmd.env(k, v);
    }
    own_process_group(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| format!("{}: {e}", argv[0]))?;
    *slot = Some(child.id());
    drop(slot);
    *state.last_log.lock().unwrap() = Some(log_path.clone());
    let started = now_secs();
    if let Some(d) = &report_dir {
        *state.report.lock().unwrap() = Some((d.clone(), true));
        session_event(d, "start", &format!("pid={}", child.id()));
        let (d2, b2, root2, now) = (d.clone(), b.clone(), root.clone(), started);
        let env2 = env.clone();
        let argv2 = argv.clone();
        thread::spawn(move || {
            let _ = fs::write(d2.join(report::SYSTEM), system_info(&b2, &root2, &env2, &argv2, now));
        });
        spawn_ticker(app.clone(), d.clone());
    }
    let a = app.clone();
    let session = report_dir.clone();
    thread::spawn(move || {
        let status = child.wait();
        let code = status.as_ref().ok().and_then(|s| s.code()).unwrap_or(-1);
        let st = a.state::<AppState>();
        *st.game.lock().unwrap() = None;
        if let Some((_, live)) = st.report.lock().unwrap().as_mut() {
            *live = false;
        }
        let _ = a.emit("game-exit", code);
        let debug = session.is_some();
        if let Some(d) = session {
            // play.sh's own lines (a refusal) next to the game's
            let _ = fs::copy(data_root().join(PLAY_LOG), d.join(PLAY_LOG));
            session_exit(&d, status.ok(), started);
            let _ = a.emit("report-changed", ());
        }
        if code == 0 && !debug && *st.exit_with_game.lock().unwrap() {
            a.exit(0);
        }
    });
    Ok(PlayStarted { log: self::s(&log_path), backup, backup_error, report: report_dir.map(|d| self::s(&d)) })
}

/// Stop: SIGTERM to the process group Play started (play.sh, the window host and the game); if
/// that group is still there 8 s later it gets SIGKILL. Only this launcher's own group, by its pid,
/// never by name.
#[tauri::command]
fn stop_game(app: AppHandle, state: State<'_, AppState>) {
    if let Some(pid) = *state.game.lock().unwrap() {
        if let Some((d, true)) = state.report.lock().unwrap().clone() {
            session_event(&d, "stop", "");
        }
        kill_tree(pid, false);
        thread::spawn(move || {
            thread::sleep(std::time::Duration::from_secs(8));
            if *app.state::<AppState>().game.lock().unwrap() == Some(pid) {
                kill_tree(pid, true);
            }
        });
    }
}

// ---------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    builds: Option<Builds>,
    game: GameInfo,
    icon: Option<String>,
    background: Option<String>,
    last_save: Option<SaveInfo>,
    saves_dir: Option<String>,
    game_running: bool,
    /// A DemonsSoulsRecomp this launcher did not start (a terminal, another session).
    other_game_running: bool,
    rebuild_running: bool,
    data_root: String,
    host_supported: bool,
    os: String,
    app_bundle: Option<String>,
    finder_icon: bool,
    version: String,
    /// FEATURE_MARKERS found in the build.
    features: Vec<String>,
    /// libavcodec for the movies, as play.sh would find it.
    ffmpeg: Option<String>,
}

#[tauri::command]
async fn get_status(app: AppHandle, state: State<'_, AppState>) -> Result<Status, String> {
    let s = load_settings_file();
    let game_running = state.game.lock().unwrap().is_some();
    let rebuild_running = state.rebuild.lock().unwrap().is_some();
    let app2 = app.clone();
    let st = tauri::async_runtime::spawn_blocking(move || {
        let root = port_root(&s);
        let builds = root.as_deref().map(resolve_builds);
        let features = builds.as_ref().map(|b| build_features(b, &app2.state::<AppState>().features)).unwrap_or_default();
        let (icon, pic1) = game_art(root.as_deref());
        sync_app_icon(&app2);
        let bundle = app_icon::app_bundle().filter(|_| cfg!(target_os = "macos"));
        let orun = !game_running && process_running(GAME_EXE);
        Status {
            builds,
            game: game_info(root.as_deref()),
            icon: icon.and_then(|p| data_url(&p, "image/png")),
            background: pic1.and_then(|p| data_url(&p, "image/png")),
            last_save: last_save(&s),
            saves_dir: locations(&s).ok().map(|l| self::s(&l.port_savedata)),
            game_running,
            other_game_running: orun,
            rebuild_running,
            data_root: self::s(&data_root()),
            host_supported: host_supported(),
            os: std::env::consts::OS.into(),
            finder_icon: bundle.as_deref().is_some_and(app_icon::has_finder_icon),
            app_bundle: bundle.map(|b| self::s(&b)),
            version: env!("CARGO_PKG_VERSION").into(),
            features,
            ffmpeg: ffmpeg_found(&s).map(|p| self::s(&p)),
        }
    })
    .await
    .map_err(|e| e.to_string())?;
    Ok(st)
}

// ---------------------------------------------------------------------------
// What the build supports
// ---------------------------------------------------------------------------

/// Names whose presence in the game's executable (as a NUL-terminated string) says that it has
/// what a control drives. A control whose name is missing says it is unavailable, and
/// `launch_env` does not pass a variable nothing reads. (mac/play.sh's own DES_FPS, DES_MOVIES,
/// DES_NAME, DES_SIZE and DES_LOG are always passed.)
const FEATURE_MARKERS: &[&str] = &[
    "PS3_LANG",
    "PS3_AA",
    "PS3_SHARPEN",
    "PS3_ANISO",
    "PS3_DISPLAY_GAMMA",
    "PS3_VIBRANCE",
    "PS3_CONTRAST",
    "PS3_VIGNETTE",
    "PS3_GRAIN",
    "PS3_LUT",
    "PS3_LUT_STRENGTH",
    "PS3_LUT_PRESET",
    "PS3_RES_SCALE",
    "PS3_UPSCALE",
    "PS3_WINDOW_MODE",
    "PS3_DISPLAY",
    "PS3_VSYNC",
    "PS3_WINDOW_ICON",
    "PS3_MODS",
    "PS3_MODS_DIR",
    "PS3_MODS_DUMP",
    // the value PS3_AA compares against when the build has SMAA
    "smaa",
    "PS3_INPUT_MAP",
    "PS3_INPUT_MODE",
    "PS3_MOUSE",
    "PS3_MOUSE_SENS",
    "PS3_MOUSE_INVERT_X",
    "PS3_MOUSE_INVERT_Y",
    "PS3_MOUSE_DEADZONE",
    "PS3_MOUSE_CAPTURE",
    "PS3_RUMBLE",
    "PS3_RUMBLE_STRENGTH",
    "PS3_PAD_LOG",
    "PS3_STALL_SAMPLE",
    "PS3RECOMP_METAL_FPS",
    "PS3_VERBOSE",
    "AUDIO_MUTE",
    "PS3RECOMP_FFMPEG_AVCODEC",
    "PS3RECOMP_FFMPEG_AVUTIL",
    "PS3RECOMP_METAL_FRAME_DUMP",
    "RSX_ENGINE_PASS_DUMP_TRIGGER",
    "LV2_ERRDBG",
    "OSK_TEXT",
    // the port's own (patches/lifted-code.patch)
    "DES_SKIP_INTRO",
    "DES_60FPS",
];

type Features = BTreeSet<String>;

/// The markers found in `data`: a marker counts as a whole word right before a NUL, the end of a C
/// string. One pass over the bytes: the executable is about 280 MB, and a search per marker would
/// take many seconds.
fn markers_in(data: &[u8], found: &mut Features) {
    const MAX: usize = 40;
    let tails: std::collections::HashSet<[u8; 4]> =
        FEATURE_MARKERS.iter().map(|m| { let b = m.as_bytes(); [b[b.len() - 4], b[b.len() - 3], b[b.len() - 2], b[b.len() - 1]] }).collect();
    for i in 4..data.len() {
        if data[i] != 0 || !(data[i - 1].is_ascii_alphanumeric() || data[i - 1] == b'_') {
            continue;
        }
        let tail = [data[i - 4], data[i - 3], data[i - 2], data[i - 1]];
        if !tails.contains(&tail) {
            continue;
        }
        let word = &data[i.saturating_sub(MAX)..i];
        for m in FEATURE_MARKERS {
            if word.ends_with(m.as_bytes()) {
                // the whole word, not a longer name that ends the same way
                let before = i.checked_sub(m.len() + 1).map(|j| data[j]);
                if before.is_none_or(|c| !(c.is_ascii_alphanumeric() || c == b'_')) {
                    found.insert((*m).to_string());
                }
            }
        }
    }
}

/// `markers_in` over a file, read in pieces with an overlap for a name that falls across two.
fn scan_markers(path: &Path) -> Features {
    let mut found = Features::new();
    let Ok(mut f) = fs::File::open(path) else { return found };
    let mut buf = vec![0u8; 8 << 20];
    let mut keep = 0;
    loop {
        let n = match f.read(&mut buf[keep..]) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        let have = keep + n;
        markers_in(&buf[..have], &mut found);
        keep = have.min(64);
        buf.copy_within(have - keep..have, 0);
    }
    found
}

type FeatureCache = BTreeMap<String, (u64, u64, Vec<String>)>;

/// The markers in the game's executable, cached by path, size and mtime, in memory and in
/// `<data>/build-features.json` (a scan reads the whole file).
fn build_features(b: &Builds, cache: &Mutex<FeatureCache>) -> Vec<String> {
    build_features_in(b, cache, &data_root().join("build-features.json"))
}

fn build_features_in(b: &Builds, cache: &Mutex<FeatureCache>, file: &Path) -> Vec<String> {
    let Some(p) = &b.eboot else { return Vec::new() };
    let meta = fs::metadata(p).ok();
    let key = (meta.as_ref().map_or(0, |m| m.len()), meta.as_ref().map_or(0, mtime_of));
    if let Some(c) = cache.lock().unwrap().get(p).filter(|c| (c.0, c.1) == key) {
        return c.2.clone();
    }
    let mut disk: FeatureCache = fs::read_to_string(file).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
    let v = match disk.get(p).filter(|c| (c.0, c.1) == key) {
        Some(c) => c.2.clone(),
        None => {
            let v: Vec<String> = scan_markers(Path::new(p)).into_iter().collect();
            disk.insert(p.clone(), (key.0, key.1, v.clone()));
            if let Some(d) = file.parent() {
                let _ = fs::create_dir_all(d);
            }
            let _ = serde_json::to_string(&disk).map(|t| fs::write(file, t));
            v
        }
    };
    cache.lock().unwrap().insert(p.clone(), (key.0, key.1, v.clone()));
    v
}

fn feature_set(b: &Builds, cache: &Mutex<FeatureCache>) -> Features {
    build_features(b, cache).into_iter().collect()
}

fn mtime_of(m: &fs::Metadata) -> u64 {
    m.modified().ok().and_then(|t| t.duration_since(UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0)
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

/// The controls for the Controls page: what the file the game reads binds (the page fills in the
/// runtime's defaults for the rest), where the launcher's copy is, and the port's own layout.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InputMapView {
    path: String,
    exists: bool,
    /// mac/input.toml, which applies while the launcher has no file of its own.
    base: Option<String>,
    bindings: Bindings,
}

#[tauri::command]
fn get_input_map() -> InputMapView {
    let p = input_map_path();
    let base = base_input_map(port_root(&load_settings_file()).as_deref());
    let own = fs::read_to_string(&p);
    let exists = own.is_ok();
    let text = own.ok().or_else(|| base.as_deref().and_then(|b| fs::read_to_string(b).ok()));
    InputMapView { path: s(&p), exists, base: base.map(|b| s(&b)), bindings: text.map(|t| input_map::parse(&t).bindings).unwrap_or_default() }
}

/// Write the bindings into `path`; the file's other sections ([mouse], anything newer) stay as
/// they were, and a first save takes them from `base` (mac/input.toml).
fn write_input_map(path: &Path, base: Option<&Path>, bindings: Bindings) -> Result<(), String> {
    input_map::validate(&bindings)?;
    let mut file = fs::read_to_string(path).or_else(|_| base.map(fs::read_to_string).unwrap_or(Ok(String::new()))).map(|t| input_map::parse(&t)).unwrap_or_default();
    file.bindings = bindings;
    if let Some(d) = path.parent() {
        fs::create_dir_all(d).map_err(|e| e.to_string())?;
    }
    let tmp = path.with_extension("toml.tmp");
    fs::write(&tmp, input_map::render(&file)).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_input_map(bindings: Bindings) -> Result<String, String> {
    let p = input_map_path();
    let base = base_input_map(port_root(&load_settings_file()).as_deref());
    write_input_map(&p, base.as_deref(), bindings)?;
    Ok(s(&p))
}

/// "Restore defaults": the launcher's file goes (kept as input.toml.bak), so Play passes no
/// PS3_INPUT_MAP again and play.sh uses mac/input.toml.
#[tauri::command]
fn reset_input_map() -> Result<(), String> {
    let p = input_map_path();
    if p.is_file() {
        fs::rename(&p, p.with_extension("toml.bak")).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// The names in the JSON array the screen probe prints.
fn parse_screens(json: &str) -> Vec<String> {
    serde_json::from_str::<Vec<String>>(json.trim()).unwrap_or_default()
}

/// The screens in the system's order (NSScreen.screens: the first has the menu bar), by the names
/// PS3_DISPLAY matches.
#[tauri::command]
async fn list_screens() -> Vec<String> {
    if !cfg!(target_os = "macos") {
        return Vec::new();
    }
    tauri::async_runtime::spawn_blocking(|| {
        command_stdout(Command::new("/usr/bin/osascript").args([
            "-l",
            "JavaScript",
            "-e",
            "ObjC.import('AppKit'); JSON.stringify($.NSScreen.screens.js.map(s => s.localizedName.js))",
        ]))
        .map(|s| parse_screens(&s))
        .unwrap_or_default()
    })
    .await
    .unwrap_or_default()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ModsView {
    dir: String,
    dump_dir: String,
    packs: Vec<mods::ModPack>,
}

/// The texture packs in <data>/mods (the folder is created, so "Open the mods folder" always has
/// somewhere to go).
#[tauri::command]
fn list_mods() -> ModsView {
    let dir = mods_dir();
    ModsView { packs: mods::list(&dir), dir: s(&dir), dump_dir: s(&mods_dump_dir()) }
}

#[tauri::command]
fn get_settings() -> Settings {
    load_settings_file()
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: Settings) -> Result<(), String> {
    write_settings(&settings)?;
    sync_app_icon(&app);
    Ok(())
}

#[tauri::command]
async fn find_port_dirs() -> Vec<Builds> {
    tauri::async_runtime::spawn_blocking(find_port_dirs_now).await.unwrap_or_default()
}

#[tauri::command]
fn builds_at(path: String) -> Builds {
    resolve_builds(Path::new(path.trim()))
}

#[tauri::command]
async fn game_status() -> GameInfo {
    tauri::async_runtime::spawn_blocking(|| game_info(port_root(&load_settings_file()).as_deref())).await.unwrap_or_default()
}

// ---------------------------------------------------------------------------
// The Dock and Finder icons from the player's game files (app_icon.rs)
// ---------------------------------------------------------------------------

fn app_icon_cache() -> PathBuf {
    data_root().join(app_icon::CACHE_NAME)
}

fn composed_icon(s: &Settings) -> Option<PathBuf> {
    if !s.game_icon {
        return None;
    }
    app_icon::refresh(&app_icon_cache(), game_art_of(s).0.as_deref())
}

fn sync_app_icon(app: &AppHandle) {
    if !cfg!(target_os = "macos") {
        return;
    }
    let app = app.clone();
    thread::spawn(move || {
        let icon = composed_icon(&load_settings_file());
        let key = app_icon::key(icon.as_deref());
        let state = app.state::<AppState>();
        let mut cur = state.dock_icon.lock().unwrap();
        if *cur != key {
            *cur = key;
            app_icon::apply_dock_icon(&app, icon);
        }
    });
}

#[tauri::command]
async fn finder_icon(app: AppHandle, set: bool) -> Result<bool, String> {
    if !cfg!(target_os = "macos") {
        return Err("the Finder icon is macOS only".into());
    }
    let bundle = app_icon::app_bundle().ok_or("the launcher is not running from an .app (development build)")?;
    let icon = if set {
        let st = load_settings_file();
        Some(app_icon::refresh(&app_icon_cache(), game_art_of(&st).0.as_deref()).ok_or("no ICON0.PNG in your game files yet")?)
    } else {
        None
    };
    let (tx, rx) = std::sync::mpsc::channel();
    let b = bundle.clone();
    app.run_on_main_thread(move || {
        let _ = tx.send(app_icon::set_finder_icon(&b, icon.as_deref()));
    })
    .map_err(|e| e.to_string())?;
    rx.recv().map_err(|e| e.to_string())??;
    Ok(app_icon::has_finder_icon(&bundle))
}

#[tauri::command]
fn take_play_request(state: State<'_, AppState>) -> bool {
    let asked = std::mem::take(&mut *state.play_request.lock().unwrap());
    if asked {
        eprintln!("[launcher] --play: starting the game once the window is ready");
    }
    asked
}

/// The window's uncaught errors, on the launcher's stderr (development).
#[tauri::command]
fn frontend_log(message: String) {
    eprintln!("[launcher window] {}", message.chars().take(2000).collect::<String>());
}

#[tauri::command]
fn take_start_view(state: State<'_, AppState>) -> Option<String> {
    state.start_view.lock().unwrap().take()
}

/// Home > Status > "Play shortcut on the Desktop" (play_shortcut.rs).
#[tauri::command]
async fn create_play_shortcut(app: AppHandle) -> Result<String, String> {
    if !cfg!(target_os = "macos") {
        return Err("the Play shortcut is macOS only".into());
    }
    let bundle = app_icon::app_bundle().ok_or("the launcher is not running from an .app (development build)")?;
    let icns = play_shortcut::bundle_icns(&bundle);
    let path = play_shortcut::write(&home().join("Desktop"), &app.config().identifier, icns.as_deref())?;
    if let Some(icon) = composed_icon(&load_settings_file()) {
        let (tx, rx) = std::sync::mpsc::channel();
        let p = path.clone();
        app.run_on_main_thread(move || {
            let _ = tx.send(app_icon::set_finder_icon(&p, Some(&icon)));
        })
        .map_err(|e| e.to_string())?;
        if let Ok(Err(e)) = rx.recv() {
            eprintln!("[launcher] Play shortcut icon: {e}");
        }
    }
    Ok(s(&path))
}

// ---------------------------------------------------------------------------
// Add to Steam (steam.rs, steam_art.rs)
// ---------------------------------------------------------------------------

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SteamStatus {
    available: bool,
    installed: bool,
    running: bool,
    users: usize,
    added: usize,
}

fn steam_dir() -> PathBuf {
    data_root().join("steam")
}

fn steam_target() -> steam::Target {
    steam::Target::new(&play_shortcut::executable(&steam_dir().join(play_shortcut::NAME)))
}

fn steam_available() -> bool {
    cfg!(target_os = "macos") && app_icon::app_bundle().is_some()
}

fn steam_art(st: &Settings) -> Option<steam::Art> {
    let (icon0, pic1) = game_art_of(st);
    let icon0 = app_icon::decode_png(&fs::read(icon0?).ok()?).ok()?;
    let pic1 = pic1.and_then(|p| fs::read(p).ok()).and_then(|b| app_icon::decode_png(&b).ok());
    let imgs = steam_art::draw(&icon0, pic1.as_ref());
    let enc = |i: &app_icon::Rgba| app_icon::encode_png(i).ok();
    Some([enc(&imgs.portrait)?, enc(&imgs.landscape)?, enc(&imgs.hero)?, enc(&imgs.icon)?])
}

#[tauri::command]
async fn steam_status() -> SteamStatus {
    tauri::async_runtime::spawn_blocking(|| {
        let users = steam::users(&steam::root(&home()));
        let t = steam_target();
        SteamStatus {
            available: steam_available(),
            installed: !users.is_empty(),
            running: steam::running(),
            users: users.len(),
            added: users.iter().filter(|u| steam::user_has(u, &t)).count(),
        }
    })
    .await
    .unwrap_or(SteamStatus { available: false, installed: false, running: false, users: 0, added: 0 })
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SteamAdded {
    users: usize,
    art: bool,
}

#[tauri::command]
async fn steam_add(app: AppHandle) -> Result<SteamAdded, String> {
    if !steam_available() {
        return Err("Add to Steam needs the packaged app on macOS".into());
    }
    let id = app.config().identifier.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let users = steam::users(&steam::root(&home()));
        if users.is_empty() {
            return Err("Steam is not installed here, or nobody has signed in to it yet".to_string());
        }
        if steam::running() {
            return Err("steam-running".to_string());
        }
        let icns = app_icon::app_bundle().and_then(|b| play_shortcut::bundle_icns(&b));
        fs::create_dir_all(steam_dir()).map_err(|e| e.to_string())?;
        play_shortcut::write_kind(&steam_dir(), &id, icns.as_deref(), play_shortcut::Kind::Steam)?;
        let art = steam_art(&load_settings_file());
        let t = steam_target();
        for u in &users {
            steam::add(u, &t, art.as_ref())?;
        }
        Ok(SteamAdded { users: users.len(), art: art.is_some() })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn steam_remove(app: AppHandle) -> Result<usize, String> {
    let id = app.config().identifier.clone();
    tauri::async_runtime::spawn_blocking(move || {
        if steam::running() {
            return Err("steam-running".to_string());
        }
        let t = steam_target();
        let mut n = 0;
        for u in &steam::users(&steam::root(&home())) {
            n += steam::remove(u, &t)? as usize;
        }
        let bundle = steam_dir().join(play_shortcut::NAME);
        if play_shortcut::is_ours(&bundle, &id, play_shortcut::Kind::Steam) {
            fs::remove_dir_all(&bundle).map_err(|e| format!("{}: {e}", bundle.display()))?;
        }
        Ok(n)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn steam_quit() -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(steam::quit).await.map_err(|e| e.to_string())?
}

// ---------------------------------------------------------------------------
// Requirements, the install and the rebuild
// ---------------------------------------------------------------------------

/// One line of Advanced > Install / rebuild > "What this computer needs". `level`: "ok", "warn",
/// "fail", "info" (not a problem, only to know) or "optional" (absent, and not needed). The window
/// shows `key` (an i18n key under `prereq.msg.`, with `vars`) and falls back to the English
/// `message`; `path` is shown on a line of its own; `optional` marks something only some features
/// need.
#[derive(Serialize, Clone, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct CheckItem {
    level: String,
    name: String,
    message: String,
    key: String,
    vars: BTreeMap<String, String>,
    path: Option<String>,
    optional: bool,
}

impl CheckItem {
    fn new(level: &str, name: &str, key: &str, message: impl Into<String>) -> Self {
        CheckItem { level: level.into(), name: name.into(), key: key.into(), message: message.into(), ..Default::default() }
    }
    /// A check whose detail is only a path.
    fn at(level: &str, name: &str, path: &Path) -> Self {
        CheckItem::new(level, name, "", s(path)).path(path)
    }
    fn var(mut self, k: &str, v: impl ToString) -> Self {
        self.vars.insert(k.into(), v.to_string());
        self
    }
    fn path(mut self, p: &Path) -> Self {
        self.path = Some(s(p));
        self
    }
    fn optional(mut self) -> Self {
        self.optional = true;
        self
    }
}

#[derive(Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Prereqs {
    supported: bool,
    clt: bool,
    checks: Vec<CheckItem>,
    ok: bool,
    builds_ok: bool,
    free_gb: Option<u64>,
    /// Homebrew is installed, and the formulas the build still needs.
    brew: bool,
    brew_missing: Vec<String>,
    /// The space an install asks for, and where it would go.
    need_gb: u64,
    install_dir: String,
    /// game/ is extracted there already (the disc image is not needed any more).
    extracted: bool,
    /// The sources are there already (no clone).
    sources: bool,
    sources_url: String,
}

fn free_gb(p: &Path) -> Option<u64> {
    let out = command_stdout(Command::new("/bin/df").arg("-k").arg(p))?;
    let kb: u64 = out.lines().nth(1)?.split_whitespace().nth(3)?.parse().ok()?;
    Some(kb / (1024 * 1024))
}

fn sources_url() -> String {
    std::env::var("DES_SOURCES_URL").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| SOURCES_URL.into())
}

fn sources_branch() -> String {
    std::env::var("DES_SOURCES_BRANCH").ok().filter(|v| !v.is_empty()).unwrap_or_else(|| SOURCES_BRANCH.into())
}

/// The nearest folder that exists, for `df`.
fn existing_parent(p: &Path) -> PathBuf {
    let mut at = p.to_path_buf();
    while !at.exists() {
        match at.parent() {
            Some(up) => at = up.to_path_buf(),
            None => return home(),
        }
    }
    at
}

#[tauri::command]
async fn check_prereqs() -> Prereqs {
    tauri::async_runtime::spawn_blocking(|| {
        let st = load_settings_file();
        let mut p = Prereqs { supported: host_supported(), clt: clt_installed(), ..Default::default() };
        let mut add = |c: CheckItem| p.checks.push(c);
        if !p.supported {
            return p;
        }
        let root = port_root(&st);
        let b = root.as_deref().map(resolve_builds);
        add(if p.clt {
            CheckItem::new("ok", "xcode-clt", "cltOk", "installed")
        } else {
            CheckItem::new("fail", "xcode-clt", "cltMissing", "not installed (Apple's installer: the compiler and git)")
        });
        let missing = install::brew_missing(&brew_prefix());
        p.brew = find_brew().is_some();
        for (formula, _) in install::BREW_NEEDS {
            let name = formula.trim_end_matches("@3.12");
            add(if !missing.contains(formula) {
                CheckItem::new("ok", name, "brewOk", "installed (Homebrew)")
            } else {
                CheckItem::new("warn", name, "brewMissing", format!("missing: brew install {formula}")).var("cmd", format!("brew install {formula}"))
            });
        }
        p.brew_missing = missing.iter().map(|m| m.to_string()).collect();
        p.need_gb = install::NEED_GB;
        let target = install_target(&st);
        p.install_dir = s(&target);
        p.sources = target.join(INSTALL_SH).is_file();
        p.sources_url = format!("{} ({})", sources_url(), sources_branch());
        p.extracted = game_root(&target).join(".extracted").is_file();
        if let Some(r) = &root {
            let g = game_info(Some(r));
            add(match (&g.root, g.ours, g.extracted) {
                (Some(d), true, true) => CheckItem::at("ok", "game", Path::new(d)),
                (Some(_), false, _) => CheckItem::new("fail", "game", "gameNotOurs", format!("game/ holds {}, not {TITLE_ID}", g.title_id)).var("id", &g.title_id),
                _ => CheckItem::new("warn", "game", "gameMissing", "no game files yet: Install the game extracts them from your disc image").path(&game_root(r)),
            });
            let py = r.join(".venv/bin/python");
            add(if py.is_file() { CheckItem::at("ok", "venv", &py) } else { CheckItem::new("warn", "venv", "venvMissing", "not made yet: the install makes it").path(&py) });
            let tk = r.join("deps/ps3recomp");
            add(if tk.join(".ds_patched").is_file() {
                CheckItem::at("ok", "toolkit", &tk)
            } else {
                CheckItem::new("warn", "toolkit", "toolkitMissing", "not set up yet: the install fetches it").path(&tk)
            });
        }
        let at = existing_parent(&target);
        p.free_gb = free_gb(&at);
        if let Some(gb) = p.free_gb {
            add(if gb >= install::NEED_GB || b.as_ref().is_some_and(|b| b.ok) {
                CheckItem::new("ok", "disk", "diskEnough", format!("{gb} GB free")).var("free", gb)
            } else {
                CheckItem::new("warn", "disk", "diskLow", format!("only {gb} GB free; an install needs about {} GB", install::NEED_GB)).var("free", gb).var("need", install::NEED_GB)
            });
        }
        if let Some(lib) = ffmpeg_found(&st) {
            add(CheckItem::at("ok", "movies", &lib).optional());
        } else {
            add(CheckItem::new("info", "movies", "ffmpegMissing", "no FFmpeg: the game runs without its movies (brew install ffmpeg)").optional());
        }
        match &b {
            Some(b) => {
                p.builds_ok = b.ok;
                add(if b.ok {
                    CheckItem::at("ok", "builds", Path::new(&b.root))
                } else {
                    CheckItem::new("warn", "builds", "buildsMissing", format!("missing: {}", b.missing.join(", "))).var("missing", b.missing.join(", "))
                });
            }
            None => add(CheckItem::new("warn", "builds", "noPort", "no port folder yet: Install the game makes one")),
        }
        p.ok = !p.checks.iter().any(|c| c.level == "fail");
        p
    })
    .await
    .unwrap_or_default()
}

/// Advanced > Install / rebuild: `brew install` what the build still needs. Only after the player
/// said yes in the window; streamed as setup-line / setup-exit.
#[tauri::command]
fn install_brew_deps(app: AppHandle, state: State<'_, AppState>) -> Result<Vec<String>, String> {
    let brew = find_brew().ok_or("Homebrew is not installed (brew.sh)")?;
    let missing = install::brew_missing(&brew_prefix());
    if missing.is_empty() {
        return Ok(Vec::new());
    }
    let mut slot = state.setup.lock().unwrap();
    if slot.is_some() {
        return Err("an install is already running".into());
    }
    let mut cmd = Command::new(&brew);
    cmd.arg("install")
        .args(&missing)
        .env("PATH", tool_path())
        .env("HOMEBREW_NO_AUTO_UPDATE", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    own_process_group(&mut cmd);
    let child = cmd.spawn().map_err(|e| format!("brew: {e}"))?;
    *slot = Some(child.id());
    drop(slot);
    let _ = app.emit("setup-line", format!("$ brew install {}", missing.join(" ")));
    stream_child(&app, child, "setup", |s| &s.setup);
    Ok(missing.iter().map(|m| m.to_string()).collect())
}

#[tauri::command]
fn cancel_setup(state: State<'_, AppState>) {
    if let Some(pid) = *state.setup.lock().unwrap() {
        kill_tree(pid, false);
    }
}

fn install_log() -> PathBuf {
    data_root().join("install.log")
}

/// Home > "Install the game": install.zsh (the sources, then mac/install.sh) with the player's
/// image, streamed as rebuild-line / rebuild-exit and kept in <data>/install.log. Pressing it again
/// continues where it stopped.
#[tauri::command]
fn start_install(app: AppHandle, state: State<'_, AppState>, inputs: install::Inputs) -> Result<String, String> {
    require_supported_host()?;
    if state.game.lock().unwrap().is_some() || process_running(GAME_EXE) {
        return Err("the game is running: close it first".into());
    }
    let mut slot = state.rebuild.lock().unwrap();
    if slot.is_some() {
        return Err("an install or a rebuild is already running".into());
    }
    if !clt_installed() {
        return Err("clt".into());
    }
    if !install::brew_missing(&brew_prefix()).is_empty() {
        return Err("brew".into());
    }
    let mut st = load_settings_file();
    let target = install_target(&st);
    let checked = install::check(&inputs, game_root(&target).join(".extracted").is_file())?;
    if let Some(gb) = free_gb(&existing_parent(&target)) {
        let done = resolve_builds(&target).ok;
        let need = if game_root(&target).join(".extracted").is_file() { install::NEED_GB.saturating_sub(8) } else { install::NEED_GB };
        if !done && gb < need {
            return Err(format!("disk:{gb}"));
        }
    }
    fs::create_dir_all(data_root()).map_err(|e| format!("{}: {e}", data_root().display()))?;
    st.install = inputs;
    write_settings(&st)?;
    let mut cmd = Command::new("/usr/bin/nice");
    cmd.args(["-n", "10", "/bin/zsh", "-c", install::SCRIPT])
        .current_dir(data_root())
        .env("PATH", tool_path())
        .env("TERM", "dumb")
        .env("GIT_TERMINAL_PROMPT", "0")
        // the scripts find their folders from DES_SRC
        .env_remove("DES_ROOT")
        .env_remove("DES_VENV")
        .env_remove("DES_BUILD")
        .env_remove("PY")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (k, v) in checked.env(&target, &sources_url(), &sources_branch()) {
        cmd.env(k, v);
    }
    if st.jobs > 0 {
        cmd.env("JOBS", st.jobs.to_string());
    }
    own_process_group(&mut cmd);
    let log = fs::File::create(install_log()).ok();
    let child = cmd.spawn().map_err(|e| format!("zsh: {e}"))?;
    *slot = Some(child.id());
    drop(slot);
    let first = format!("$ install   # into {}", target.display());
    if let Some(mut f) = log.as_ref().and_then(|f| f.try_clone().ok()) {
        use std::io::Write;
        let _ = writeln!(f, "{first}");
    }
    let _ = app.emit("rebuild-line", first);
    stream_child_logged(&app, child, "rebuild", |s| &s.rebuild, log);
    Ok(s(&target))
}

/// After a successful install: Play uses the folder it installed into.
#[tauri::command]
fn install_finished(state: State<'_, AppState>) -> Result<(), String> {
    if game_busy(&state) {
        return Err(BUSY.into());
    }
    let mut st = load_settings_file();
    let target = install_target(&st);
    if !resolve_builds(&target).ok {
        return Err(format!("{}: the build is not complete", target.display()));
    }
    st.port_dir = s(&target);
    write_settings(&st)
}

#[tauri::command]
fn install_clt() -> Result<(), String> {
    Command::new("xcode-select")
        .arg("--install")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("xcode-select: {e}"))
}

/// Stream a child's stdout and stderr to the window as `<event>-line`, and its exit code as
/// `<event>-exit`; `slot` holds its pid while it runs.
fn stream_child(app: &AppHandle, child: std::process::Child, event: &'static str, which: fn(&AppState) -> &Mutex<Option<u32>>) {
    stream_child_logged(app, child, event, which, None)
}

/// stream_child, each line also written to `log` (the install's log file).
fn stream_child_logged(app: &AppHandle, mut child: std::process::Child, event: &'static str, which: fn(&AppState) -> &Mutex<Option<u32>>, log: Option<fs::File>) {
    use std::io::Write;
    let log = std::sync::Arc::new(Mutex::new(log));
    let (stdout, stderr) = (child.stdout.take().unwrap(), child.stderr.take().unwrap());
    let (a1, l1) = (app.clone(), log.clone());
    let out = thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(f) = l1.lock().unwrap().as_mut() {
                let _ = writeln!(f, "{line}");
            }
            let _ = a1.emit(&format!("{event}-line"), line);
        }
    });
    let (a2, l2) = (app.clone(), log);
    let err = thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if let Some(f) = l2.lock().unwrap().as_mut() {
                let _ = writeln!(f, "{line}");
            }
            let _ = a2.emit(&format!("{event}-line"), line);
        }
    });
    let a3 = app.clone();
    thread::spawn(move || {
        let code = child.wait().map(|s| s.code().unwrap_or(-1)).unwrap_or(-1);
        // every line out before the exit
        let _ = (out.join(), err.join());
        *which(&a3.state::<AppState>()).lock().unwrap() = None;
        let _ = a3.emit(&format!("{event}-exit"), code);
    });
}

/// mac/rebuild.sh's steps the rebuild lets the player pick, in its order. deps and venv always
/// come first (both are quick once done).
const STEPS: &[&str] = &["decrypt", "toolkit", "lift", "build"];

/// The rebuild, as a zsh script run in the port folder.
fn rebuild_script(steps: &[String]) -> String {
    let want: Vec<&str> = STEPS.iter().copied().filter(|s| steps.is_empty() || steps.iter().any(|x| x == s)).collect();
    format!("set -e\nexec /bin/zsh {REBUILD_SH} deps venv {}\n", want.join(" "))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RebuildRequest {
    steps: Vec<String>,
    jobs: Option<u32>,
}

#[tauri::command]
fn start_rebuild(app: AppHandle, state: State<'_, AppState>, req: RebuildRequest) -> Result<(), String> {
    require_supported_host()?;
    if let Some(bad) = req.steps.iter().find(|s| !STEPS.contains(&s.as_str())) {
        return Err(format!("{bad}: not a step ({})", STEPS.join(" ")));
    }
    if state.game.lock().unwrap().is_some() || process_running(GAME_EXE) {
        return Err("the game is running: close it before rebuilding".into());
    }
    let mut slot = state.rebuild.lock().unwrap();
    if slot.is_some() {
        return Err("a rebuild is already running".into());
    }
    let st = load_settings_file();
    let root = port_root(&st).ok_or("no port folder")?;
    if !root.join(REBUILD_SH).is_file() {
        return Err(format!("{}: no {REBUILD_SH}", root.display()));
    }
    let mut cmd = Command::new("/usr/bin/nice");
    cmd.args(["-n", "10", "/bin/zsh", "-c", &rebuild_script(&req.steps)])
        .current_dir(&root)
        .env("PATH", tool_path())
        .env("TERM", "dumb")
        .env_remove("DES_ROOT")
        .env_remove("DES_BUILD")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(j) = req.jobs.filter(|j| *j > 0) {
        cmd.env("JOBS", j.to_string());
    }
    own_process_group(&mut cmd);
    let child = cmd.spawn().map_err(|e| format!("zsh: {e}"))?;
    *slot = Some(child.id());
    drop(slot);
    let shown = if req.steps.is_empty() { STEPS.join(" ") } else { req.steps.join(" ") };
    let _ = app.emit("rebuild-line", format!("$ cd {} && {REBUILD_SH} deps venv {shown}", root.display()));
    stream_child(&app, child, "rebuild", |s| &s.rebuild);
    Ok(())
}

#[tauri::command]
fn install_log_path() -> String {
    s(&install_log())
}

#[tauri::command]
fn cancel_rebuild(state: State<'_, AppState>) {
    if let Some(pid) = *state.rebuild.lock().unwrap() {
        kill_tree(pid, false);
    }
}

// ---------------------------------------------------------------------------
// Updates (update.rs)
// ---------------------------------------------------------------------------

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    sources: update::Sources,
    /// The newest commit touching the port is newer than the build.
    rebuild_needed: bool,
    built_at: u64,
    app: update::AppUpdate,
}

#[tauri::command]
async fn check_updates(online: bool) -> UpdateInfo {
    tauri::async_runtime::spawn_blocking(move || {
        let st = load_settings_file();
        let root = port_root(&st);
        let b = root.as_deref().map(resolve_builds);
        let sources = root.as_deref().map(|r| update::sources(r, online)).unwrap_or_default();
        let built_at = b.as_ref().map_or(0, |b| b.built_at);
        let rebuild_needed = built_at > 0 && sources.sources_time > built_at;
        let app = if online {
            update::check_app(env!("CARGO_PKG_VERSION"))
        } else {
            update::AppUpdate { current: env!("CARGO_PKG_VERSION").into(), ..Default::default() }
        };
        UpdateInfo { sources, rebuild_needed, built_at, app }
    })
    .await
    .unwrap_or(UpdateInfo { sources: Default::default(), rebuild_needed: false, built_at: 0, app: Default::default() })
}

/// "Get the new sources": git pull --ff-only in the port folder, streamed as rebuild-line /
/// rebuild-exit (the Install tab's log).
#[tauri::command]
fn pull_sources(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let mut slot = state.rebuild.lock().unwrap();
    if slot.is_some() {
        return Err("a rebuild is running".into());
    }
    let root = port_root(&load_settings_file()).ok_or("no port folder")?;
    let mut cmd = Command::new("git");
    cmd.arg("-C")
        .arg(&root)
        .args(["pull", "--ff-only"])
        .env("GIT_TERMINAL_PROMPT", "0")
        .env("PATH", tool_path())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    own_process_group(&mut cmd);
    let child = cmd.spawn().map_err(|e| format!("git: {e}"))?;
    *slot = Some(child.id());
    drop(slot);
    let _ = app.emit("rebuild-line", format!("$ git -C {} pull --ff-only", root.display()));
    stream_child(&app, child, "rebuild", |s| &s.rebuild);
    Ok(())
}

// ---------------------------------------------------------------------------
// Links, files, the log
// ---------------------------------------------------------------------------

const URL_ALLOWED: &[&str] = &[
    "https://brew.sh/",
    "https://github.com/erikomis/demons-souls-recomp",
    "https://github.com/timboat/demons-souls-recomp",
    "https://github.com/sp00nznet/ps3recomp",
    "http://redump.org/disc/16199/",
];

#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    if !URL_ALLOWED.iter().any(|p| url.starts_with(p)) || url.chars().any(|c| c.is_whitespace() || c == '"') {
        return Err(format!("{url}: not a link this app opens"));
    }
    Command::new("open").arg(&url).spawn().map(|_| ()).map_err(|e| e.to_string())
}

/// Show a folder or file in Finder (never opens an .app: that would run it).
#[tauri::command]
fn reveal(path: String) -> Result<(), String> {
    reveal_unix(PathBuf::from(&path))
}

/// What `open` gets for a reveal: the item and whether to select it in its folder (`-R`) rather
/// than open it. A path that does not exist is revealed as its nearest existing ancestor, under the
/// same rule, so a missing file inside an app bundle can never make `open` launch that bundle.
fn reveal_target(p: &Path) -> Result<(PathBuf, bool), String> {
    if !p.is_absolute() {
        return Err(format!("{}: not an absolute path", p.display()));
    }
    let mut at = p.to_path_buf();
    while !at.exists() {
        match at.parent() {
            Some(up) => at = up.to_path_buf(),
            None => return Err(format!("{}: nothing to show", p.display())),
        }
    }
    let open_folder = at.is_dir() && at.extension().is_none_or(|e| e != "app");
    Ok((at, !open_folder))
}

fn reveal_unix(p: PathBuf) -> Result<(), String> {
    let (target, select) = reveal_target(&p)?;
    let mut cmd = Command::new("open");
    if select {
        cmd.arg("-R");
    }
    cmd.arg(&target).spawn().map(|_| ()).map_err(|e| e.to_string())
}

fn game_log_path(state: &State<'_, AppState>) -> PathBuf {
    state.last_log.lock().unwrap().clone().unwrap_or_else(|| {
        let st = load_settings_file();
        port_root(&st).map(|r| logs_dir(&r).join(GAME_LOG)).unwrap_or_else(|| data_root().join(PLAY_LOG))
    })
}

fn tail_text(data: &[u8], cut: bool) -> String {
    let start = if cut { data.iter().position(|&b| b == b'\n').map_or(0, |i| i + 1) } else { 0 };
    String::from_utf8_lossy(&data[start..]).into_owned()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GameLog {
    path: String,
    exists: bool,
    size: u64,
    modified: u64,
    text: String,
    truncated: bool,
}

#[tauri::command]
fn read_game_log(state: State<'_, AppState>, max_bytes: Option<u64>) -> Result<GameLog, String> {
    let path = game_log_path(&state);
    let max = max_bytes.unwrap_or(512 * 1024).clamp(4 * 1024, 8 * 1024 * 1024);
    let mut out = GameLog { path: s(&path), exists: false, size: 0, modified: 0, text: String::new(), truncated: false };
    let Ok(mut f) = fs::File::open(&path) else { return Ok(out) };
    let meta = f.metadata().map_err(|e| e.to_string())?;
    out.exists = true;
    out.size = meta.len();
    out.modified = mtime(&path);
    out.truncated = meta.len() > max;
    if out.truncated {
        f.seek(SeekFrom::Start(meta.len() - max)).map_err(|e| e.to_string())?;
    }
    let mut buf = Vec::with_capacity(max.min(meta.len()) as usize);
    f.take(max).read_to_end(&mut buf).map_err(|e| e.to_string())?;
    out.text = tail_text(&buf, out.truncated);
    Ok(out)
}

#[tauri::command]
fn log_paths(state: State<'_, AppState>) -> BTreeMap<String, String> {
    let st = load_settings_file();
    let mut m = BTreeMap::new();
    let game = game_log_path(&state);
    if let Some(d) = game.parent() {
        m.insert("sessions".into(), s(d));
    }
    m.insert("game".into(), s(&game));
    if let Ok(l) = locations(&st) {
        m.insert("saves".into(), s(&l.port_savedata));
    }
    m.insert("data".into(), s(&data_root()));
    m.insert("play".into(), s(&data_root().join(PLAY_LOG)));
    m
}

// ---------------------------------------------------------------------------
// Shader cache
// ---------------------------------------------------------------------------

fn dir_usage(dir: &Path) -> (u64, u64) {
    let (mut bytes, mut files) = (0u64, 0u64);
    if let Ok(rd) = fs::read_dir(dir) {
        for e in rd.flatten() {
            match e.metadata() {
                Ok(m) if m.is_dir() => {
                    let (b, f) = dir_usage(&e.path());
                    bytes += b;
                    files += f;
                }
                Ok(m) => {
                    bytes += m.len();
                    files += 1;
                }
                Err(_) => {}
            }
        }
    }
    (bytes, files)
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShaderCacheInfo {
    path: Option<String>,
    bytes: u64,
    files: u64,
}

fn shader_cache_info_now() -> ShaderCacheInfo {
    match msl_cache_dir(&load_settings_file()) {
        Some(d) => {
            let (bytes, files) = dir_usage(&d);
            ShaderCacheInfo { path: Some(s(&d)), bytes, files }
        }
        None => ShaderCacheInfo { path: None, bytes: 0, files: 0 },
    }
}

#[tauri::command]
fn shader_cache_info() -> ShaderCacheInfo {
    shader_cache_info_now()
}

/// The translated shaders (PS3RECOMP_MSL_CACHE): made again as the game meets them.
#[tauri::command]
fn shader_cache_clear(state: State<'_, AppState>) -> Result<ShaderCacheInfo, String> {
    if state.game.lock().unwrap().is_some() || process_running(GAME_EXE) {
        return Err("the game is running: close it before clearing the shader cache".into());
    }
    if let Some(d) = msl_cache_dir(&load_settings_file()) {
        if d.exists() {
            fs::remove_dir_all(&d).map_err(|e| format!("{}: {e}", d.display()))?;
        }
    }
    Ok(shader_cache_info_now())
}

// ---------------------------------------------------------------------------
// Debug mode (report.rs)
// ---------------------------------------------------------------------------

fn session_event(dir: &Path, kind: &str, detail: &str) {
    let ms = now_ms();
    let _ = report::event(dir, ms, &utc_text(ms / 1000), kind, detail);
}

fn spawn_ticker(app: AppHandle, dir: PathBuf) {
    thread::spawn(move || loop {
        thread::sleep(std::time::Duration::from_secs(2));
        let live = matches!(app.state::<AppState>().report.lock().unwrap().as_ref(), Some((d, true)) if *d == dir);
        if !live {
            break;
        }
        session_event(&dir, "tick", "");
    });
}

fn session_exit(dir: &Path, status: Option<std::process::ExitStatus>, started: u64) {
    #[cfg(unix)]
    let signal = {
        use std::os::unix::process::ExitStatusExt;
        status.and_then(|s| s.signal())
    };
    #[cfg(not(unix))]
    let signal: Option<i32> = None;
    let code = status.and_then(|s| s.code());
    let detail = match (code, signal) {
        (Some(c), _) => format!("code={c}"),
        (None, Some(sig)) => format!("signal={sig}"),
        _ => "unknown".into(),
    };
    session_event(dir, "exit", &detail);
    let stopped = fs::read_to_string(dir.join(report::EVENTS)).is_ok_and(|t| t.contains("\tstop\t"));
    let crashed = signal.is_some() || code.is_some_and(|c| c != 0);
    if !crashed || stopped || !cfg!(target_os = "macos") {
        return;
    }
    let diag = home().join("Library/Logs/DiagnosticReports");
    for _ in 0..20 {
        if let Some(p) = report::find_crash_report(&diag, &[GAME_EXE, WINDOW_EXE], started) {
            if fs::copy(&p, dir.join(report::CRASH)).is_ok() {
                session_event(dir, "crash-report", &format!("file={}", p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()));
            }
            return;
        }
        thread::sleep(std::time::Duration::from_secs(1));
    }
}

fn command_line(program: &str, args: &[&str]) -> String {
    command_stdout(Command::new(program).args(args)).map(|s| s.trim().to_string()).unwrap_or_default()
}

/// UTC "YYYY-MM-DD HH:MM:SS".
fn utc_text(secs: u64) -> String {
    let st = saves::stamp(secs);
    format!("{}-{}-{} {}:{}:{}", &st[0..4], &st[4..6], &st[6..8], &st[9..11], &st[11..13], &st[13..15])
}

fn system_info(b: &Builds, root: &Path, env: &[(String, String)], argv: &[String], now: u64) -> String {
    let mut t = String::new();
    let mut line = |k: &str, v: &str| {
        if !v.is_empty() {
            t.push_str(&format!("{k}: {v}\n"));
        }
    };
    line("report", &utc_text(now));
    line("launcher", env!("CARGO_PKG_VERSION"));
    line("os", &format!("{} {}", std::env::consts::OS, std::env::consts::ARCH));
    if cfg!(target_os = "macos") {
        line("macos", &format!("{} ({})", command_line("sw_vers", &["-productVersion"]), command_line("sw_vers", &["-buildVersion"])));
        line("model", &command_line("sysctl", &["-n", "hw.model"]));
        line("cpu", &command_line("sysctl", &["-n", "machdep.cpu.brand_string"]));
        let mem = command_line("sysctl", &["-n", "hw.memsize"]).parse::<u64>().unwrap_or(0);
        if mem > 0 {
            line("memory", &format!("{} GB", mem >> 30));
        }
        let gpus = command_stdout(Command::new("/usr/sbin/system_profiler").args(["SPDisplaysDataType", "-json"]))
            .and_then(|j| serde_json::from_str::<serde_json::Value>(&j).ok())
            .map(|v| {
                v["SPDisplaysDataType"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|g| g["sppci_model"].as_str().map(String::from))
                    .collect::<Vec<_>>()
                    .join(", ")
            })
            .unwrap_or_default();
        line("gpu", &gpus);
    }
    let g = game_info(Some(root));
    line("game", &format!("{} {} {}", g.title_id, g.title, g.app_ver));
    line("port folder", &b.root);
    line("built", &utc_text(b.built_at));
    line("commit", &command_line("git", &["-C", &b.root, "rev-parse", "--short", "HEAD"]));
    t.push_str("\ncommand:\n  ");
    t.push_str(&argv.iter().map(|a| shell_quote(a)).collect::<Vec<_>>().join(" "));
    t.push_str("\n\nenvironment:\n");
    for (k, v) in env {
        t.push_str(&format!("  {k}={}\n", shell_quote(v)));
    }
    let home = s(&home());
    if home.len() > 1 {
        t = t.replace(&home, "~");
    }
    t
}

fn current_report(state: &State<'_, AppState>) -> Option<(PathBuf, bool)> {
    let r = state.report.lock().unwrap().clone();
    r.or_else(|| report::latest(&reports_dir()).map(|d| (d, false)))
}

#[tauri::command]
fn report_info(state: State<'_, AppState>) -> Option<report::Info> {
    current_report(&state).map(|(d, live)| report::info(&d, live))
}

#[tauri::command]
fn report_capture(state: State<'_, AppState>) -> Result<report::Info, String> {
    let game = state.game.lock().unwrap().is_some();
    match state.report.lock().unwrap().clone() {
        Some((d, true)) if game => {
            let ms = now_ms();
            report::capture(&d, &utc_text(ms / 1000), ms)?;
            Ok(report::info(&d, true))
        }
        _ => Err("the game was not started in debug mode".into()),
    }
}

fn report_dir_of(state: &State<'_, AppState>, id: Option<&str>) -> Result<(PathBuf, bool), String> {
    let cur = current_report(state);
    match id {
        Some(id) => {
            let d = report::by_id(&reports_dir(), id)?;
            let live = cur.is_some_and(|(c, live)| live && c == d);
            Ok((d, live))
        }
        None => cur.ok_or_else(|| "no report yet: start the game in debug mode first".into()),
    }
}

#[tauri::command]
async fn report_list(state: State<'_, AppState>) -> Result<Vec<report::Info>, String> {
    let cur = current_report(&state);
    tauri::async_runtime::spawn_blocking(move || {
        report::list(&reports_dir(), 40)
            .into_iter()
            .map(|d| {
                let live = cur.as_ref().is_some_and(|(c, live)| *live && *c == d);
                report::info(&d, live)
            })
            .collect()
    })
    .await
    .map_err(|e| e.to_string())
}

#[tauri::command]
async fn report_triage(state: State<'_, AppState>, id: String) -> Result<report::Info, String> {
    let (dir, live) = report_dir_of(&state, Some(&id))?;
    tauri::async_runtime::spawn_blocking(move || {
        report::summarise(&dir)?;
        Ok(report::info(&dir, live))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn report_zip(state: State<'_, AppState>, id: Option<String>, notes: Option<String>) -> Result<report::Info, String> {
    let (dir, live) = report_dir_of(&state, id.as_deref())?;
    tauri::async_runtime::spawn_blocking(move || {
        if let Some(n) = notes.as_deref().map(str::trim).filter(|n| !n.is_empty()) {
            fs::write(dir.join(report::NOTES), format!("{n}\n")).map_err(|e| e.to_string())?;
        }
        let _ = report::summarise(&dir);
        report::pack(&dir, &report::zip_path(&dir), &s(&home()))?;
        Ok(report::info(&dir, live))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn report_delete(state: State<'_, AppState>, id: String) -> Result<(), String> {
    let (_, live) = report_dir_of(&state, Some(&id))?;
    if live {
        return Err("that session is still running".into());
    }
    report::delete(&reports_dir(), &id)
}

// ---------------------------------------------------------------------------
// Saves (saves.rs) and trophies (trophies.rs)
// ---------------------------------------------------------------------------

fn game_busy(state: &AppState) -> bool {
    state.game.lock().unwrap().is_some() || process_running(GAME_EXE)
}

const BUSY: &str = "the game is running: close it before changing saves";

/// Run `f` on the saves' folders. Never while the game runs.
fn with_saves<T>(state: &State<'_, AppState>, f: impl FnOnce(&saves::Locations) -> Result<T, String>) -> Result<T, String> {
    let game = state.game.lock().unwrap();
    if game.is_some() || process_running(GAME_EXE) {
        return Err(BUSY.into());
    }
    let loc = locations(&load_settings_file())?;
    let r = f(&loc);
    drop(game);
    r
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SavesOverview {
    port: Vec<Slot>,
    rpcs3: Vec<Slot>,
    rpcs3_users: Vec<String>,
    rpcs3_user: String,
    backups: Vec<BackupMeta>,
    port_dir: String,
    rpcs3_dir: String,
    backups_dir: String,
    game_running: bool,
    rpcs3_running: bool,
}

#[tauri::command]
async fn saves_overview(state: State<'_, AppState>, user: Option<String>) -> Result<SavesOverview, String> {
    let running = game_busy(&state);
    tauri::async_runtime::spawn_blocking(move || -> Result<SavesOverview, String> {
        let loc = locations(&load_settings_file())?;
        let users = saves::rpcs3_users(&loc);
        let user = user.filter(|u| users.contains(u)).or_else(|| users.first().cloned()).unwrap_or_else(|| saves::PORT_USER.into());
        let mut port = saves::list_slots(&loc, Side::Port, "", true);
        let mut rpcs3 = if users.is_empty() { Vec::new() } else { saves::list_slots(&loc, Side::Rpcs3, &user, true) };
        saves::hash_twins(&mut port, &mut rpcs3);
        Ok(SavesOverview {
            port,
            rpcs3,
            rpcs3_users: users,
            rpcs3_user: user.clone(),
            backups: saves::list_backups(&loc),
            port_dir: s(&loc.port_savedata),
            rpcs3_dir: s(&loc.rpcs3_savedata(&user)),
            backups_dir: s(&loc.backups),
            game_running: running,
            rpcs3_running: process_running("rpcs3") || process_running("RPCS3"),
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn saves_backup(state: State<'_, AppState>, side: Side, user: String, slot: Option<String>) -> Result<Option<BackupMeta>, String> {
    with_saves(&state, |loc| {
        let one = slot.map(|s| vec![s]);
        saves::create_backup(loc, side, &user, one.as_deref(), "manual", now_secs())
    })
}

#[tauri::command]
async fn saves_restore(state: State<'_, AppState>, id: String, slot: Option<String>) -> Result<saves::Report, String> {
    with_saves(&state, |loc| saves::restore_backup(loc, &id, slot.as_deref(), now_secs()))
}

#[tauri::command]
async fn saves_delete_backup(state: State<'_, AppState>, id: String) -> Result<(), String> {
    with_saves(&state, |loc| saves::delete_backup(loc, &id))
}

#[tauri::command]
async fn saves_copy(state: State<'_, AppState>, from: Side, to: Side, user: String, slot: String) -> Result<saves::Report, String> {
    with_saves(&state, |loc| saves::copy_slot(loc, from, to, &user, &slot, now_secs()))
}

#[tauri::command]
async fn saves_delete_slot(state: State<'_, AppState>, side: Side, user: String, slot: String) -> Result<BackupMeta, String> {
    with_saves(&state, |loc| saves::delete_slot(loc, side, &user, &slot, now_secs()))
}

fn zip_dest(dest: &str) -> Result<PathBuf, String> {
    let mut dest = PathBuf::from(dest.trim());
    if dest.as_os_str().is_empty() {
        return Err("no file chosen".into());
    }
    if !dest.extension().is_some_and(|e| e.eq_ignore_ascii_case("zip")) {
        dest.as_mut_os_string().push(".zip");
    }
    Ok(dest)
}

#[tauri::command]
async fn saves_export_zip(state: State<'_, AppState>, slots: Option<Vec<String>>, dest: String) -> Result<String, String> {
    let dest = zip_dest(&dest)?;
    with_saves(&state, |loc| saves::export_zip(loc, slots.as_deref(), &dest, now_secs()))?;
    Ok(s(&dest))
}

#[tauri::command]
async fn saves_import_zip(state: State<'_, AppState>, path: String) -> Result<saves::Report, String> {
    with_saves(&state, |loc| saves::import_zip(loc, Path::new(path.trim()), now_secs()))
}

/// The trophy list's language: the console language when one is set, else the launcher's.
fn trophy_lang(st: &Settings) -> String {
    if !st.game_lang.trim().is_empty() {
        st.game_lang.trim().to_ascii_lowercase()
    } else if st.ui_lang.starts_with("pt") {
        "pt".into()
    } else {
        "en".into()
    }
}

/// The game's trophies with the unlocks the runtime keeps (Game page): names and icons from the
/// player's own game/PS3_GAME/TROPDIR, unlocks from <gamedata>/trophies.
#[tauri::command]
async fn list_trophies() -> Result<trophies::TrophyList, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let st = load_settings_file();
        let port = port_root(&st).ok_or("no port folder yet")?;
        trophies::list(&game_root(&port), &gamedata_root(&st, &port), &trophy_lang(&st), true)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .setup(|app| {
            sync_app_icon(app.handle());
            let args: Vec<String> = std::env::args().collect();
            let st = app.state::<AppState>();
            *st.play_request.lock().unwrap() = play_shortcut::requested(args.iter().cloned());
            *st.exit_with_game.lock().unwrap() = play_shortcut::exit_requested(&args);
            *st.start_view.lock().unwrap() = play_shortcut::start_view(&args);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            get_input_map,
            save_input_map,
            reset_input_map,
            list_screens,
            list_mods,
            get_status,
            find_port_dirs,
            builds_at,
            game_status,
            check_updates,
            pull_sources,
            check_prereqs,
            install_clt,
            install_brew_deps,
            cancel_setup,
            start_install,
            install_finished,
            install_log_path,
            open_url,
            start_rebuild,
            cancel_rebuild,
            launch_preview,
            play,
            stop_game,
            reveal,
            log_paths,
            read_game_log,
            shader_cache_info,
            shader_cache_clear,
            saves_overview,
            saves_backup,
            saves_restore,
            saves_delete_backup,
            saves_copy,
            saves_delete_slot,
            saves_export_zip,
            saves_import_zip,
            list_trophies,
            report_info,
            report_list,
            report_triage,
            report_capture,
            report_zip,
            report_delete,
            finder_icon,
            take_play_request,
            take_start_view,
            frontend_log,
            create_play_shortcut,
            steam_status,
            steam_add,
            steam_remove,
            steam_quit
        ])
        .build(tauri::generate_context!())
        .expect("error while running the launcher")
        .run(|app, ev| {
            // Quitting stops an install, a rebuild or a brew install (their own process groups, by
            // pid). The game keeps running, as it would from a shell.
            if let tauri::RunEvent::Exit = ev {
                let st = app.state::<AppState>();
                for slot in [&st.rebuild, &st.setup] {
                    if let Some(pid) = *slot.lock().unwrap() {
                        kill_tree(pid, false);
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests;
