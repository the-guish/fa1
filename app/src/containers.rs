//! Mode 2: the Compose project `fa1` (docs/specs/containers.md). Its files are built into the app
//! and written to `compose/` in the folder at each start.

use std::fs;
use std::time::Duration;

use crate::actions::Action;
use crate::control;
use crate::folder::{self, Folder, Keys};

/// The project's files, as this repository's `compose/` holds them.
const FILES: &[(&str, &str)] = &[
    ("compose.yaml", include_str!("../../compose/compose.yaml")),
    (
        "robinauts.toml",
        include_str!("../../compose/robinauts.toml"),
    ),
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
];

/// The services up before the code worker's token exists.
const CONTROL_PLANE: &[&str] = &["control", "fetch", "browser", "files", "todo", "diagrams"];

/// The code worker's volumes, which a reset deletes.
const CODE_VOLUMES: &[&str] = &["fa1_code-claude", "fa1_code-workspaces"];

pub struct Project {
    pub folder: Folder,
    pub port: u16,
}

impl Project {
    /// `docker compose` on the project, with its two variables.
    fn compose(&self, what: &str, args: &[&str]) -> Action {
        let file = self.folder.compose().join("compose.yaml");
        Action::new(what, "docker", &["compose", "-f"])
            .arg(file.to_string_lossy())
            .env("FA1_PORT", self.port.to_string())
            .env("FA1_SECRETS", self.folder.secrets().to_string_lossy())
            .args_from(args)
    }

    pub fn build(&self) -> Action {
        self.compose("build the images", &["build"])
    }

    pub fn up_control_plane(&self) -> Action {
        let mut args = vec!["up", "--detach", "--no-build"];
        args.extend_from_slice(CONTROL_PLANE);
        self.compose("start the control plane", &args)
    }

    pub fn up_code(&self) -> Action {
        self.compose(
            "start the code worker",
            &["up", "--detach", "--no-build", "code"],
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
        vec![
            format!(
                "write {}: {}",
                self.folder.compose().display(),
                FILES.iter().map(|f| f.0).collect::<Vec<_>>().join(", ")
            ),
            format!(
                "write {}: launch, control.env, code.env, files.env, worker_token",
                self.folder.secrets().display()
            ),
            self.build().line(),
            self.up_control_plane().line(),
            format!(
                "GET http://127.0.0.1:{}/auth/session, until it answers",
                self.port
            ),
            format!(
                "POST http://127.0.0.1:{}/auth/services, once: the code worker's token",
                self.port
            ),
            self.up_code().line(),
            format!(
                "GET http://127.0.0.1:{}/health, until it answers ok",
                self.port
            ),
        ]
    }

    /// Writes the project's files and the secrets the start needs.
    pub fn write(&self, keys: &Keys) -> std::io::Result<()> {
        self.folder.ensure()?;
        let root = self.folder.compose();
        for (name, text) in FILES {
            let path = root.join(name);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            folder::write_file(&path, text, 0o644)?;
        }
        self.folder.secret_or("launch", folder::launch_secret)?;
        let files_key = self.folder.secret_or("files_key", folder::random_secret)?;
        self.folder.write_secret(
            "control.env",
            &env_file(&[
                ("FA1_ANTHROPIC_KEY", &keys.anthropic),
                ("FA1_FILES_KEY", &files_key),
            ]),
        )?;
        self.folder.write_secret(
            "files.env",
            &env_file(&[("SUPERGATEWAY_API_KEY", &files_key)]),
        )?;
        self.folder.write_secret(
            "code.env",
            &env_file(&[
                ("CLAUDE_CODE_OAUTH_TOKEN", &keys.claude_code),
                ("GITHUB_TOKEN", &keys.github),
                ("GIT_AUTHOR_NAME", &keys.git_name),
                ("GIT_AUTHOR_EMAIL", &keys.git_email),
                ("GIT_COMMITTER_NAME", &keys.git_name),
                ("GIT_COMMITTER_EMAIL", &keys.git_email),
            ]),
        )?;
        if self.folder.read_secret("worker_token").is_empty() {
            self.folder.write_secret("worker_token", "")?;
        }
        Ok(())
    }

    /// The whole start: the files, the images, the control plane, the token, the code worker.
    pub fn start(&self, keys: &Keys, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        self.write(keys)
            .map_err(|e| format!("the app could not write its folder: {e}"))?;
        say("Building the images. The first build takes several minutes.");
        self.build().run(&logs, &mut *say)?;
        self.up_control_plane().run(&logs, &mut *say)?;
        say("Waiting for the control plane to answer.");
        control::wait_until_up(self.port, Duration::from_secs(180))?;
        let launch = self.folder.read_secret("launch");
        if self.folder.read_secret("worker_token").is_empty() {
            say("Creating the code worker's token.");
            let token = control::create_worker_token(self.port, &launch)?;
            self.folder
                .write_secret("worker_token", &token)
                .map_err(|e| format!("the app could not write the worker's token: {e}"))?;
        }
        self.up_code().run(&logs, &mut *say)?;
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

    pub fn reset_code(&self, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        self.remove_code().run(&logs, &mut *say)?;
        self.remove_code_volumes().run(&logs, &mut *say)?;
        self.up_code().run(&logs, &mut *say)?;
        Ok(())
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
    use super::env_file;

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
