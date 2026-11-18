//! The Checks screen in mode 2: the Docker engine, Compose and Buildx. A missing one comes with
//! the commands that install it, which the person runs.

use std::path::Path;

use serde::Serialize;

use crate::actions::{Action, program_path};

#[derive(Serialize)]
pub struct Check {
    pub name: String,
    pub ok: bool,
    pub detail: String,
    /// The commands that fix it, one per line.
    pub fix: String,
}

fn check(logs: &Path, name: &str, action: Action, fix: &str) -> Check {
    match action.run(logs, |_| {}) {
        Ok(out) => Check {
            name: name.into(),
            ok: true,
            detail: out.trim().to_string(),
            fix: String::new(),
        },
        Err(error) => Check {
            name: name.into(),
            ok: false,
            detail: error.lines().last().unwrap_or_default().to_string(),
            fix: fix.to_string(),
        },
    }
}

pub fn containers(logs: &Path) -> Vec<Check> {
    let macos = cfg!(target_os = "macos");
    let install = if macos {
        "brew install colima docker docker-compose docker-buildx\ncolima start --cpu 4 --memory 8"
    } else {
        "sudo apt install docker.io docker-compose docker-buildx\n\
         # Ubuntu names the Compose package docker-compose-v2."
    };
    if !program_path("docker").is_file() {
        return vec![Check {
            name: "Docker".into(),
            ok: false,
            detail: "the docker command is not installed".into(),
            fix: install.into(),
        }];
    }
    let engine_fix = if macos {
        "colima start --cpu 4 --memory 8"
    } else {
        "sudo systemctl start docker\n\
         # If Docker answers \"permission denied\": add yourself to the group docker,\n\
         # then log out and in. Members of that group control the host as root does.\n\
         sudo usermod -aG docker $USER"
    };
    let plugin_fix = if macos {
        "brew install docker-compose docker-buildx\n\
         # Then add to ~/.docker/config.json:\n\
         # \"cliPluginsExtraDirs\": [\"/opt/homebrew/lib/docker/cli-plugins\"]"
    } else {
        install
    };
    vec![
        check(
            logs,
            "Docker engine",
            Action::new(
                "check the Docker engine",
                "docker",
                &["version", "--format", "{{.Server.Version}}"],
            ),
            engine_fix,
        ),
        check(
            logs,
            "Docker Compose",
            Action::new(
                "check Docker Compose",
                "docker",
                &["compose", "version", "--short"],
            ),
            plugin_fix,
        ),
        check(
            logs,
            "Docker Buildx",
            Action::new("check Docker Buildx", "docker", &["buildx", "version"]),
            plugin_fix,
        ),
    ]
}
