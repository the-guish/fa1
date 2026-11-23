"""The CLI's stream-json lines as the engine's events, and the files the CLI reads from a
workspace: pure functions, as rows. The shapes are the ones Cursor documents."""

from __future__ import annotations

import json

import pytest
from fa1_cursor_worker import checkpoints, tools
from fa1_cursor_worker.events import Translation
from robinauts.agent_engines.contract.domain import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    FunctionTool,
    ModelsConfig,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServerAuth,
    ToolServerConfig,
)
from robinauts.agent_engines.contract.ports import ToolSecretLookup


def assistant(text: str, **more) -> dict:
    message = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    return {"type": "assistant", "message": message, "session_id": "c1", **more}


def tool(subtype: str, call_id: str, body: dict) -> dict:
    return {"type": "tool_call", "subtype": subtype, "call_id": call_id, "tool_call": body}


# The shapes CLI 2026.11.22 printed, cut to what matters.
READ = {"readToolCall": {"args": {"path": "a.txt"}}}
READ_DONE = {"readToolCall": {"args": {"path": "a.txt"}, "result": {"success": {
    "content": "hello", "isEmpty": False, "exceededLimit": False, "totalLines": 1,
    "fileSize": 5}}}}
EDIT = {"editToolCall": {"args": {"path": "/w/b.txt", "streamContent": "x"}}}
EDIT_DONE = {"editToolCall": {"args": {}, "result": {"success": {
    "path": "/w/b.txt", "linesAdded": 1, "message": "Wrote contents to /w/b.txt"}}}}
SHELL = {"shellToolCall": {"args": {
    "command": "uname -s", "workingDirectory": "", "timeout": 30000, "toolCallId": "c",
    "simpleCommands": ["uname"], "parsingResult": {"parsingFailed": False}}}}
SHELL_REJECTED = {"shellToolCall": {"args": {}, "result": {"rejected": {
    "command": "uname -s", "isReadonly": False, "reason": ""}}}}
SHELL_DONE = {"shellToolCall": {"args": {}, "result": {"success": {
    "command": "uname -s", "exitCode": 0, "stdout": "Linux\n", "stderr": "",
    "interleavedOutput": "Linux\n"}}}}
SHELL_FAILED = {"shellToolCall": {"args": {}, "result": {"success": {
    "command": "false", "exitCode": 1, "stdout": "", "stderr": "no\n",
    "interleavedOutput": "no\n"}}}}
MCP = {"mcpToolCall": {"args": {
    "name": "todo-add_todo", "args": {"text": "x"}, "toolCallId": "c",
    "providerIdentifier": "todo", "toolName": "add_todo", "skipApproval": False}}}
MCP_DONE = {"mcpToolCall": {"args": {}, "result": {"success": {
    "content": [{"text": {"text": "added"}}, {"text": {"text": "1 left"}}], "isError": False}}}}
MCP_FAILED = {"mcpToolCall": {"args": {}, "result": {"success": {
    "content": [{"text": {"text": "no such list"}}], "isError": True}}}}
LOOKUP = {"getMcpToolsToolCall": {"args": {"server": "todo", "toolCallId": "c"}}}
# What Cursor documents for the tools it names no kind for.
FUNCTION = {"function": {"name": "search", "arguments": '{"q": "x"}'}}


@pytest.mark.parametrize(
    ("partial", "line", "expected"),
    [
        # Partial output: a delta has timestamp_ms and no model_call_id. The two flushes repeat.
        (True, assistant("he", timestamp_ms=1), [TextDelta("he")]),
        (True, assistant("hello", timestamp_ms=2, model_call_id="m"), []),
        (True, assistant("hello"), []),
        # Whole messages: each line is text.
        (False, assistant("hello"), [TextDelta("hello")]),
        (False, assistant(""), []),
        (True, {"type": "thinking", "subtype": "delta", "text": "hm"}, [ReasoningDelta("hm")]),
        (True, {"type": "thinking", "subtype": "completed"}, []),
        (True, tool("started", "1", READ), [ToolCall("1", "read", {"path": "a.txt"})]),
        (True, tool("started", "2", FUNCTION), [ToolCall("2", "search", {"q": "x"})]),
        # A call's id holds two lines: the first is the id.
        (True, tool("started", "call-3\nfc_3", MCP), [ToolCall("call-3", "add_todo", {"text": "x"})]),
        (True, tool("started", "4", SHELL), [ToolCall("4", "shell", {"command": "uname -s"})]),
        (True, tool("started", "5", LOOKUP), [ToolCall("5", "getMcpTools", {"server": "todo"})]),
        (
            True,
            tool("started", "6", EDIT),
            [ToolCall("6", "edit", {"path": "/w/b.txt", "streamContent": "x"})],
        ),
        # A line of a type this worker does not know, and the user's own prompt.
        (True, {"type": "interaction_query", "session_id": "c1"}, []),
        (True, {"type": "user", "message": {"role": "user", "content": []}}, []),
    ],
)
def test_a_line_becomes_its_events(partial, line, expected) -> None:
    assert Translation(partial=partial).translate(line) == expected


@pytest.mark.parametrize(
    ("started", "completed", "expected"),
    [
        (READ, READ_DONE, ToolResult("1", "read", "hello", False)),
        (EDIT, EDIT_DONE, ToolResult("1", "edit", "Wrote contents to /w/b.txt", False)),
        (SHELL, SHELL_DONE, ToolResult("1", "shell", "Linux\n", False)),
        (SHELL, SHELL_FAILED, ToolResult("1", "shell", "no\n", True)),
        (
            SHELL,
            SHELL_REJECTED,
            ToolResult(
                "1",
                "shell",
                '{"rejected": {"command": "uname -s", "isReadonly": false, "reason": ""}}',
                True,
            ),
        ),
        (MCP, MCP_DONE, ToolResult("1", "add_todo", "added\n1 left", False)),
        (MCP, MCP_FAILED, ToolResult("1", "add_todo", "no such list", True)),
        (
            FUNCTION,
            {"function": {**FUNCTION["function"], "result": {"success": "found"}}},
            ToolResult("1", "search", "found", False),
        ),
        (FUNCTION, {"function": {"result": {"error": "why"}}}, ToolResult("1", "search", "why", True)),
    ],
)
def test_a_completed_call_is_its_result(started, completed, expected) -> None:
    translation = Translation(partial=True)
    translation.translate(tool("started", "1", started))
    assert translation.translate(tool("completed", "1", completed)) == [expected]


def test_a_result_whose_call_was_never_seen_shows_both() -> None:
    events = Translation(partial=True).translate(tool("completed", "9", READ_DONE))
    assert events == [ToolCall("9", "read", {"path": "a.txt"}), ToolResult("9", "read", "hello")]


def test_a_turn_ends_with_its_chat_and_its_text() -> None:
    translation = Translation(partial=True)
    assert translation.failure() == "Cursor's CLI ended without a result"
    translation.translate({"type": "system", "subtype": "init", "session_id": "c1"})
    translation.translate(assistant("Look", timestamp_ms=1))
    translation.translate(assistant("ing.", timestamp_ms=2))
    translation.translate(tool("started", "1", READ))
    translation.translate(tool("completed", "1", READ_DONE))
    # The CLI joins the messages around a tool call with nothing between them.
    assert translation.translate(assistant("Done", timestamp_ms=3)) == [TextDelta("\n\nDone")]
    translation.translate(assistant(".", timestamp_ms=4))
    translation.translate({"type": "result", "subtype": "success", "is_error": False,
                           "result": "Looking.Done.", "session_id": "c1"})
    assert (translation.chat, translation.failure()) == ("c1", None)
    assert translation.done("k") == Done("Looking.\n\nDone.", "k")
    # Whole messages: each is parted from the one before. No text at all: the result's.
    whole = Translation(partial=False)
    assert whole.translate(assistant("One.")) == [TextDelta("One.")]
    assert whole.translate(assistant("Two.")) == [TextDelta("\n\nTwo.")]
    silent = Translation(partial=True)
    silent.translate({"type": "result", "subtype": "success", "result": "whole"})
    assert silent.done("k") == Done("whole", "k")
    failed = Translation(partial=True)
    failed.translate({"type": "result", "subtype": "error", "is_error": True, "result": "why"})
    assert failed.failure() == "why"


@pytest.mark.parametrize("text", ["", "chat", "#turn", "a chat#t", "chat#"])
def test_a_string_that_is_no_checkpoint_is_refused(text) -> None:
    with pytest.raises(CheckpointNotFoundError):
        checkpoints.decode(text)


def test_a_checkpoint_names_its_chat_and_each_turn_has_its_own() -> None:
    first, second = checkpoints.new("c-1"), checkpoints.new("c-1")
    assert checkpoints.decode(checkpoints.encode(first)) == first
    assert first.chat == second.chat == "c-1"
    assert checkpoints.encode(first) != checkpoints.encode(second)


class Secrets(ToolSecretLookup):
    def secret_for(self, server_id: str) -> str:
        return f"secret-of-{server_id}"


MODELS = ModelsConfig(
    tool_servers={
        "open": ToolServerConfig("open", "http://open:1/mcp", auth=ToolServerAuth.NONE),
        "bearer": ToolServerConfig("bearer", "http://bearer:2/mcp", "KEY", exclude=("rm", "mv")),
        "basic": ToolServerConfig("basic", "http://basic:3/mcp", "KEY", ToolServerAuth.BASIC, "u"),
        "header": ToolServerConfig(
            "header", "http://header:4/mcp", "KEY", ToolServerAuth.HEADER, header="X-Key"
        ),
    }
)


async def _nothing(arguments) -> str:
    return ""


def test_the_workspace_files_name_the_tool_servers_and_hold_no_secret(tmp_path) -> None:
    function = FunctionTool("search", "", {}, _nothing)
    agent = AgentDefinition("Be brief.", ("open", "bearer", "basic", "header"), (function,))
    environment = tools.write(tmp_path, agent, MODELS, Secrets(), "http://127.0.0.1:9/t/mcp")
    assert environment == {
        "FA1_CURSOR_MCP_HEADER_1": "Bearer secret-of-bearer",
        "FA1_CURSOR_MCP_HEADER_2": "Basic dTpzZWNyZXQtb2YtYmFzaWM=",
        "FA1_CURSOR_MCP_HEADER_3": "secret-of-header",
    }
    written = (tmp_path / ".cursor" / "mcp.json").read_text()
    assert "secret-of" not in written
    assert json.loads(written) == {"mcpServers": {
        "open": {"url": "http://open:1/mcp"},
        "bearer": {"url": "http://bearer:2/mcp",
                   "headers": {"Authorization": "${env:FA1_CURSOR_MCP_HEADER_1}"}},
        "basic": {"url": "http://basic:3/mcp",
                  "headers": {"Authorization": "${env:FA1_CURSOR_MCP_HEADER_2}"}},
        "header": {"url": "http://header:4/mcp",
                   "headers": {"X-Key": "${env:FA1_CURSOR_MCP_HEADER_3}"}},
        "robinauts": {"url": "http://127.0.0.1:9/t/mcp"},
    }}
    assert json.loads((tmp_path / ".cursor" / "cli.json").read_text()) == {"permissions": {
        "allow": ["Mcp(open:*)", "Mcp(bearer:*)", "Mcp(basic:*)", "Mcp(header:*)",
                  "Mcp(robinauts:*)"],
        "deny": ["Mcp(bearer:rm)", "Mcp(bearer:mv)"],
    }}
    rule = (tmp_path / ".cursor" / "rules" / "agent.mdc").read_text()
    assert "alwaysApply: true" in rule and rule.endswith("Be brief.\n")
    # The next turn's agent has no instructions and no tools: the files say so.
    assert tools.write(tmp_path, AgentDefinition(""), MODELS, Secrets()) == {}
    assert not (tmp_path / ".cursor" / "rules" / "agent.mdc").exists()
    assert json.loads((tmp_path / ".cursor" / "mcp.json").read_text()) == {"mcpServers": {}}
