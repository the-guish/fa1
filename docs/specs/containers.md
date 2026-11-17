# Mode 2: containers

Mode 2 runs the control plane and the code worker in Docker containers on the host. It protects
against accidents. A container shares the host's kernel, so mode 2 assumes no hostile actor in
the code worker.

## The project

The app runs one Compose project, `fa1`, from `compose/` in its folder.

| service | image | role |
|---|---|---|
| `control` | Robinauts' `Dockerfile`, at the pinned commit | the server, in the local mode, on SQLite |
| `code` | the Claude Code worker's `Dockerfile`, at the same commit | the coding agents |
| `fetch`, `browser`, `search`, `files` | FA1's Dockerfiles, versions pinned | MCP servers for the web and a folder |
| `todo`, `diagrams` | FA1's Dockerfiles, from Robinauts' `mcp/` | MCP servers with views in the side panel |

Every image is built on the host by `docker compose build`.

## Networks

| network | kind | members | for |
|---|---|---|---|
| `link` | internal | `control`, `code`, the MCP servers | the worker listener and the MCP servers |
| `out` | with a way out | `control`, `code`, `fetch`, `browser`, `search` | the internet |

- `control` publishes its front listener on the host's `127.0.0.1`, at the app's port.
- No other service publishes a port.
- `control` serves the front listener on `out` and the worker listener on `link`:
  `robinauts start --local --host <its address on out> --public-host 127.0.0.1 --worker-host
  <its address on link>`.

## Storage

Each service keeps its data in a named volume of the project:

| volume | service | holds |
|---|---|---|
| `control-data` | `control` | `robinauts.db`, `oneberth.db`, `neorc.db` |
| `code-claude` | `code` | Claude Code's transcripts |
| `code-workspaces` | `code` | a directory per conversation |
| `files` | `files` | the folder of the files tool |
| `todos` | `todo` | the to-do list |

No service mounts a host folder or the Docker socket.

## Secrets

- The app writes each secret to a file in `secrets/`. Compose mounts each file in
  `/run/secrets/` of its service.
- `control` reads the launch secret on its standard input, from `/run/secrets/launch`.
- `code` reads its token from the file `ONEBERTH_TOKEN_FILE` names.
- `control` holds the model providers' keys. `code` holds the Claude Code token and the GitHub
  token.

## Starting

1. The app writes the secrets files.
2. `docker compose up control` and the MCP servers. The app waits for `/auth/session` to answer.
3. With no worker token yet, the app creates one and writes it to its file.
4. `docker compose up code`.
5. The app asks for a ticket and opens Robinauts.

## The code worker

- It runs Claude Code with `bypassPermissions`.
- It runs as a user without root, in its own container.
- It reaches the internet, the worker listener and the MCP servers.

## Docker on each platform

| platform | engine |
|---|---|
| Linux | Docker Engine, from the distribution or Docker's packages |
| macOS | Colima |
| Windows | open |

The app uses the engine the `docker` command reaches. The person installs it.

## Open

- The Docker engine on Windows.
- Secrets files on macOS, where Colima shares only some host folders with its VM.
- A container on `out` reaches the host and the LAN. Mode 2 accepts it.
