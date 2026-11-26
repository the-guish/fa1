"""Dates: date arithmetic for the agents, as an MCP server.

FA1 runs it as the local MCP server `dates` (docs/specs/local-mcp-servers.md in FA1). The
contract every local server follows:

- It speaks MCP over streamable HTTP, on 0.0.0.0, at the port and path FA1 gives as MCP_PORT
  and MCP_PATH.
- It answers only requests that carry `Authorization: Bearer <MCP_ACCESS_KEY>`.
- It reads its settings and secrets from its variables: here TIMEZONE, from mcp.toml's [env].
"""

import datetime
import hmac
import os
import zoneinfo

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import PlainTextResponse

ZONE = zoneinfo.ZoneInfo(os.environ.get("TIMEZONE", "UTC"))

# The agents reach the server by its service's name, such as mcp-dates. With its default host,
# 127.0.0.1, the SDK would accept no other name in a request's Host, and answer 421.
server = FastMCP(
    "dates",
    host="0.0.0.0",
    instructions="Date arithmetic. Dates are ISO 8601: YYYY-MM-DD.",
    stateless_http=True,
    json_response=True,
    streamable_http_path=os.environ.get("MCP_PATH", "/mcp"),
    log_level="WARNING",
)


def parse(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text.strip())


def shown(day: datetime.date) -> str:
    return f"{day.isoformat()}, {day.strftime('%A')}"


@server.tool()
def today() -> str:
    """Today's date and weekday, in the server's time zone."""
    return shown(datetime.datetime.now(ZONE).date())


@server.tool()
def add_days(date: str, days: int) -> str:
    """The date `days` after `date`, or before it when `days` is negative."""
    return shown(parse(date) + datetime.timedelta(days=days))


@server.tool()
def days_between(start: str, end: str) -> int:
    """The number of days from `start` to `end`: negative when `end` comes first."""
    return (parse(end) - parse(start)).days


@server.tool()
def weekday(date: str) -> str:
    """The weekday of `date`."""
    return parse(date).strftime("%A")


class Keyed:
    """Answers 401 to a request without the access key, before the MCP server sees it."""

    def __init__(self, app, key: str) -> None:
        self.app = app
        self.wanted = f"Bearer {key}".encode()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self.wanted):
                await PlainTextResponse("the access key is missing or wrong", 401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    app = Keyed(server.streamable_http_app(), os.environ["MCP_ACCESS_KEY"])
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ["MCP_PORT"]), log_level="warning")
