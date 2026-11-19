//! FA1: the app on the host (docs/specs/app.md). `fa1 --plan` prints what a start runs, and runs
//! nothing.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod actions;
mod checks;
mod containers;
mod control;
mod folder;
mod setup;

use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;
use serde_json::json;
use tauri::{
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewBuilder, WebviewUrl, Window,
    WindowBuilder, WindowEvent,
};

use containers::Project;
use folder::{DEFAULT_PORT, Folder, Keys};

/// One long action at a time: a start, a reset or a removal.
static BUSY: AtomicBool = AtomicBool::new(false);

/// The app's one window. It holds three webviews: the bar on top, and below it the admin
/// screens or Robinauts, one at a time.
const WINDOW: &str = "main";
const BAR: &str = "bar";
const ADMIN: &str = "admin";
const APP: &str = "app";
/// The bar's height, in logical pixels.
const BAR_HEIGHT: f64 = 44.0;

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
    /// The setup folder, once chosen; and the one the Welcome screen suggests.
    setup_folder: Option<String>,
    suggested_setup_folder: String,
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
        setup_folder: settings.setup_folder,
        suggested_setup_folder: std::env::var_os("HOME")
            .map(|home| std::path::Path::new(&home).join("fa1-setup"))
            .unwrap_or_default()
            .display()
            .to_string(),
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
    folder.save_keys(&saved).map_err(|e| e.to_string())?;
    let mut settings = folder.settings();
    settings.mode = Some("containers".to_string());
    settings.port.get_or_insert(DEFAULT_PORT);
    folder.save_settings(&settings).map_err(|e| e.to_string())
}

/// Makes `path` the setup folder: a new or empty folder gets the starter, in a git repository
/// (docs/specs/setup-folder.md). The app keeps the location in its settings.
#[tauri::command]
fn choose_setup_folder(path: String) -> Result<String, String> {
    let folder = folder();
    folder.ensure().map_err(|e| e.to_string())?;
    let chosen = std::path::PathBuf::from(path.trim());
    setup::choose(&chosen, &folder.root, &folder.logs())?;
    let mut settings = folder.settings();
    settings.setup_folder = Some(chosen.display().to_string());
    folder.save_settings(&settings).map_err(|e| e.to_string())?;
    Ok(chosen.display().to_string())
}

/// Takes the approved changes and the upstream's into the setup folder, then starts with it:
/// the control plane and the code worker start anew when the setup changed.
#[tauri::command]
fn refresh(app: AppHandle) -> Result<(), String> {
    let project = project();
    let keys = project.folder.keys();
    let signer = app.clone();
    in_background(app, "refresh", move |say| {
        project.pull_setup(&keys, &mut *say)?;
        project.start(&keys, say)?;
        sign_in_again(&signer, project.port, &project.folder.read_secret("launch"));
        Ok(())
    })
}

/// Runs `work` on a thread of its own. Its lines go to the admin screens as `log` events, and
/// its end as `done`.
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
            let _ = emitter.emit_to(ADMIN, "log", line.to_string());
        };
        let result = work(&mut say);
        BUSY.store(false, Ordering::SeqCst);
        let _ = app.emit_to(ADMIN, "done", json!({"what": what, "error": result.err()}));
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
    let signer = app.clone();
    in_background(app, "start", move |say| {
        project.start(&keys, say)?;
        sign_in_again(&signer, project.port, &project.folder.read_secret("launch"));
        Ok(())
    })
}

/// A start may restart the control plane, which ends the App tab's sign-in. An open App tab
/// loads Robinauts again, with a new ticket.
fn sign_in_again(app: &AppHandle, port: u16, launch: &str) {
    let Some(webview) = app.get_webview(APP) else {
        return;
    };
    if let Ok(url) = control::ticket_url(port, launch)
        && let Ok(url) = url.parse::<tauri::Url>()
    {
        let _ = webview.navigate(url);
    }
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

/// Where a webview of the window goes, in logical pixels: the bar along the top, and every other
/// webview in the rest.
fn bounds(label: &str, width: f64, height: f64) -> (LogicalPosition<f64>, LogicalSize<f64>) {
    if label == BAR {
        (
            LogicalPosition::new(0.0, 0.0),
            LogicalSize::new(width, BAR_HEIGHT),
        )
    } else {
        let below = (height - BAR_HEIGHT).max(0.0);
        (
            LogicalPosition::new(0.0, BAR_HEIGHT),
            LogicalSize::new(width, below),
        )
    }
}

/// The window's inner size, in logical pixels.
fn logical_size(window: &Window) -> Result<LogicalSize<f64>, String> {
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    let size = window.inner_size().map_err(|e| e.to_string())?;
    Ok(size.to_logical(scale))
}

/// Fits each webview of the window to its place, after the window changes size. On Linux, GTK
/// lays them out instead (`pin_bar`).
fn lay_out(window: &Window) {
    if cfg!(target_os = "linux") {
        return;
    }
    let Ok(size) = logical_size(window) else {
        return;
    };
    for webview in window.webviews() {
        let (position, size) = bounds(webview.label(), size.width, size.height);
        let _ = webview.set_position(position);
        let _ = webview.set_size(size);
    }
}

/// Adds a webview to the window, in its place.
fn add_webview(app: &AppHandle, label: &str, url: WebviewUrl) -> Result<tauri::Webview, String> {
    let window = app
        .get_window(WINDOW)
        .ok_or_else(|| "the app's window is gone".to_string())?;
    let size = logical_size(&window)?;
    let (position, size) = bounds(label, size.width, size.height);
    window
        .add_child(WebviewBuilder::new(label, url), position, size)
        .map_err(|e| e.to_string())
}

/// On Linux, Tauri packs each webview in the window's vertical GTK box, where they share the
/// height, and the place given to `add_child` counts for nothing. The bar goes first in the box,
/// at its own height. The tabs share the rest, and GTK gives a hidden tab's share to the other.
#[cfg(target_os = "linux")]
fn pin_bar(bar: &tauri::Webview) -> Result<(), String> {
    bar.with_webview(|webview| {
        use gtk::prelude::*;
        let widget: gtk::Widget = webview.inner().upcast();
        widget.set_size_request(-1, BAR_HEIGHT as i32);
        if let Some(column) = widget.parent().and_then(|p| p.downcast::<gtk::Box>().ok()) {
            column.set_child_packing(&widget, false, true, 0, gtk::PackType::Start);
            column.reorder_child(&widget, 0);
        }
    })
    .map_err(|e| e.to_string())
}

/// Shows the tab `tab`, admin or app, and hides the other. The bar hears of it as `tab`.
fn switch_to(app: &AppHandle, tab: &str) -> Result<(), String> {
    for label in [ADMIN, APP] {
        if let Some(webview) = app.get_webview(label) {
            let shown = if label == tab {
                webview.show().and_then(|_| webview.set_focus())
            } else {
                webview.hide()
            };
            shown.map_err(|e| e.to_string())?;
        }
    }
    app.emit_to(BAR, "tab", tab).map_err(|e| e.to_string())
}

/// Opens Robinauts in the app tab, signed in with a new ticket. The app tab's webview is in no
/// capability: it calls none of the app's commands.
#[tauri::command]
fn open_robinauts(app: AppHandle) -> Result<(), String> {
    let project = project();
    let url = control::ticket_url(project.port, &project.folder.read_secret("launch"))?;
    let url: tauri::Url = url.parse().map_err(|e| format!("{e}"))?;
    match app.get_webview(APP) {
        Some(webview) => webview.navigate(url).map_err(|e| e.to_string())?,
        None => {
            add_webview(&app, APP, WebviewUrl::External(url))?;
        }
    }
    switch_to(&app, APP)
}

/// Shows the admin screens or Robinauts. The first switch to Robinauts opens it.
#[tauri::command]
fn show_tab(app: AppHandle, tab: String) -> Result<(), String> {
    match tab.as_str() {
        ADMIN => switch_to(&app, ADMIN),
        APP if app.get_webview(APP).is_none() => open_robinauts(app),
        APP => switch_to(&app, APP),
        _ => Err(format!("there is no tab {tab:?}")),
    }
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
    if let Some(webview) = app.get_webview(APP) {
        let _ = webview.close();
    }
    switch_to(&app, ADMIN)?;
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
        .setup(|app| {
            let window = WindowBuilder::new(app, WINDOW)
                .title("FA1")
                .inner_size(1280.0, 860.0)
                .build()?;
            // The admin screens first: WebDriver drives the first webview the app makes.
            add_webview(app.handle(), ADMIN, WebviewUrl::App("index.html".into()))?;
            #[cfg_attr(not(target_os = "linux"), allow(unused_variables))]
            let bar = add_webview(app.handle(), BAR, WebviewUrl::App("bar.html".into()))?;
            #[cfg(target_os = "linux")]
            pin_bar(&bar)?;
            lay_out(&window);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::Resized(_) = event {
                lay_out(window);
            }
        })
        .invoke_handler(tauri::generate_handler![
            state,
            plan,
            checks,
            save_keys,
            start,
            stop,
            status,
            open_robinauts,
            show_tab,
            choose_setup_folder,
            refresh,
            reset_code,
            remove_everything
        ])
        .run(tauri::generate_context!())
        .expect("FA1 could not start its window");
}

#[cfg(test)]
mod tests {
    use super::{ADMIN, APP, BAR, BAR_HEIGHT, bounds};

    #[test]
    fn the_bar_takes_the_top_and_each_tab_the_rest() {
        // (label, window width, window height) -> (x, y, width, height)
        let cases = [
            (BAR, 1280.0, 860.0, (0.0, 0.0, 1280.0, BAR_HEIGHT)),
            (
                ADMIN,
                1280.0,
                860.0,
                (0.0, BAR_HEIGHT, 1280.0, 860.0 - BAR_HEIGHT),
            ),
            (
                APP,
                1280.0,
                860.0,
                (0.0, BAR_HEIGHT, 1280.0, 860.0 - BAR_HEIGHT),
            ),
            (APP, 640.0, 30.0, (0.0, BAR_HEIGHT, 640.0, 0.0)),
        ];
        for (label, width, height, expected) in cases {
            let (position, size) = bounds(label, width, height);
            let got = (position.x, position.y, size.width, size.height);
            assert_eq!(got, expected, "{label} in {width}x{height}");
        }
    }
}
