//! FA1: the app on the host (docs/specs/app.md). `fa1 --plan` prints what a start runs, and runs
//! nothing.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod actions;
mod checks;
mod containers;
mod control;
mod folder;

use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

use containers::Project;
use folder::{DEFAULT_PORT, Folder, Keys};

/// One long action at a time: a start, a reset or a removal.
static BUSY: AtomicBool = AtomicBool::new(false);

fn folder() -> Folder {
    Folder::new(folder::default_root())
}

fn project() -> Project {
    let folder = folder();
    let port = folder.settings().port.unwrap_or(DEFAULT_PORT);
    Project { folder, port }
}

#[derive(Serialize)]
struct State {
    folder: String,
    mode: Option<String>,
    port: u16,
    /// Which keys were given. The values stay in the core.
    given: serde_json::Value,
    git_name: String,
    git_email: String,
}

#[tauri::command]
fn state() -> State {
    let folder = folder();
    let settings = folder.settings();
    let keys = folder.keys();
    State {
        folder: folder.root.display().to_string(),
        mode: settings.mode,
        port: settings.port.unwrap_or(DEFAULT_PORT),
        given: json!({
            "anthropic": !keys.anthropic.is_empty(),
            "claude_code": !keys.claude_code.is_empty(),
            "github": !keys.github.is_empty(),
        }),
        git_name: keys.git_name,
        git_email: keys.git_email,
    }
}

#[tauri::command]
fn plan() -> Vec<String> {
    project().start_plan()
}

#[tauri::command]
fn checks() -> Result<Vec<checks::Check>, String> {
    let folder = folder();
    folder.ensure().map_err(|e| e.to_string())?;
    Ok(checks::containers(&folder.logs()))
}

/// Saves the mode and the keys. An empty key keeps the one saved before.
#[tauri::command]
fn save_keys(keys: Keys) -> Result<(), String> {
    let folder = folder();
    folder.ensure().map_err(|e| e.to_string())?;
    let mut saved = folder.keys();
    for (field, given) in [
        (&mut saved.anthropic, keys.anthropic),
        (&mut saved.claude_code, keys.claude_code),
        (&mut saved.github, keys.github),
    ] {
        if !given.trim().is_empty() {
            *field = given.trim().to_string();
        }
    }
    saved.git_name = keys.git_name.trim().to_string();
    saved.git_email = keys.git_email.trim().to_string();
    folder.save_keys(&saved).map_err(|e| e.to_string())?;
    let mut settings = folder.settings();
    settings.mode = Some("containers".to_string());
    settings.port.get_or_insert(DEFAULT_PORT);
    folder.save_settings(&settings).map_err(|e| e.to_string())
}

/// Runs `work` on a thread of its own. Its lines go to the window as `log` events, and its end
/// as `done`.
fn in_background(
    app: AppHandle,
    what: &'static str,
    work: impl FnOnce(&mut dyn FnMut(&str)) -> Result<(), String> + Send + 'static,
) -> Result<(), String> {
    if BUSY.swap(true, Ordering::SeqCst) {
        return Err("another action is running".to_string());
    }
    std::thread::spawn(move || {
        let emitter = app.clone();
        let mut say = move |line: &str| {
            let _ = emitter.emit("log", line.to_string());
        };
        let result = work(&mut say);
        BUSY.store(false, Ordering::SeqCst);
        let _ = app.emit("done", json!({"what": what, "error": result.err()}));
    });
    Ok(())
}

#[tauri::command]
fn start(app: AppHandle) -> Result<(), String> {
    let project = project();
    let keys = project.folder.keys();
    if keys.claude_code.is_empty() {
        return Err("the Claude Code token is missing: add it on the Keys screen".to_string());
    }
    in_background(app, "start", move |say| project.start(&keys, say))
}

#[tauri::command]
fn stop(app: AppHandle) -> Result<(), String> {
    let project = project();
    in_background(app, "stop", move |say| {
        project.stop().run(&project.folder.logs(), say).map(|_| ())
    })
}

#[derive(Serialize)]
struct Status {
    containers: String,
    health: String,
}

#[tauri::command]
fn status() -> Status {
    let project = project();
    let containers = project
        .ps()
        .run(&project.folder.logs(), |_| {})
        .unwrap_or_else(|e| e);
    Status {
        containers,
        health: control::health(project.port),
    }
}

/// Opens Robinauts in a window of its own, signed in with a new ticket. That window is in no
/// capability: it calls none of the app's commands.
#[tauri::command]
fn open_robinauts(app: AppHandle) -> Result<(), String> {
    let project = project();
    let url = control::ticket_url(project.port, &project.folder.read_secret("launch"))?;
    let url: tauri::Url = url.parse().map_err(|e| format!("{e}"))?;
    if let Some(window) = app.get_webview_window("robinauts") {
        let _ = window.close();
    }
    WebviewWindowBuilder::new(&app, "robinauts", WebviewUrl::External(url))
        .title("Robinauts")
        .inner_size(1280.0, 860.0)
        .build()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn reset_code(app: AppHandle) -> Result<(), String> {
    let project = project();
    in_background(app, "reset", move |say| project.reset_code(say))
}

/// Removes the project's containers, network, volumes and images, then the folder.
#[tauri::command]
fn remove_everything(app: AppHandle) -> Result<(), String> {
    let project = project();
    if let Some(window) = app.get_webview_window("robinauts") {
        let _ = window.close();
    }
    in_background(app, "remove", move |say| {
        if project.folder.compose().join("compose.yaml").is_file() {
            project
                .down_everything()
                .run(&project.folder.logs(), &mut *say)?;
        }
        say(&format!("Deleting {}", project.folder.root.display()));
        fs::remove_dir_all(&project.folder.root).or_else(|e| match e.kind() {
            std::io::ErrorKind::NotFound => Ok(()),
            _ => Err(format!("the app could not delete its folder: {e}")),
        })
    })
}

fn main() {
    if std::env::args().any(|a| a == "--plan") {
        println!("The first start in mode 2 runs these steps, in order:\n");
        for (number, step) in project().start_plan().iter().enumerate() {
            println!("{}. {step}\n", number + 1);
        }
        return;
    }
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            state,
            plan,
            checks,
            save_keys,
            start,
            stop,
            status,
            open_robinauts,
            reset_code,
            remove_everything
        ])
        .run(tauri::generate_context!())
        .expect("FA1 could not start its window");
}
