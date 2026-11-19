//! The actions: each runs one program with a fixed list of arguments, without a shell. Each is
//! written to `logs/actions.log` before it runs, and its output to `logs/output.log`.

use std::ffi::OsString;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct Action {
    /// What the action does, in the person's words.
    pub what: String,
    pub program: String,
    pub args: Vec<String>,
    /// Variables set for the program, beside the app's own. Their values are shown: none is a
    /// secret.
    pub env: Vec<(String, String)>,
    /// Secret variables: the log shows their names, never their values.
    pub secret_env: Vec<(String, String)>,
}

impl Action {
    pub fn new(what: &str, program: &str, args: &[&str]) -> Self {
        Action {
            what: what.to_string(),
            program: program.to_string(),
            args: args.iter().map(|a| a.to_string()).collect(),
            env: Vec::new(),
            secret_env: Vec::new(),
        }
    }

    pub fn arg(mut self, arg: impl Into<String>) -> Self {
        self.args.push(arg.into());
        self
    }

    pub fn env(mut self, name: &str, value: impl Into<String>) -> Self {
        self.env.push((name.to_string(), value.into()));
        self
    }

    /// A secret variable for the program. The log shows `NAME=***`.
    pub fn secret_env(mut self, name: &str, value: impl Into<String>) -> Self {
        self.secret_env.push((name.to_string(), value.into()));
        self
    }

    /// The action as one line: the variables, the program and its arguments.
    pub fn line(&self) -> String {
        let mut parts: Vec<String> = self
            .env
            .iter()
            .map(|(k, v)| format!("{k}={}", quoted(v)))
            .chain(self.secret_env.iter().map(|(k, _)| format!("{k}=***")))
            .collect();
        parts.push(self.program.clone());
        parts.extend(self.args.iter().map(|a| quoted(a)));
        parts.join(" ")
    }

    /// Runs the action, calls `each` with every line it prints, and returns what it printed on
    /// its standard output. An exit other than 0 is an error, with the last lines it printed.
    pub fn run(&self, logs: &Path, mut each: impl FnMut(&str)) -> Result<String, String> {
        append(
            &logs.join("actions.log"),
            &format!("{} {}: {}", now(), self.what, self.line()),
        );
        each(&format!("$ {}", self.line()));
        let mut child = Command::new(program_path(&self.program))
            .args(&self.args)
            .envs(self.env.iter().map(|(k, v)| (k.as_str(), v.as_str())))
            .envs(
                self.secret_env
                    .iter()
                    .map(|(k, v)| (k.as_str(), v.as_str())),
            )
            .env("PATH", search_path())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("{} could not start: {e}", self.program))?;
        let (sender, lines) = mpsc::channel::<(bool, String)>();
        let readers: Vec<_> = [
            (
                true,
                Box::new(child.stdout.take().unwrap()) as Box<dyn std::io::Read + Send>,
            ),
            (
                false,
                Box::new(child.stderr.take().unwrap()) as Box<dyn std::io::Read + Send>,
            ),
        ]
        .into_iter()
        .map(|(is_out, stream)| {
            let sender = sender.clone();
            thread::spawn(move || {
                for line in BufReader::new(stream).lines().map_while(Result::ok) {
                    let _ = sender.send((is_out, line));
                }
            })
        })
        .collect();
        drop(sender);
        let output = logs.join("output.log");
        let mut stdout = String::new();
        let mut last = Vec::new();
        for (is_out, line) in lines {
            append(&output, &line);
            each(&line);
            if is_out {
                stdout.push_str(&line);
                stdout.push('\n');
            }
            last.push(line);
            if last.len() > 12 {
                last.remove(0);
            }
        }
        for reader in readers {
            let _ = reader.join();
        }
        let status = child.wait().map_err(|e| e.to_string())?;
        if status.success() {
            Ok(stdout)
        } else {
            Err(format!(
                "{} failed ({status}):\n{}",
                self.what,
                last.join("\n")
            ))
        }
    }
}

/// The folders a program is looked for in: the app's `PATH`, then where Homebrew and Docker
/// install on macOS. An app opened from the Finder gets a short `PATH`.
pub fn search_path() -> OsString {
    let mut dirs: Vec<PathBuf> = std::env::var_os("PATH")
        .map(|p| std::env::split_paths(&p).collect())
        .unwrap_or_default();
    for extra in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"] {
        let extra = PathBuf::from(extra);
        if !dirs.contains(&extra) {
            dirs.push(extra);
        }
    }
    std::env::join_paths(dirs).unwrap_or_default()
}

/// `program` as found in `search_path()`, or as it is.
pub fn program_path(program: &str) -> PathBuf {
    for dir in std::env::split_paths(&search_path()) {
        let candidate = dir.join(program);
        if candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(program)
}

fn quoted(text: &str) -> String {
    if !text.is_empty()
        && text
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "-_./:=@,+".contains(c))
    {
        text.to_string()
    } else {
        format!("'{}'", text.replace('\'', "'\\''"))
    }
}

fn append(path: &Path, line: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{line}");
    }
}

fn now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("[{seconds}]")
}
