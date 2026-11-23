"""The CLI's ``stream-json`` lines, one turn's worth, as the engine contract's events.

Pure: it is handed the parsed lines and gives back the engine's events, so it is tested without
the CLI. The format is Cursor's (https://cursor.com/docs/cli/reference/output-format), and the
shapes Cursor does not document are the ones CLI 2026.11.22 printed:

- ``system`` / ``init`` names the chat, as ``session_id``.
- ``assistant`` carries text. With partial output, a line with ``timestamp_ms`` and no
  ``model_call_id`` is a delta; the other two kinds repeat text already sent, and are skipped.
  Without partial output, each line is one whole message.
- ``thinking`` carries the model's reasoning, as deltas.
- ``tool_call`` comes as ``started`` and ``completed``, with one ``call_id``. Its ``tool_call``
  object has one key for the tool's kind, such as ``readToolCall``, ``editToolCall``,
  ``shellToolCall`` or ``mcpToolCall``, or ``function`` with a name. That key holds ``args``
  and, once completed, ``result``: ``success`` for a call that went well, another key otherwise.
- ``result`` ends a turn that went well. A turn that failed ends without one.

A line of an unknown type is skipped, and a tool of an unknown kind is read by the same shape.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from robinauts.agent_engines.contract.domain import (
    Done,
    Event,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
)

UNKNOWN_TOOL = "?"
SUFFIX = "ToolCall"
MCP = "mcp" + SUFFIX
SHELL = "shell" + SUFFIX
TEXT_KEYS = ("content", "interleavedOutput", "stdout", "output", "text", "message")
"""Where a tool's successful result may hold its text, first found first."""
OWN_KEYS = ("toolCallId",)
"""What the CLI adds to a call's arguments for itself."""
BREAK = "\n\n"
"""What parts one message of the answer from the next, when a tool call came between them."""


def _text_of(message: Any) -> str:
    """The text parts of an ``assistant`` line's message, joined."""
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, Mapping) and part.get("type") == "text"
    )


def tool_of(tool_call: Any) -> tuple[str, str, Mapping[str, Any]]:
    """A ``tool_call`` object's tool: its kind, its name, and its own object."""
    if not isinstance(tool_call, Mapping) or not tool_call:
        return "", UNKNOWN_TOOL, {}
    kind, body = next(iter(tool_call.items()))
    kind = str(kind)
    if not isinstance(body, Mapping):
        return kind, kind, {}
    if kind == "function":
        return kind, str(body.get("name") or UNKNOWN_TOOL), body
    name = kind.removesuffix(SUFFIX) or UNKNOWN_TOOL
    args = body.get("args")
    if kind == MCP and isinstance(args, Mapping):
        # A tool of a tool server: named by its own name, as the server names it.
        named = args.get("toolName") or args.get("name")
        if isinstance(named, str) and named:
            name = named
    return kind, name, body


def arguments_of(kind: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """The call's arguments, as the model sent them, without what the CLI adds for itself."""
    args = body.get("args")
    if isinstance(args, Mapping):
        if kind == MCP and isinstance(args.get("args"), Mapping):
            return dict(args["args"])
        if kind == SHELL and isinstance(args.get("command"), str):
            # The CLI's own reading of the command comes with it: the command is enough.
            return {"command": args["command"]}
        return {key: value for key, value in args.items() if key not in OWN_KEYS}
    arguments = body.get("arguments")
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
        except ValueError:
            return {"arguments": arguments}
        return dict(parsed) if isinstance(parsed, Mapping) else {"arguments": parsed}
    return {}


def _parts(content: Any) -> str | None:
    """The text of an MCP result's content: its parts, joined. ``None`` for another shape."""
    if not isinstance(content, list):
        return None
    texts = []
    for part in content:
        text = part.get("text") if isinstance(part, Mapping) else None
        if isinstance(text, Mapping):
            text = text.get("text")
        texts.append(text if isinstance(text, str) else json.dumps(part, sort_keys=True))
    return "\n".join(texts)


def outcome_of(body: Mapping[str, Any]) -> tuple[str, bool]:
    """A completed call's output as text, and whether it failed."""
    result = body.get("result")
    if isinstance(result, str):
        return result, False
    if not isinstance(result, Mapping):
        return ("" if result is None else json.dumps(result, sort_keys=True)), False
    if "success" not in result:
        said = next(iter(result.values()), None) if len(result) == 1 else None
        return (said if isinstance(said, str) else json.dumps(result, sort_keys=True)), True
    success = result["success"]
    if isinstance(success, str):
        return success, False
    if isinstance(success, Mapping):
        # A tool server says its own failure, and a command its exit code.
        code = success.get("exitCode")
        failed = success.get("isError") is True or (isinstance(code, int) and code != 0)
        parts = _parts(success.get("content"))
        if parts is not None:
            return parts, failed
        for key in TEXT_KEYS:
            if isinstance(success.get(key), str):
                return success[key], failed
    return json.dumps(success, sort_keys=True), False


def call_id_of(line: Mapping[str, Any]) -> str:
    """The call's id: the first line of the CLI's, which holds two."""
    return str(line.get("call_id") or "").split("\n", 1)[0]


class Translation:
    """One turn's lines in, its events out, and what the end needs: the chat, the result, and
    the text."""

    def __init__(self, *, partial: bool) -> None:
        self._partial = partial
        self._names: dict[str, str] = {}
        self._text: list[str] = []
        self._after_tool = False
        self.chat: str | None = None
        self.result: Mapping[str, Any] | None = None

    def translate(self, line: Mapping[str, Any]) -> list[Event]:
        chat = line.get("session_id")
        if isinstance(chat, str) and chat:
            self.chat = chat
        kind = line.get("type")
        if kind == "assistant":
            return self._assistant(line)
        if kind == "thinking":
            text = line.get("text")
            return [ReasoningDelta(text)] if isinstance(text, str) and text else []
        if kind == "tool_call":
            return self._tool_call(line)
        if kind == "result":
            self.result = line
        return []

    def _assistant(self, line: Mapping[str, Any]) -> list[Event]:
        if self._partial and ("timestamp_ms" not in line or "model_call_id" in line):
            return []
        text = _text_of(line.get("message"))
        if not text:
            return []
        if self._text and (self._after_tool or not self._partial):
            # The CLI joins the answer's messages with nothing between them.
            text = BREAK + text
        self._after_tool = False
        self._text.append(text)
        return [TextDelta(text)]

    def _tool_call(self, line: Mapping[str, Any]) -> list[Event]:
        call_id = call_id_of(line)
        kind, name, body = tool_of(line.get("tool_call"))
        self._after_tool = True
        if line.get("subtype") == "started":
            self._names[call_id] = name
            return [ToolCall(call_id, name, arguments_of(kind, body))]
        if line.get("subtype") == "completed":
            events: list[Event] = []
            if call_id not in self._names:
                # A call whose start this turn never saw: shown all the same.
                events.append(ToolCall(call_id, name, arguments_of(kind, body)))
            output, failed = outcome_of(body)
            events.append(ToolResult(call_id, self._names.get(call_id, name), output, failed))
            return events
        return []

    def text(self) -> str:
        """The answer's text: what streamed, else the result's."""
        if self._text:
            return "".join(self._text)
        result = self.result
        said = None if result is None else result.get("result")
        return said if isinstance(said, str) else ""

    def failure(self) -> str | None:
        """Why the turn did not end well, from its lines, or ``None`` when it did."""
        result = self.result
        if result is None:
            return "Cursor's CLI ended without a result"
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            said = result.get("result")
            return (
                said
                if isinstance(said, str) and said
                else f"Cursor's CLI ended the turn with {result.get('subtype')!r}"
            )
        return None

    def done(self, checkpoint: str) -> Done:
        return Done(self.text(), checkpoint)
