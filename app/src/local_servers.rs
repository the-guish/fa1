//! The person's local MCP servers (docs/specs/local-mcp-servers.md): tool servers whose source is
//! in the setup folder's `local-mcp-servers/<id>/`. The app reads each manifest, writes a
//! Compose service per server, and adds the server to Robinauts' configuration.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

/// The setup folder's folder of local servers, and its copy in `compose/`.
pub const FOLDER: &str = "local-mcp-servers";

/// The Compose file the app writes beside `compose.yaml`, with a service per local server.
pub const COMPOSE_FILE: &str = "local-mcp-servers.yaml";

const MANIFEST: &str = "mcp.toml";

/// The manifest's keys, as the spec lists them.
const MANIFEST_KEYS: &[&str] = &[
    "title",
    "port",
    "path",
    "timeout_seconds",
    "exclude",
    "env",
    "keys",
];

/// What every local server's container gets, besides its manifest's variables: these names are
/// FA1's.
const RESERVED_PREFIXES: &[&str] = &["FA1_", "MCP_"];

#[derive(Clone, Debug, PartialEq)]
pub struct LocalServer {
    pub id: String,
    pub title: String,
    pub port: u16,
    pub path: String,
    pub timeout_seconds: f64,
    pub exclude: Vec<String>,
    /// `[env]`: the container's settings, by variable.
    pub env: BTreeMap<String, String>,
    /// `[keys]`: the secrets the server needs, by variable, with their labels.
    pub keys: BTreeMap<String, String>,
    /// The server's folder: its files, by path inside it.
    pub files: Vec<(PathBuf, Vec<u8>)>,
}

impl LocalServer {
    /// The Compose service, and the host name the agents reach.
    pub fn service(&self) -> String {
        format!("mcp-{}", self.id)
    }

    /// The variable that holds the access key, in `control` and in the workers.
    pub fn variable(&self) -> String {
        access_key_variable(&self.id)
    }

    /// The file of `secrets/` that keeps the access key.
    pub fn key_file(&self) -> String {
        format!("mcp-{}.key", self.id)
    }

    /// The file of `secrets/` the server's container reads its variables from.
    pub fn env_file(&self) -> String {
        format!("mcp-{}.env", self.id)
    }

    /// The server's table of Robinauts' `[tool_servers]`.
    pub fn tool_server(&self) -> toml::Table {
        let mut table = toml::Table::new();
        table.insert(
            "url".to_string(),
            format!("http://{}:{}{}", self.service(), self.port, self.path).into(),
        );
        table.insert("secret_env".to_string(), self.variable().into());
        table.insert("timeout_seconds".to_string(), self.timeout_seconds.into());
        if !self.exclude.is_empty() {
            table.insert("exclude".to_string(), self.exclude.clone().into());
        }
        table
    }
}

/// `FA1_MCP_<ID>_KEY`: the id in upper case, with `_` for `-`. An id holds no `_`, so two ids
/// never share a variable.
pub fn access_key_variable(id: &str) -> String {
    format!("FA1_MCP_{}_KEY", id.to_ascii_uppercase().replace('-', "_"))
}

/// A server's id, which is its folder's name: as an agent's id.
pub fn is_id(id: &str) -> bool {
    id.chars().next().is_some_and(|c| c.is_ascii_alphanumeric())
        && id
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// A variable a manifest may name: upper-case letters, digits and `_`, and none of FA1's.
fn is_variable(name: &str) -> bool {
    name.chars()
        .next()
        .is_some_and(|c| c.is_ascii_uppercase() || c == '_')
        && name
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
        && !RESERVED_PREFIXES.iter().any(|p| name.starts_with(p))
}

/// The setup folder's local servers, by id. `reserved` holds the ids other tools take. A problem
/// names its file.
pub fn read(folder: &Path, reserved: &[String]) -> Result<Vec<LocalServer>, String> {
    let root = folder.join(FOLDER);
    if !root.is_dir() {
        return Ok(Vec::new());
    }
    let mut dirs: Vec<PathBuf> = fs::read_dir(&root)
        .map_err(|e| format!("{FOLDER}/: {e}"))?
        .filter_map(|entry| entry.ok().map(|e| e.path()))
        .filter(|path| path.is_dir())
        .collect();
    dirs.sort();
    let mut servers = Vec::new();
    for dir in dirs {
        let id = dir
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        let at = format!("{FOLDER}/{id}");
        if !is_id(&id) {
            return Err(format!(
                "{at}: a server's folder name is its id: lowercase letters, digits and -"
            ));
        }
        if reserved.contains(&id) {
            return Err(format!(
                "{at}: {id} is the id of a tool FA1 or Robinauts has"
            ));
        }
        if !dir.join("Dockerfile").is_file() {
            return Err(format!("{at}: no Dockerfile"));
        }
        let name = format!("{at}/{MANIFEST}");
        let text = fs::read_to_string(dir.join(MANIFEST)).map_err(|e| format!("{name}: {e}"))?;
        let manifest: toml::Table = toml::from_str(&text).map_err(|e| format!("{name}: {e}"))?;
        let mut server = parse(&id, &manifest).map_err(|e| format!("{name}: {e}"))?;
        collect(&dir, Path::new(""), &mut server.files)?;
        server.files.sort();
        servers.push(server);
    }
    Ok(servers)
}

/// A manifest, as a server without its files.
pub fn parse(id: &str, manifest: &toml::Table) -> Result<LocalServer, String> {
    if let Some(unknown) = manifest
        .keys()
        .find(|k| !MANIFEST_KEYS.contains(&k.as_str()))
    {
        return Err(format!(
            "{unknown}: a manifest holds {} alone",
            MANIFEST_KEYS.join(", ")
        ));
    }
    let text = |key: &str, default: &str| -> Result<String, String> {
        match manifest.get(key) {
            None => Ok(default.to_string()),
            Some(toml::Value::String(value)) => Ok(value.clone()),
            Some(_) => Err(format!("{key}: a string")),
        }
    };
    let port = match manifest.get("port") {
        Some(toml::Value::Integer(port)) if (1..=65535).contains(port) => *port as u16,
        Some(_) => return Err("port: a number from 1 to 65535".to_string()),
        None => return Err("port: the port the server listens on".to_string()),
    };
    let path = text("path", "/mcp")?;
    if !path.starts_with('/') || path.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return Err("path: a path that starts with /".to_string());
    }
    let timeout_seconds = match manifest.get("timeout_seconds") {
        None => 60.0,
        Some(toml::Value::Integer(n)) if *n > 0 => *n as f64,
        Some(toml::Value::Float(n)) if *n > 0.0 => *n,
        Some(_) => return Err("timeout_seconds: a positive number".to_string()),
    };
    let exclude = match manifest.get("exclude") {
        None => Vec::new(),
        Some(toml::Value::Array(names)) => names
            .iter()
            .map(|n| n.as_str().map(str::to_string))
            .collect::<Option<Vec<_>>>()
            .ok_or("exclude: a list of tool names")?,
        Some(_) => return Err("exclude: a list of tool names".to_string()),
    };
    let strings = |key: &str| -> Result<BTreeMap<String, String>, String> {
        let Some(found) = manifest.get(key) else {
            return Ok(BTreeMap::new());
        };
        let table = found
            .as_table()
            .ok_or(format!("[{key}]: a table of variables"))?;
        let mut held = BTreeMap::new();
        for (name, value) in table {
            if !is_variable(name) {
                return Err(format!(
                    "[{key}] {name}: a variable's name is upper-case letters, digits and _, and \
                     does not start with FA1_ or MCP_"
                ));
            }
            let value = value.as_str().ok_or(format!("[{key}] {name}: a string"))?;
            if value.contains(['\n', '\r', '\0']) {
                return Err(format!("[{key}] {name}: one line"));
            }
            held.insert(name.clone(), value.to_string());
        }
        Ok(held)
    };
    let env = strings("env")?;
    let keys = strings("keys")?;
    if let Some(both) = env.keys().find(|name| keys.contains_key(*name)) {
        return Err(format!("{both}: in [env] or in [keys], not in both"));
    }
    Ok(LocalServer {
        id: id.to_string(),
        title: text("title", id)?,
        port,
        path,
        timeout_seconds,
        exclude,
        env,
        keys,
        files: Vec::new(),
    })
}

/// The Compose file of the local servers: a service each, built from its folder's copy in
/// `compose/`, with the same limits as FA1's own MCP servers.
pub fn compose_yaml(servers: &[LocalServer]) -> String {
    let mut yaml = String::from(
        "# The setup folder's local MCP servers (docs/specs/local-mcp-servers.md). FA1 writes this\n\
         # file at each start, beside compose.yaml.\n\n",
    );
    if servers.is_empty() {
        yaml.push_str("services: {}\n");
        return yaml;
    }
    yaml.push_str("services:\n");
    for server in servers {
        // JSON is YAML. Compose reads `$` as the start of a variable, and `$$` as a `$`.
        let environment = serde_json::to_string(&server.env)
            .expect("a map of strings")
            .replace('$', "$$");
        yaml.push_str(&format!(
            "  {service}:\n\
             \x20   build: ./{FOLDER}/{id}\n\
             \x20   env_file: ${{FA1_SECRETS:?}}/{env_file}\n\
             \x20   environment: {environment}\n\
             \x20   read_only: true\n\
             \x20   tmpfs: [/tmp]\n\
             \x20   cap_drop: [ALL]\n\
             \x20   security_opt: [\"no-new-privileges:true\"]\n\
             \x20   mem_limit: 512m\n\
             \x20   pids_limit: 256\n\
             \x20   restart: unless-stopped\n",
            service = server.service(),
            id = server.id,
            env_file = server.env_file(),
        ));
    }
    yaml
}

/// The variables of a server's container: its access key, port and path, and the values the
/// person gave for its `[keys]`.
pub fn container_env(
    server: &LocalServer,
    access_key: &str,
    given: &BTreeMap<String, String>,
) -> Vec<(String, String)> {
    let mut env = vec![
        ("MCP_ACCESS_KEY".to_string(), access_key.to_string()),
        ("MCP_PORT".to_string(), server.port.to_string()),
        ("MCP_PATH".to_string(), server.path.clone()),
    ];
    for name in server.keys.keys() {
        if let Some(value) = given.get(name) {
            env.push((name.clone(), value.trim().to_string()));
        }
    }
    env
}

/// The keys of `[keys]` the person has not given yet.
pub fn missing_keys(server: &LocalServer, given: Option<&BTreeMap<String, String>>) -> Vec<String> {
    server
        .keys
        .keys()
        .filter(|name| {
            given
                .and_then(|g| g.get(*name))
                .is_none_or(|v| v.trim().is_empty())
        })
        .cloned()
        .collect()
}

/// Every file of a server's folder, by its path inside it. Python's caches are left out.
fn collect(dir: &Path, at: &Path, into: &mut Vec<(PathBuf, Vec<u8>)>) -> Result<(), String> {
    let entries = fs::read_dir(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
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

#[cfg(test)]
mod tests {
    use super::{access_key_variable, compose_yaml, container_env, missing_keys, parse};
    use std::collections::BTreeMap;

    #[test]
    fn a_manifest_is_read_or_refused_with_its_key() {
        // (manifest) -> Ok((port, path, timeout, env, keys)) or the words of the error
        type Read<'a> = (&'a str, u16, &'a str, f64, &'a [&'a str], &'a [&'a str]);
        let good: &[Read] = &[
            ("port = 8080", 8080, "/mcp", 60.0, &[], &[]),
            (
                "port = 9000\npath = \"/\"\ntimeout_seconds = 2.5\n[env]\nTIMEZONE = \"UTC\"\n[keys]\nJIRA_API_TOKEN = \"Jira API token\"",
                9000,
                "/",
                2.5,
                &["TIMEZONE"],
                &["JIRA_API_TOKEN"],
            ),
            (
                "title = \"T\"\nport = 1\nexclude = [\"drop\"]\n[env]\n_X = \"\"",
                1,
                "/mcp",
                60.0,
                &["_X"],
                &[],
            ),
        ];
        for (text, port, path, timeout, env, keys) in good {
            let server = parse("s", &toml::from_str(text).unwrap()).unwrap();
            assert_eq!(
                (
                    server.port,
                    server.path.as_str(),
                    server.timeout_seconds,
                    server.env.keys().map(String::as_str).collect::<Vec<_>>(),
                    server.keys.keys().map(String::as_str).collect::<Vec<_>>(),
                ),
                (*port, *path, *timeout, env.to_vec(), keys.to_vec()),
                "{text}"
            );
        }
        let bad = [
            ("", "port: the port"),
            ("port = 0", "port: a number"),
            ("port = 70000", "port: a number"),
            ("port = \"80\"", "port: a number"),
            (
                "port = 80\npath = \"mcp\"",
                "path: a path that starts with /",
            ),
            ("port = 80\ntimeout_seconds = 0", "timeout_seconds"),
            ("port = 80\nexclude = [1]", "exclude"),
            ("port = 80\nimage = \"x\"", "image: a manifest holds"),
            ("port = 80\n[env]\nlower = \"x\"", "[env] lower"),
            (
                "port = 80\n[env]\nFA1_ANTHROPIC_KEY = \"x\"",
                "[env] FA1_ANTHROPIC_KEY",
            ),
            (
                "port = 80\n[keys]\nMCP_ACCESS_KEY = \"x\"",
                "[keys] MCP_ACCESS_KEY",
            ),
            ("port = 80\n[env]\nA = 1", "[env] A: a string"),
            ("port = 80\n[env]\nA = \"x\\ny\"", "[env] A: one line"),
            ("port = 80\nenv = \"x\"", "[env]: a table"),
            (
                "port = 80\n[env]\nTOKEN = \"x\"\n[keys]\nTOKEN = \"Token\"",
                "TOKEN: in [env] or in [keys]",
            ),
        ];
        for (text, words) in bad {
            let error = parse("s", &toml::from_str(text).unwrap()).unwrap_err();
            assert!(error.contains(words), "{text}: {error}");
        }
    }

    #[test]
    fn a_server_is_a_tool_server_reached_by_its_service_name() {
        let server = parse(
            "jira-cloud",
            &toml::from_str("port = 8080\nexclude = [\"x\"]").unwrap(),
        )
        .unwrap();
        let table = server.tool_server();
        assert_eq!(
            table["url"].as_str(),
            Some("http://mcp-jira-cloud:8080/mcp")
        );
        assert_eq!(table["secret_env"].as_str(), Some("FA1_MCP_JIRA_CLOUD_KEY"));
        assert_eq!(table["exclude"].as_array().unwrap().len(), 1);
        for (id, variable) in [
            ("dates", "FA1_MCP_DATES_KEY"),
            ("a-b-1", "FA1_MCP_A_B_1_KEY"),
        ] {
            assert_eq!(access_key_variable(id), variable);
        }
    }

    #[test]
    fn the_compose_file_holds_a_hardened_service_per_server() {
        assert!(compose_yaml(&[]).ends_with("services: {}\n"));
        let server = parse(
            "dates",
            &toml::from_str("port = 8080\n[env]\nTIMEZONE = \"UTC\"\nPRICE = \"$5\"").unwrap(),
        )
        .unwrap();
        let yaml = compose_yaml(&[server]);
        for wanted in [
            "  mcp-dates:\n    build: ./local-mcp-servers/dates\n",
            "    env_file: ${FA1_SECRETS:?}/mcp-dates.env\n",
            "    environment: {\"PRICE\":\"$$5\",\"TIMEZONE\":\"UTC\"}\n",
            "    read_only: true\n",
            "    cap_drop: [ALL]\n",
            "    security_opt: [\"no-new-privileges:true\"]\n",
            "    pids_limit: 256\n",
        ] {
            assert!(yaml.contains(wanted), "{wanted}\n{yaml}");
        }
        assert!(
            !yaml.contains("ports:") && !yaml.contains("volumes:"),
            "{yaml}"
        );
    }

    #[test]
    fn the_container_gets_its_access_key_and_the_keys_the_person_gave() {
        let server = parse(
            "jira",
            &toml::from_str("port = 8080\n[keys]\nJIRA_API_TOKEN = \"t\"\nJIRA_OTHER = \"o\"")
                .unwrap(),
        )
        .unwrap();
        let given: BTreeMap<String, String> =
            [("JIRA_API_TOKEN".to_string(), " tok ".to_string())].into();
        assert_eq!(missing_keys(&server, Some(&given)), ["JIRA_OTHER"]);
        assert_eq!(
            missing_keys(&server, None),
            ["JIRA_API_TOKEN", "JIRA_OTHER"]
        );
        let env = container_env(&server, "k", &given);
        let names: Vec<_> = env.iter().map(|(n, v)| format!("{n}={v}")).collect();
        assert_eq!(
            names,
            [
                "MCP_ACCESS_KEY=k",
                "MCP_PORT=8080",
                "MCP_PATH=/mcp",
                "JIRA_API_TOKEN=tok"
            ]
        );
    }
}
