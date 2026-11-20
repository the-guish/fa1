//! Mode 2: the Compose project `fa1` (docs/specs/containers.md). Its files are built into the app
//! and written to `compose/` in the folder at each start.

use std::fs;
use std::time::Duration;

use crate::actions::Action;
use crate::control;
use crate::folder::{self, Folder, Keys};
use crate::setup::{self, Setup};

/// The project's files, as this repository's `compose/` holds them.
const FILES: &[(&str, &str)] = &[
    ("compose.yaml", include_str!("../../compose/compose.yaml")),
    (
        "fetch/Dockerfile",
        include_str!("../../compose/fetch/Dockerfile"),
    ),
    (
        "files/Dockerfile",
        include_str!("../../compose/files/Dockerfile"),
    ),
    (
        "todo/Dockerfile",
        include_str!("../../compose/todo/Dockerfile"),
    ),
    (
        "diagrams/Dockerfile",
        include_str!("../../compose/diagrams/Dockerfile"),
    ),
    (
        "setup-tools/Dockerfile",
        include_str!("../../compose/setup-tools/Dockerfile"),
    ),
    (
        "setup-tools/start.sh",
        include_str!("../../compose/setup-tools/start.sh"),
    ),
];

/// FA1's applications and its host of them, as this repository's `apps/` holds them
/// (docs/specs/apps.md). They are written to `compose/apps/`, the build context of `control`.
const APPS: &[(&str, &str)] = &[
    (".dockerignore", include_str!("../../apps/.dockerignore")),
    (".npmrc", include_str!("../../apps/.npmrc")),
    ("Dockerfile", include_str!("../../apps/Dockerfile")),
    ("backend.py", include_str!("../../apps/backend.py")),
    ("index.html", include_str!("../../apps/index.html")),
    ("main.tsx", include_str!("../../apps/main.tsx")),
    (
        "package-lock.json",
        include_str!("../../apps/package-lock.json"),
    ),
    ("package.json", include_str!("../../apps/package.json")),
    (
        "reviews/ReviewsApp.tsx",
        include_str!("../../apps/reviews/ReviewsApp.tsx"),
    ),
    (
        "reviews/diff.ts",
        include_str!("../../apps/reviews/diff.ts"),
    ),
    (
        "reviews/backend.py",
        include_str!("../../apps/reviews/backend.py"),
    ),
    (
        "reviews/checks.py",
        include_str!("../../apps/reviews/checks.py"),
    ),
    (
        "reviews/tools.py",
        include_str!("../../apps/reviews/tools.py"),
    ),
    (
        "reviews/index.tsx",
        include_str!("../../apps/reviews/index.tsx"),
    ),
    (
        "reviews/reviews.css",
        include_str!("../../apps/reviews/reviews.css"),
    ),
    ("tsconfig.json", include_str!("../../apps/tsconfig.json")),
    ("vendor.sh", include_str!("../../apps/vendor.sh")),
    ("vite.config.ts", include_str!("../../apps/vite.config.ts")),
];

/// What a developer's own build leaves in `apps/`. The app writes none of it.
#[cfg(test)]
const BUILT: &[&str] = &["node_modules", "dist", "vendor", "__pycache__"];

/// The services up before the code worker's token exists.
const CONTROL_PLANE: &[&str] = &[
    "control",
    "fetch",
    "browser",
    "files",
    "todo",
    "diagrams",
    "setup-git",
    "setup-files",
];

/// The code worker's volumes, which a reset deletes.
const CODE_VOLUMES: &[&str] = &["fa1_code-claude", "fa1_code-workspaces"];

pub struct Project {
    pub folder: Folder,
    pub port: u16,
}

impl Project {
    /// `docker compose` on the project, with its three variables. A new HEAD of the setup
    /// folder is a new `FA1_SETUP_HEAD`, which starts the designer's git server anew: it
    /// brings the working copy's `main` to that HEAD as it starts.
    fn compose(&self, what: &str, args: &[&str]) -> Action {
        let file = self.folder.compose().join("compose.yaml");
        Action::new(what, "docker", &["compose", "-f"])
            .arg(file.to_string_lossy())
            .env("FA1_PORT", self.port.to_string())
            .env("FA1_SECRETS", self.folder.secrets().to_string_lossy())
            .env("FA1_SETUP_HEAD", setup::published(&self.published()))
            .args_from(args)
    }

    /// Where the setup folder's HEAD is published: `compose/setup/`, which the control plane
    /// and the designer's git server mount.
    pub fn published(&self) -> std::path::PathBuf {
        self.folder.compose().join("setup")
    }

    pub fn build(&self) -> Action {
        self.compose("build the images", &["build"])
    }

    pub fn up_control_plane(&self) -> Action {
        let mut args = vec!["up", "--detach", "--no-build"];
        args.extend_from_slice(CONTROL_PLANE);
        self.compose("start the control plane", &args)
    }

    /// The control plane reads Robinauts' configuration as it starts, so a new setup needs new
    /// containers.
    pub fn up_control_plane_anew(&self) -> Action {
        let mut args = vec!["up", "--detach", "--no-build", "--force-recreate"];
        args.extend_from_slice(CONTROL_PLANE);
        self.compose("start the control plane anew, with the new setup", &args)
    }

    pub fn up_code(&self) -> Action {
        self.compose(
            "start the code worker",
            &["up", "--detach", "--no-build", "code"],
        )
    }

    /// The code worker reads its token and Robinauts' configuration as it starts, so a change to
    /// either needs a new container.
    pub fn up_code_anew(&self) -> Action {
        self.compose(
            "start the code worker anew, with its new token or setup",
            &["up", "--detach", "--no-build", "--force-recreate", "code"],
        )
    }

    pub fn stop(&self) -> Action {
        self.compose("stop everything", &["stop"])
    }

    pub fn ps(&self) -> Action {
        self.compose(
            "list the containers",
            &[
                "ps",
                "--all",
                "--format",
                "{{.Service}}\t{{.State}}\t{{.Status}}",
            ],
        )
    }

    pub fn remove_code(&self) -> Action {
        self.compose(
            "remove the code worker's container",
            &["rm", "--stop", "--force", "code"],
        )
    }

    pub fn remove_code_volumes(&self) -> Action {
        let mut action = Action::new(
            "delete the code worker's volumes",
            "docker",
            &["volume", "rm", "--force"],
        );
        for volume in CODE_VOLUMES {
            action = action.arg(*volume);
        }
        action
    }

    pub fn down_everything(&self) -> Action {
        self.compose(
            "remove the containers, the network, the volumes and the images",
            &["down", "--volumes", "--rmi", "all"],
        )
    }

    /// The actions of a start, in order, as `--plan` prints them. The steps between them are
    /// HTTP requests to the control plane.
    pub fn start_plan(&self) -> Vec<String> {
        let setup_folder = self
            .folder
            .settings()
            .setup_folder
            .unwrap_or_else(|| "(chosen on this screen)".to_string());
        vec![
            format!("read the setup folder {setup_folder}: fa1.toml, models.toml, agents/, flows/"),
            format!(
                "write {}: {}, robinauts.toml, flows/, apps/",
                self.folder.compose().display(),
                FILES.iter().map(|f| f.0).collect::<Vec<_>>().join(", ")
            ),
            format!(
                "write {}: launch, control.env, code.env, files.env, setup.env, worker_token",
                self.folder.secrets().display()
            ),
            format!(
                "git -C {setup_folder} bundle create {} HEAD: the setup folder's HEAD, for the \
                 review app and the designer's working copy",
                self.published().join(setup::BUNDLE).display()
            ),
            self.build().line(),
            format!(
                "{}, or with a new setup: {}",
                self.up_control_plane().line(),
                self.up_control_plane_anew().line()
            ),
            format!(
                "GET http://127.0.0.1:{}/auth/session, until it answers",
                self.port
            ),
            format!(
                "GET http://127.0.0.1:{}/auth/services: is the code worker's token held? If not, \
                 DELETE the old one and POST a new one",
                self.port
            ),
            format!(
                "{}, or with a new token or a new setup: {}",
                self.up_code().line(),
                self.up_code_anew().line()
            ),
            format!(
                "GET http://127.0.0.1:{}/health, until it answers ok",
                self.port
            ),
        ]
    }

    /// Writes the project's files, the setup's and the secrets the start needs. The answer says
    /// whether the setup, Robinauts' configuration or the flows, changed.
    pub fn write(&self, keys: &Keys, setup: &Setup) -> std::io::Result<bool> {
        self.folder.ensure()?;
        let root = self.folder.compose();
        for (name, text) in FILES {
            let path = root.join(name);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            folder::write_file(&path, text, 0o644)?;
        }
        // The applications' folder, written anew: a file a release dropped goes too.
        let apps = root.join("apps");
        if apps.is_dir() {
            fs::remove_dir_all(&apps)?;
        }
        for (name, text) in APPS {
            let path = apps.join(name);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            folder::write_file(&path, text, 0o644)?;
        }
        self.folder.secret_or("launch", folder::launch_secret)?;
        let files_key = self.folder.secret_or("files_key", folder::random_secret)?;
        // One key for the designer's three tool servers.
        let setup_key = self.folder.secret_or("setup_key", folder::random_secret)?;
        self.folder.write_secret(
            "control.env",
            &env_file(&[
                ("FA1_ANTHROPIC_KEY", &keys.anthropic),
                ("FA1_FILES_KEY", &files_key),
                ("FA1_SETUP_KEY", &setup_key),
            ]),
        )?;
        self.folder.write_secret(
            "files.env",
            &env_file(&[("SUPERGATEWAY_API_KEY", &files_key)]),
        )?;
        self.folder.write_secret(
            "setup.env",
            &env_file(&[("SUPERGATEWAY_API_KEY", &setup_key)]),
        )?;
        // Compose mounts this folder: Docker would make a missing one, as root.
        fs::create_dir_all(self.published())?;
        let mut code = vec![
            ("CLAUDE_CODE_OAUTH_TOKEN", keys.claude_code.as_str()),
            ("GITHUB_TOKEN", keys.github.as_str()),
            ("GIT_AUTHOR_NAME", setup.git_name.as_str()),
            ("GIT_AUTHOR_EMAIL", setup.git_email.as_str()),
            ("GIT_COMMITTER_NAME", setup.git_name.as_str()),
            ("GIT_COMMITTER_EMAIL", setup.git_email.as_str()),
        ];
        // The code worker holds the key of a tool server only while an agent of its own uses
        // that server (setup::code_secrets).
        for (name, key) in [
            ("FA1_FILES_KEY", files_key.as_str()),
            ("FA1_SETUP_KEY", setup_key.as_str()),
        ] {
            if setup.code_secrets.iter().any(|wanted| wanted == name) {
                code.push((name, key));
            }
        }
        self.folder.write_secret("code.env", &env_file(&code))?;
        if self.folder.read_secret("worker_token").is_empty() {
            self.folder.write_secret("worker_token", "")?;
        }
        let config = root.join("robinauts.toml");
        let mut changed =
            fs::read_to_string(&config).ok().as_deref() != Some(setup.robinauts_toml.as_str());
        folder::write_file(&config, &setup.robinauts_toml, 0o644)?;
        // The flows' folder, written anew: a file the setup folder dropped goes too.
        let flows = root.join("flows");
        let mut before = Vec::new();
        if flows.is_dir() {
            collect_files(&flows, &flows, &mut before)?;
        }
        before.sort();
        changed |= before != setup.flows;
        if flows.is_dir() {
            fs::remove_dir_all(&flows)?;
        }
        for (path, bytes) in &setup.flows {
            let path = flows.join(path);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(&path, bytes)?;
        }
        Ok(changed)
    }

    /// The setup folder the person chose, read and checked.
    pub fn read_setup(&self) -> Result<Setup, String> {
        let chosen =
            self.folder.settings().setup_folder.ok_or_else(|| {
                "no setup folder yet: choose one on the Welcome screen".to_string()
            })?;
        let at = std::path::Path::new(&chosen);
        setup::read(at).map_err(|e| format!("the setup folder {chosen}: {e}"))
    }

    /// The whole start: the setup folder, the files, the images, the control plane, the token,
    /// the code worker. A changed setup starts the control plane and the code worker anew.
    pub fn start(&self, keys: &Keys, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        say("Reading the setup folder.");
        let setup = self.read_setup()?;
        let setup_changed = self
            .write(keys, &setup)
            .map_err(|e| format!("the app could not write its folder: {e}"))?;
        if let Some(chosen) = self.folder.settings().setup_folder {
            setup::publish(
                std::path::Path::new(&chosen),
                &self.published(),
                &logs,
                &mut *say,
            )?;
        }
        say("Building the images. The first build takes several minutes.");
        self.build().run(&logs, &mut *say)?;
        if setup_changed {
            self.up_control_plane_anew().run(&logs, &mut *say)?;
        } else {
            self.up_control_plane().run(&logs, &mut *say)?;
        }
        say("Waiting for the control plane to answer.");
        control::wait_until_up(self.port, Duration::from_secs(180))?;
        let launch = self.folder.read_secret("launch");
        let held = control::service_tokens(self.port, &launch)?;
        let saved_id = self.folder.read_secret("worker_token_id");
        let saved = self.folder.read_secret("worker_token");
        let new_token = match token_step(&saved_id, &saved, &held) {
            TokenStep::Keep => false,
            TokenStep::Replace { revoke } => {
                say("Creating the code worker's token.");
                for id in revoke {
                    control::revoke_service_token(self.port, &launch, &id)?;
                }
                let (id, token) = control::create_worker_token(self.port, &launch)?;
                self.folder
                    .write_secret("worker_token", &token)
                    .and_then(|_| self.folder.write_secret("worker_token_id", &id))
                    .map_err(|e| format!("the app could not write the worker's token: {e}"))?;
                true
            }
        };
        if new_token || setup_changed {
            self.up_code_anew().run(&logs, &mut *say)?;
        } else {
            self.up_code().run(&logs, &mut *say)?;
        }
        say("Waiting for the code worker to join.");
        for _ in 0..120 {
            if control::health(self.port) == "ok" {
                say("Everything is up.");
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        Err(
            "the code worker did not join within a minute: see its log on the Status screen"
                .to_string(),
        )
    }

    /// What a refresh does to the setup folder before the start: the changelists the person
    /// approved in the review app, then the folder's upstream (docs/specs/setup-folder.md,
    /// "Deploying it"). A folder with changes of its own takes neither.
    pub fn pull_setup(&self, keys: &Keys, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        let chosen = self
            .folder
            .settings()
            .setup_folder
            .ok_or("no setup folder yet: choose one on the Welcome screen")?;
        let at = std::path::Path::new(&chosen);
        if setup::has_changes(at, &logs, &mut *say)? {
            say(
                "The setup folder has changes of its own: it is deployed as it is, without \
                 the approved changes and without a pull.",
            );
            return Ok(());
        }
        let launch = self.folder.read_secret("launch");
        if launch.is_empty() || !control::is_up(self.port) {
            say("The control plane is not running: no approved change is fetched.");
        } else if let Some(bundle) = control::approved_bundle(self.port, &launch)? {
            say("Applying the approved changes to the setup folder.");
            let downloads = self.folder.downloads();
            fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
            let file = downloads.join("approved.bundle");
            fs::write(&file, bundle).map_err(|e| format!("{}: {e}", file.display()))?;
            setup::apply_approved(at, &file, &logs, &mut *say).map_err(|refused| {
                format!(
                    "{refused}\nThe setup folder holds commits the approved change does not \
                     start from. Merge it by hand: git -C {chosen} merge FETCH_HEAD. Then \
                     press Refresh again."
                )
            })?;
        } else {
            say("No approved change waits for the setup folder.");
        }
        setup::pull(at, &keys.github, &logs, say)
    }

    pub fn reset_code(&self, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        self.remove_code().run(&logs, &mut *say)?;
        self.remove_code_volumes().run(&logs, &mut *say)?;
        self.up_code().run(&logs, &mut *say)?;
        Ok(())
    }
}

/// Every file under `dir`, by its path from `root`, with its bytes.
fn collect_files(
    root: &std::path::Path,
    dir: &std::path::Path,
    into: &mut Vec<(std::path::PathBuf, Vec<u8>)>,
) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        if path.is_dir() {
            collect_files(root, &path, into)?;
        } else {
            let inside = path.strip_prefix(root).map_err(std::io::Error::other)?;
            into.push((inside.to_path_buf(), fs::read(&path)?));
        }
    }
    Ok(())
}

/// What a start does about the code worker's token.
#[derive(Debug, PartialEq)]
pub enum TokenStep {
    /// The control plane holds the saved token: the worker keeps it.
    Keep,
    /// The control plane lost the saved token, at a stop, or the folder has none. The start
    /// revokes the worker's tokens left in the control plane, by id, and makes a new one.
    Replace { revoke: Vec<String> },
}

/// Decides from the saved token's id and secret, and the tokens the control plane holds.
pub fn token_step(saved_id: &str, saved: &str, held: &[control::ServiceToken]) -> TokenStep {
    if !saved_id.is_empty() && !saved.is_empty() && held.iter().any(|t| t.id == saved_id) {
        return TokenStep::Keep;
    }
    TokenStep::Replace {
        revoke: held
            .iter()
            .filter(|t| t.name == control::WORKER_TOKEN_NAME)
            .map(|t| t.id.clone())
            .collect(),
    }
}

/// `NAME=value` lines, as `docker compose` reads them, without quotes. A variable with no value
/// is left out: the code worker refuses an empty `GITHUB_TOKEN`.
fn env_file(pairs: &[(&str, &str)]) -> String {
    pairs
        .iter()
        .filter(|(_, value)| !value.trim().is_empty())
        .map(|(name, value)| format!("{name}={}\n", value.trim()))
        .collect()
}

trait ArgsFrom {
    fn args_from(self, args: &[&str]) -> Self;
}

impl ArgsFrom for Action {
    fn args_from(mut self, args: &[&str]) -> Self {
        self.args.extend(args.iter().map(|a| a.to_string()));
        self
    }
}

#[cfg(test)]
mod tests {
    use super::{APPS, BUILT, TokenStep, collect_files, env_file, token_step};
    use crate::control::{ServiceToken, WORKER_TOKEN_NAME};

    #[test]
    fn the_app_writes_every_file_of_the_applications() {
        let apps = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../apps");
        let mut found = Vec::new();
        collect_files(&apps, &apps, &mut found).unwrap();
        let mut found: Vec<String> = found
            .iter()
            .map(|(path, _)| path.to_string_lossy().replace('\\', "/"))
            .filter(|path| !path.split('/').any(|part| BUILT.contains(&part)))
            .collect();
        found.sort();
        let mut written: Vec<String> = APPS.iter().map(|(name, _)| name.to_string()).collect();
        written.sort();
        assert_eq!(written, found);
    }

    fn held(id: &str, name: &str) -> ServiceToken {
        ServiceToken {
            id: id.to_string(),
            name: name.to_string(),
        }
    }

    #[test]
    fn a_start_keeps_the_token_the_control_plane_holds_and_replaces_any_other() {
        let worker = |id: &str| held(id, WORKER_TOKEN_NAME);
        let other = held("o", "a-person's-script");
        let replace = |ids: &[&str]| TokenStep::Replace {
            revoke: ids.iter().map(|i| i.to_string()).collect(),
        };
        // (saved id, saved secret, held) -> step
        let cases = [
            // Held: the control plane kept running.
            (
                "a",
                "ob_svc_a",
                vec![worker("a"), other.clone()],
                TokenStep::Keep,
            ),
            // The control plane stopped: it holds no token.
            ("a", "ob_svc_a", vec![], replace(&[])),
            // The first start, and a folder from before the id was saved.
            ("", "", vec![], replace(&[])),
            ("", "ob_svc_a", vec![worker("a")], replace(&["a"])),
            // The secret is gone from the folder, and its token is still held.
            ("a", "", vec![worker("a")], replace(&["a"])),
            // Another worker token is held: it goes. Other tokens stay.
            (
                "a",
                "ob_svc_a",
                vec![worker("b"), other.clone()],
                replace(&["b"]),
            ),
        ];
        for (saved_id, saved, held, expected) in cases {
            assert_eq!(
                token_step(saved_id, saved, &held),
                expected,
                "saved {saved_id:?} {saved:?}, held {held:?}"
            );
        }
    }

    #[test]
    fn an_env_file_leaves_out_the_variables_without_a_value() {
        let cases: &[(&[(&str, &str)], &str)] = &[
            (&[("A", "1"), ("B", "")], "A=1\n"),
            (&[("A", " 1 "), ("B", "   ")], "A=1\n"),
            (&[("NAME", "Ada Lovelace")], "NAME=Ada Lovelace\n"),
            (&[], ""),
        ];
        for (pairs, expected) in cases {
            assert_eq!(env_file(pairs), *expected);
        }
    }
}
