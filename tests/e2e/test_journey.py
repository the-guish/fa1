"""The person's journey through FA1 in mode 2, on the real app and a real Docker engine.

From a fresh folder: the welcome screen, the checks, the keys, the start, a second start while
everything runs, the Cursor API key and the Cursor worker it brings, a stop and a start, Robinauts signed in in the app tab of the one window, FA1's
own application on its rail, a change the designer proposes through its tool servers, the
person's review and approval of it, which puts it in the setup folder, a refresh that deploys
it, a reset of the code workers, a stop, and the removal of everything. WebDriver sees each
webview of the window as a window handle: the admin screens, the bar, and Robinauts. The Claude Code token is not a
real one: the code worker joins the control plane with it, and no turn runs. The Flow designer's
turn is played without its model.

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


REVIEWED = (
    'title = "Reviewed"\nengine = "claude-code"\nmodels = ["cc-haiku"]\nworker = "claude"\n'
    'tools = ["sessions"]\nsystem_prompt = "You help."\n'
)
"""The agent the designer proposes, and the person approves."""

DESIGNER = (
    """
import asyncio, os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

KEY = {"authorization": "Bearer " + os.environ["FA1_SETUP_KEY"]}
FILES = "http://setup-files:8938/mcp"
GIT = "http://setup-git:8939/mcp"
REVIEW = "http://127.0.0.1:8422/mcp"
REPO = "/work/setup"
AGENT = %r


async def call(url, tool, **arguments):
    async with streamablehttp_client(url, headers=KEY) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            done = await session.call_tool(tool, arguments)
            text = " ".join(getattr(part, "text", "") for part in done.content)
            assert not done.isError, (tool, text)
            print(tool + ": " + text)
            return text


async def main():
    branch = "proposals/reviewed"
    await call(GIT, "git_create_branch", repo_path=REPO, branch_name=branch, base_branch="main")
    await call(GIT, "git_checkout", repo_path=REPO, branch_name=branch)
    await call(FILES, "write_file", path=REPO + "/agents/reviewed.toml", content=AGENT)
    checked = await call(REVIEW, "validate_setup")
    assert "passes its checks" in checked, checked
    await call(GIT, "git_add", repo_path=REPO, files=["agents/reviewed.toml"])
    await call(GIT, "git_commit", repo_path=REPO, message="Add the agent Reviewed")
    await call(
        REVIEW,
        "submit_changelist",
        name="add-reviewed",
        branch=branch,
        title="An agent, reviewed",
        description="Adds the agent Reviewed.",
    )


asyncio.run(main())
"""
    % REVIEWED
)
"""The Flow designer's turn, without its model: the calls it makes to its three tool servers,
from where its worker runs, the code container, with the key the app gave that worker
(docs/specs/review-app.md)."""

CONNECTS = """
set -eu
export CLAUDE_CONFIG_DIR=/tmp/journey-claude
mkdir -p /tmp/journey-work && cd /tmp/journey-work
# Claude Code, as the worker's image bundles it with the Agent SDK.
claude=$(python -c 'import claude_agent_sdk as sdk, pathlib
print(pathlib.Path(sdk.__file__).parent / "_bundled" / "claude")')
add() {
    "$claude" mcp add --transport http "$1" "$2" --header "Authorization: Bearer $3" >/dev/null
}
add setup-files http://setup-files:8938/mcp "$FA1_SETUP_KEY"
add setup-git http://setup-git:8939/mcp "$FA1_SETUP_KEY"
add setup-review http://127.0.0.1:8422/mcp "$FA1_SETUP_KEY"
add without-the-key http://setup-git:8939/mcp not-the-key
"$claude" mcp list
"""
"""Claude Code's own MCP client, asked for the health of the designer's three tool servers as
the worker names them, and of one with a wrong key."""


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


def working_copy_main() -> str:
    """The commit the designer's working copy has as main."""
    return docker(
        "exec", "fa1-setup-git-1", "git", "-C", "/work/setup", "rev-parse", "main"
    ).strip()


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
    assert len(steps) == 11
    assert steps[0].startswith("read the setup folder")
    assert steps[3].startswith("mount ") and "in the control plane" in steps[3]
    assert f"{HOME}/compose/compose.yaml build," in steps[4]
    assert steps[4].endswith("--profile cursor build")

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
                 "agents/cursor.toml", "knowledge", "flows/flows.toml", "README.md", ".git"):
        assert (SETUP / name).exists(), name
    # The starter is one commit, FA1's: a changelist starts from a commit.
    assert git(SETUP, "log", "--format=%an: %s").strip() == "FA1: The starter"
    assert git(SETUP, "status", "--porcelain") == ""

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
    git(SETUP, "commit", "-q", "-a", "-m", "My name")

    # Start: the setup folder, the images, the control plane, the token, the code worker. The
    # Keys screen holds no Cursor API key, so the starter's agent on Cursor is left out, and no
    # Cursor worker runs.
    before = len(log_text(driver))
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert "the agents on Cursor are left out (cursor)" in log_text(driver)[before:]
    assert health(driver) == "ok"
    assert docker("ps", "--all", "--quiet", "--filter", "name=fa1-cursor-1") == ""
    assert (HOME / "secrets" / "cursor.env").read_text() == ""
    assert "[workers.cursor]" not in (HOME / "compose" / "robinauts.toml").read_text().split(
        "the setup folder's models and agents"
    )[1]
    code_env = (HOME / "secrets" / "code.env").read_text()
    assert "GITHUB_TOKEN" not in code_env
    # The Keys screen holds no GitHub token, so the control plane's handlers get none either.
    assert "GH_TOKEN" not in (HOME / "secrets" / "control.env").read_text()
    assert "GIT_AUTHOR_NAME=Ada Lovelace" in code_env
    assert (HOME / "secrets" / "worker_token").read_text().startswith("ob_svc_")
    # The control plane mounts the setup folder, and runs as the folder's owner. The designer's
    # working copy starts at the folder's commit.
    head = git(SETUP, "rev-parse", "HEAD").strip()
    owner = str(SETUP.stat().st_uid)
    for container in ("fa1-control-1", "fa1-setup-git-1", "fa1-setup-files-1"):
        assert docker("exec", container, "id", "-u").strip() == owner, container
    assert docker("exec", "fa1-control-1", "git", "-C", "/setup", "rev-parse", "HEAD").strip() == head
    assert working_copy_main() == head
    # The code worker reads the flows' settings, whose repositories a code task names.
    assert docker(
        "exec", "fa1-code-1", "sh", "-c", 'cat "$ROBINAUTS_FLOWS_DIR/flows.toml"'
    ) == (SETUP / "flows" / "flows.toml").read_text()
    # The starter's Flow designer runs on the code worker, so that worker holds the key of the
    # designer's tool servers. No agent of its own uses the files tool, so it holds no key of it.
    setup_key = (HOME / "secrets" / "setup_key").read_text().strip()
    assert setup_key and f"FA1_SETUP_KEY={setup_key}\n" in code_env
    assert setup_key in (HOME / "secrets" / "control.env").read_text()
    assert "FA1_FILES_KEY" not in code_env

    # Start again, while everything runs: the control plane keeps running, and the worker keeps
    # its token.
    control_started = started_at("fa1-control-1")
    token = (HOME / "secrets" / "worker_token").read_text()
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert started_at("fa1-control-1") == control_started
    assert (HOME / "secrets" / "worker_token").read_text() == token
    assert health(driver) == "ok"

    # The Cursor API key, on the Keys screen: the next start deploys the agent on Cursor, builds
    # the Cursor worker with Cursor's CLI, gives it a token and its key, and the worker joins.
    # The key is no real one: the journey runs no turn on Cursor.
    click(driver, "nav button[data-go=keys]")
    form = driver.find_element(By.ID, "key-form")
    form.find_element(By.NAME, "cursor").send_keys("key_not-a-real-key")
    click(driver, "#key-form button[type=submit]")
    WebDriverWait(driver, 10).until(lambda d: screen(d, "run").is_displayed())
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert health(driver) == "ok"
    # The setup changed, so the control plane started anew and forgot the tokens: each worker
    # has a new one.
    assert started_at("fa1-control-1") != control_started
    assert (HOME / "secrets" / "worker_token").read_text() != token
    token = (HOME / "secrets" / "worker_token").read_text()
    cursor_token = (HOME / "secrets" / "cursor_token").read_text()
    assert cursor_token.startswith("ob_svc_") and cursor_token != token
    cursor_env = (HOME / "secrets" / "cursor.env").read_text()
    assert "CURSOR_API_KEY=key_not-a-real-key\n" in cursor_env
    assert "GIT_AUTHOR_NAME=Ada Lovelace" in cursor_env and "FA1_SETUP_KEY" not in cursor_env
    assert docker("exec", "fa1-cursor-1", "id", "-un").strip() == "robinauts"
    version = docker("exec", "fa1-cursor-1", "cursor-agent", "--version").strip()
    assert version and version in (HOME / "compose/workers/cursor/Dockerfile").read_text()
    assert docker(
        "exec", "fa1-cursor-1", "sh", "-c", 'cat "$ROBINAUTS_FLOWS_DIR/flows.toml"'
    ) == (SETUP / "flows" / "flows.toml").read_text()

    # Stop, then start: the control plane forgets the worker's token when it stops. The start
    # gives the worker a new one, and the worker joins again.
    act(driver, "#stop", "stop: done.", 300)
    act(driver, "#start", "Everything is up.", START_SECONDS)
    assert health(driver) == "ok"
    assert (HOME / "secrets" / "worker_token").read_text() != token
    assert (HOME / "secrets" / "cursor_token").read_text() != cursor_token

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
    assert sorted(a["id"] for a in agents["items"]) == [
        "assistant",
        "claude-code",
        "cursor",
        "flow-designer",
    ]

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

    # Reviews, FA1's own application, on the rail below neorc.
    on_rail = "nav[aria-label=Applications] a[data-app]"
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, on_rail))
    rail = [a.get_attribute("data-app") for a in driver.find_elements(By.CSS_SELECTOR, on_rail)]
    assert rail == ["robinauts", "neorc", "reviews"]
    assert {"reviews/submitter", "reviews/approver"} <= set(session["roles"])

    # Claude Code's own client reaches the designer's three tool servers from the code worker,
    # with the key, and is refused without it.
    listed = subprocess.run(
        ["docker", "exec", "-i", "fa1-code-1", "sh", "-s"],
        input=CONNECTS,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stdout + listed.stderr
    reached = {
        line.split(":")[0]: "Connected" in line
        for line in listed.stdout.splitlines()
        if line.startswith(("setup-", "without-the-key"))
    }
    assert reached == {
        "setup-files": True,
        "setup-git": True,
        "setup-review": True,
        "without-the-key": False,
    }, listed.stdout

    # The Flow designer proposes a change: a branch of its working copy, a file, the checks, a
    # commit and a changelist, through its three tool servers. Nothing reaches the setup folder.
    played = subprocess.run(
        ["docker", "exec", "-i", "fa1-code-1", "python", "-"],
        input=DESIGNER,
        capture_output=True,
        text=True,
    )
    assert played.returncode == 0, played.stdout + played.stderr
    assert "Changelist add-reviewed is submitted" in played.stdout, played.stdout
    assert not (SETUP / "agents" / "reviewed.toml").exists()

    # The person reviews it: the changelist on the Pending list, its file side by side, what
    # was checked, and the approval.
    press(driver, "a[data-app=reviews]")
    pending = ".reviews-list tr[data-changelist=add-reviewed]"
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, pending))
    row = driver.find_element(By.CSS_SELECTOR, pending).text
    assert "submitted" in row and "An agent, reviewed" in row, row
    press(driver, pending)
    panel = '.reviews-file[data-path="agents/reviewed.toml"]'
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, panel))
    assert "new file" in driver.find_element(By.CSS_SELECTOR, f"{panel} summary").text
    new = [e.text for e in driver.find_elements(By.CSS_SELECTOR, f"{panel} .reviews-line.new")]
    assert new == REVIEWED.splitlines(), new
    checked = driver.find_element(By.CSS_SELECTOR, ".reviews-checks").text
    assert "5 agents" in checked, checked
    press(driver, "[data-action=approve]")
    approved = ".reviews-header .reviews-status[data-status=approved]"
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, approved))
    outcome = driver.find_element(By.CSS_SELECTOR, ".reviews-outcome")
    assert outcome.get_attribute("data-applied") == "yes" and "Refresh" in outcome.text
    # The approval put the designer's commit in the setup folder, as the folder's owner. The
    # working copy's main follows. Robinauts serves the new agent only after a refresh.
    reviewed = SETUP / "agents" / "reviewed.toml"
    assert reviewed.read_text() == REVIEWED
    assert reviewed.stat().st_uid == SETUP.stat().st_uid
    assert (
        git(SETUP, "log", "-1", "--format=%an: %s").strip()
        == "Flow designer: Add the agent Reviewed"
    )
    assert git(SETUP, "status", "--porcelain") == ""
    head = git(SETUP, "rev-parse", "HEAD").strip()
    WebDriverWait(driver, 30).until(lambda d: working_copy_main() == head)
    press(driver, "[data-action=back]")
    closed_row = ".reviews-list tr[data-changelist=add-reviewed]"
    WebDriverWait(driver, 30).until(lambda d: d.find_elements(By.CSS_SELECTOR, closed_row))
    assert (
        driver.find_element(By.CSS_SELECTOR, ".reviews-entry[data-state=closed]").get_attribute(
            "aria-current"
        )
        == "page"
    )
    data = docker("exec", "fa1-control-1", "ls", "/var/lib/robinauts/data").split()
    assert "reviews.db" in data, data
    press(driver, "a[data-app=robinauts]")

    def serving_again() -> list[str]:
        """The agents Robinauts serves, once the App tab signed in again after a restart."""
        driver.switch_to.window(robinauts)
        WebDriverWait(driver, 60).until(
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
        return sorted(a["id"] for a in agents["items"])

    # Refresh: FA1 deploys the setup folder, and Robinauts serves the new agent. The review app
    # still sees the change in the folder.
    assert serving_again() == ["assistant", "claude-code", "cursor", "flow-designer"]
    driver.switch_to.window(main)
    act(driver, "#refresh-setup", "refresh: done.", START_SECONDS)
    assert git(SETUP, "rev-parse", "HEAD").strip() == head
    assert serving_again() == ["assistant", "claude-code", "cursor", "flow-designer", "reviewed"]
    closed = driver.execute_async_script(
        "const done = arguments[arguments.length - 1];"
        "fetch('/reviews/api/changelists?state=closed').then(r => r.json())"
        ".then(done, e => done(String(e)));"
    )
    assert [(c["name"], c["status"], c["applied"]) for c in closed["items"]] == [
        ("add-reviewed", "approved", True)
    ], closed
    assert working_copy_main() == head

    # Refresh again: the setup folder pulls a new agent from its remote, and Robinauts serves it.
    remote = HOME.parent / "setup-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
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
    assert serving_again() == [
        "assistant",
        "claude-code",
        "cursor",
        "flow-designer",
        "helper",
        "reviewed",
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

    # Reset: the code workers' containers and volumes go, and they join again.
    docker("exec", "fa1-code-1", "touch", "/workspace/left-behind")
    docker("exec", "fa1-cursor-1", "touch", "/workspace/left-behind", "/var/lib/cursor/left-behind")
    driver.execute_script("window.confirm = () => true")
    act(driver, "#reset", "reset: done.", 300)
    WebDriverWait(driver, 120, poll_frequency=3).until(lambda d: health(d) == "ok")
    listed = subprocess.run(
        ["docker", "exec", "fa1-code-1", "ls", "/workspace"], capture_output=True, text=True
    )
    assert "left-behind" not in listed.stdout
    assert "left-behind" not in docker("exec", "fa1-cursor-1", "ls", "/workspace", "/var/lib/cursor")

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
