"""The engine on a stand-in for Cursor's CLI (stand_in/cursor-agent), a real process outside the
worker: a conversation of several turns, a turn that fails, one that runs past its deadline, a
tool of the worker's own called over MCP, and what the start refuses."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from importlib.metadata import entry_points
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fa1_cursor_worker import checkpoints
from fa1_cursor_worker.__main__ import problems_of
from fa1_cursor_worker.engine import CursorEngine, arguments, chats_of, project_of
from fa1_cursor_worker.settings import Settings, SettingsError, settings_from
from robinauts.agent_engines.contract.domain import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    EngineError,
    FunctionTool,
    FunctionToolError,
    ModelConfig,
    ModelProviderConfig,
    ModelsConfig,
    ProviderKind,
    SessionExistsError,
    SessionNotFoundError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServerConfig,
    UnknownModelError,
)
from robinauts.agent_engines.contract.ports import (
    ENTRY_POINTS,
    EngineSettings,
    ProviderKeyLookup,
    ToolSecretLookup,
)

STAND_IN = Path(__file__).parent / "stand_in" / "cursor-agent"


class Keys(ProviderKeyLookup):
    def key_for(self, provider_id: str) -> str:
        return "key-of-cursor"


class Secrets(ToolSecretLookup):
    def secret_for(self, server_id: str) -> str:
        return "secret-of-files"


SETTINGS = EngineSettings(
    models=ModelsConfig(
        providers={
            "cursor": ModelProviderConfig(
                "cursor", ProviderKind.OPENAI_COMPATIBLE, "CURSOR_API_KEY"
            )
        },
        models={"auto": ModelConfig("auto", "cursor", "auto")},
        tool_servers={"files": ToolServerConfig("files", "http://files:8935/mcp", "FA1_FILES_KEY")},
    ),
    keys=Keys(),
    tool_secrets=Secrets(),
)


async def search(arguments) -> str:
    if not arguments.get("words"):
        raise FunctionToolError("no words")
    return f"found {arguments['words']}"


AGENT = AgentDefinition(
    "Say what you did.", ("files",), (FunctionTool("search_sessions", "Search.", {}, search),)
)


@pytest.fixture
def engine(tmp_path, monkeypatch) -> CursorEngine:
    # The stand-in keeps its chats and its record of each run under its home.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    (tmp_path / "home").mkdir()
    container = Settings(tmp_path / "workspaces", str(STAND_IN), force=True, partial_output=True)
    return CursorEngine(SETTINGS, container)


def runs(tmp_path) -> list[dict]:
    text = (tmp_path / "home" / ".stand-in" / "runs").read_text()
    return [json.loads(line) for line in text.splitlines()]


async def turn(
    engine, session, prompt, checkpoint=None, *, agent=AGENT, timeout=30.0, model="auto"
) -> list:
    stream = engine.stream(
        session, agent, prompt, model=model, checkpoint_id=checkpoint, timeout_seconds=timeout
    )
    return [event async for event in stream]


def test_a_conversation_of_several_turns(engine, tmp_path) -> None:
    async def journey() -> None:
        await engine.setup()
        session = uuid.uuid4()
        assert not await engine.exists(session)
        with pytest.raises(SessionNotFoundError):
            await turn(engine, session, "hello")
        await engine.create(session)
        with pytest.raises(SessionExistsError):
            await engine.create(session)
        workspace = engine.workspace(session)

        # The first turn starts a chat. The text streams as deltas, and the flushes that repeat
        # it are left out.
        events = await turn(engine, session, "hello")
        assert events[:-1] == [TextDelta("he"), TextDelta("llo")]
        assert isinstance(events[-1], Done) and events[-1].text == "hello"
        first = events[-1].checkpoint_id
        chat = checkpoints.decode(first).chat

        # What the CLI was given: print mode, the model, the workspace, and the key. The tool
        # server's key is in a variable, and the workspace's files name the variable.
        run = runs(tmp_path)[0]
        assert run["args"] == [
            "--print", "--output-format", "stream-json", "--stream-partial-output", "--trust",
            "--approve-mcps", "--force", "--workspace", str(workspace), "--model", "auto", "hello",
        ]
        assert run["cwd"] == str(workspace)
        assert run["environment"] == {
            "CURSOR_API_KEY": "key-of-cursor",
            "FA1_CURSOR_MCP_HEADER_0": "Bearer secret-of-files",
        }
        servers = json.loads(run["files"][".cursor/mcp.json"])["mcpServers"]
        assert servers["files"] == {
            "url": "http://files:8935/mcp",
            "headers": {"Authorization": "${env:FA1_CURSOR_MCP_HEADER_0}"},
        }
        assert servers["robinauts"]["url"].startswith("http://127.0.0.1:")
        assert "Say what you did." in run["files"][".cursor/rules/agent.mdc"]
        assert "secret-of-files" not in json.dumps(run["files"])

        # The second turn resumes the chat, which remembers the first.
        events = await turn(engine, session, "and again", first)
        assert events[-1].text == "hello | and again"
        second = events[-1].checkpoint_id
        assert checkpoints.decode(second).chat == chat and second != first
        assert f"--resume={chat}" in runs(tmp_path)[1]["args"]

        # A tool call of the CLI's own: the call, its result, and the file in the workspace.
        # The text before the call and the text after it are two messages.
        # The CLI has no fork: a turn from an earlier checkpoint, which an edit or a regenerate
        # asks for, is refused before the CLI runs.
        ran = len(runs(tmp_path))
        with pytest.raises(EngineError, match="continues a chat from its end alone"):
            await turn(engine, session, "hello, edited", first)
        assert len(runs(tmp_path)) == ran
        events = await turn(engine, session, "write notes.txt remember", second)
        assert events[0] == TextDelta("Writing.")
        assert events[1] == ToolCall(
            "call-w1", "edit", {"path": str(workspace / "notes.txt"), "streamContent": "remember"}
        )
        assert events[2] == ToolResult(
            "call-w1", "edit", f"Wrote contents to {workspace / 'notes.txt'}", False
        )
        assert (workspace / "notes.txt").read_text() == "remember"
        assert events[-1].text == "Writing.\n\nwrote notes.txt"
        third = events[-1].checkpoint_id

        # A tool of the worker's own, over MCP, at this turn's address: listed, called, and
        # refused with the tool's own words.
        events = await turn(engine, session, 'call search_sessions {"words": "tide"}', third)
        assert events[0] == ToolCall("call-f1", "search_sessions", {"words": "tide"})
        assert events[1] == ToolResult("call-f1", "search_sessions", "found tide", False)
        assert events[-1].text == "tools search_sessions: found tide"
        events = await turn(engine, session, "call search_sessions {}", events[-1].checkpoint_id)
        assert events[1] == ToolResult("call-f1", "search_sessions", "no words", True)
        # The address was this turn's alone: it answers nothing after the turn.
        url = json.loads(runs(tmp_path)[-1]["files"][".cursor/mcp.json"])["mcpServers"][
            "robinauts"
        ]["url"]
        address = urlsplit(url)
        reader, writer = await asyncio.open_connection("127.0.0.1", address.port)
        writer.write(f"POST {address.path} HTTP/1.1\r\nContent-Length: 2\r\n\r\n{{}}".encode())
        assert (await reader.readline()).startswith(b"HTTP/1.1 404")
        writer.close()

        # A turn that fails says why, with the CLI's own words, and leaves the chat. The next
        # turn runs from the last checkpoint.
        latest = events[-1].checkpoint_id
        with pytest.raises(EngineError, match=r"exit code 1\): ⚠ Warning: the model is poisoned$"):
            await turn(engine, session, "poison", latest)
        events = await turn(engine, session, "after", latest)
        assert events[-1].text.endswith("poison | after")
        latest = events[-1].checkpoint_id

        # A turn past its deadline ends, and the command it started ends with it.
        began = time.monotonic()
        with pytest.raises(TimeoutError):
            await turn(engine, session, "sleep", latest, timeout=3.0)
        assert time.monotonic() - began < 20
        child = int((workspace / "child.pid").read_text())
        await asyncio.sleep(0.5)
        assert not Path(f"/proc/{child}").exists() or "Z" in Path(
            f"/proc/{child}/stat"
        ).read_text().split(")")[1]

        # A turn from no checkpoint, which an edit of the first message asks for, starts a new
        # chat. Its agent has no tools of the worker's own, and its prompt opens with a dash.
        events = await turn(engine, session, "--help", agent=AgentDefinition(""))
        assert events[-1].text == "--help"
        fresh = events[-1].checkpoint_id
        assert checkpoints.decode(fresh).chat != chat
        with pytest.raises(EngineError, match="continues a chat from its end alone"):
            await turn(engine, session, "x", latest)
        assert "robinauts" not in json.loads(runs(tmp_path)[-1]["files"][".cursor/mcp.json"])[
            "mcpServers"
        ]

        # What the engine refuses before the CLI runs.
        with pytest.raises(UnknownModelError):
            await turn(engine, session, "x", model="nope")
        with pytest.raises(CheckpointNotFoundError):
            await turn(engine, session, "x", "not a checkpoint")
        # The CLI answers a chat it does not hold as a new one: the engine refuses it first.
        shutil.rmtree(chats_of(workspace) / checkpoints.decode(fresh).chat)
        with pytest.raises(CheckpointNotFoundError, match="is gone"):
            await turn(engine, session, "x", fresh)

        # A forgotten session leaves nothing: its directory, its chats, the CLI's own folder.
        chats = tmp_path / "home" / ".cursor" / "chats"
        project = project_of(workspace)
        project.mkdir(parents=True)
        assert chat in [p.name for p in chats_of(workspace).iterdir()]

        await engine.forget(session)
        assert not workspace.exists() and not await engine.exists(session)
        assert not project.exists() and list(chats.iterdir()) == []
        assert not engine.latest(session).exists()
        await engine.close()

    asyncio.run(journey())


def test_a_cli_that_is_not_there_fails_the_turn(tmp_path) -> None:
    async def run() -> None:
        engine = CursorEngine(SETTINGS, Settings(tmp_path, str(tmp_path / "nowhere"), True, True))
        session = uuid.uuid4()
        await engine.create(session)
        with pytest.raises(EngineError, match="did not start"):
            await turn(engine, session, "hello")

    asyncio.run(run())


def test_the_command_line_follows_the_settings(tmp_path) -> None:
    quiet = Settings(tmp_path, "cursor-agent", force=False, partial_output=False)
    assert arguments(quiet, tmp_path / "w", "gpt-5", "c1", "-x") == [
        "cursor-agent", "--print", "--output-format", "stream-json", "--trust", "--approve-mcps",
        "--workspace", str(tmp_path / "w"), "--model", "gpt-5", "--resume=c1", "\n-x",
    ]


def test_the_engine_is_registered_under_its_name() -> None:
    names = {entry.name: entry.value for entry in entry_points(group=ENTRY_POINTS)}
    assert names.get("cursor") == "fa1_cursor_worker.engine:init_cursor"


def test_the_settings_come_from_the_environment() -> None:
    assert settings_from({}) == Settings(Path("/workspace"), "cursor-agent", False, True)
    given = {"FA1_CURSOR_WORKSPACES": "/w", "FA1_CURSOR_CLI": "/bin/agent",
             "FA1_CURSOR_FORCE": "yes", "FA1_CURSOR_PARTIAL_OUTPUT": "no"}
    assert settings_from(given) == Settings(Path("/w"), "/bin/agent", True, False)
    with pytest.raises(SettingsError) as refused:
        settings_from({"FA1_CURSOR_FORCE": "maybe", "ROBINAUTS_DATABASE_URL": "postgres://x"})
    assert len(str(refused.value).splitlines()) == 2


CONFIG = """
[model_providers.cursor]
kind = "openai-compatible"
api_key_env = "CURSOR_API_KEY"

[model_providers.anthropic]
kind = "anthropic"
api_key_env = "ANTHROPIC_API_KEY"

[models.auto]
provider = "cursor"
name = "auto"

[models.opus]
provider = "anthropic"
name = "claude-opus-5-5"

[agents.cursor]
title = "Cursor"
system_prompt = "x"
models = ["auto"]
engine = "{engine}"
worker = "cursor"

[agents.assistant]
title = "Assistant"
system_prompt = "x"
models = ["opus"]
engine = "echo"

[workers.cursor]
external = true
"""


def test_the_start_names_every_problem(tmp_path) -> None:
    config = tmp_path / "robinauts.toml"
    config.write_text(CONFIG.format(engine="cursor"))
    good = {
        "ROBINAUTS_CONFIG": str(config),
        "ROBINAUTS_WORKER_NAME": "cursor",
        "ROBINAUTS_WORKER_BROKER_URL": "http://127.0.0.1:8421/robinauts",
        "CURSOR_API_KEY": "k",
        "FA1_CURSOR_CLI": str(STAND_IN),
        "PATH": os.environ["PATH"],
    }
    assert problems_of(good) == []
    # (what changes) -> words of the one problem
    cases = [
        ({"CURSOR_API_KEY": ""}, "Cursor API key of provider 'cursor' is read from CURSOR_API_KEY"),
        ({"ROBINAUTS_WORKER_NAME": "other"}, "no agent of the configuration names worker 'other'"),
        ({"FA1_CURSOR_CLI": "no-such-cli"}, "'no-such-cli', is not on this worker's path"),
        ({"ROBINAUTS_CONFIG": ""}, "ROBINAUTS_CONFIG is not set"),
        ({"ROBINAUTS_WORKER_BROKER_URL": ""}, "ROBINAUTS_WORKER_BROKER_URL is not set"),
        ({"GITHUB_TOKEN": ""}, "GITHUB_TOKEN"),
        ({"ROBINAUTS_DATABASE_URL": "postgres://x"}, "opens no database"),
    ]
    for change, words in cases:
        problems = problems_of({**good, **change})
        assert len(problems) == 1 and words in problems[0], (change, problems)
    config.write_text(CONFIG.format(engine="echo"))
    assert "runs 'cursor' alone" in problems_of(good)[0]
