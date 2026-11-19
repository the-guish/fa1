"""The designer's two tools, as an MCP server (docs/specs/review-app.md, "The designer's tools").

`validate_setup` checks the working copy as it is. `submit_changelist` asks a person to review
a branch of it. An approval is no tool: a person gives it on the review app's screens.

The server speaks streamable HTTP at `/mcp`, statelessly and with plain JSON answers, on the
loopback address of the control plane. Every request carries the key in `Authorization: Bearer`.
It runs on a thread of its own, beside the backend. The module imports the MCP SDK and uvicorn,
which Robinauts brings to the control image.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from reviews.backend import Reviews

log = logging.getLogger("fa1.reviews")

HOST = "127.0.0.1"
START_SECONDS = 10.0

INSTRUCTIONS = (
    "The review of the setup folder's changes. validate_setup checks the working copy."
    " submit_changelist asks the person to review a branch. The person approves or rejects on"
    " the Reviews screen, then applies an approved change with Refresh in FA1."
)


class Keyed:
    """Answers a request without the key with 401, before `app` sees it."""

    def __init__(self, app: ASGIApp, key: str) -> None:
        self.app = app
        self.wanted = f"Bearer {key}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self.wanted):
                await PlainTextResponse("the key is missing or wrong", 401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def lines(title: str, items: list[str]) -> str:
    return "\n".join([title, *(f"- {item}" for item in items)])


def build_server(store: Reviews, port: int) -> FastMCP:
    from reviews.backend import Conflict, Invalid, NotFound, Refused

    server = FastMCP(
        "fa1-setup-review",
        instructions=INSTRUCTIONS,
        host=HOST,
        port=port,
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
    )

    @server.tool(
        title="Check the setup folder",
        description=(
            "Check the working copy of the setup folder as it is now, committed or not: the"
            " agents, the models, the flows, their forms, their handlers and each changed"
            " flow's version. Reads the files and runs none. Returns every problem with its"
            " file, or what was checked."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    )
    def validate_setup() -> str:
        problems, summary = store.validate_setup()
        if problems:
            return lines(f"The setup folder has {len(problems)} problem(s):", problems)
        return lines("The setup folder passes its checks:", summary)

    @server.tool(
        title="Ask for a review",
        description=(
            "Ask the person to review a branch of the working copy, as the changelist `name`."
            " The branch starts from main, and its changes are committed. The commit the"
            " branch is at now is the one reviewed: a later commit needs a new submit, under"
            " the same name. Refused with every problem when the commit fails the checks of"
            " validate_setup. `title` is one line the person reads in the list, and"
            " `description` says what changes and how to try it."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
    )
    def submit_changelist(name: str, branch: str, title: str, description: str = "") -> str:
        try:
            made = store.submit(name, branch, title, description)
        except Refused as refused:
            raise ToolError(
                lines("The branch is not submitted. Fix these and submit again:", refused.problems)
            ) from None
        except (Invalid, NotFound, Conflict) as refused:
            raise ToolError(str(refused)) from None
        return lines(
            f"Changelist {made['name']} is submitted at commit {made['commit'][:12]}. The person"
            " reviews it on the Reviews screen, then presses Refresh in FA1 to apply it."
            " Checked:",
            made["summary"],
        )

    return server


@contextmanager
def serve_tools(store: Reviews, *, key: str, port: int) -> Iterator[None]:
    """Serves the tools on the loopback address at `port`, on a thread, until the end."""
    app = Keyed(build_server(store, port).streamable_http_app(), key)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="reviews-tools", daemon=True)
    thread.start()
    waited = time.monotonic()
    while not server.started and thread.is_alive():
        if time.monotonic() - waited > START_SECONDS:
            break
        time.sleep(0.05)
    if not server.started:
        log.warning("the designer's tools did not start on %s:%d", HOST, port)
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(START_SECONDS)
