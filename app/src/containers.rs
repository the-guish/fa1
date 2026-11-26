//! Mode 2: the Compose project `fa1` (docs/specs/containers.md). Its files are built into the app
//! and written to `compose/` in the folder at each start.

use std::fs;
use std::time::Duration;

use crate::actions::Action;
use crate::control;
use crate::folder::{self, Folder, Keys};
use crate::local_servers;
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
    (
        "setup-tools/git_server.py",
        include_str!("../../compose/setup-tools/git_server.py"),
    ),
];

/// The Cursor worker's build context, as this repository's `workers/cursor/` holds it
/// (docs/specs/cursor-worker.md). It is written to `compose/workers/cursor/`.
const CURSOR_WORKER: &[(&str, &str)] = &[
    (
        "Dockerfile",
        include_str!("../../workers/cursor/Dockerfile"),
    ),
    (
        "pyproject.toml",
        include_str!("../../workers/cursor/pyproject.toml"),
    ),
    (
        "src/fa1_cursor_worker/__init__.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/__init__.py"),
    ),
    (
        "src/fa1_cursor_worker/__main__.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/__main__.py"),
    ),
    (
        "src/fa1_cursor_worker/checkpoints.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/checkpoints.py"),
    ),
    (
        "src/fa1_cursor_worker/engine.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/engine.py"),
    ),
    (
        "src/fa1_cursor_worker/events.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/events.py"),
    ),
    (
        "src/fa1_cursor_worker/functions.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/functions.py"),
    ),
    (
        "src/fa1_cursor_worker/settings.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/settings.py"),
    ),
    (
        "src/fa1_cursor_worker/tools.py",
        include_str!("../../workers/cursor/src/fa1_cursor_worker/tools.py"),
    ),
];

/// FA1's applications and its host of them, as this repository's `apps/` holds them
/// (docs/specs/apps.md). They are written to `compose/apps/`, the build context of `control`.
const APPS: &[(&str, &str)] = &[
    (".dockerignore", include_str!("../../apps/.dockerignore")),
    (".npmrc", include_str!("../../apps/.npmrc")),
    ("Dockerfile", include_str!("../../apps/Dockerfile")),
    ("Fallback.tsx", include_str!("../../apps/Fallback.tsx")),
    ("backend.py", include_str!("../../apps/backend.py")),
    ("fallback.css", include_str!("../../apps/fallback.css")),
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

/// The code workers' volumes, which a reset deletes.
const CODE_VOLUMES: &[&str] = &[
    "fa1_code-claude",
    "fa1_code-workspaces",
    "fa1_cursor-home",
    "fa1_cursor-workspaces",
];

/// The Compose profile of the Cursor worker's service. A build leaves the service out without
/// it, so a person with no Cursor API key downloads no Cursor CLI.
const CURSOR_PROFILE: &str = "cursor";

pub struct Project {
    pub folder: Folder,
    pub port: u16,
}

impl Project {
    /// `docker compose` on the project, with its variables. The services that reach the setup
    /// folder mount it, and run as its owner (docs/specs/containers.md, "The setup folder").
    /// Before the person chose a folder, the variables name the app's own: Compose reads them
    /// for every command, and no service starts then.
    fn compose(&self, what: &str, args: &[&str]) -> Action {
        self.compose_with(what, true, args)
    }

    /// `cursor` says whether the command covers the Cursor worker's service too. Every command
    /// does, but the build of a start without that worker.
    fn compose_with(&self, what: &str, cursor: bool, args: &[&str]) -> Action {
        let file = self.folder.compose().join("compose.yaml");
        let chosen = self
            .folder
            .settings()
            .setup_folder
            .map(std::path::PathBuf::from);
        let (uid, gid) = chosen
            .as_deref()
            .and_then(setup::owner)
            .or_else(|| setup::owner(&self.folder.root))
            .unwrap_or((1000, 1000));
        let setup = chosen.unwrap_or_else(|| self.folder.compose().join("no-setup-folder"));
        let mut action =
            Action::new(what, "docker", &["compose", "-f"]).arg(file.to_string_lossy());
        // The setup folder's local MCP servers, once a start wrote their file.
        let local = self.folder.compose().join(local_servers::COMPOSE_FILE);
        if local.is_file() {
            action = action.arg("-f").arg(local.to_string_lossy());
        }
        if cursor {
            action = action.arg("--profile").arg(CURSOR_PROFILE);
        }
        action
            .env("FA1_PORT", self.port.to_string())
            .env("FA1_SECRETS", self.folder.secrets().to_string_lossy())
            .env("FA1_SETUP", setup.to_string_lossy())
            .env("FA1_UID", uid.to_string())
            .env("FA1_GID", gid.to_string())
            .args_from(args)
    }

    /// `cursor` says whether the Cursor worker runs, and so whether its image is built.
    pub fn build(&self, cursor: bool) -> Action {
        self.compose_with("build the images", cursor, &["build"])
    }

    /// `local` are the services of the setup folder's local MCP servers, which start with the
    /// control plane. A server the setup folder no longer holds leaves an orphan container,
    /// which goes.
    pub fn up_control_plane(&self, local: &[String]) -> Action {
        let mut args = vec!["up", "--detach", "--no-build", "--remove-orphans"];
        args.extend_from_slice(CONTROL_PLANE);
        args.extend(local.iter().map(String::as_str));
        self.compose("start the control plane", &args)
    }

    /// The control plane reads Robinauts' configuration as it starts, so a new setup needs new
    /// containers.
    pub fn up_control_plane_anew(&self, local: &[String]) -> Action {
        let mut args = vec![
            "up",
            "--detach",
            "--no-build",
            "--remove-orphans",
            "--force-recreate",
        ];
        args.extend_from_slice(CONTROL_PLANE);
        args.extend(local.iter().map(String::as_str));
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

    pub fn up_cursor(&self) -> Action {
        self.compose(
            "start the Cursor worker",
            &["up", "--detach", "--no-build", "cursor"],
        )
    }

    /// The Cursor worker reads its token, its key and Robinauts' configuration as it starts.
    pub fn up_cursor_anew(&self) -> Action {
        self.compose(
            "start the Cursor worker anew, with its new token or setup",
            &["up", "--detach", "--no-build", "--force-recreate", "cursor"],
        )
    }

    /// Without a Cursor API key, or an agent on Cursor, the Cursor worker's container goes:
    /// Robinauts' configuration names it no more.
    pub fn remove_cursor(&self) -> Action {
        self.compose(
            "remove the Cursor worker's container",
            &["rm", "--stop", "--force", "cursor"],
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
            "remove the code workers' containers",
            &["rm", "--stop", "--force", "code", "cursor"],
        )
    }

    pub fn remove_code_volumes(&self) -> Action {
        let mut action = Action::new(
            "delete the code workers' volumes",
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
            format!(
                "read the setup folder {setup_folder}: fa1.toml, models.toml, agents/, flows/, \
                 local-mcp-servers/"
            ),
            format!(
                "write {}: {}, robinauts.toml, flows/, apps/, workers/cursor/, \
                 local-mcp-servers/, {}",
                self.folder.compose().display(),
                FILES.iter().map(|f| f.0).collect::<Vec<_>>().join(", "),
                local_servers::COMPOSE_FILE
            ),
            format!(
                "write {}: launch, control.env, code.env, cursor.env, files.env, setup.env, \
                 worker_token, cursor_token, and mcp-<id>.env and mcp-<id>.key per local MCP \
                 server",
                self.folder.secrets().display()
            ),
            format!(
                "mount {setup_folder} in the control plane, for the review app, and read-only in \
                 the designer's git server"
            ),
            format!(
                "{}, or with a Cursor API key and an agent on Cursor: {}",
                self.build(false).line(),
                self.build(true).line()
            ),
            format!(
                "{} mcp-<id>..., or with a new setup: {} mcp-<id>...",
                self.up_control_plane(&[]).line(),
                self.up_control_plane_anew(&[]).line()
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
                "with a Cursor API key and an agent on Cursor, the same token step, then: {}; \
                 otherwise: {}",
                self.up_cursor().line(),
                self.remove_cursor().line()
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
        // The Cursor worker's build context, written anew.
        let cursor_worker = root.join("workers").join("cursor");
        if cursor_worker.is_dir() {
            fs::remove_dir_all(&cursor_worker)?;
        }
        for (name, text) in CURSOR_WORKER {
            let path = cursor_worker.join(name);
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
        // The keyed tool servers, by the variable that holds each key: FA1's, then the local
        // MCP servers' access keys (docs/specs/local-mcp-servers.md).
        let mut keyed = vec![
            ("FA1_FILES_KEY".to_string(), files_key.clone()),
            ("FA1_SETUP_KEY".to_string(), setup_key.clone()),
        ];
        // The local servers' folders, written anew: a server the setup folder dropped goes.
        let local_root = root.join(local_servers::FOLDER);
        if local_root.is_dir() {
            fs::remove_dir_all(&local_root)?;
        }
        for server in &setup.local_servers {
            for (path, bytes, executable) in &server.files {
                let path = local_root.join(&server.id).join(path);
                if let Some(parent) = path.parent() {
                    fs::create_dir_all(parent)?;
                }
                // The build copies each file with its mode: a script the image runs keeps
                // its mark.
                folder::write_bytes(&path, bytes, if *executable { 0o755 } else { 0o644 })?;
            }
            let access = self
                .folder
                .secret_or(&server.key_file(), folder::random_secret)?;
            let given = keys.servers.get(&server.id).cloned().unwrap_or_default();
            let env = local_servers::container_env(server, &access, &given);
            let pairs: Vec<(&str, &str)> =
                env.iter().map(|(n, v)| (n.as_str(), v.as_str())).collect();
            self.folder
                .write_secret(&server.env_file(), &quoted_env_file(&pairs))?;
            keyed.push((server.variable(), access));
        }
        // The variables of a server that no longer runs go, its secrets with them. Its access
        // key stays, for the day it comes back.
        let running: Vec<String> = setup.local_servers.iter().map(|s| s.env_file()).collect();
        for entry in fs::read_dir(self.folder.secrets())?.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("mcp-") && name.ends_with(".env") && !running.contains(&name) {
                fs::remove_file(entry.path())?;
            }
        }
        folder::write_file(
            &root.join(local_servers::COMPOSE_FILE),
            &local_servers::compose_yaml(&setup.local_servers),
            0o644,
        )?;
        self.folder
            .write_secret("control.env", &control_env(keys, &keyed))?;
        self.folder.write_secret(
            "files.env",
            &env_file(&[("SUPERGATEWAY_API_KEY", &files_key)]),
        )?;
        self.folder.write_secret(
            "setup.env",
            &env_file(&[("SUPERGATEWAY_API_KEY", &setup_key)]),
        )?;
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
        for (name, key) in &keyed {
            if setup.code_secrets.contains(name) {
                code.push((name, key));
            }
        }
        self.folder.write_secret("code.env", &env_file(&code))?;
        // The Cursor worker's variables: the Cursor API key, then the same as the code worker's.
        // Compose reads the file for every command, so it is written without that worker too.
        let mut cursor = vec![
            ("CURSOR_API_KEY", keys.cursor.as_str()),
            ("GITHUB_TOKEN", keys.github.as_str()),
            ("GIT_AUTHOR_NAME", setup.git_name.as_str()),
            ("GIT_AUTHOR_EMAIL", setup.git_email.as_str()),
            ("GIT_COMMITTER_NAME", setup.git_name.as_str()),
            ("GIT_COMMITTER_EMAIL", setup.git_email.as_str()),
        ];
        for (name, key) in &keyed {
            if setup.cursor_secrets.contains(name) {
                cursor.push((name, key));
            }
        }
        let cursor = if setup.cursor { cursor } else { Vec::new() };
        self.folder.write_secret("cursor.env", &env_file(&cursor))?;
        for token in [control::CODE.token_file, control::CURSOR.token_file] {
            if self.folder.read_secret(token).is_empty() {
                self.folder.write_secret(token, "")?;
            }
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
        let cursor_key = !self.folder.keys().cursor.is_empty();
        setup::read(at, cursor_key, &self.folder.keys().servers)
            .map_err(|e| format!("the setup folder {chosen}: {e}"))
    }

    /// The whole start: the setup folder, the files, the images, the control plane, the token,
    /// the code worker. A changed setup starts the control plane and the code worker anew.
    pub fn start(&self, keys: &Keys, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        say("Reading the setup folder.");
        let setup = self.read_setup()?;
        if !setup.left_out.is_empty() {
            say(&format!(
                "No Cursor API key on the Keys screen: the agents on Cursor are left out ({}).",
                setup.left_out.join(", ")
            ));
        }
        for (id, missing) in &setup.missing_keys {
            say(&format!(
                "The local MCP server {id} waits for its keys on the Keys screen: {}.",
                missing.join(", ")
            ));
        }
        if !setup.left_out_for_keys.is_empty() {
            say(&format!(
                "The agents that use it are left out until then ({}).",
                setup.left_out_for_keys.join(", ")
            ));
        }
        let local: Vec<String> = setup.local_servers.iter().map(|s| s.service()).collect();
        let setup_changed = self
            .write(keys, &setup)
            .map_err(|e| format!("the app could not write its folder: {e}"))?;
        if let Some(chosen) = self.folder.settings().setup_folder
            && setup::head(std::path::Path::new(&chosen), &logs).is_empty()
        {
            say(
                "The setup folder has no commit yet: commit it, and the Flow designer can propose changes.",
            );
        }
        say("Building the images. The first build takes several minutes.");
        self.build(setup.cursor).run(&logs, &mut *say)?;
        if setup_changed {
            self.up_control_plane_anew(&local).run(&logs, &mut *say)?;
        } else {
            self.up_control_plane(&local).run(&logs, &mut *say)?;
        }
        say("Waiting for the control plane to answer.");
        control::wait_until_up(self.port, Duration::from_secs(180))?;
        let launch = self.folder.read_secret("launch");
        say("Checking the code worker's token.");
        if self.worker_token(control::CODE, &launch)? || setup_changed {
            self.up_code_anew().run(&logs, &mut *say)?;
        } else {
            self.up_code().run(&logs, &mut *say)?;
        }
        if setup.cursor {
            say("Checking the Cursor worker's token.");
            if self.worker_token(control::CURSOR, &launch)? || setup_changed {
                self.up_cursor_anew().run(&logs, &mut *say)?;
            } else {
                self.up_cursor().run(&logs, &mut *say)?;
            }
        } else {
            self.remove_cursor().run(&logs, &mut *say)?;
        }
        say("Waiting for the code workers to join.");
        for _ in 0..120 {
            if control::health(self.port) == "ok" {
                say("Everything is up.");
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(500));
        }
        Err(
            "a code worker did not join within a minute: see the logs on the Status screen"
                .to_string(),
        )
    }

    /// The token step of a start, for one worker (docs/specs/containers.md, "Starting"): keeps
    /// the token the control plane holds, or makes a new one. The answer says whether the
    /// token is new, which the worker reads only as it starts.
    fn worker_token(&self, worker: control::Worker, launch: &str) -> Result<bool, String> {
        let held = control::service_tokens(self.port, launch)?;
        let saved_id = self.folder.read_secret(worker.token_id_file);
        let saved = self.folder.read_secret(worker.token_file);
        match token_step(&saved_id, &saved, &held, worker.token_name) {
            TokenStep::Keep => Ok(false),
            TokenStep::Replace { revoke } => {
                for id in revoke {
                    control::revoke_service_token(self.port, launch, &id)?;
                }
                let (id, token) = control::create_worker_token(self.port, launch, worker)?;
                self.folder
                    .write_secret(worker.token_file, &token)
                    .and_then(|_| self.folder.write_secret(worker.token_id_file, &id))
                    .map_err(|e| format!("the app could not write the worker's token: {e}"))?;
                Ok(true)
            }
        }
    }

    /// What a refresh does to the setup folder before the start: a pull of the folder's upstream
    /// (docs/specs/setup-folder.md, "Deploying it"). A folder with changes of its own takes
    /// none. An approved changelist is in the folder already: the review app put it there.
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
                "The setup folder has changes of its own: it is deployed as it is, without a pull.",
            );
            return Ok(());
        }
        setup::pull(at, &keys.github, &logs, say)
    }

    pub fn reset_code(&self, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        self.remove_code().run(&logs, &mut *say)?;
        self.remove_code_volumes().run(&logs, &mut *say)?;
        self.up_code().run(&logs, &mut *say)?;
        if self.read_setup().is_ok_and(|setup| setup.cursor) {
            self.up_cursor().run(&logs, &mut *say)?;
        }
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

/// What a start does about a worker's token.
#[derive(Debug, PartialEq)]
pub enum TokenStep {
    /// The control plane holds the saved token: the worker keeps it.
    Keep,
    /// The control plane lost the saved token, at a stop, or the folder has none. The start
    /// revokes the worker's tokens left in the control plane, by id, and makes a new one.
    Replace { revoke: Vec<String> },
}

/// Decides from the saved token's id and secret, and the tokens the control plane holds. `name`
/// is the name of the worker's tokens.
pub fn token_step(
    saved_id: &str,
    saved: &str,
    held: &[control::ServiceToken],
    name: &str,
) -> TokenStep {
    if !saved_id.is_empty() && !saved.is_empty() && held.iter().any(|t| t.id == saved_id) {
        return TokenStep::Keep;
    }
    TokenStep::Replace {
        revoke: held
            .iter()
            .filter(|t| t.name == name)
            .map(|t| t.id.clone())
            .collect(),
    }
}

/// The variables of `control`: the Anthropic API key, the GitHub token, and the key of each
/// keyed tool server, by its variable. The GitHub token is `GH_TOKEN` there, which Robinauts
/// hands the flows' handlers with the rest of the server's environment: a handler reads GitHub
/// with it (docs/specs/containers.md, "Secrets"). Robinauts keeps the tool servers' keys from
/// the handlers, since its configuration names them.
fn control_env(keys: &Keys, keyed: &[(String, String)]) -> String {
    let mut pairs = vec![
        ("FA1_ANTHROPIC_KEY", keys.anthropic.as_str()),
        ("GH_TOKEN", keys.github.as_str()),
    ];
    pairs.extend(keyed.iter().map(|(n, k)| (n.as_str(), k.as_str())));
    env_file(&pairs)
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

/// `NAME="value"` lines, each value as the person typed it. Compose reads `$` in an env file as
/// the start of a variable, and ` #` as the start of a comment, but in a double-quoted value
/// only where `\$`, `\"` and `\\` do not escape them.
fn quoted_env_file(pairs: &[(&str, &str)]) -> String {
    pairs
        .iter()
        .map(|(name, value)| {
            let escaped = value
                .replace('\\', "\\\\")
                .replace('"', "\\\"")
                .replace('$', "\\$");
            format!("{name}=\"{escaped}\"\n")
        })
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
    use super::{
        APPS, BUILT, CURSOR_WORKER, TokenStep, collect_files, control_env, env_file,
        quoted_env_file, token_step,
    };
    use crate::control::{CODE, CURSOR, ServiceToken};
    use crate::folder::Keys;

    #[test]
    fn the_app_writes_every_file_of_the_cursor_worker() {
        let worker = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../workers/cursor");
        let mut found = Vec::new();
        collect_files(&worker, &worker, &mut found).unwrap();
        let mut found: Vec<String> = found
            .iter()
            .map(|(path, _)| path.to_string_lossy().replace('\\', "/"))
            .filter(|path| !path.split('/').any(|part| BUILT.contains(&part)))
            .collect();
        found.sort();
        let mut written: Vec<String> = CURSOR_WORKER.iter().map(|(n, _)| n.to_string()).collect();
        written.sort();
        assert_eq!(written, found);
    }

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
        let worker = |id: &str| held(id, CODE.token_name);
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
            // The Cursor worker's token is another worker's: it stays.
            (
                "a",
                "ob_svc_a",
                vec![held("c", CURSOR.token_name)],
                replace(&[]),
            ),
        ];
        for (saved_id, saved, held, expected) in cases {
            assert_eq!(
                token_step(saved_id, saved, &held, CODE.token_name),
                expected,
                "saved {saved_id:?} {saved:?}, held {held:?}"
            );
        }
    }

    #[test]
    fn a_quoted_env_file_keeps_every_character_of_a_value() {
        // (the value typed) -> the line Compose reads back as that value: verified with
        // `docker compose run` and printenv, Compose 2.26.
        let cases = [
            ("plain", r#"K="plain""#),
            ("pa$word", r#"K="pa\$word""#),
            ("pa${HOME}x", r#"K="pa\${HOME}x""#),
            ("pass #word", r#"K="pass #word""#),
            (r#"it's "q" \ end"#, r#"K="it's \"q\" \\ end""#),
            (r"\n", r#"K="\\n""#),
        ];
        for (value, line) in cases {
            assert_eq!(
                quoted_env_file(&[("K", value)]),
                format!("{line}\n"),
                "{value}"
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

    #[test]
    fn the_control_plane_holds_the_github_token_as_gh_token() {
        // The Anthropic API key, the GitHub token, then the variables expected.
        let cases = [
            (
                "sk-ant-1",
                "github_pat_1",
                "FA1_ANTHROPIC_KEY=sk-ant-1\nGH_TOKEN=github_pat_1\nFA1_FILES_KEY=f\nFA1_SETUP_KEY=s\n",
            ),
            (
                "sk-ant-1",
                "",
                "FA1_ANTHROPIC_KEY=sk-ant-1\nFA1_FILES_KEY=f\nFA1_SETUP_KEY=s\n",
            ),
            (
                "",
                " github_pat_1 ",
                "GH_TOKEN=github_pat_1\nFA1_FILES_KEY=f\nFA1_SETUP_KEY=s\n",
            ),
        ];
        for (anthropic, github, expected) in cases {
            let keys = Keys {
                anthropic: anthropic.to_string(),
                github: github.to_string(),
                ..Keys::default()
            };
            assert_eq!(
                control_env(
                    &keys,
                    &[
                        ("FA1_FILES_KEY".to_string(), "f".to_string()),
                        ("FA1_SETUP_KEY".to_string(), "s".to_string())
                    ]
                ),
                expected,
                "{anthropic:?} {github:?}"
            );
        }
    }
}
