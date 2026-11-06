//! "Install the game": the player's own disc image in, a build Play can run out. The work is the
//! repository's `mac/install.sh` (deps, venv, game, decrypt, toolkit, lift, build); `install.zsh`
//! (bundled into the binary) clones the sources first when there is no checkout, and lib.rs's
//! `start_install` runs it. This module checks the inputs before it starts.
//!
//! The disc key, when the image needs one, is only handed on (DES_KEY) to
//! `tools/iso_extract.py`; the decryption keys for the EBOOT are fetched by the
//! port's own `tools/fetch_keys.py` into a file outside the repository.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const SCRIPT: &str = include_str!("install.zsh");

/// The steps an install announces, in order (src/progress.ts has the same).
#[cfg(test)]
pub const STEPS: &[&str] = &["sources", "deps", "venv", "game", "decrypt", "toolkit", "lift", "build"];

/// The free space an install asks for (mac/install.sh's NEED_GB): the game files about 8 GB, the
/// lift and the build about 1.2 GB, the toolkit and the venv 0.3 GB, with room on the way.
pub const NEED_GB: u64 = 14;

/// Homebrew formulas the build needs (git and the compiler come with Apple's Command Line Tools),
/// and what shows each one is installed. FFmpeg is for the movies (loaded at run time); without it
/// the game runs and skips them, so it is optional.
pub const BREW_NEEDS: &[(&str, &[&str])] = &[
    ("cmake", &["bin/cmake"]),
    ("ninja", &["bin/ninja"]),
    ("sdl2", &["lib/libSDL2.dylib", "opt/sdl2", "opt/sdl2-compat"]),
    ("glslang", &["bin/glslangValidator", "opt/glslang"]),
    ("spirv-cross", &["bin/spirv-cross", "opt/spirv-cross"]),
    ("ffmpeg", &["lib/libavcodec.dylib", "opt/ffmpeg"]),
    // any Python 3.10+ will do; Apple's is 3.9
    ("python@3.12", &["bin/python3.12", "bin/python3.13", "bin/python3.14", "bin/python3.11", "bin/python3.10"]),
];

pub fn brew_missing(prefix: &Path) -> Vec<&'static str> {
    BREW_NEEDS.iter().filter(|(_, marks)| !marks.iter().any(|m| prefix.join(m).exists())).map(|(f, _)| *f).collect()
}

/// What the player chose, as the Home card sends it (and the settings keep it).
#[derive(Serialize, Deserialize, Clone, Debug, Default, PartialEq)]
#[serde(rename_all = "camelCase", default)]
pub struct Inputs {
    /// The disc image (.iso, or a Redump .zip holding one), or a dumped disc folder with PS3_GAME/.
    pub iso: String,
    /// The disc key of an encrypted (Redump) image: 32 hex digits or a .dkey file. Empty: a .dkey
    /// next to the image, or none for a decrypted image.
    pub key: String,
}

fn plain_absolute(what: &str, p: &str) -> Result<PathBuf, String> {
    let path = PathBuf::from(p.trim());
    if p.trim().is_empty() {
        return Err(format!("choose {what} first"));
    }
    if !path.is_absolute() || path.components().any(|c| matches!(c, std::path::Component::ParentDir)) {
        return Err(format!("{what}: {} is not a plain absolute path", path.display()));
    }
    Ok(path)
}

/// A disc key as typed: 32 hex digits (spaces and dashes allowed), or a key file.
pub fn key_text_ok(k: &str) -> bool {
    let hex: String = k.chars().filter(|c| !c.is_whitespace() && *c != '-').collect();
    hex.len() == 32 && hex.chars().all(|c| c.is_ascii_hexdigit())
}

/// The inputs, checked as far as can be without reading the image: an .iso or .zip file, or a
/// folder holding PS3_GAME/USRDIR/EBOOT.BIN; a key that is 32 hex digits or an existing file.
/// `extracted`: game/ is already there, and the image is not needed any more.
pub fn check(i: &Inputs, extracted: bool) -> Result<Checked, String> {
    let iso = if i.iso.trim().is_empty() && extracted {
        None
    } else {
        let p = plain_absolute("the disc image", &i.iso)?;
        if p.is_dir() {
            if !p.join("PS3_GAME/USRDIR/EBOOT.BIN").is_file() {
                return Err(format!("{}: a dumped disc folder has PS3_GAME/USRDIR/EBOOT.BIN inside", p.display()));
            }
        } else if !p.is_file() {
            return Err(format!("the disc image: {} is not there", p.display()));
        } else if !p.extension().is_some_and(|e| e.eq_ignore_ascii_case("iso") || e.eq_ignore_ascii_case("zip")) {
            return Err(format!("{}: not an .iso or a .zip", p.display()));
        }
        Some(p)
    };
    let k = i.key.trim();
    let key = if k.is_empty() {
        None
    } else if key_text_ok(k) {
        Some(k.to_string())
    } else {
        let p = plain_absolute("the disc key", k)?;
        if !p.is_file() {
            return Err(format!("the disc key: give its 32 hex digits or a .dkey file ({k} is neither)"));
        }
        Some(p.to_string_lossy().into_owned())
    };
    Ok(Checked { iso, key })
}

#[derive(Debug)]
pub struct Checked {
    pub iso: Option<PathBuf>,
    pub key: Option<String>,
}

impl Checked {
    /// The environment `install.zsh` (and so mac/install.sh) reads.
    pub fn env(&self, src: &Path, url: &str, branch: &str) -> Vec<(String, String)> {
        vec![
            ("DES_SRC".into(), src.to_string_lossy().into_owned()),
            ("DES_SOURCES_URL".into(), url.into()),
            ("DES_SOURCES_BRANCH".into(), branch.into()),
            ("DES_ISO".into(), self.iso.as_deref().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default()),
            ("DES_KEY".into(), self.key.clone().unwrap_or_default()),
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("des-install-{tag}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn inputs_are_checked() {
        let d = tmp("inputs");
        let iso = d.join("Demon's Souls (USA).iso");
        fs::write(&iso, "iso").unwrap();
        let ok = Inputs { iso: iso.to_string_lossy().into(), key: String::new() };
        let c = check(&ok, false).unwrap();
        assert_eq!(c.iso.as_deref(), Some(iso.as_path()));
        assert!(c.key.is_none());

        // a Redump zip, a dumped folder
        let zip = d.join("Demon's Souls (USA).zip");
        fs::write(&zip, "zip").unwrap();
        assert!(check(&Inputs { iso: zip.to_string_lossy().into(), ..Default::default() }, false).is_ok());
        let dump = d.join("dump");
        fs::create_dir_all(dump.join("PS3_GAME/USRDIR")).unwrap();
        let i = Inputs { iso: dump.to_string_lossy().into(), ..Default::default() };
        assert!(check(&i, false).unwrap_err().contains("PS3_GAME/USRDIR/EBOOT.BIN"));
        fs::write(dump.join("PS3_GAME/USRDIR/EBOOT.BIN"), "self").unwrap();
        assert!(check(&i, false).is_ok());

        // refused: another kind of file, a relative path, nothing before extraction
        let img = d.join("x.img");
        fs::write(&img, "").unwrap();
        assert!(check(&Inputs { iso: img.to_string_lossy().into(), ..Default::default() }, false).unwrap_err().contains("not an .iso"));
        assert!(check(&Inputs { iso: "game.iso".into(), ..Default::default() }, false).unwrap_err().contains("plain absolute"));
        assert!(check(&Inputs::default(), false).is_err());
        assert!(check(&Inputs::default(), true).unwrap().iso.is_none(), "no image needed once game/ is extracted");

        // the key: hex digits as typed, or a file
        let mut i = ok.clone();
        i.key = "0123456789ABCDEF 0123456789abcdef".into();
        assert!(check(&i, false).unwrap().key.is_some());
        i.key = "not a key".into();
        assert!(check(&i, false).is_err());
        let dkey = d.join("Demon's Souls (USA).dkey");
        fs::write(&dkey, [0u8; 16]).unwrap();
        i.key = dkey.to_string_lossy().into();
        assert_eq!(check(&i, false).unwrap().key.as_deref(), Some(dkey.to_string_lossy().as_ref()));
        fs::remove_dir_all(&d).unwrap();
    }

    #[test]
    fn environment_for_the_script() {
        let c = Checked { iso: Some(PathBuf::from("/x/a.iso")), key: None };
        let e: std::collections::BTreeMap<String, String> = c.env(Path::new("/data/src"), "https://example.invalid/r.git", "main").into_iter().collect();
        assert_eq!(e["DES_SRC"], "/data/src");
        assert_eq!(e["DES_ISO"], "/x/a.iso");
        assert_eq!(e["DES_KEY"], "");
        assert_eq!(e["DES_SOURCES_BRANCH"], "main");
    }

    #[test]
    fn script_runs_the_repository_install() {
        assert!(SCRIPT.contains("==> $*") && SCRIPT.contains("say \"sources"));
        assert!(SCRIPT.contains("exec /bin/zsh \"$DES_SRC/mac/install.sh\""));
        // the steps the repository's scripts announce
        let rebuild = include_str!("../../../rebuild.sh");
        for s in STEPS.iter().filter(|s| **s != "sources") {
            assert!(rebuild.contains(&format!("    {s})")), "{s}");
        }
    }

    #[test]
    fn brew_formulas() {
        let d = tmp("brew");
        assert_eq!(brew_missing(&d), vec!["cmake", "ninja", "sdl2", "glslang", "spirv-cross", "ffmpeg", "python@3.12"]);
        fs::create_dir_all(d.join("bin")).unwrap();
        fs::write(d.join("bin/cmake"), "").unwrap();
        fs::write(d.join("bin/python3.14"), "").unwrap();
        fs::create_dir_all(d.join("opt/sdl2-compat")).unwrap();
        assert_eq!(brew_missing(&d), vec!["ninja", "glslang", "spirv-cross", "ffmpeg"]);
        fs::remove_dir_all(&d).unwrap();
    }
}
