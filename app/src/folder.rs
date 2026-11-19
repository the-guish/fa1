//! The one folder the app writes to (docs/specs/app.md, "The folder"), and what it keeps there:
//! the settings, the keys and the secrets.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use base64::Engine;
use serde::{Deserialize, Serialize};

/// The port of the front listener at the first start, when it is free.
pub const DEFAULT_PORT: u16 = 8420;

/// The app's folder on this platform. `FA1_HOME` names another one, for tests.
pub fn default_root() -> PathBuf {
    if let Some(named) = std::env::var_os("FA1_HOME") {
        return PathBuf::from(named);
    }
    let home = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    if cfg!(target_os = "macos") {
        return home.join("Library/Application Support/FA1");
    }
    match std::env::var_os("XDG_DATA_HOME") {
        Some(data) if !data.is_empty() => PathBuf::from(data).join("fa1"),
        _ => home.join(".local/share/fa1"),
    }
}

#[derive(Clone, Debug)]
pub struct Folder {
    pub root: PathBuf,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Settings {
    /// `containers` once the person chose mode 2.
    pub mode: Option<String>,
    pub port: Option<u16>,
}

/// What the person typed on the Keys screen. Empty means not given.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Keys {
    #[serde(default)]
    pub anthropic: String,
    #[serde(default)]
    pub claude_code: String,
    #[serde(default)]
    pub github: String,
    #[serde(default)]
    pub git_name: String,
    #[serde(default)]
    pub git_email: String,
    /// The repositories the agents work on, as the person typed them: one per line.
    #[serde(default)]
    pub repositories: String,
}

impl Folder {
    pub fn new(root: PathBuf) -> Self {
        Folder { root }
    }

    pub fn secrets(&self) -> PathBuf {
        self.root.join("secrets")
    }

    pub fn compose(&self) -> PathBuf {
        self.root.join("compose")
    }

    pub fn logs(&self) -> PathBuf {
        self.root.join("logs")
    }

    /// The folder and its parts. `secrets/` is the person's alone.
    pub fn ensure(&self) -> std::io::Result<()> {
        fs::create_dir_all(self.logs())?;
        fs::create_dir_all(self.compose())?;
        fs::create_dir_all(self.secrets())?;
        set_mode(&self.secrets(), 0o700)
    }

    pub fn settings(&self) -> Settings {
        read_toml(&self.root.join("settings.toml")).unwrap_or_default()
    }

    pub fn save_settings(&self, settings: &Settings) -> std::io::Result<()> {
        let text = toml::to_string(settings).map_err(std::io::Error::other)?;
        write_file(&self.root.join("settings.toml"), &text, 0o644)
    }

    pub fn keys(&self) -> Keys {
        read_toml(&self.secrets().join("keys.toml")).unwrap_or_default()
    }

    pub fn save_keys(&self, keys: &Keys) -> std::io::Result<()> {
        let text = toml::to_string(keys).map_err(std::io::Error::other)?;
        write_file(&self.secrets().join("keys.toml"), &text, 0o600)
    }

    /// A secret file of `secrets/`, made with `make` when it is missing or empty.
    pub fn secret_or(&self, name: &str, make: impl FnOnce() -> String) -> std::io::Result<String> {
        let path = self.secrets().join(name);
        match fs::read_to_string(&path) {
            Ok(text) if !text.trim().is_empty() => Ok(text.trim().to_string()),
            _ => {
                let made = make();
                self.write_secret(name, &made)?;
                Ok(made)
            }
        }
    }

    /// The containers' users read the files of `secrets/`. The folder keeps them the person's.
    pub fn write_secret(&self, name: &str, text: &str) -> std::io::Result<()> {
        write_file(&self.secrets().join(name), text, 0o644)
    }

    pub fn read_secret(&self, name: &str) -> String {
        fs::read_to_string(self.secrets().join(name))
            .map(|t| t.trim().to_string())
            .unwrap_or_default()
    }
}

/// 256 random bits, URL-safe, as oneberth makes its secrets.
pub fn random_secret() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the system has no random source");
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

/// A launch secret oneberth accepts: its prefix, then 256 random bits.
pub fn launch_secret() -> String {
    format!("ob_lch_{}", random_secret())
}

fn read_toml<T: for<'de> Deserialize<'de>>(path: &Path) -> Option<T> {
    toml::from_str(&fs::read_to_string(path).ok()?).ok()
}

pub fn write_file(path: &Path, text: &str, mode: u32) -> std::io::Result<()> {
    let mut file = fs::File::create(path)?;
    file.write_all(text.as_bytes())?;
    set_mode(path, mode)
}

#[cfg(unix)]
fn set_mode(path: &Path, mode: u32) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
}

#[cfg(not(unix))]
fn set_mode(_path: &Path, _mode: u32) -> std::io::Result<()> {
    Ok(())
}
