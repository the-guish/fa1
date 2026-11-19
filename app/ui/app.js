// FA1's screens. Every command runs in the app's core: this page asks and shows.
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (selector) => document.querySelector(selector);

function show(screen) {
  for (const section of document.querySelectorAll("main > section")) {
    section.hidden = section.id !== screen;
  }
  if (screen === "checks") runChecks();
  if (screen === "run") refresh();
}

function log(line) {
  const pre = $("#log");
  pre.textContent += line + "\n";
  pre.scrollTop = pre.scrollHeight;
}

async function act(command) {
  try {
    await invoke(command);
  } catch (error) {
    log(`! ${error}`);
  }
}

async function runChecks() {
  const list = $("#check-list");
  list.textContent = "Checking…";
  const found = await invoke("checks");
  list.textContent = "";
  for (const check of found) {
    const item = document.createElement("li");
    item.className = check.ok ? "ok" : "missing";
    item.append(`${check.ok ? "✓" : "✗"} ${check.name}: ${check.detail}`);
    if (check.fix) {
      const fix = document.createElement("pre");
      fix.textContent = check.fix;
      item.append(fix);
    }
    list.append(item);
  }
}

async function refresh() {
  const status = await invoke("status");
  $("#health").textContent = status.health;
  $("#containers").textContent = status.containers.trim() || "No containers yet.";
}

async function load() {
  const state = await invoke("state");
  $("#folder").textContent = state.folder;
  for (const small of document.querySelectorAll("[data-given]")) {
    small.textContent = state.given[small.dataset.given] ? "Saved." : "";
  }
  const form = $("#key-form");
  $("#setup-folder").value = state.setup_folder || "";
  $("#setup-folder").placeholder = state.suggested_setup_folder;
  $("#setup-path").textContent = state.setup_folder || "none yet";
  const plan = $("#plan");
  plan.textContent = "";
  for (const step of await invoke("plan")) {
    const item = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = step;
    item.append(code);
    plan.append(item);
  }
  show(state.mode ? "run" : "welcome");
}

for (const button of document.querySelectorAll("[data-go]")) {
  button.addEventListener("click", () => show(button.dataset.go));
}

$("#recheck").addEventListener("click", runChecks);

$("#welcome-next").addEventListener("click", async () => {
  const input = $("#setup-folder");
  $("#setup-error").textContent = "";
  try {
    const chosen = await invoke("choose_setup_folder", { path: input.value.trim() || input.placeholder });
    input.value = chosen;
    $("#setup-path").textContent = chosen;
    show("checks");
  } catch (error) {
    $("#setup-error").textContent = `${error}`;
  }
});

$("#key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const keys = Object.fromEntries(new FormData(form));
  $("#key-error").textContent = "";
  try {
    await invoke("save_keys", { keys });
    for (const field of ["claude_code", "anthropic", "github"]) form[field].value = "";
    await load();
    show("run");
  } catch (error) {
    $("#key-error").textContent = `${error}`;
  }
});

$("#start").addEventListener("click", () => act("start"));
$("#stop").addEventListener("click", () => act("stop"));
$("#refresh").addEventListener("click", refresh);
$("#refresh-setup").addEventListener("click", () => act("refresh"));
$("#open").addEventListener("click", () => act("open_robinauts"));
$("#reset").addEventListener("click", () => {
  if (confirm("Delete the code worker's container, workspaces and transcripts, and start it again?")) {
    act("reset_code");
  }
});
$("#remove").addEventListener("click", () => {
  if (confirm(`Remove FA1's containers, volumes, images, and the folder ${$("#folder").textContent}?`)) {
    act("remove_everything");
  }
});

listen("log", (event) => log(event.payload));
listen("done", (event) => {
  const { what, error } = event.payload;
  log(error ? `! ${what} failed: ${error}` : `${what}: done.`);
  if (what === "remove" && !error) $("#removed").hidden = false;
  refresh();
});

load();
