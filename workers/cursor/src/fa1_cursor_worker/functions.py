"""The tools run in the worker's own process, such as the search of the person's conversations,
as a tool server the CLI reaches: MCP over HTTP, on the worker's loopback.

Robinauts binds these tools to one turn, so each turn gets an address of its own, with a random
part, for as long as it runs. The server answers each request with one JSON object, which MCP's
Streamable HTTP transport allows, and keeps no session.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from robinauts.agent_engines.contract.domain import FunctionTool, FunctionToolError

_log = logging.getLogger(__name__)

PROTOCOL = "2025-06-18"
"""The MCP revision this server speaks when the client names none it knows."""
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 4 * 1024 * 1024
STATUS = {200: "OK", 202: "Accepted", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed"}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def answer(tools: Sequence[FunctionTool], message: Any) -> dict[str, Any] | None:
    """The answer to one JSON-RPC message, or ``None`` for a notification."""
    if not isinstance(message, Mapping) or not isinstance(message.get("method"), str):
        return _error(None, -32600, "not a JSON-RPC request")
    method, request_id = message["method"], message.get("id")
    params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
    if "id" not in message:
        return None
    result: dict[str, Any]
    if method == "initialize":
        asked = params.get("protocolVersion")
        result = {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "robinauts", "version": "1"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": dict(tool.input_schema),
                }
                for tool in tools
            ]
        }
    elif method == "tools/call":
        named = {tool.name: tool for tool in tools}.get(str(params.get("name")))
        if named is None:
            return _error(request_id, -32602, f"no tool {params.get('name')!r}")
        arguments = params.get("arguments")
        failed = False
        try:
            text = await named.call(dict(arguments) if isinstance(arguments, Mapping) else {})
        except FunctionToolError as refused:
            text, failed = str(refused), True
        except Exception as error:
            # What a tool raises beside its own refusal is told to the model as its kind alone.
            text, failed = type(error).__name__, True
        result = {"content": [{"type": "text", "text": text}], "isError": failed}
    else:
        return _error(request_id, -32601, f"no method {method!r}")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class FunctionsServer:
    """One listener on the loopback, started at the first turn that needs it."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._port = 0
        self._turns: dict[str, Sequence[FunctionTool]] = {}
        self._starting = asyncio.Lock()

    async def _start(self) -> None:
        async with self._starting:
            if self._server is None:
                self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
                self._port = self._server.sockets[0].getsockname()[1]

    @contextlib.asynccontextmanager
    async def serving(self, tools: Sequence[FunctionTool]):
        """The address of ``tools`` for one turn, or ``None`` for a turn with none."""
        if not tools:
            yield None
            return
        await self._start()
        turn = secrets.token_urlsafe(24)
        self._turns[turn] = tools
        try:
            yield f"http://127.0.0.1:{self._port}/{turn}/mcp"
        finally:
            del self._turns[turn]

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while await self._request(reader, writer):
                pass
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        except Exception:
            _log.exception("a request to the worker's own tools failed")
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """Reads one request and answers it. False once the connection is to close."""
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, path, _ = lines[0].split(" ", 2)
        except ValueError:
            return False
        headers = {
            name.strip().lower(): value.strip()
            for name, _, value in (line.partition(":") for line in lines[1:] if line)
        }
        length = int(headers.get("content-length") or 0)
        if length > MAX_BODY or headers.get("transfer-encoding"):
            await self._respond(writer, 400, None)
            return False
        body = await reader.readexactly(length) if length else b""
        parts = path.split("?", 1)[0].strip("/").split("/")
        tools = self._turns.get(parts[0]) if len(parts) == 2 and parts[1] == "mcp" else None
        if tools is None:
            await self._respond(writer, 404, None)
        elif method == "DELETE":
            await self._respond(writer, 200, None)
        elif method != "POST":
            # No stream from the server to the client: nothing here sends on its own.
            await self._respond(writer, 405, None, allow="POST, DELETE")
        else:
            try:
                message = json.loads(body)
            except ValueError:
                await self._respond(writer, 400, _error(None, -32700, "not JSON"))
                return True
            if isinstance(message, list):
                answers = [a for m in message if (a := await answer(tools, m)) is not None]
                await self._respond(writer, 200 if answers else 202, answers or None)
            else:
                answered = await answer(tools, message)
                await self._respond(writer, 202 if answered is None else 200, answered)
        return headers.get("connection", "").lower() != "close"

    async def _respond(
        self, writer: asyncio.StreamWriter, status: int, body: Any, *, allow: str = ""
    ) -> None:
        data = b"" if body is None else json.dumps(body).encode()
        head = [f"HTTP/1.1 {status} {STATUS[status]}", f"Content-Length: {len(data)}"]
        if data:
            head.append("Content-Type: application/json")
        if allow:
            head.append(f"Allow: {allow}")
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode() + data)
        await writer.drain()
