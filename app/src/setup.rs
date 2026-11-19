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
const PROVIDERS: &[&str] = &["anthropic", "claude-code"];

/// What FA1 deploys from a setup folder.
#[derive(Debug, PartialEq)]
pub struct Setup {
    /// Robinauts' configuration: FA1's fixed part, then the folder's models and agents.
    pub robinauts_toml: String,
    /// The flows' folder (docs/specs/flows.md): the setup folder's `flows/`, by path inside it.
    pub flows: Vec<(PathBuf, Vec<u8>)>,
    pub git_name: String,
    pub git_email: String,
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
    Ok(())
}

/// Reads and checks the setup folder. The error names the file.
pub fn read(folder: &Path) -> Result<Setup, String> {
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

    let mut added = toml::Table::new();
    added.insert("models".to_string(), models.into());
    added.insert("agents".to_string(), agents.into());
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
    })
}

/// Pulls the setup folder, fast-forward only, unless it has changes of its own or no upstream
/// branch: then it is deployed as it is. The GitHub token goes through git's credential helper,
/// in a variable the log never shows.
pub fn pull(
    folder: &Path,
    github_token: &str,
    logs: &Path,
    say: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let at = folder.to_string_lossy().to_string();
    let changes = Action::new(
        "look for changes in the setup folder",
        "git",
        &["-C", &at, "status", "--porcelain"],
    )
    .run(logs, &mut *say)?;
    if !changes.trim().is_empty() {
        say("The setup folder has changes of its own: it is deployed as it is, without a pull.");
        return Ok(());
    }
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
    use super::{STARTER, read};
    use std::fs;
    use std::path::{Path, PathBuf};

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
        let setup = read(&at).unwrap();
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
            let error = read(&at).expect_err(file);
            assert!(error.contains(words), "{file}: {error}");
            let _ = fs::remove_dir_all(at);
        }
    }
}
