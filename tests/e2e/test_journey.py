"""The person's journey through FA1 in mode 2, on the real app and a real Docker engine.

From a fresh folder: the welcome screen, the checks, the keys, the start, Robinauts signed in
in its own window, a reset of the code worker, a stop, and the removal of everything. The
Claude Code token is not a real one: the code worker joins the control plane with it, and no
turn runs.

Needs: Docker with Compose and Buildx, an X display (Xvfb), WebKitWebDriver, tauri-driver on
4444, and the app built: `cargo build --manifest-path app/Cargo.toml`. tests/e2e/run.sh starts
them. FA1_HOME names the app's folder for the run. Nothing else may listen on 127.0.0.1:8420.
"""

from __future__ import annotations

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


def log_text(driver) -> str:
    return driver.find_element(By.ID, "log").text


def wait_for_log(driver, text: str, seconds: float) -> None:
    WebDriverWait(driver, seconds, poll_frequency=2).until(
        lambda d: text in log_text(d) or "failed:" in log_text(d)
    )
    assert "failed:" not in log_text(driver), log_text(driver)[-3000:]


def health(driver) -> str:
    click(driver, "#refresh")
    time.sleep(1)
    return driver.find_element(By.ID, "health").text


def test_the_journey_from_a_fresh_folder_to_its_removal(app) -> None:
    driver = app
    assert not HOME.exists()

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
    assert len(steps) == 8
    assert steps[2].endswith(f"{HOME}/compose/compose.yaml build")

    # Checks: Docker, Compose and Buildx are here.
    click(driver, "#welcome button.primary")
    WebDriverWait(driver, 60).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "#check-list li")) == 3
    )
    for item in driver.find_elements(By.CSS_SELECTOR, "#check-list li"):
        assert item.get_attribute("class") == "ok", item.text

    # Keys: the token and the author. The secrets folder is the person's alone.
    click(driver, "#checks button.primary")
    form = driver.find_element(By.ID, "key-form")
    form.find_element(By.NAME, "claude_code").send_keys("sk-ant-oat01-not-a-real-token")
    form.find_element(By.NAME, "git_name").send_keys("Ada Lovelace")
    form.find_element(By.NAME, "git_email").send_keys("ada@example.com")
    click(driver, "#key-form button[type=submit]")
    WebDriverWait(driver, 10).until(lambda d: screen(d, "run").is_displayed())
    assert (HOME / "secrets").stat().st_mode & 0o777 == 0o700
    assert (HOME / "secrets" / "keys.toml").stat().st_mode & 0o777 == 0o600

    # Start: the images, the control plane, the token, the code worker.
    click(driver, "#start")
    wait_for_log(driver, "Everything is up.", START_SECONDS)
    assert health(driver) == "ok"
    code_env = (HOME / "secrets" / "code.env").read_text()
    assert "GITHUB_TOKEN" not in code_env
    assert "GIT_AUTHOR_NAME=Ada Lovelace" in code_env
    assert (HOME / "secrets" / "worker_token").read_text().startswith("ob_svc_")
    published = docker("port", "fa1-control-1")
    assert published.strip() == "8420/tcp -> 127.0.0.1:8420"

    # Robinauts, signed in, in its own window. That window calls none of the app's commands.
    main = driver.current_window_handle
    click(driver, "#open")
    WebDriverWait(driver, 30).until(lambda d: len(d.window_handles) == 2)
    driver.switch_to.window(next(h for h in driver.window_handles if h != main))
    WebDriverWait(driver, 30).until(lambda d: d.current_url.startswith("http://127.0.0.1:8420/"))
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
    assert sorted(a["id"] for a in agents["items"]) == ["assistant", "claude-code"]
    called = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "window.__TAURI__.core.invoke('state').then(() => done('allowed'), e => done(String(e)));"
    )
    assert called != "allowed"
    assert "not allowed" in called, called
    driver.switch_to.window(main)

    # Reset: the code worker's container and volumes go, and it joins again.
    docker("exec", "fa1-code-1", "touch", "/workspace/left-behind")
    driver.execute_script("window.confirm = () => true")
    click(driver, "#reset")
    wait_for_log(driver, "reset: done.", 300)
    WebDriverWait(driver, 120, poll_frequency=3).until(lambda d: health(d) == "ok")
    listed = subprocess.run(
        ["docker", "exec", "fa1-code-1", "ls", "/workspace"], capture_output=True, text=True
    )
    assert "left-behind" not in listed.stdout

    # Stop: the control plane stops answering.
    click(driver, "#stop")
    wait_for_log(driver, "stop: done.", 300)
    assert health(driver) == "unreachable"

    # Remove everything: the project's containers, volumes and images, then the folder.
    driver.execute_script("window.confirm = () => true")
    click(driver, "#remove")
    wait_for_log(driver, "remove: done.", 600)
    assert driver.find_element(By.ID, "removed").is_displayed()
    assert not HOME.exists()
    assert docker("ps", "--all", "--filter", "label=com.docker.compose.project=fa1", "--quiet") == ""
    assert docker("volume", "ls", "--filter", "label=com.docker.compose.project=fa1", "--quiet") == ""
    images = docker("image", "ls", "--format", "{{.Repository}}")
    assert not [i for i in images.split() if i.startswith("fa1-")]
