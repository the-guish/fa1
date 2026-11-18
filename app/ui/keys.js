// Ctrl+1 shows Admin and Ctrl+2 shows App, from FA1's own pages: the bar and the admin screens.
// Robinauts' page gets the same keys from a script the core adds to its webview.
document.addEventListener(
  "keydown",
  (event) => {
    if (!event.ctrlKey || event.altKey || event.shiftKey || event.metaKey) return;
    const tab = { 1: "admin", 2: "app" }[event.key];
    if (!tab) return;
    event.preventDefault();
    window.__TAURI__.core.invoke("show_tab", { tab }).catch(() => {});
  },
  true,
);
