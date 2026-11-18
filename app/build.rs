// The app's commands, each allowed by name in capabilities/main.json. The window that shows
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
            "reset_code",
            "remove_everything",
        ]),
    ))
    .expect("tauri-build failed");
}
