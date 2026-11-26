# Local MCP servers

A local MCP server is a tool server the person writes. Its source is in the setup folder, and
FA1 builds it, runs it in a container, and gives it to the agents that name it.

The story: the person wants a Jira tool that FA1 does not provide. They write a small server
that calls Jira's API, put it in `local-mcp-servers/jira/`, enter their Jira token on the Keys
screen, and add `jira` to an agent's `tools`.

## The folder

```
<setup folder>/
    local-mcp-servers/
        <id>/
            mcp.toml         the manifest
            Dockerfile       the server's image
            ...              the server's source: whatever the Dockerfile builds
```

- The folder's name is the server's id: lowercase letters, digits and `-`, as an agent's id.
- An agent names the id in its `tools`, beside FA1's tool servers.
- The id of one of FA1's tool servers, or of a tool of Robinauts such as `sessions`, is refused.
- Every file is text, as everywhere in the setup folder. A changelist holds a server's files
  like any other ([review-app.md](review-app.md), "Submitting").
- A server's folder holds plain files and folders. A link stops the deploy, as the review app
  refuses it: followed, it would copy a file from outside the folder into the image.
- A file keeps its executable mark in the copy FA1 builds from, so a Dockerfile may run a script
  of the folder directly.

## The manifest

```toml
# local-mcp-servers/jira/mcp.toml
title = "Jira"
port = 8080
path = "/mcp"
timeout_seconds = 60
exclude = []

[env]
JIRA_URL = "https://example.atlassian.net"

[keys]
JIRA_API_TOKEN = "Jira API token"
```

| key | holds | default |
|---|---|---|
| `title` | the name the Keys screen shows | the id |
| `port` | the port the server listens on, in its container | needed |
| `path` | the path of the MCP endpoint | `/mcp` |
| `timeout_seconds` | how long an agent waits for a tool's answer | 60 |
| `exclude` | the server's tools that no agent gets, by their names | none |
| `[env]` | variables of the server's container, with their values | none |
| `[keys]` | the secrets the server needs: each variable's name, and the label the Keys screen shows | none |

- `[env]` holds settings, and `[keys]` holds the secrets' names alone. The setup folder holds
  no secret.
- A variable's name is upper-case letters, digits and `_`. It does not start with `FA1_` or
  `MCP_`, which FA1 keeps for itself. A name is in `[env]` or in `[keys]`, not in both.

## The server's contract

- The server speaks MCP over streamable HTTP, on `0.0.0.0` at its `port` and `path`. FA1 gives
  its container both, as `MCP_PORT` and `MCP_PATH`.
- The server answers a request only with `Authorization: Bearer <key>`, where the key is the
  variable `MCP_ACCESS_KEY` of its container. Other requests get 401.
- The server accepts `mcp-<id>` as the host of a request, since the agents reach it by that
  name. An SDK that protects against DNS rebinding may accept `localhost` alone by default: the
  Python SDK's `FastMCP` does unless its `host` is `0.0.0.0`, and answers 421 otherwise.
- The server reads its settings and its secrets from its variables.

The access key is FA1's. An agent of a worker gets it only when the agent names the server, so
other containers of the project reach the server's network port and nothing more.

## The sample

The starter holds one local server, `dates`: date arithmetic, which models do poorly.

| tool | answers |
|---|---|
| `today` | today's date and weekday, in the server's time zone |
| `add_days(date, days)` | the date `days` after `date`, or before it |
| `days_between(start, end)` | the days from `start` to `end` |
| `weekday(date)` | the weekday of `date` |

- It is Python, on the MCP SDK, with versions pinned. A person copies it to start a server of
  their own.
- Its time zone is `TIMEZONE` in `[env]`.
- It needs no secret. Its manifest shows a `[keys]` table as a comment.

## Deploying

At each start, FA1 reads `local-mcp-servers/*/mcp.toml` with the rest of the setup folder
([setup-folder.md](setup-folder.md), "Deploying it"). A manifest with a problem stops the
deploy, and names its file.

For each server, FA1:

1. Copies the server's folder to `compose/local-mcp-servers/<id>/`.
2. Writes the service `mcp-<id>` in `compose/local-mcp-servers.yaml`, which every Compose
   command reads beside `compose.yaml`. The service builds from the copy, and holds the
   variables of `[env]`.
3. Makes the server's access key at the first start, and keeps it in `secrets/`.
4. Writes `secrets/mcp-<id>.env`: `MCP_ACCESS_KEY`, `MCP_PORT`, `MCP_PATH`, and each key of
   `[keys]` with the value the person entered. Each value is quoted, so `$`, `#` and quotes reach
   the server as typed.
5. Adds `[tool_servers.<id>]` to Robinauts' configuration. Its URL is
   `http://mcp-<id>:<port><path>`, and its key is in the variable `FA1_MCP_<ID>_KEY`: the id in
   upper case, with `_` for `-`.

The access key reaches the containers that call the server:

- `control` holds the key of every local server.
- A worker holds the key of each local server that its agents name, as for FA1's keyed tool
  servers ([containers.md](containers.md), "Secrets").

A server whose `[keys]` has a key the person has not entered stays out of the deploy. The agents
that name it stay out too, and the start says which, as it does for the agents on Cursor
without a Cursor API key.

## The container

| setting | value |
|---|---|
| image | built by `docker compose build`, from the server's Dockerfile |
| network | the project's network, with a way out. No port is published. |
| file system | read-only, with a `tmpfs` at `/tmp` |
| capabilities | none, and no new privileges |
| limits | 512 MB of memory, 256 processes |
| restart | unless stopped |

- A local server mounts no volume, and holds no state between starts.
- The control plane's services start with the local servers. A start removes the container of a
  server the setup folder no longer holds, and its `mcp-<id>.env`.
- The build runs the person's Dockerfile, which may fetch from the internet. The person pins
  what it fetches, as the sample does.
- Status lists each server's container with FA1's own.

## Review

- A changelist may add, change or remove a local server.
- The checks read each manifest, as the deploy does, and check the agents with the setup's
  local servers ([review-app.md](review-app.md), "Checks"). The checks build nothing and run
  nothing.
- A file under `local-mcp-servers/` carries a mark on the Reviews screen: its code runs in a
  container.

## Open

- Mode 3: the local servers run in the control VM's Docker, and the code VM's firewall lets it
  reach their ports on the link ([vms.md](vms.md)).
- A volume for a server that keeps state.
- A server that signs in with OAuth. Robinauts sends a static key alone.
