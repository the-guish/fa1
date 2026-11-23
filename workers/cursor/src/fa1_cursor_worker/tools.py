"""What the CLI reads from a conversation's directory before a turn: the agent's tool servers,
its permissions, and its instructions. The CLI takes none of them as a flag, so each is a file
under ``.cursor/`` of the workspace (https://cursor.com/docs/cli/mcp, .../reference/permissions,
.../using).

- ``.cursor/mcp.json``: the agent's tool servers over HTTP. A header's value is written as
  ``${env:NAME}``, and the worker gives the CLI the variable: no secret is in the file.
- ``.cursor/cli.json``: the agent's tool servers are allowed, whole, and the tools a server's
  ``exclude`` names are denied.
- ``.cursor/rules/agent.mdc``: the agent's ``system_prompt``, as a rule that always applies.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from robinauts.agent_engines.contract.domain import (
    AgentDefinition,
    ModelsConfig,
    ToolServerAuth,
)
from robinauts.agent_engines.contract.ports import ToolSecretLookup

FUNCTIONS_SERVER = "robinauts"
"""The name of the tool server that holds the tools run in the worker's own process, such as
the search of the person's conversations (functions.py)."""

HEADER_VARIABLE = "FA1_CURSOR_MCP_HEADER_{number}"
"""The variable that holds a tool server's header for the CLI, by the server's place."""

RULE = """---
description: The agent's instructions
alwaysApply: true
---

{prompt}
"""


def mcp_servers(
    agent: AgentDefinition,
    models: ModelsConfig,
    secrets: ToolSecretLookup,
    functions_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """The content of ``mcp.json``, and the variables its headers name."""
    servers: dict[str, Any] = {}
    environment: dict[str, str] = {}
    for number, server_id in enumerate(agent.tools):
        table = models.tool_servers[server_id]
        header, value = "Authorization", ""
        if table.auth is ToolServerAuth.BEARER:
            value = f"Bearer {secrets.secret_for(server_id)}"
        elif table.auth is ToolServerAuth.BASIC:
            pair = f"{table.user}:{secrets.secret_for(server_id)}".encode()
            value = "Basic " + base64.b64encode(pair).decode()
        elif table.auth is ToolServerAuth.HEADER:
            header, value = table.header, secrets.secret_for(server_id)
        server: dict[str, Any] = {"url": table.url}
        if value:
            variable = HEADER_VARIABLE.format(number=number)
            environment[variable] = value
            server["headers"] = {header: f"${{env:{variable}}}"}
        servers[server_id] = server
    if functions_url is not None:
        servers[FUNCTIONS_SERVER] = {"url": functions_url}
    return {"mcpServers": servers}, environment


def permissions(agent: AgentDefinition, models: ModelsConfig) -> dict[str, Any]:
    """The content of ``cli.json``: what runs without asking, and what never runs."""
    allow = [f"Mcp({server_id}:*)" for server_id in agent.tools]
    if agent.functions:
        allow.append(f"Mcp({FUNCTIONS_SERVER}:*)")
    deny = [
        f"Mcp({server_id}:{name})"
        for server_id in agent.tools
        for name in models.tool_servers[server_id].exclude
    ]
    return {"permissions": {"allow": allow, "deny": deny}}


def write(
    workspace: Path,
    agent: AgentDefinition,
    models: ModelsConfig,
    secrets: ToolSecretLookup,
    functions_url: str | None = None,
) -> dict[str, str]:
    """Writes the three files for this turn's agent, anew. The answer is the variables the CLI
    needs beside them."""
    folder = workspace / ".cursor"
    (folder / "rules").mkdir(parents=True, exist_ok=True)
    servers, environment = mcp_servers(agent, models, secrets, functions_url)
    (folder / "mcp.json").write_text(json.dumps(servers, indent=2) + "\n")
    (folder / "cli.json").write_text(json.dumps(permissions(agent, models), indent=2) + "\n")
    rule = folder / "rules" / "agent.mdc"
    if agent.system_prompt.strip():
        rule.write_text(RULE.format(prompt=agent.system_prompt.strip()))
    else:
        rule.unlink(missing_ok=True)
    return environment
