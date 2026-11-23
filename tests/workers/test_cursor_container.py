"""The worker in its container holds conversations: a Robinauts server with no database starts it
from its image with ``docker run -i``; the turns of the agent on that worker run in the
container, on the stand-in for Cursor's CLI. The second turn resumes the first one's chat. A
second conversation searches the first through Robinauts' own tool, which the CLI reaches over
MCP on the worker's loopback.

Skipped unless ``FA1_CURSOR_WORKER_IMAGE`` names the image, which ``run.sh`` builds.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from oneberth.identity import CredentialKind, new_secret

HERE = Path(__file__).resolve().parent
ROBINAUTS = Path(sys.executable).with_name("robinauts")
IMAGE = os.environ.get("FA1_CURSOR_WORKER_IMAGE", "")
CONTAINER = "fa1-cursor-worker-test"

CONFIG = """
[model_providers.cursor]
kind = "openai-compatible"
api_key_env = "CURSOR_API_KEY"

[models.cursor-auto]
provider = "cursor"
name = "auto"
title = "Auto"

[agents.cursor]
title = "Cursor"
system_prompt = "Say what you did."
models = ["cursor-auto"]
engine = "cursor"
worker = "cursor"
tools = ["sessions"]

[workers.cursor]
command = [
    "docker", "run", "-i", "--rm", "--network", "host", "--name", "{container}",
    "-e", "ROBINAUTS_CONFIG", "-e", "ROBINAUTS_WORKER_NAME", "-e", "ROBINAUTS_WORKER_BROKER_URL",
    "-e", "CURSOR_API_KEY", "-e", "FA1_CURSOR_FORCE=yes",
    "-e", "FA1_CURSOR_CLI=/stand-in/cursor-agent", "-v", "{stand_in}:/stand-in:ro",
    "-v", "{config}:{config}:ro",
    "{image}",
]
"""

pytestmark = pytest.mark.skipif(not IMAGE, reason="FA1_CURSOR_WORKER_IMAGE names no image")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def finished(response: httpx.Response) -> str:
    """A turn that ended well: its conversation's id."""
    assert response.status_code == 200, response.text
    data = [line for line in response.text.splitlines() if line.startswith("data: ")]
    ended: dict[str, Any] = json.loads(data[-1].removeprefix("data: "))
    assert (ended["type"], ended.get("outcome")) == ("RUN_FINISHED", None), ended
    return response.headers["x-robinauts-conversation-id"]


def thread(api: httpx.Client, cid: str) -> list[tuple[str, str]]:
    messages = api.get(f"/robinauts/api/conversations/{cid}").json()["messages"]
    return [
        (m["role"], "".join(p.get("text", "") for p in m["parts"]))
        for m in messages
    ]


def in_container(*command: str) -> str:
    done = subprocess.run(["docker", "exec", CONTAINER, *command], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_the_worker_in_its_container_holds_conversations(tmp_path: Path) -> None:
    config = tmp_path / "robinauts.toml"
    config.write_text(
        CONFIG.format(container=CONTAINER, stand_in=HERE / "stand_in", config=config, image=IMAGE)
    )
    environment = {**os.environ, "ROBINAUTS_CONFIG": str(config), "CURSOR_API_KEY": "not-a-key"}
    environment.pop("ROBINAUTS_DATABASE_URL", None)
    port = free_port()
    command = [str(ROBINAUTS), "start", "--local", "--port", str(port)]
    command += ["--worker-port", str(free_port())]
    secret = new_secret(CredentialKind.LAUNCH)
    server = subprocess.Popen(
        command, env=environment, stdin=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert server.stdin is not None
    server.stdin.write(f"{secret}\n".encode())
    server.stdin.close()
    server.stdin = None
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180.0) as api:
            deadline = time.monotonic() + 120
            while True:
                assert server.poll() is None, server.communicate()[1].decode()
                try:
                    if api.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "nothing answered"
                time.sleep(0.2)
            asked = api.post(
                "/auth/tickets", json={}, headers={"authorization": f"Bearer {secret}"}
            )
            assert asked.status_code in (200, 201), asked.text
            assert api.get(asked.json()["url"]).status_code == 303
            api.headers["origin"] = str(api.base_url).rstrip("/")

            # Two turns of one conversation: the second resumes the chat of the first.
            cid = finished(
                api.post("/robinauts/api/turns", json={"agent_id": "cursor", "text": "marigold"})
            )
            first = api.get(f"/robinauts/api/conversations/{cid}").json()["messages"][1]["id"]
            finished(
                api.post(
                    f"/robinauts/api/conversations/{cid}/turns",
                    json={"parent_id": first, "text": "and again"},
                )
            )
            assert thread(api, cid) == [
                ("user", "marigold"),
                ("assistant", "marigold"),
                ("user", "and again"),
                ("assistant", "marigold | and again"),
            ]

            # The conversation works in a directory of its own, as the image's user, with the
            # agent's instructions as a rule. The real CLI is in the image, at FA1's version.
            workspace = f"/workspace/{cid}"
            assert "Say what you did." in in_container(
                "cat", f"{workspace}/.cursor/rules/agent.mdc"
            )
            assert in_container("id", "-un").strip() == "robinauts"
            version = in_container("cursor-agent", "--version").strip()
            assert version in (HERE.parents[1] / "workers/cursor/Dockerfile").read_text()

            # A second conversation finds the first with Robinauts' own tool, which the CLI
            # reaches over MCP on the worker's loopback.
            other = finished(
                api.post(
                    "/robinauts/api/turns",
                    json={
                        "agent_id": "cursor",
                        "text": 'call search_sessions {"query": "marigold"}',
                    },
                )
            )
            answer = thread(api, other)[1][1]
            # The message holds the tool's output and the answer, which lists the tool.
            assert "tools search_sessions:" in answer and "marigold | and again" in answer, answer

            # An edit of the first answer's question is refused: the CLI has no fork. A turn
            # the CLI fails ends badly too. The worker goes on after both.
            last = api.get(f"/robinauts/api/conversations/{cid}").json()["messages"][-1]["id"]
            for parent, text in ((first, "an edit"), (last, "poison")):
                ended = api.post(
                    f"/robinauts/api/conversations/{cid}/turns",
                    json={"parent_id": parent, "text": text},
                )
                closing = json.loads(
                    [line for line in ended.text.splitlines() if line.startswith("data: ")][
                        -1
                    ].removeprefix("data: ")
                )
                assert closing.get("outcome") is not None or closing["type"] != "RUN_FINISHED", (
                    text,
                    closing,
                )
            assert api.get("/health").json()["status"] == "ok"
        server.send_signal(signal.SIGTERM)
        server.communicate(timeout=60)
    finally:
        if server.poll() is None:
            server.kill()
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
