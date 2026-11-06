use super::*;

fn tmp(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("des-launcher-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d.canonicalize().unwrap()
}

fn all_features() -> Features {
    FEATURE_MARKERS.iter().map(|m| m.to_string()).collect()
}

fn env_of(s: &Settings, input: &InputEnv, features: &Features) -> BTreeMap<String, String> {
    launch_env(s, input, features).into_iter().collect()
}

#[test]
fn base64_matches_rfc4648() {
    assert_eq!(base64(b""), "");
    assert_eq!(base64(b"f"), "Zg==");
    assert_eq!(base64(b"foobar"), "Zm9vYmFy");
}

#[test]
fn env_lines() {
    let v = parse_env_lines("# c\nA=1\nexport B=\"x y\"\nbad key=2\n\nC=");
    assert_eq!(v, vec![("A".into(), "1".into()), ("B".into(), "x y".into()), ("C".into(), "".into())]);
}

#[test]
fn builds_and_argv() {
    let root = tmp("builds");
    let b = resolve_builds(&root);
    assert!(!b.ok && b.missing.len() == 4 && b.rebuild_sh.is_none());
    assert!(launch_argv(&Settings::default(), &b).is_err());
    for f in ["port/build_mac/DemonsSoulsRecomp", "port/build_mac/DemonsSoulsRecomp_window", ELF_REL, PLAY_SH, REBUILD_SH] {
        let p = root.join(f);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, b"x").unwrap();
    }
    let b = resolve_builds(&root);
    assert!(b.ok, "{:?}", b.missing);
    assert!(b.rebuild_sh.is_some());
    let mut st = Settings { keep_awake: false, ..Default::default() };
    assert_eq!(launch_argv(&st, &b).unwrap(), vec!["/bin/sh".to_string(), s(&root.join(PLAY_SH))]);
    st.keep_awake = true;
    let argv = launch_argv(&st, &b).unwrap();
    if Path::new("/usr/bin/caffeinate").is_file() {
        assert_eq!(&argv[..2], ["/usr/bin/caffeinate", "-i"]);
    }
    fs::remove_dir_all(&root).unwrap();
}

#[test]
fn a_checkout_is_recognised() {
    let root = tmp("checkout");
    assert!(!is_port_checkout(&root));
    fs::create_dir_all(root.join("mac")).unwrap();
    fs::create_dir_all(root.join("setup")).unwrap();
    fs::write(root.join("setup/setup.py"), "").unwrap();
    fs::write(root.join(PLAY_SH), "#!/bin/sh\n# another game's\n").unwrap();
    assert!(!is_port_checkout(&root), "a play.sh that is not this port's");
    fs::write(root.join(PLAY_SH), "BIN=\"$D/port/build_mac/DemonsSoulsRecomp\"\n").unwrap();
    assert!(is_port_checkout(&root));
    // the repository the launcher is built from
    let own = own_repo().expect("mac/launcher sits in the port's checkout");
    assert!(own.join("mac/play.sh").is_file());
    fs::remove_dir_all(&root).unwrap();
}

#[test]
fn game_files_from_the_extracted_disc() {
    let root = tmp("game");
    assert!(game_info(Some(&root)).root.is_none());
    let g = root.join("game/PS3_GAME");
    fs::create_dir_all(&g).unwrap();
    let sfo = |id: &str| {
        saves::psf_write(&[
            saves::PsfEntry { key: "APP_VER".into(), fmt: saves::PSF_UTF8, data: b"01.00\0".to_vec(), max_len: 8 },
            saves::PsfEntry { key: "TITLE".into(), fmt: saves::PSF_UTF8, data: b"Demon's Souls\0".to_vec(), max_len: 128 },
            saves::PsfEntry { key: "TITLE_ID".into(), fmt: saves::PSF_UTF8, data: format!("{id}\0").into_bytes(), max_len: 16 },
        ])
    };
    fs::write(g.join("PARAM.SFO"), sfo("BLUS30443")).unwrap();
    fs::write(g.join("ICON0.PNG"), b"png").unwrap();
    let i = game_info(Some(&root));
    assert!(i.ours && !i.extracted && i.title == "Demon's Souls" && i.app_ver == "01.00");
    fs::write(root.join("game/.extracted"), "/x/Demon's Souls (USA).iso\n").unwrap();
    let i = game_info(Some(&root));
    assert!(i.extracted);
    assert_eq!(i.image.as_deref(), Some("/x/Demon's Souls (USA).iso"));
    assert_eq!(game_art(Some(&root)).0, Some(g.join("ICON0.PNG")));
    assert!(game_art(Some(&root)).1.is_none());
    fs::write(g.join("PARAM.SFO"), sfo("BLES00932")).unwrap();
    assert!(!game_info(Some(&root)).ours);
    fs::remove_dir_all(&root).unwrap();
}

/// With the default settings Play adds nothing: the environment is mac/play.sh's own.
#[test]
fn defaults_are_play_sh() {
    assert!(env_of(&Settings::default(), &InputEnv::default(), &all_features()).is_empty());
}

#[test]
fn launch_env_maps_the_settings() {
    let st = Settings {
        fps: "30".into(),
        movies: false,
        char_name: "  Ostrava ".into(),
        skip_intro: true,
        window_size: "1920x1080".into(),
        game_lang: "pt-BR".into(),
        aa: "smaa".into(),
        sharpen: 0.35,
        aniso: 16,
        gamma_override: true,
        gamma: 1.1,
        vibrance: -0.25,
        contrast: 1.2,
        input_mode: "controller".into(),
        mouse_sens: 1.5,
        mouse_invert_y: true,
        rumble_strength: 150,
        audio_mute: true,
        show_fps: true,
        verbose_log: true,
        pad_log: true,
        stall_sample_ms: 300,
        ffmpeg_avcodec: "/opt/x/libavcodec.62.dylib".into(),
        extra_env: "PS3_GAMEDATA_ROOT=/elsewhere\nDES_FPS=60".into(),
        ..Default::default()
    };
    let input = InputEnv { path: Some("/data/input.toml".into()), has_mouse_section: false };
    let v = launch_env(&st, &input, &all_features());
    let e: BTreeMap<String, String> = v.iter().cloned().collect();
    for (k, want) in [
        ("DES_MOVIES", "0"),
        ("DES_NAME", "Ostrava"),
        ("DES_SKIP_INTRO", "1"),
        ("DES_SIZE", "1920x1080"),
        ("DES_LOG", "1"),
        ("PS3_LANG", "pt-BR"),
        ("PS3_AA", "smaa"),
        ("PS3_SHARPEN", "0.35"),
        ("PS3_ANISO", "16"),
        ("PS3_DISPLAY_GAMMA", "1.10"),
        ("PS3_VIBRANCE", "-0.25"),
        ("PS3_CONTRAST", "1.20"),
        ("PS3_INPUT_MAP", "/data/input.toml"),
        ("PS3_INPUT_MODE", "controller"),
        ("PS3_MOUSE_SENS", "1.50"),
        ("PS3_MOUSE_INVERT_Y", "1"),
        ("PS3_RUMBLE_STRENGTH", "150"),
        ("AUDIO_MUTE", "1"),
        ("PS3RECOMP_METAL_FPS", "1"),
        ("PS3_PAD_LOG", "1"),
        ("PS3_STALL_SAMPLE", "300"),
        ("PS3_GAMEDATA_ROOT", "/elsewhere"),
    ] {
        assert_eq!(e.get(k).map(String::as_str), Some(want), "{k}");
    }
    // the movies are off, so their libraries are not passed; the extra variables come last
    assert!(!e.contains_key("PS3RECOMP_FFMPEG_AVCODEC"));
    assert_eq!(v.iter().filter(|(k, _)| k == "DES_FPS").map(|(_, v)| v.as_str()).collect::<Vec<_>>(), ["30", "60"]);
    // movies on: the chosen library
    let e = env_of(&Settings { ffmpeg_avcodec: "/opt/x/libavcodec.62.dylib".into(), ..Default::default() }, &InputEnv::default(), &all_features());
    assert_eq!(e["PS3RECOMP_FFMPEG_AVCODEC"], "/opt/x/libavcodec.62.dylib");
}

/// A file with a [mouse] section (mac/input.toml has one): every mouse setting is passed, so the
/// launcher's win over the file's.
#[test]
fn mouse_settings_win_over_the_file() {
    let e = env_of(&Settings::default(), &InputEnv { path: None, has_mouse_section: true }, &all_features());
    for (k, v) in [("PS3_MOUSE", "1"), ("PS3_MOUSE_SENS", "1.00"), ("PS3_MOUSE_INVERT_Y", "0"), ("PS3_MOUSE_INVERT_X", "0"), ("PS3_MOUSE_DEADZONE", "30"), ("PS3_MOUSE_CAPTURE", "1")] {
        assert_eq!(e[k], v, "{k}");
    }
    assert!(!e.contains_key("PS3_INPUT_MAP"), "no launcher file: play.sh's mac/input.toml");
    let e = env_of(&Settings { mouse: false, ..Default::default() }, &InputEnv { path: None, has_mouse_section: true }, &all_features());
    assert_eq!(e["PS3_MOUSE"], "0");
    assert!(!e.contains_key("PS3_MOUSE_SENS"));
}

#[test]
fn values_that_change_nothing_or_are_invalid_stay_out() {
    let st = Settings {
        fps: "50".into(),
        char_name: "a name far longer than sixteen".into(),
        window_size: "1280x720".into(),
        game_lang: "pt;rm -rf".into(),
        aa: "msaa".into(),
        aniso: 1,
        vibrance: 0.001,
        contrast: 1.001,
        ..Default::default()
    };
    assert!(env_of(&st, &InputEnv::default(), &all_features()).is_empty());
    assert!(env_of(&Settings { window_size: "10x10".into(), ..Default::default() }, &InputEnv::default(), &all_features()).is_empty());
    assert!(valid_name("Slayer\n").is_some() && valid_name("bad\u{7}").is_none() && valid_name("   ").is_none());
}

/// A build without a feature gets none of its variables; play.sh's own always go.
#[test]
fn features_gate_the_build_variables() {
    let st = Settings { aa: "smaa".into(), vibrance: 0.5, skip_intro: true, fps: "30".into(), audio_mute: true, ..Default::default() };
    let none = Features::new();
    let e = env_of(&st, &InputEnv::default(), &none);
    assert_eq!(e.keys().map(String::as_str).collect::<Vec<_>>(), ["DES_FPS"]);
    let mut f: Features = ["PS3_AA", "PS3_VIBRANCE"].iter().map(|m| m.to_string()).collect();
    assert!(!env_of(&st, &InputEnv::default(), &f).contains_key("PS3_AA"), "SMAA needs the build to have it");
    f.insert("smaa".into());
    assert_eq!(env_of(&st, &InputEnv::default(), &f)["PS3_AA"], "smaa");
    assert_eq!(env_of(&Settings { aa: "fxaa".into(), ..Default::default() }, &InputEnv::default(), &f)["PS3_AA"], "fxaa");
}

#[test]
fn old_settings_files_still_load() {
    let st: Settings = serde_json::from_str(r#"{"uiLang":"en","aa":"fxaa","somethingGone":1}"#).unwrap();
    assert_eq!(st.ui_lang, "en");
    assert_eq!(st.aa, "fxaa");
    assert!(st.movies && st.keep_awake && st.fps == "60" && st.save_backups_keep == 10 && (st.contrast - 1.0).abs() < 1e-6);
}

#[test]
fn input_map_starts_from_the_ports_layout() {
    let d = tmp("input");
    let base = d.join("mac/input.toml");
    fs::create_dir_all(base.parent().unwrap()).unwrap();
    fs::write(&base, "[keyboard]\ncross = \"E\"\n[mouse]\ncamera = true\ncapture = true\n").unwrap();
    let p = d.join("data/input.toml");
    let mut b = Bindings::default();
    b.keyboard.insert("cross".into(), vec!["Space".into()]);
    b.mouse_buttons.insert("r1".into(), vec!["Left".into()]);
    write_input_map(&p, Some(&base), b.clone()).unwrap();
    let text = fs::read_to_string(&p).unwrap();
    assert!(text.starts_with("# Demon's Souls recomp: controls"));
    let f = input_map::parse(&text);
    assert_eq!(f.bindings, b);
    assert!(f.has_mouse_section && f.other.contains("camera = true"), "the port's [mouse] is kept");
    // the port's file is not touched
    assert!(fs::read_to_string(&base).unwrap().contains("cross = \"E\""));
    // the next save keeps the launcher's own file's sections
    fs::write(&p, format!("{text}\n[future]\nx = 1\n")).unwrap();
    b.keyboard.insert("r1".into(), vec!["F".into()]);
    write_input_map(&p, Some(&base), b.clone()).unwrap();
    let f = input_map::parse(&fs::read_to_string(&p).unwrap());
    assert_eq!(f.bindings.keyboard["r1"], vec!["F"]);
    assert!(f.other.contains("[future]"));
    b.keyboard.insert("cross".into(), vec!["Q\"\n[x]".into()]);
    assert!(write_input_map(&p, Some(&base), b).is_err());
    // the real layout parses and has its [mouse]
    let real = input_map::parse(&fs::read_to_string(own_repo().unwrap().join("mac/input.toml")).unwrap());
    assert_eq!(real.bindings.keyboard["cross"], vec!["E"]);
    assert_eq!(real.bindings.mouse_buttons["r1"], vec!["Left"]);
    assert!(real.has_mouse_section);
    fs::remove_dir_all(&d).unwrap();
}

#[test]
fn feature_markers_in_a_build() {
    let d = tmp("features");
    let exe = d.join("game");
    fs::write(&exe, b"\x7fELF junk\0PS3_INPUT_MAP\0more PS3_STALL_SAMPLE=%s\0 PS3_STALL_SAMPLE\0 PS3_AA_X\0XPS3_LANG\0smaa\0").unwrap();
    let b = Builds { eboot: Some(s(&exe)), ..Default::default() };
    let cache = Mutex::new(FeatureCache::new());
    let file = d.join("data/build-features.json");
    assert_eq!(build_features_in(&b, &cache, &file), vec!["PS3_INPUT_MAP".to_string(), "PS3_STALL_SAMPLE".to_string(), "smaa".to_string()]);
    assert_eq!(build_features_in(&b, &cache, &file).len(), 3, "from the cache");
    assert!(fs::read_to_string(&file).unwrap().contains("PS3_INPUT_MAP"));
    assert_eq!(build_features_in(&b, &Mutex::new(FeatureCache::new()), &file).len(), 3);
    assert!(build_features_in(&Builds::default(), &cache, &file).is_empty());
    // PS3_MOUSE is not found in its longer names
    let mut found = Features::new();
    markers_in(b"\0PS3_DISPLAY_GAMMA\0PS3_MOUSE_SENS\0", &mut found);
    assert_eq!(found.into_iter().collect::<Vec<_>>(), ["PS3_DISPLAY_GAMMA", "PS3_MOUSE_SENS"]);
    // a name across two of the pieces the file is read in
    let exe2 = d.join("big");
    let mut big = vec![1u8; (8 << 20) - 5];
    big.extend_from_slice(b"\0AUDIO_MUTE\0");
    big.extend_from_slice(&[1u8; 4096]);
    fs::write(&exe2, &big).unwrap();
    assert!(scan_markers(&exe2).contains("AUDIO_MUTE"));
    fs::remove_dir_all(&d).unwrap();
}

/// The marker list against the real build, when it is there:
/// `cargo test -- --ignored real_build --nocapture`.
#[test]
#[ignore]
fn real_build_features() {
    let exe = own_repo().unwrap().join(BUILD_DIR).join(GAME_EXE);
    let t = std::time::Instant::now();
    let found = scan_markers(&exe);
    println!("{:.1} s: {found:?}", t.elapsed().as_secs_f64());
    println!("not in the build: {:?}", FEATURE_MARKERS.iter().filter(|m| !found.contains(**m)).collect::<Vec<_>>());
    for m in ["PS3_AA", "PS3_INPUT_MAP", "AUDIO_MUTE", "DES_SKIP_INTRO", "PS3RECOMP_METAL_FPS"] {
        assert!(found.contains(m), "{m}");
    }
}

#[test]
fn window_sizes() {
    assert!(valid_window_size("1280x720"));
    assert!(valid_window_size("2560x1440"));
    assert!(!valid_window_size(""));
    assert!(!valid_window_size("10x10"));
    assert!(!valid_window_size("1280x720x1"));
}

#[test]
fn rebuild_script_steps() {
    assert_eq!(rebuild_script(&[]), "set -e\nexec /bin/zsh mac/rebuild.sh deps venv decrypt toolkit lift build\n");
    assert_eq!(rebuild_script(&["build".into()]), "set -e\nexec /bin/zsh mac/rebuild.sh deps venv build\n");
    assert_eq!(rebuild_script(&["lift".into(), "toolkit".into()]), "set -e\nexec /bin/zsh mac/rebuild.sh deps venv toolkit lift\n");
    // every step the launcher offers is one mac/rebuild.sh has
    let sh = fs::read_to_string(own_repo().unwrap().join(REBUILD_SH)).unwrap();
    for s in STEPS {
        assert!(sh.contains(&format!("    {s})")), "{s}");
    }
}

#[test]
fn saves_live_under_gamedata() {
    let st = Settings { port_dir: "/port".into(), ..Default::default() };
    let l = locations(&st).unwrap();
    assert_eq!(l.port_savedata, PathBuf::from("/port/gamedata/dev_hdd0/home/00000001/savedata"));
    let st = Settings { port_dir: "/port".into(), extra_env: "PS3_GAMEDATA_ROOT=/g".into(), ..Default::default() };
    assert_eq!(locations(&st).unwrap().port_savedata, PathBuf::from("/g/dev_hdd0/home/00000001/savedata"));
    assert_eq!(msl_cache_dir(&Settings { port_dir: "/port".into(), ..Default::default() }), Some(PathBuf::from("/port/cache/msl")));
}

#[test]
fn trophy_language() {
    assert_eq!(trophy_lang(&Settings::default()), "pt");
    assert_eq!(trophy_lang(&Settings { ui_lang: "en".into(), ..Default::default() }), "en");
    assert_eq!(trophy_lang(&Settings { game_lang: "FR".into(), ..Default::default() }), "fr");
}

#[test]
fn reveal_never_opens_an_app_bundle() {
    let tmp = std::env::temp_dir().join(format!("des-reveal-{}", std::process::id()));
    let app = tmp.join("Some.app");
    std::fs::create_dir_all(&app).unwrap();
    let (t, select) = crate::reveal_target(&app.join("missing/file.txt")).unwrap();
    assert_eq!(t, app);
    assert!(select);
    let (_, select) = crate::reveal_target(&app).unwrap();
    assert!(select);
    let (t, select) = crate::reveal_target(&tmp.join("nope.log")).unwrap();
    assert_eq!(t, tmp);
    assert!(!select);
    assert!(crate::reveal_target(std::path::Path::new("relative/path")).is_err());
    std::fs::remove_dir_all(&tmp).unwrap();
}
