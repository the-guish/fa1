// The bar above the tabs: Admin shows FA1's screens, App shows Robinauts. The core switches the
// tabs, and tells the bar which one shows with the event `tab`.
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const error = document.querySelector("#bar-error");

function mark(tab) {
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.setAttribute("aria-pressed", String(button.dataset.tab === tab));
  }
}

for (const button of document.querySelectorAll("[data-tab]")) {
  button.addEventListener("click", async () => {
    error.textContent = "";
    try {
      await invoke("show_tab", { tab: button.dataset.tab });
    } catch (e) {
      error.textContent = `${e}`;
    }
  });
}

listen("tab", (event) => {
  error.textContent = "";
  mark(event.payload);
});
