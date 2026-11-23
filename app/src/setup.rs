//! The setup folder: the person's settings, models, agents, knowledge and flows, in a git
//! repository of their own (docs/specs/setup-folder.md). FA1 reads it at each start and refresh,
//! and makes Robinauts' configuration and the flows' folder from it.

use std::fs;
use std::path::{Path, PathBuf};

use crate::actions::Action;

/// FA1's fixed part of Robinauts' configuration: the providers, the tool servers, the workers.
const BASE: &str = include_str!("../../compose/robinauts.base.toml");

/// The starter of a new setup folder, as `setup-starter/` holds it.
const STARTER: &[(&str, &str)] = &[
    ("README.md", include_str!("../../setup-starter/README.md")),
    ("fa1.toml", include_str!("../../setup-starter/fa1.toml")),
    (
        "models.toml",
        include_str!("../../setup-starter/models.toml"),
    ),
    (
        "agents/assistant.toml",
        include_str!("../../setup-starter/agents/assistant.toml"),
    ),
    (
        "agents/claude-code.toml",
        include_str!("../../setup-starter/agents/claude-code.toml"),
    ),
    (
        "agents/cursor.toml",
        include_str!("../../setup-starter/agents/cursor.toml"),
    ),
    (
        "agents/flow-designer.toml",
        include_str!("../../setup-starter/agents/flow-designer.toml"),
    ),
    (
        "knowledge/README.md",
        include_str!("../../setup-starter/knowledge/README.md"),
    ),
    (
        "knowledge/flows.md",
        include_str!("../../setup-starter/knowledge/flows.md"),
    ),
    (
        "flows/flows.toml",
        include_str!("../../setup-starter/flows/flows.toml"),
    ),
    (
        "flows/code_and_review.yaml",
        include_str!("../../setup-starter/flows/code_and_review.yaml"),
    ),
    (
        "flows/code_and_review.form.toml",
        include_str!("../../setup-starter/flows/code_and_review.form.toml"),
    ),
    (
        "flows/hello.yaml",
        include_str!("../../setup-starter/flows/hello.yaml"),
    ),
    (
        "flows/hello.form.toml",
        include_str!("../../setup-starter/flows/hello.form.toml"),
    ),
    (
        "flows/handlers/examples.py",
        include_str!("../../setup-starter/flows/handlers/examples.py"),
    ),
    (
        "flows/handlers/README.md",
        include_str!("../../setup-starter/flows/handlers/README.md"),
    ),
    (
        "flows/handlers/robinauts_tasks.py",
        include_str!("../../setup-starter/flows/handlers/robinauts_tasks.py"),
    ),
];

/// The providers a model of the setup folder may name: FA1's.
const PROVIDERS: &[&str] = &["anthropic", "claude-code", "cursor"];

/// The worker of the code container, as FA1's fixed part names it.
pub const CODE_WORKER: &str = "claude";

/// The worker of the Cursor container (docs/specs/cursor-worker.md). FA1 names it in Robinauts'
/// configuration only while it runs: Robinauts refuses a worker no agent names.
pub const CURSOR_WORKER: &str = "cursor";

/// What FA1 deploys from a setup folder.
#[derive(Debug, PartialEq)]
pub struct Setup {
    /// Robinauts' configuration: FA1's fixed part, then the folder's models and agents.
    pub robinauts_toml: String,
    /// The flows' folder (docs/specs/flows.md): the setup folder's `flows/`, by path inside it.
    pub flows: Vec<(PathBuf, Vec<u8>)>,
    pub git_name: String,
    pub git_email: String,
    /// The variables that hold the keys the code worker needs: those of the tool servers its
    /// agents use (`worker_secrets`).
    pub code_secrets: Vec<String>,
    /// Whether the Cursor worker runs: the person gave a Cursor API key, and an agent names
    /// the worker.
    pub cursor: bool,
    /// The same variables, for the Cursor worker.
    pub cursor_secrets: Vec<String>,
    /// The agents left out of the deploy, by id: those of the Cursor worker, without a Cursor
    /// API key.
    pub left_out: Vec<String>,
}

/// The variables that hold the keys of the tool servers the agents of `worker` use. A worker
/// reads a tool server's key from its own environment, so an agent of a worker in a container
/// reaches a keyed server only with that key in the container. `base` is FA1's fixed part,
/// whose tool servers name their variable in `secret_env`. `agents` are the setup folder's, by
/// id.
pub fn worker_secrets(base: &toml::Table, agents: &toml::Table, worker: &str) -> Vec<String> {
    let servers = base.get("tool_servers").and_then(toml::Value::as_table);
    let mut found: Vec<String> = agents
        .values()
        .filter(|agent| agent.get("worker").and_then(toml::Value::as_str) == Some(worker))
        .filter_map(|agent| agent.get("tools").and_then(toml::Value::as_array))
        .flatten()
        .filter_map(toml::Value::as_str)
        .filter_map(|tool| servers?.get(tool)?.get("secret_env")?.as_str())
        .map(str::to_string)
        .collect();
    found.sort();
    found.dedup();
    found
}

/// Makes `folder` the setup folder: refuses one inside the app's folder `app_root`, makes it
/// when it is missing, writes the starter when it is empty, and makes it a git repository.
pub fn choose(folder: &Path, app_root: &Path, logs: &Path) -> Result<(), String> {
    if !folder.is_absolute() {
        return Err(format!(
            "{}: write the folder's whole path, from /",
            folder.display()
        ));
    }
    if folder.starts_with(app_root) {
        return Err(format!(
            "{} is inside FA1's own folder, which \"Remove everything\" deletes: choose another",
            folder.display()
        ));
    }
    fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    let empty = fs::read_dir(folder)
        .map_err(|e| format!("{}: {e}", folder.display()))?
        .next()
        .is_none();
    if empty {
        for (name, text) in STARTER {
            let path = folder.join(name);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            fs::write(&path, text).map_err(|e| format!("{}: {e}", path.display()))?;
        }
    } else if !folder.join("fa1.toml").is_file() {
        return Err(format!(
            "{} holds other files and no fa1.toml: choose an empty folder, or a setup folder",
            folder.display()
        ));
    }
    if !folder.join(".git").exists() {
        Action::new(
            "make the setup folder a git repository",
            "git",
            &["init", "-q"],
        )
        .arg(folder.to_string_lossy())
        .run(logs, |_| {})?;
    }
    if empty {
        // The starter is FA1's own writing, so its commit is FA1's. A changelist starts from
        // a commit (docs/specs/review-app.md).
        let at = folder.to_string_lossy().to_string();
        Action::new("stage the starter", "git", &["-C", &at, "add", "--all"]).run(logs, |_| {})?;
        Action::new(
            "commit the starter",
            "git",
            &[
                "-C",
                &at,
                "-c",
                "user.name=FA1",
                "-c",
                "user.email=fa1@localhost",
                "commit",
                "--quiet",
                "--message",
                "The starter",
            ],
        )
        .run(logs, |_| {})?;
    }
    Ok(())
}

/// The commit the setup folder is at, "" for a folder with no commit yet. The review app starts
/// each changelist from it (docs/specs/review-app.md, "Main").
pub fn head(folder: &Path, logs: &Path) -> String {
    let at = folder.to_string_lossy().to_string();
    Action::new(
        "read the setup folder's HEAD",
        "git",
        &[
            "-C",
            &at,
            "rev-parse",
            "--verify",
            "--quiet",
            "HEAD^{commit}",
        ],
    )
    .run(logs, |_| {})
    .map(|printed| printed.trim().to_string())
    .unwrap_or_default()
}

/// The user and the group that own `folder`. The services that reach the setup folder run as
/// that user, so the files they write keep the folder's owner (docs/specs/containers.md).
#[cfg(unix)]
pub fn owner(folder: &Path) -> Option<(u32, u32)> {
    use std::os::unix::fs::MetadataExt;
    fs::metadata(folder).ok().map(|m| (m.uid(), m.gid()))
}

#[cfg(not(unix))]
pub fn owner(_folder: &Path) -> Option<(u32, u32)> {
    None
}

/// Whether the setup folder has changes of its own, not committed: the person is editing it by
/// hand.
pub fn has_changes(folder: &Path, logs: &Path, say: &mut dyn FnMut(&str)) -> Result<bool, String> {
    let at = folder.to_string_lossy().to_string();
    let changes = Action::new(
        "look for changes in the setup folder",
        "git",
        &["-C", &at, "status", "--porcelain"],
    )
    .run(logs, &mut *say)?;
    Ok(!changes.trim().is_empty())
}

/// Reads and checks the setup folder. The error names the file. `cursor_key` says whether the
/// person gave a Cursor API key: without one, the agents of the Cursor worker are left out.
pub fn read(folder: &Path, cursor_key: bool) -> Result<Setup, String> {
    let settings = table(folder, "fa1.toml")?;
    let git = |key: &str| -> Result<String, String> {
        match settings.get("git").and_then(|g| g.get(key)) {
            None => Ok(String::new()),
            Some(toml::Value::String(text)) => Ok(text.trim().to_string()),
            Some(_) => Err(format!("fa1.toml [git] {key}: a string")),
        }
    };
    let (git_name, git_email) = (git("name")?, git("email")?);

    let models = table(folder, "models.toml")?;
    if let Some(key) = models.keys().find(|k| *k != "models") {
        return Err(format!("models.toml: {key}: only [models.<id>] tables"));
    }
    let models = models
        .get("models")
        .and_then(toml::Value::as_table)
        .cloned()
        .unwrap_or_default();
    for (id, model) in &models {
        let provider = model.get("provider").and_then(toml::Value::as_str);
        if !provider.is_some_and(|p| PROVIDERS.contains(&p)) {
            return Err(format!(
                "models.toml [models.{id}] provider: one of {}",
                PROVIDERS.join(", ")
            ));
        }
    }

    let mut agents = toml::Table::new();
    let mut files: Vec<PathBuf> = fs::read_dir(folder.join("agents"))
        .map_err(|e| format!("agents/: {e}"))?
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| path.extension().is_some_and(|x| x == "toml"))
        .collect();
    files.sort();
    for path in files {
        let id = path
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or_default()
            .to_string();
        let name = format!("agents/{id}.toml");
        if !is_id(&id) {
            return Err(format!(
                "{name}: an agent's file name is its id: lowercase letters, digits and -"
            ));
        }
        let agent = table(folder, &name)?;
        if let Some(toml::Value::Array(chosen)) = agent.get("models")
            && let Some(unknown) = chosen
                .iter()
                .filter_map(toml::Value::as_str)
                .find(|m| !models.contains_key(*m))
        {
            return Err(format!("{name} models: {unknown} is not in models.toml"));
        }
        agents.insert(id, agent.into());
    }
    if agents.is_empty() {
        return Err("agents/: no agent".to_string());
    }

    let on_cursor: Vec<String> = agents
        .iter()
        .filter(|(_, agent)| {
            agent.get("worker").and_then(toml::Value::as_str) == Some(CURSOR_WORKER)
        })
        .map(|(id, _)| id.clone())
        .collect();
    let cursor = cursor_key && !on_cursor.is_empty();
    let left_out = if cursor_key { Vec::new() } else { on_cursor };
    for id in &left_out {
        agents.remove(id);
    }
    if agents.is_empty() {
        return Err("agents/: no agent runs without the Cursor API key".to_string());
    }

    let base: toml::Table = toml::from_str(BASE).map_err(|e| format!("FA1's fixed part: {e}"))?;
    let code_secrets = worker_secrets(&base, &agents, CODE_WORKER);
    let cursor_secrets = worker_secrets(&base, &agents, CURSOR_WORKER);
    let mut added = toml::Table::new();
    added.insert("models".to_string(), models.into());
    added.insert("agents".to_string(), agents.into());
    if cursor {
        let mut worker = toml::Table::new();
        worker.insert("external".to_string(), true.into());
        let mut workers = toml::Table::new();
        workers.insert(CURSOR_WORKER.to_string(), worker.into());
        added.insert("workers".to_string(), workers.into());
    }
    let robinauts_toml = format!(
        "{BASE}\n# --- the setup folder's models and agents ---------------------------------------------\n\n{}",
        toml::to_string(&added).map_err(|e| e.to_string())?
    );

    table(folder, "flows/flows.toml")?;
    let mut flows = Vec::new();
    collect(&folder.join("flows"), Path::new(""), &mut flows)?;
    flows.sort();
    Ok(Setup {
        robinauts_toml,
        flows,
        git_name,
        git_email,
        code_secrets,
        cursor,
        cursor_secrets,
        left_out,
    })
}

/// Pulls the setup folder from its upstream branch, fast-forward only. A folder with no
/// upstream branch is deployed as it is. The GitHub token goes through git's credential helper,
/// in a variable the log never shows.
pub fn pull(
    folder: &Path,
    github_token: &str,
    logs: &Path,
    say: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let at = folder.to_string_lossy().to_string();
    let upstream = Action::new(
        "look for the setup folder's upstream branch",
        "git",
        &["-C", &at, "rev-parse", "--abbrev-ref", "@{upstream}"],
    )
    .run(logs, |_| {});
    if upstream.is_err() {
        say("The setup folder's branch has no upstream: it is deployed as it is, without a pull.");
        return Ok(());
    }
    Action::new(
        "pull the setup folder",
        "git",
        &[
            "-C",
            &at,
            "-c",
            "credential.https://github.com.helper=",
            "-c",
            "credential.https://github.com.helper=!f() { echo username=x-access-token; echo \"password=$FA1_GITHUB_TOKEN\"; }; f",
            "pull",
            "--ff-only",
        ],
    )
    .secret_env("FA1_GITHUB_TOKEN", github_token)
    .run(logs, &mut *say)
    .map(|_| ())
}

/// A TOML file of the setup folder, as a table. The error names the file.
fn table(folder: &Path, name: &str) -> Result<toml::Table, String> {
    let text = fs::read_to_string(folder.join(name)).map_err(|e| format!("{name}: {e}"))?;
    toml::from_str(&text).map_err(|e| format!("{name}: {e}"))
}

/// Every file under `dir`, by its path from the flows' folder. Python's caches are left out.
fn collect(dir: &Path, at: &Path, into: &mut Vec<(PathBuf, Vec<u8>)>) -> Result<(), String> {
    let entries = fs::read_dir(dir).map_err(|e| format!("flows/: {e}"))?;
    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        if name == "__pycache__" {
            continue;
        }
        let path = entry.path();
        let inside = at.join(&name);
        if path.is_dir() {
            collect(&path, &inside, into)?;
        } else {
            let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            into.push((inside, bytes));
        }
    }
    Ok(())
}

fn is_id(id: &str) -> bool {
    !id.is_empty()
        && id.chars().next().is_some_and(|c| c.is_ascii_alphanumeric())
        && id
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

#[cfg(test)]
mod tests {
    use super::{STARTER, choose, has_changes, head, owner, read};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::process::Command;

    /// git in `at`, as a person with a name; what it printed.
    fn git(at: &Path, args: &[&str]) -> String {
        let done = Command::new("git")
            .arg("-C")
            .arg(at)
            .args(["-c", "user.name=Ada", "-c", "user.email=ada@example.com"])
            .args(args)
            .output()
            .unwrap();
        assert!(
            done.status.success(),
            "git {args:?}: {}",
            String::from_utf8_lossy(&done.stderr)
        );
        String::from_utf8_lossy(&done.stdout).trim().to_string()
    }

    /// A new setup folder on real git: the starter is one commit of FA1's, the folder's HEAD
    /// and owner are read, and a change by hand shows.
    #[test]
    fn a_new_setup_folder_is_committed_and_its_head_and_owner_are_read() {
        let root = std::env::temp_dir().join(format!("fa1-setup-test-head-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let (folder, logs) = (root.join("setup"), root.join("logs"));
        fs::create_dir_all(&logs).unwrap();
        let mut say = |_: &str| {};

        choose(&folder, &root.join("app"), &logs).unwrap();
        assert_eq!(
            git(&folder, &["log", "--format=%an: %s"]),
            "FA1: The starter"
        );
        assert!(!has_changes(&folder, &logs, &mut say).unwrap());
        assert_eq!(head(&folder, &logs), git(&folder, &["rev-parse", "HEAD"]));
        #[cfg(unix)]
        assert_eq!(owner(&folder), owner(&root));

        fs::write(folder.join("README.md"), "mine\n").unwrap();
        assert!(has_changes(&folder, &logs, &mut say).unwrap());

        // A setup folder with no commit has no HEAD.
        let bare = root.join("no-commit");
        fs::create_dir_all(&bare).unwrap();
        git(&bare, &["init", "-q"]);
        assert_eq!(head(&bare, &logs), "");
        assert_eq!(owner(&root.join("nowhere")), None);
        let _ = fs::remove_dir_all(root);
    }

    fn starter(at: &Path) {
        for (name, text) in STARTER {
            let path = at.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        }
    }

    fn folder(name: &str) -> PathBuf {
        let at = std::env::temp_dir().join(format!("fa1-setup-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&at);
        starter(&at);
        at
    }

    #[test]
    fn the_starter_deploys_its_agents_and_models() {
        let at = folder("starter");
        let setup = read(&at, false).unwrap();
        for wanted in [
            "[workers.claude]",
            "[models.cc-haiku]",
            "[agents.assistant]",
            "[agents.claude-code]",
            "[agents.flow-designer]",
        ] {
            assert!(setup.robinauts_toml.contains(wanted), "{wanted}");
        }
        let toml: toml::Table = toml::from_str(&setup.robinauts_toml).unwrap();
        assert_eq!(
            toml["agents"]["flow-designer"]["engine"].as_str(),
            Some("claude-code")
        );
        // The designer runs on the code worker, which then needs the key of its tool servers,
        // and no other.
        assert_eq!(setup.code_secrets, ["FA1_SETUP_KEY"]);
        // The designer's tools are tool servers of FA1's fixed part.
        for tool in toml["agents"]["flow-designer"]["tools"].as_array().unwrap() {
            let id = tool.as_str().unwrap();
            assert!(
                id == "sessions" || toml["tool_servers"].get(id).is_some(),
                "{id}"
            );
        }
        // Without a Cursor API key, the starter's agent on Cursor is left out, and Robinauts'
        // configuration names no Cursor worker.
        assert!(!setup.cursor);
        assert_eq!(setup.left_out, ["cursor"]);
        assert!(toml["agents"].get("cursor").is_none());
        assert!(toml["workers"].get("cursor").is_none());
        assert_eq!(
            toml["models"]["cursor-auto"]["provider"].as_str(),
            Some("cursor")
        );
        assert_eq!(setup.git_name, "");
        let flows = String::from_utf8(
            setup
                .flows
                .iter()
                .find(|(p, _)| p == Path::new("flows.toml"))
                .unwrap()
                .1
                .clone(),
        )
        .unwrap();
        assert!(flows.contains("code_location = \"handlers\""), "{flows}");
        let paths: Vec<_> = setup
            .flows
            .iter()
            .map(|(p, _)| p.display().to_string())
            .collect();
        for wanted in [
            "code_and_review.yaml",
            "handlers/robinauts_tasks.py",
            "hello.yaml",
            "hello.form.toml",
            "handlers/examples.py",
        ] {
            assert!(paths.contains(&wanted.to_string()), "{wanted}: {paths:?}");
        }
        let _ = fs::remove_dir_all(at);
    }

    #[test]
    fn the_cursor_worker_runs_with_a_key_and_an_agent() {
        // With the key, the starter's agent is deployed, and its worker is named.
        let at = folder("cursor");
        let setup = read(&at, true).unwrap();
        assert!(setup.cursor && setup.left_out.is_empty());
        let toml: toml::Table = toml::from_str(&setup.robinauts_toml).unwrap();
        assert_eq!(toml["agents"]["cursor"]["engine"].as_str(), Some("cursor"));
        assert_eq!(toml["workers"]["cursor"]["external"].as_bool(), Some(true));
        assert_eq!(toml["workers"]["claude"]["external"].as_bool(), Some(true));
        assert_eq!(
            toml["model_providers"]["cursor"]["api_key_env"].as_str(),
            Some("CURSOR_API_KEY")
        );
        assert!(setup.cursor_secrets.is_empty());
        // An agent of the Cursor worker that uses a keyed tool server gives the worker its key.
        fs::write(
            at.join("agents/cursor.toml"),
            "engine = \"cursor\"\nworker = \"cursor\"\nmodels = [\"cursor-auto\"]\ntools = [\"files\"]\n",
        )
        .unwrap();
        assert_eq!(read(&at, true).unwrap().cursor_secrets, ["FA1_FILES_KEY"]);
        // With the key and no agent on Cursor, the worker stays out.
        fs::remove_file(at.join("agents/cursor.toml")).unwrap();
        let setup = read(&at, true).unwrap();
        let toml: toml::Table = toml::from_str(&setup.robinauts_toml).unwrap();
        assert!(!setup.cursor && toml["workers"].get("cursor").is_none());
        // A setup folder whose agents are all on Cursor deploys none without the key.
        for agent in ["assistant", "claude-code", "flow-designer"] {
            fs::remove_file(at.join(format!("agents/{agent}.toml"))).unwrap();
        }
        fs::write(at.join("agents/only.toml"), "worker = \"cursor\"\n").unwrap();
        let error = read(&at, false).unwrap_err();
        assert!(error.contains("without the Cursor API key"), "{error}");
        let _ = fs::remove_dir_all(at);
    }

    #[test]
    fn the_code_worker_gets_the_keys_of_the_tool_servers_its_agents_use() {
        let base: toml::Table = toml::from_str(super::BASE).unwrap();
        // (the agents) -> the variables of the code worker
        let cases: &[(&str, &[&str])] = &[
            // The starter's designer, on the code worker.
            (
                "[d]\nworker = \"claude\"\ntools = [\"setup-files\", \"setup-git\", \"setup-review\", \"sessions\"]",
                &["FA1_SETUP_KEY"],
            ),
            // The same designer on the server's own worker: the code worker holds no key.
            (
                "[d]\nengine = \"pydantic-ai\"\ntools = [\"setup-files\", \"setup-git\", \"setup-review\"]",
                &[],
            ),
            // A coding agent given the files tool, beside an assistant that has it too.
            (
                "[c]\nworker = \"claude\"\ntools = [\"files\", \"fetch\"]\n[a]\ntools = [\"files\", \"setup-git\"]",
                &["FA1_FILES_KEY"],
            ),
            // Both keys, each once; a tool without a key, and one FA1 does not have, add none.
            (
                "[c]\nworker = \"claude\"\ntools = [\"setup-git\", \"files\", \"todo\", \"nope\"]\n[d]\nworker = \"claude\"\ntools = [\"setup-files\"]",
                &["FA1_FILES_KEY", "FA1_SETUP_KEY"],
            ),
            ("[c]\nworker = \"claude\"", &[]),
        ];
        for (agents, expected) in cases {
            let agents: toml::Table = toml::from_str(agents).unwrap();
            assert_eq!(
                super::worker_secrets(&base, &agents, super::CODE_WORKER),
                *expected,
                "{agents:?}"
            );
        }
    }

    #[test]
    fn a_problem_names_its_file() {
        // (file, text) -> words the error holds
        let cases = [
            ("fa1.toml", "[git]\nname = 1", "fa1.toml [git] name"),
            ("fa1.toml", "not toml", "fa1.toml:"),
            ("flows/flows.toml", "not toml", "flows/flows.toml:"),
            (
                "models.toml",
                "[models.x]\nprovider = \"openai\"",
                "models.toml [models.x] provider",
            ),
            ("models.toml", "[elsewhere]", "models.toml: elsewhere"),
            (
                "agents/Bad.toml",
                "title = \"x\"",
                "agents/Bad.toml: an agent's file name",
            ),
            (
                "agents/x.toml",
                "models = [\"gpt\"]",
                "agents/x.toml models: gpt is not in models.toml",
            ),
        ];
        for (number, (file, text, words)) in cases.iter().enumerate() {
            let at = folder(&format!("bad{number}"));
            fs::write(at.join(file), text).unwrap();
            let error = read(&at, true).expect_err(file);
            assert!(error.contains(words), "{file}: {error}");
            let _ = fs::remove_dir_all(at);
        }
    }
}
