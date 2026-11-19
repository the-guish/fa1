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

    /// The code worker reads its token and its repositories as it starts, so a change to either
    /// needs a new container.
    pub fn up_code_anew(&self) -> Action {
        self.compose(
            "start the code worker anew, with its new token or repositories",
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
                "GET http://127.0.0.1:{}/auth/services: is the code worker's token held? If not, \
                 DELETE the old one and POST a new one",
                self.port
            ),
            format!(
                "{}, or with a new token or new repositories: {}",
                self.up_code().line(),
                self.up_code_anew().line()
            ),
            format!(
                "GET http://127.0.0.1:{}/health, until it answers ok",
                self.port
            ),
        ]
    }

    /// Writes the project's files and the secrets the start needs. The answer says whether
    /// `flows.toml`, the repositories, changed.
    pub fn write(&self, keys: &Keys) -> std::io::Result<bool> {
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
        // Always written: Docker makes a folder of a missing file it mounts.
        let flows = flows_toml(&keys.repositories).map_err(std::io::Error::other)?;
        let path = root.join("flows.toml");
        let changed = fs::read_to_string(&path).ok().as_deref() != Some(flows.as_str());
        folder::write_file(&path, &flows, 0o644)?;
        Ok(changed)
    }

    /// The whole start: the files, the images, the control plane, the token, the code worker.
    pub fn start(&self, keys: &Keys, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        let repositories_changed = self
            .write(keys)
            .map_err(|e| format!("the app could not write its folder: {e}"))?;
        say("Building the images. The first build takes several minutes.");
        self.build().run(&logs, &mut *say)?;
        self.up_control_plane().run(&logs, &mut *say)?;
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
        if new_token || repositories_changed {
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

    pub fn reset_code(&self, say: &mut dyn FnMut(&str)) -> Result<(), String> {
        let logs = self.folder.logs();
        self.remove_code().run(&logs, &mut *say)?;
        self.remove_code_volumes().run(&logs, &mut *say)?;
        self.up_code().run(&logs, &mut *say)?;
        Ok(())
    }
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

/// `flows.toml` for the repositories the person typed: one per line, `owner/name` or
/// `https://github.com/owner/name`, then the branches a code task may start from, `main` without
/// any. Blank lines and lines from `#` are left out. The error names the line and what is wrong.
pub fn flows_toml(typed: &str) -> Result<String, String> {
    let mut repositories = toml::Table::new();
    for (number, line) in typed.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut words = line.split_whitespace();
        let source = words.next().unwrap_or_default();
        let (owner, name) = github_repository(source)
            .ok_or_else(|| format!("line {}: {source} is not a repository on GitHub: write owner/name, or https://github.com/owner/name", number + 1))?;
        if repositories.contains_key(&name) {
            return Err(format!(
                "line {}: a second repository named {name}: the agents' folders are named after it",
                number + 1
            ));
        }
        let mut branches: Vec<String> = words.map(str::to_string).collect();
        if let Some(bad) = branches.iter().find(|b| !is_branch_name(b)) {
            return Err(format!("line {}: {bad} is not a branch name", number + 1));
        }
        if branches.is_empty() {
            branches.push("main".to_string());
        }
        let mut table = toml::Table::new();
        table.insert(
            "url".to_string(),
            format!("https://github.com/{owner}/{name}").into(),
        );
        table.insert("branches".to_string(), branches.into());
        repositories.insert(name, table.into());
    }
    let mut settings = toml::Table::new();
    if !repositories.is_empty() {
        settings.insert("repositories".to_string(), repositories.into());
    }
    let body = toml::to_string(&settings).map_err(|e| e.to_string())?;
    Ok(format!(
        "# Written by FA1 at each start, from the repositories of its Keys screen.\n{body}"
    ))
}

/// The owner and name of a repository on GitHub: `owner/name`, or its https URL, with or without
/// `.git`. `None` for another host, credentials, or a path that is not a repository's.
fn github_repository(source: &str) -> Option<(String, String)> {
    let path = match source.strip_prefix("https://github.com/") {
        Some(path) => path.trim_end_matches('/'),
        None if source.contains("://") || source.contains('@') => return None,
        None => source,
    };
    let (owner, name) = path.split_once('/')?;
    let name = name.strip_suffix(".git").unwrap_or(name);
    let owner_ok =
        !owner.is_empty() && owner.chars().all(|c| c.is_ascii_alphanumeric() || c == '-');
    let name_ok = !name.is_empty()
        && name != "."
        && name != ".."
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'));
    (owner_ok && name_ok).then(|| (owner.to_string(), name.to_string()))
}

/// A branch name git takes and Robinauts accepts: no `@`, no spaces, no quotes or backslashes.
fn is_branch_name(branch: &str) -> bool {
    !branch.is_empty()
        && !branch.starts_with('-')
        && !branch.contains("..")
        && branch
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '/'))
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
    use super::{TokenStep, env_file, flows_toml, token_step};

    #[test]
    fn the_repositories_typed_become_flows_toml() {
        let header = "# Written by FA1 at each start, from the repositories of its Keys screen.\n";
        // typed -> the TOML after the header
        let accepted = [
            ("", ""),
            ("\n  \n# a note\n", ""),
            (
                "octocat/Hello-World",
                "[repositories.Hello-World]\nbranches = [\"main\"]\nurl = \"https://github.com/octocat/Hello-World\"\n",
            ),
            (
                "https://github.com/the-guish/fa1.git/ main release/1.x",
                "[repositories.fa1]\nbranches = [\"main\", \"release/1.x\"]\nurl = \"https://github.com/the-guish/fa1\"\n",
            ),
        ];
        for (typed, expected) in accepted {
            assert_eq!(
                flows_toml(typed),
                Ok(format!("{header}{expected}")),
                "{typed:?}"
            );
        }
        // typed -> words the error holds
        let refused = [
            (
                "https://gitlab.com/someone/thing",
                "line 1: https://gitlab.com/someone/thing",
            ),
            ("ok/one\nhttps://x:secret@github.com/a/b", "line 2:"),
            ("owner", "line 1: owner is not a repository"),
            ("a/b/c", "line 1: a/b/c"),
            ("a/..", "line 1: a/.."),
            ("a/same\nb/same", "line 2: a second repository named same"),
            ("a/b main@x", "line 1: main@x is not a branch name"),
            ("a/b -rf", "line 1: -rf is not a branch name"),
        ];
        for (typed, words) in refused {
            let error = flows_toml(typed).expect_err(typed);
            assert!(error.contains(words), "{typed:?}: {error}");
        }
    }
    use crate::control::{ServiceToken, WORKER_TOKEN_NAME};

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
