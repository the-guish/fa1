"""The review app, without Docker (docs/specs/review-app.md): a setup folder, its bundle, a
working copy as the tool servers hold it, and the review app's own repository, on real git.

Needs Robinauts at the pinned commit, with neorc and oneberth, and git: tests/apps/run.sh
runs these with them.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps"))

from reviews.backend import (  # noqa: E402
    Conflict,
    Invalid,
    NotFound,
    Refused,
    Reviews,
    reviews,
    snapshot,
)

STARTER = ROOT / "setup-starter"
BASE = ROOT / "compose" / "robinauts.base.toml"
KEY = "a-key-of-the-tests"

GIT_ENV = {
    "PATH": os.environ["PATH"],
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Ada",
    "GIT_AUTHOR_EMAIL": "ada@example.com",
    "GIT_COMMITTER_NAME": "Ada",
    "GIT_COMMITTER_EMAIL": "ada@example.com",
}


def git(folder: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(folder), *arguments], env=GIT_ENV, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


class World:
    """The setup folder on the host, the bundle the app writes from it, the designer's working
    copy, and the review app."""

    def __init__(self, at: Path) -> None:
        self.at = at
        self.setup = at / "setup"
        self.bundle = at / "published" / "main.bundle"
        self.work = at / "work" / "setup"
        self.deployed = at / "deployed-flows"
        shutil.copytree(STARTER, self.setup)
        git(self.setup, "init", "--quiet", "--initial-branch", "trunk")
        git(self.setup, "add", "--all")
        git(self.setup, "commit", "--quiet", "--message", "The starter")
        self.publish()
        # The working copy, as the tool servers' start makes it (compose/setup-tools/start.sh).
        self.work.mkdir(parents=True)
        git(self.work, "init", "--quiet", "--initial-branch", "main")
        git(self.work, "fetch", "--quiet", str(self.bundle), "HEAD")
        git(self.work, "checkout", "--quiet", "-B", "main", "FETCH_HEAD")
        self.store = Reviews(
            at / "data", work=self.work, published=self.bundle, config=BASE, flows=self.deployed
        )
        self.store.set_up()

    def publish(self) -> None:
        """What the app does at each start and refresh: the bundle, and the flows that run."""
        self.bundle.parent.mkdir(exist_ok=True)
        git(self.setup, "bundle", "create", "--quiet", str(self.bundle), "HEAD")
        shutil.rmtree(self.deployed, ignore_errors=True)
        shutil.copytree(self.setup / "flows", self.deployed)

    def branch(self, name: str, files: dict[str, str | None], message: str = "A change") -> str:
        """A branch of the working copy from its main, with `files` written or removed, and
        committed; the commit."""
        git(self.work, "checkout", "--quiet", "-B", name, "main")
        self.commit(files, message)
        return git(self.work, "rev-parse", "HEAD")

    def commit(self, files: dict[str, str | None], message: str = "More") -> None:
        for path, text in files.items():
            target = self.work / path
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        git(self.work, "add", "--all")
        git(self.work, "commit", "--quiet", "--message", message)

    def refresh(self) -> bool:
        """What Refresh does on the host: the approved commits into the setup folder, then
        the bundle anew. Whether there was any."""
        bundle = self.store.approved_bundle()
        if bundle is None:
            return False
        fetched = self.at / "approved.bundle"
        fetched.write_bytes(bundle)
        git(
            self.setup,
            "-c",
            "fetch.fsckObjects=true",
            "fetch",
            "--quiet",
            str(fetched),
            "refs/heads/main",
        )
        git(self.setup, "merge", "--quiet", "--ff-only", "FETCH_HEAD")
        self.publish()
        return True


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


HELPER = (
    'title = "Helper"\nsystem_prompt = "You help."\nengine = "pydantic-ai"\nmodels = ["sonnet"]\n'
)


def test_a_branch_is_submitted_reviewed_approved_and_reaches_the_setup_folder(world: World) -> None:
    commit = world.branch(
        "proposals/helper", {"agents/helper.toml": HELPER, "knowledge/README.md": None}
    )
    made = world.store.submit("helper", "proposals/helper", "A helper", "Adds the agent Helper.")
    assert made["status"] == "submitted" and made["commit"] == commit
    assert made["summary"][0] == "4 agents, 5 models"

    [listed] = world.store.changelists("pending")
    assert (listed["name"], listed["title"], listed["applied"]) == ("helper", "A helper", False)
    shown = world.store.changelist("helper")
    assert shown["description"] == "Adds the agent Helper."
    files = {f["path"]: (f["status"], f["old"], f["new"]) for f in shown["files"]}
    assert files["agents/helper.toml"] == ("added", None, HELPER)
    status, old, new = files["knowledge/README.md"]
    assert (status, new) == ("deleted", None) and old == (
        STARTER / "knowledge/README.md"
    ).read_text()

    # Nothing reaches the setup folder before the approval.
    assert world.store.approved_bundle() is None
    assert world.store.approve("helper") == {"name": "helper", "status": "approved"}
    assert world.store.changelists("pending") == []
    [closed] = world.store.changelists("closed")
    assert (closed["status"], closed["applied"]) == ("approved", False)

    assert world.refresh()
    assert (world.setup / "agents/helper.toml").read_text() == HELPER
    assert not (world.setup / "knowledge/README.md").exists()
    assert git(world.setup, "rev-parse", "HEAD") == commit
    assert git(world.setup, "status", "--porcelain") == ""
    [closed] = world.store.changelists("closed")
    assert closed["applied"] is True
    assert world.store.approved_bundle() is None


def test_a_changelist_pins_the_commit_it_was_submitted_at(world: World) -> None:
    reviewed = world.branch("proposals/pin", {"knowledge/pin.md": "reviewed\n"})
    world.store.submit("pin", "proposals/pin", "Pin")
    world.commit({"knowledge/pin.md": "slipped in after the review\n"})
    assert world.store.changelist("pin")["commit"] == reviewed
    world.store.approve("pin")
    world.refresh()
    assert (world.setup / "knowledge/pin.md").read_text() == "reviewed\n"

    # The later commit is a new submit, and an approved name is not taken again.
    with pytest.raises(Conflict, match="approved"):
        world.store.submit("pin", "proposals/pin", "Pin")


def test_a_rejected_changelist_takes_a_new_commit_under_its_name(world: World) -> None:
    world.branch("proposals/again", {"knowledge/again.md": "first\n"})
    world.store.submit("again", "proposals/again", "Again")
    assert world.store.reject("again")["status"] == "rejected"
    assert [c["status"] for c in world.store.changelists("closed")] == ["rejected"]
    with pytest.raises(Conflict, match="rejected"):
        world.store.approve("again")
    world.commit({"knowledge/again.md": "second\n"})
    world.store.submit("again", "proposals/again", "Again, better")
    [pending] = world.store.changelists("pending")
    assert pending["title"] == "Again, better"
    [file] = world.store.changelist("again")["files"]
    assert file["new"] == "second\n"


def test_a_second_changelist_applies_once_it_holds_the_main_the_first_moved(world: World) -> None:
    world.branch("proposals/one", {"knowledge/one.md": "one\n"})
    world.branch("proposals/two", {"knowledge/two.md": "two\n"})
    world.store.submit("one", "proposals/one", "One")
    world.store.submit("two", "proposals/two", "Two")
    world.store.approve("one")
    with pytest.raises(Conflict, match="main moved"):
        world.store.approve("two")
    with pytest.raises(Conflict, match="does not start from the current main"):
        world.store.submit("two", "proposals/two", "Two")

    # Refresh takes the first to the setup folder, and the working copy's main follows.
    world.refresh()
    git(world.work, "fetch", "--quiet", str(world.bundle), "HEAD")
    git(world.work, "branch", "--force", "main", "FETCH_HEAD")
    git(world.work, "checkout", "--quiet", "proposals/two")
    git(world.work, "merge", "--quiet", "--no-edit", "main")
    world.store.submit("two", "proposals/two", "Two")
    world.store.approve("two")
    world.refresh()
    assert (world.setup / "knowledge/one.md").exists() and (
        world.setup / "knowledge/two.md"
    ).exists()


def test_a_branch_the_review_app_does_not_take(world: World) -> None:
    with pytest.raises(NotFound, match="no branch"):
        world.store.submit("none", "proposals/none", "None")
    with pytest.raises(Invalid, match="changelist name"):
        world.store.submit("../x", "proposals/none", "None")
    with pytest.raises(Invalid, match="branch name"):
        world.store.submit("x", "--upload-pack=touch /tmp/x", "None")
    git(world.work, "branch", "proposals/empty", "main")
    with pytest.raises(Conflict, match="holds no change"):
        world.store.submit("empty", "proposals/empty", "Empty")

    # (the files of the branch) -> a word of the problem
    cases: list[tuple[dict[str, str | None], str]] = [
        ({".gitattributes": "* filter=lfs\n"}, "steers git"),
        ({"knowledge/.gitmodules": "x\n"}, "steers git"),
        ({"flows/hello.yaml": "name: hello\nversion: 0.1.0\nsteps: {}\n"}, "flows/hello.yaml"),
        ({"flows/handlers/examples.py": "def hello(:\n"}, "flows/handlers/examples.py: line 1"),
        ({"agents/helper.toml": HELPER.replace("sonnet", "gpt")}, "gpt is not in models.toml"),
        ({"agents/helper.toml": HELPER + 'tools = ["shell"]\n'}, "tool 'shell'"),
        ({"models.toml": "[elsewhere]\n"}, "models.toml: elsewhere"),
    ]
    for number, (files, word) in enumerate(cases):
        world.branch(f"proposals/bad{number}", files)
        with pytest.raises(Refused) as refused:
            world.store.submit(f"bad{number}", f"proposals/bad{number}", "Bad")
        assert any(word in problem for problem in refused.value.problems), refused.value.problems
    assert world.store.changelists("pending") == []

    git(world.work, "checkout", "--quiet", "-B", "proposals/link", "main")
    (world.work / "knowledge" / "passwd.md").symlink_to("/etc/passwd")
    (world.work / "knowledge" / "bytes.md").write_bytes(b"\xff\xfe\x00binary")
    git(world.work, "add", "--all")
    git(world.work, "commit", "--quiet", "--message", "A link and bytes")
    with pytest.raises(Refused) as refused:
        world.store.submit("link", "proposals/link", "Link")
    assert len(refused.value.problems) == 2, refused.value.problems
    assert "a link" in refused.value.problems[1] and "not text" in refused.value.problems[0]


def test_a_changed_flow_needs_a_higher_version_than_the_one_that_runs(world: World) -> None:
    hello = (STARTER / "flows/hello.yaml").read_text()
    changed = hello.replace("name: inputs.name", "name: inputs.name\n    fixed_params:\n      x: 1")
    world.branch("proposals/flow", {"flows/hello.yaml": changed})
    with pytest.raises(Refused, match="its version is still 0.1.0"):
        world.store.submit("flow", "proposals/flow", "Flow")
    world.commit({"flows/hello.yaml": changed.replace("version: 0.1.0", "version: 0.1.1")})
    made = world.store.submit("flow", "proposals/flow", "Flow")
    assert "hello 0.1.1" in made["summary"][1]


def test_the_working_copy_s_own_git_settings_run_nothing(world: World, tmp_path: Path) -> None:
    world.branch("proposals/quiet", {"knowledge/quiet.md": "quiet\n"})
    marks = tmp_path / "marks"
    marks.mkdir()
    hooks = world.work / ".git" / "hooks"
    for hook in ("pre-upload-pack", "post-upload-pack", "reference-transaction", "pre-receive"):
        (hooks / hook).write_text(f"#!/bin/sh\ntouch {marks}/{hook}\n")
        (hooks / hook).chmod(0o755)
    for key in ("core.fsmonitor", "uploadpack.packObjectsHook", "core.sshCommand", "core.pager"):
        git(world.work, "config", key, f"touch {marks}/{key}")
    git(world.work, "config", "core.hooksPath", str(hooks))
    world.store.submit("quiet", "proposals/quiet", "Quiet")
    world.store.changelist("quiet")
    world.store.approve("quiet")
    assert list(marks.iterdir()) == []


def test_validate_setup_reads_the_working_copy_as_it_is_and_follows_no_link(world: World) -> None:
    assert world.store.validate_setup() == (
        [],
        [
            "3 agents, 5 models",
            "2 flows: code_and_review 0.2.0, hello 0.1.0",
            "2 handler modules, read and not run",
        ],
    )
    # Not committed, and found all the same.
    (world.work / "flows" / "hello.yaml").write_text("name: hello\nversion: 0.1.0\n")
    (world.work / "agents" / "Wrong Name.toml").write_text(HELPER)
    problems, _ = world.store.validate_setup()
    assert any(p.startswith("flows/hello.yaml:") for p in problems), problems
    assert any(p.startswith("agents/Wrong Name.toml:") for p in problems), problems

    secret = world.at / "secret.toml"
    secret.write_text('[models.leaked]\nprovider = "anthropic"\n')
    (world.work / "models.toml").unlink()
    (world.work / "models.toml").symlink_to(secret)
    problems, _ = world.store.validate_setup()
    assert "models.toml: no such file" in problems, problems
    copied = world.at / "copied"
    snapshot(world.work, copied)
    assert not (copied / ".git").exists() and not (copied / "models.toml").exists()
    assert (copied / "flows" / "handlers" / "examples.py").is_file()


def test_main_follows_the_setup_folder(world: World) -> None:
    # A commit the person makes by hand reaches main at the next publish.
    (world.setup / "knowledge" / "by-hand.md").write_text("by hand\n")
    git(world.setup, "add", "--all")
    git(world.setup, "commit", "--quiet", "--message", "By hand")
    world.branch("proposals/stale", {"knowledge/stale.md": "stale\n"})
    world.store.submit("stale", "proposals/stale", "Stale")
    world.publish()
    with pytest.raises(Conflict, match="main moved"):
        world.store.approve("stale")
    assert world.store.rev("refs/heads/main") == git(world.setup, "rev-parse", "HEAD")

    # A setup folder without a commit gives nothing to start from.
    empty = Reviews(world.at / "other", work=world.work, published=world.at / "none.bundle")
    empty.set_up()
    with pytest.raises(Conflict, match="no commit yet"):
        empty.submit("stale", "proposals/stale", "Stale")


def test_a_file_from_before_branches_starts_again(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with sqlite3.connect(data / "reviews.db") as old:
        old.executescript(
            "CREATE TABLE folders (path TEXT PRIMARY KEY, registered_at TEXT NOT NULL);"
            "CREATE TABLE changelists (name TEXT PRIMARY KEY, status TEXT NOT NULL);"
            "INSERT INTO changelists VALUES ('old', 'open');"
            "PRAGMA user_version = 1;"
        )
    store = Reviews(data, work=tmp_path / "work", published=tmp_path / "none.bundle")
    store.set_up()
    assert store.changelists("pending") == [] and store.changelists("closed") == []
    store.set_up()


# The API, composed on oneberth as backend.py composes it, and the designer's tools.


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
def composed(world: World) -> Iterator[tuple[World, object, int]]:
    from oneberth.config import local_config
    from oneberth.stores import opened_store
    from oneberth.web import compose_app

    port = free_port()
    (world.at / "api-data").mkdir()
    component = reviews(
        world.at / "api-data",
        work=world.work,
        published=world.bundle,
        config=BASE,
        flows=world.deployed,
        tools_key=KEY,
        tools_port=port,
    )
    composition = compose_app(
        [component],
        config=local_config("reviews", port=8420),
        store=lambda: opened_store(data_dir=world.at / "api-data", setup=True),
        local=True,
    )
    yield world, composition, port


def test_the_api_keeps_the_approval_to_a_person_and_the_bundle_to_the_host(composed) -> None:
    from oneberth.web.testing import bearer, client_of, launcher, running, signed_in

    world, composition, _ = composed
    world.branch("proposals/api", {"agents/helper.toml": HELPER})

    async def journey() -> None:
        async with running(composition) as person:
            assert (await person.get("/reviews/api/changelists")).status_code == 401
            await signed_in(composition, person)
            submitted = await person.post(
                "/reviews/api/submit_changelist",
                json={"name": "api", "branch": "proposals/api", "title": "Through the API"},
            )
            assert submitted.status_code == 200, submitted.text
            listed = (await person.get("/reviews/api/changelists")).json()["items"]
            assert [c["name"] for c in listed] == ["api"]

            # The app on the host: a service token the launch secret makes, as the app does.
            async with client_of(composition) as host:
                made = await host.post(
                    "/auth/services",
                    json={"name": "fa1-host", "role": "reviews/host"},
                    headers=launcher(composition),
                )
                assert made.status_code == 201, made.text
                token = bearer(made.json()["secret"])
                early = await host.get("/reviews/api/approved.bundle", headers=token)
                assert early.status_code == 204
                # The host's token reviews nothing.
                for path in ("approve_changelist", "reject_changelist"):
                    refused = await host.post(
                        f"/reviews/api/{path}", json={"changelist_name": "api"}, headers=token
                    )
                    assert refused.status_code == 403, refused.text
                assert (
                    await host.get("/reviews/api/changelists", headers=token)
                ).status_code == 403

                bad = await person.post(
                    "/reviews/api/submit_changelist", json={"name": "api2", "branch": "nope"}
                )
                assert bad.status_code == 404, bad.text
                approved = await person.post(
                    "/reviews/api/approve_changelist", json={"changelist_name": "api"}
                )
                assert approved.status_code == 200, approved.text
                again = await person.post(
                    "/reviews/api/approve_changelist", json={"changelist_name": "api"}
                )
                assert again.status_code == 409
                # A person's session does not fetch the bundle: that is the host's.
                assert (await person.get("/reviews/api/approved.bundle")).status_code == 403
                bundle = await host.get("/reviews/api/approved.bundle", headers=token)
                assert bundle.status_code == 200 and bundle.content.startswith(b"# v2 git bundle")

    asyncio.run(journey())


def test_the_designer_s_tools_check_and_submit_and_hold_no_approval(composed) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from oneberth.web.testing import running

    world, composition, port = composed
    world.branch("proposals/tools", {"agents/helper.toml": HELPER})
    url = f"http://127.0.0.1:{port}/mcp"

    async def journey() -> None:
        async with running(composition):
            async with httpx.AsyncClient() as plain:
                for headers in ({}, {"authorization": "Bearer wrong"}):
                    refused = await plain.post(url, json={}, headers=headers)
                    assert refused.status_code == 401
            headers = {"authorization": f"Bearer {KEY}"}
            async with streamablehttp_client(url, headers=headers) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = sorted(tool.name for tool in (await session.list_tools()).tools)
                    assert tools == ["submit_changelist", "validate_setup"]

                    valid = await session.call_tool("validate_setup", {})
                    assert not valid.isError
                    assert valid.content[0].text.startswith("The setup folder passes its checks:")
                    assert "- 4 agents, 5 models" in valid.content[0].text

                    missing = await session.call_tool(
                        "submit_changelist", {"name": "t", "branch": "nope", "title": "T"}
                    )
                    assert missing.isError and "no branch 'nope'" in missing.content[0].text

                    made = await session.call_tool(
                        "submit_changelist",
                        {"name": "tools", "branch": "proposals/tools", "title": "From the tools"},
                    )
                    assert not made.isError, made.content[0].text
                    assert "Changelist tools is submitted" in made.content[0].text

                    (world.work / "flows" / "hello.yaml").write_text("name: hello\n")
                    broken = await session.call_tool("validate_setup", {})
                    assert "problem(s):" in broken.content[0].text
                    assert "- flows/hello.yaml:" in broken.content[0].text
        served = Reviews(world.at / "api-data", work=world.work, published=world.bundle)
        [pending] = served.changelists("pending")
        assert (pending["name"], pending["title"]) == ("tools", "From the tools")

    asyncio.run(journey())
