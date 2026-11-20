"""The person's journey through FA1 in mode 2, on the real app and a real Docker engine.

From a fresh folder: the welcome screen, the checks, the keys, the start, a second start while
everything runs, a stop and a start, Robinauts signed in in the app tab of the one window, FA1's
own application on its rail, a reset of the code worker, a stop, and the removal of
everything. WebDriver sees each webview of the window as a window handle: the admin screens,
the bar, and Robinauts. The
Claude Code token is not a real one: the code worker joins the control plane with it, and no
turn runs.

Needs: Docker with Compose and Buildx, an X display (Xvfb), WebKitWebDriver, tauri-driver on
4444, and the app built: `cargo build --manifest-path app/Cargo.toml`. tests/e2e/run.sh starts
them. FA1_HOME names the app's folder for the run. Nothing else may listen on 127.0.0.1:8420.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

APP = Path(__file__).resolve().parents[2] / "app" / "target" / "debug" / "fa1"
HOME = Path(os.environ["FA1_HOME"])
SETUP = HOME.parent / "setup"
"""The person's setup folder, which FA1 makes at the Welcome screen (docs/specs/setup-folder.md)."""


def git(folder: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), "-c", "user.name=Ada", "-c", "user.email=ada@example.com", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
START_SECONDS = 1800
"""A first start builds every image."""


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def app():
    options = webdriver.ChromeOptions()  # any options object: tauri-driver reads tauri:options
    options.set_capability("browserName", "wry")
    options.set_capability("tauri:options", {"application": str(APP)})
    driver = webdriver.Remote("http://127.0.0.1:4444", options=options)
    yield driver
    driver.quit()


def screen(driver, name: str):
    return driver.find_element(By.ID, name)


def click(driver, selector: str) -> None:
    driver.find_element(By.CSS_SELECTOR, selector).click()


def press(driver, selector: str) -> None:
    """Clicks from inside the page. A WebDriver click on a button that hides its own webview
    waits for that webview forever."""
    driver.execute_script("document.querySelector(arguments[0]).click()", selector)


def log_text(driver) -> str:
    return driver.find_element(By.ID, "log").text


def act(driver, selector: str, text: str, seconds: float) -> None:
    """Clicks the action at `selector`, then waits for a new line holding `text` in the log. A
    line holding "failed:" fails the journey."""
    before = len(log_text(driver))
    click(driver, selector)

    def new(d) -> str:
        return log_text(d)[before:]

    WebDriverWait(driver, seconds, poll_frequency=2).until(
        lambda d: text in new(d) or "failed:" in new(d)
    )
    assert "failed:" not in new(driver), new(driver)[-3000:]


def started_at(container: str) -> str:
    return docker("inspect", "--format", "{{.State.StartedAt}}", container).strip()


def handle_at(driver, url_part: str) -> str:
    """The handle of the webview whose URL holds `url_part`, or "" for none."""
    here = driver.current_window_handle
    found = ""
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        if url_part in driver.current_url:
            found = handle
            break
    driver.switch_to.window(here)
    return found


BAR_HEIGHT = 44
"""The bar's height, as app/src/main.rs sets it."""


def inner_size(driver, handle: str) -> tuple[int, int]:
    """The width and height of the webview at `handle`, from inside it."""
    here = driver.current_window_handle
    driver.switch_to.window(handle)
    size = driver.execute_script("return [window.innerWidth, window.innerHeight]")
    driver.switch_to.window(here)
    return tuple(size)


def health(driver) -> str:
    click(driver, "#refresh")
    time.sleep(1)
    return driver.find_element(By.ID, "health").text


def test_the_journey_from_a_fresh_folder_to_its_removal(app) -> None:
    driver = app
    assert not HOME.exists()

    # One window: the admin screens, driven first, and the bar above them.
    main = driver.current_window_handle
    assert "bar.html" not in driver.current_url
    assert len(driver.window_handles) == 2
    bar = handle_at(driver, "/bar.html")
    assert bar

    # Welcome: the modes, the folder and the plan. Containers is the one mode on offer.
    assert screen(driver, "welcome").is_displayed()
    assert driver.find_element(By.ID, "folder").text == str(HOME)
    modes = driver.find_elements(By.CSS_SELECTOR, "input[name=mode]")
    assert [(m.get_attribute("value"), m.is_enabled()) for m in modes] == [
        ("host", False),
        ("containers", True),
        ("vms", False),
    ]
    click(driver, "#welcome summary")
    steps = [li.text for li in driver.find_elements(By.CSS_SELECTOR, "#plan li")]
    assert len(steps) == 9
    assert steps[0].startswith("read the setup folder")
    assert steps[3].endswith(f"{HOME}/compose/compose.yaml build")

    # Welcome: the setup folder. One inside the app's folder is refused; a new one gets the
    # starter, in a git repository.
    folder_input = driver.find_element(By.ID, "setup-folder")
    folder_input.send_keys(str(HOME / "inside"))
    click(driver, "#welcome button.primary")
    WebDriverWait(driver, 10).until(lambda d: d.find_element(By.ID, "setup-error").text)
    assert "inside" in driver.find_element(By.ID, "setup-error").text
    assert screen(driver, "welcome").is_displayed()
    folder_input.clear()
    folder_input.send_keys(str(SETUP))

    # Checks: Docker, Compose and Buildx are here.
    click(driver, "#welcome button.primary")
    WebDriverWait(driver, 60).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "#check-list li")) == 3
    )
    for item in driver.find_elements(By.CSS_SELECTOR, "#check-list li"):
        assert item.get_attribute("class") == "ok", item.text

    for name in ("fa1.toml", "models.toml", "agents/assistant.toml", "agents/claude-code.toml",
                 "knowledge", "flows/flows.toml", "README.md", ".git"):
        assert (SETUP / name).exists(), name

    # Keys: the keys alone. The secrets folder is the person's alone.
    click(driver, "#checks button.primary")
    form = driver.find_element(By.ID, "key-form")
    form.find_element(By.NAME, "claude_code").send_keys("sk-ant-oat01-not-a-real-token")
    click(driver, "#key-form button[type=submit]")
    WebDriverWait(driver, 10).until(lambda d: screen(d, "run").is_displayed())
    assert (HOME / "secrets").stat().st_mode & 0o777 == 0o700
    assert (HOME / "secrets" / "keys.toml").stat().st_mode & 0o777 == 0o600
    assert driver.find_element(By.ID, "setup-path").text == str(SETUP)

    # The setup folder's settings: a mistake stops the start, naming the file.
    fa1_toml = SETUP / "fa1.toml"
    fa1_toml.write_text("[git]\nname = 1\n")
    before = len(log_text(driver))
    click(driver, "#start")
    WebDriverWait(driver, 60).until(lambda d: "failed:" in log_text(d)[before:])
    failure = log_text(driver)[before:]
    assert "fa1.toml [git] name" in failure, failure
    fa1_toml.write_text(
        '[git]\nname = "Ada Lovelace"\nemail = "ada@example.com"\n'
    )

    # Start: the setup folder, the images, the control plane, the token, the code worker.
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert health(driver) == "ok"
    code_env = (HOME / "secrets" / "code.env").read_text()
    assert "GITHUB_TOKEN" not in code_env
    assert "GIT_AUTHOR_NAME=Ada Lovelace" in code_env
    assert (HOME / "secrets" / "worker_token").read_text().startswith("ob_svc_")

    # Start again, while everything runs: the control plane keeps running, and the worker keeps
    # its token.
    control_started = started_at("fa1-control-1")
    token = (HOME / "secrets" / "worker_token").read_text()
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert started_at("fa1-control-1") == control_started
    assert (HOME / "secrets" / "worker_token").read_text() == token
    assert health(driver) == "ok"

    # Stop, then start: the control plane forgets the worker's token when it stops. The start
    # gives the worker a new one, and the worker joins again.
    act(driver, "#stop", "stop: done.", 300)
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert health(driver) == "ok"
    assert (HOME / "secrets" / "worker_token").read_text() != token

    # Robinauts, signed in, in the app tab. Its webview calls none of the app's commands.
    press(driver, "#open")
    WebDriverWait(driver, 30).until(lambda d: handle_at(d, "127.0.0.1:8420"))
    robinauts = handle_at(driver, "127.0.0.1:8420")
    driver.switch_to.window(robinauts)
    session = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/auth/session').then(r => r.json()).then(done, e => done(String(e)));"
    )
    assert session["mode"] == "local"
    assert session["principal"] is not None
    agents = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/robinauts/api/agents').then(r => r.json()).then(done, e => done(String(e)));"
    )
    assert sorted(a["id"] for a in agents["items"]) == ["assistant", "claude-code", "flow-designer"]

    # Flows: the starter's hello flow runs on the control plane, started from Robinauts' page
    # as a person would, and its handler's result is the run's output.
    started = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/robinauts/api/flows/hello/runs', {method: 'POST',"
        " headers: {'content-type': 'application/json'},"
        " body: JSON.stringify({inputs: {name: 'Ada'}})})"
        ".then(async r => done([r.status, await r.text()]), e => done([0, String(e)]));"
    )
    assert started[0] == 201, started
    run_id = json.loads(started[1])["id"]

    def run_state(d) -> dict:
        for path in (f"/neorc/runs/{run_id}", f"/neorc/api/runs/{run_id}"):
            answer = d.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "fetch(arguments[0]).then(async r => done([r.status, await r.text()]),"
                " e => done([0, String(e)]));",
                path,
            )
            if answer[0] == 200:
                return json.loads(answer[1])
        return {"status": "unknown", "answer": answer}

    WebDriverWait(driver, 120, poll_frequency=2).until(
        lambda d: run_state(d)["status"] in ("succeeded", "failed", "cancelled")
    )
    finished = run_state(driver)
    assert finished["status"] == "succeeded", finished
    assert finished["output"] == "Hello, Ada", finished

    # Reviews, FA1's own application: on the rail below neorc, with its one panel, its API
    # behind the same sign-in, and its records beside the control plane's.
    on_rail = "nav[aria-label=Applications] a[data-app]"
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, on_rail))
    rail = [a.get_attribute("data-app") for a in driver.find_elements(By.CSS_SELECTOR, on_rail)]
    assert rail == ["robinauts", "neorc", "reviews"]
    press(driver, "a[data-app=reviews]")
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, ".reviews-panel"))
    assert driver.find_element(By.CSS_SELECTOR, ".reviews-panel").text == "something to review"
    reviews = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/reviews/api/reviews').then(async r => done([r.status, await r.json()]),"
        " e => done([0, String(e)]));"
    )
    assert reviews == [200, {"items": []}], reviews
    assert "reviews/user" in session["roles"]
    data = docker("exec", "fa1-control-1", "ls", "/var/lib/robinauts/data").split()
    assert "reviews.db" in data, data
    press(driver, "a[data-app=robinauts]")

    # Refresh: the setup folder pulls a new agent from its remote, and Robinauts serves it.
    remote = HOME.parent / "setup-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    git(SETUP, "add", "-A")
    git(SETUP, "commit", "-q", "-m", "The starter")
    git(SETUP, "remote", "add", "origin", str(remote))
    git(SETUP, "push", "-q", "-u", "origin", "HEAD")
    other = HOME.parent / "setup-elsewhere"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    (other / "agents" / "helper.toml").write_text(
        'title = "Helper"\nengine = "claude-code"\nmodels = ["cc-haiku"]\nworker = "claude"\n'
        'tools = ["sessions"]\nsystem_prompt = "You help."\n'
    )
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "A helper")
    git(other, "push", "-q")
    driver.switch_to.window(main)
    act(driver, "#refresh-setup", "refresh: done.", START_SECONDS)
    assert (SETUP / "agents" / "helper.toml").exists()
    # The refresh restarted the control plane, which ended the sign-in: the App tab signs in
    # again on its own.
    driver.switch_to.window(robinauts)
    WebDriverWait(driver, 30).until(
        lambda d: d.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            "fetch('/robinauts/api/agents').then(r => done(r.status), e => done(0));"
        )
        == 200
    )
    agents = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/robinauts/api/agents').then(r => r.json()).then(done, e => done(String(e)));"
    )
    assert "items" in agents, agents
    assert sorted(a["id"] for a in agents["items"]) == [
        "assistant",
        "claude-code",
        "flow-designer",
        "helper",
    ]
    called = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "window.__TAURI__.core.invoke('state').then(() => done('allowed'), e => done(String(e)));"
    )
    assert called != "allowed"
    assert "not allowed" in called, called
    switched = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "window.__TAURI__.core.invoke('show_tab', {tab: 'admin'})"
        ".then(() => done('allowed'), e => done(String(e)));"
    )
    assert "not allowed" in switched, switched

    # The three webviews share one window, so the window's rectangle is the same from each.
    rects = set()
    for handle in (main, bar, robinauts):
        driver.switch_to.window(handle)
        rect = driver.get_window_rect()
        rects.add((rect["x"], rect["y"], rect["width"], rect["height"]))
    assert len(rects) == 1, rects

    # The bar takes the top of the window, and the tab on show takes the rest, at any size. Each
    # webview measures itself; the window's size is the bar's outer size.
    def layout(shown: str) -> tuple:
        here = driver.current_window_handle
        driver.switch_to.window(bar)
        window = tuple(driver.execute_script("return [outerWidth, outerHeight]"))
        driver.switch_to.window(here)
        return window, inner_size(driver, bar), inner_size(driver, shown)

    def check_layout(shown: str) -> None:
        def fits(_) -> bool:
            (width, height), bar_size, shown_size = layout(shown)
            return bar_size == (width, BAR_HEIGHT) and shown_size == (width, height - BAR_HEIGHT)

        try:
            WebDriverWait(driver, 10, poll_frequency=0.5).until(fits)
        except Exception:
            raise AssertionError(f"window, bar, tab: {layout(shown)}") from None

    check_layout(robinauts)

    # The bar marks the tab on show, and switches between them. Robinauts stays open.
    def pressed(tab: str) -> str:
        return driver.find_element(By.ID, f"tab-{tab}").get_attribute("aria-pressed")

    driver.switch_to.window(bar)
    WebDriverWait(driver, 10).until(lambda d: pressed("app") == "true")
    click(driver, "#tab-admin")
    WebDriverWait(driver, 10).until(lambda d: pressed("admin") == "true")
    assert pressed("app") == "false"
    check_layout(main)
    driver.set_window_rect(width=1000, height=700)
    WebDriverWait(driver, 10).until(lambda d: layout(main)[0] == (1000, 700))
    check_layout(main)
    click(driver, "#tab-app")
    WebDriverWait(driver, 10).until(lambda d: pressed("app") == "true")
    assert len(driver.window_handles) == 3
    click(driver, "#tab-admin")
    WebDriverWait(driver, 10).until(lambda d: pressed("admin") == "true")
    driver.switch_to.window(main)

    # Reset: the code worker's container and volumes go, and it joins again.
    docker("exec", "fa1-code-1", "touch", "/workspace/left-behind")
    driver.execute_script("window.confirm = () => true")
    act(driver, "#reset", "reset: done.", 300)
    WebDriverWait(driver, 120, poll_frequency=3).until(lambda d: health(d) == "ok")
    listed = subprocess.run(
        ["docker", "exec", "fa1-code-1", "ls", "/workspace"], capture_output=True, text=True
    )
    assert "left-behind" not in listed.stdout

    # Stop: the control plane stops answering.
    act(driver, "#stop", "stop: done.", 300)
    assert health(driver) == "unreachable"

    # Remove everything: the project's containers, volumes and images, then the folder.
    driver.execute_script("window.confirm = () => true")
    act(driver, "#remove", "remove: done.", 600)
    assert driver.find_element(By.ID, "removed").is_displayed()
    assert not HOME.exists()
    assert not handle_at(driver, "127.0.0.1:8420")
    assert docker("ps", "--all", "--filter", "label=com.docker.compose.project=fa1", "--quiet") == ""
    assert docker("volume", "ls", "--filter", "label=com.docker.compose.project=fa1", "--quiet") == ""
    images = docker("image", "ls", "--format", "{{.Repository}}")
    assert not [i for i in images.split() if i.startswith("fa1-")]
