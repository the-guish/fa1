// The app's commands, each allowed by name in capabilities/main.json. The webview that shows
// Robinauts is listed in no capability, so it calls none of them.
fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "state",
            "plan",
            "checks",
            "save_keys",
            "start",
            "stop",
            "status",
            "open_robinauts",
            "show_tab",
            "reset_code",
            "remove_everything",
        ]),
    ))
    .expect("tauri-build failed");
}
