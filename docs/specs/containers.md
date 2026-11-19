# Mode 2: containers

Mode 2 runs the control plane and the code worker in Docker containers on the host. It protects
against accidents. A container shares the host's kernel, so mode 2 assumes no hostile actor in
the code worker.

## The project

The app runs one Compose project, `fa1`, from `compose/` in its folder. The files come from
[compose/](../../compose) in this repository.

| service | image | role |
|---|---|---|
| `control` | Robinauts' `Dockerfile`, at the pinned commit | the server, in the local mode, on SQLite |
| `code` | the Claude Code worker's `Dockerfile`, at the same commit | the coding agents |
| `fetch`, `browser`, `files` | FA1's Dockerfiles, and Playwright MCP's image, versions pinned | MCP servers for the web and a folder |
| `todo`, `diagrams` | FA1's Dockerfiles, from Robinauts' `mcp/` | MCP servers with views in the side panel |

- Every image is built on the host by `docker compose build`. Compose builds through Bake.
- The Robinauts images build from a Git URL of the pinned commit. The host needs Docker alone.

## Network

- The project has one network, with a way out. Every service reaches the others by name.
- `control` publishes its front listener on the host's `127.0.0.1`, at the app's port. No other
  service publishes a port.
- `code` shares the network of `control` (`network_mode: service:control`).
- The worker listener is on the loopback of `control`. `code` alone reaches it there, at
  `http://127.0.0.1:8421/robinauts`.

The worker in the personal sign-in accepts a broker on loopback or a private address. A
service's name is neither, so `code` shares the network of `control`.

```sh
robinauts start --local --host 0.0.0.0 --public-host 127.0.0.1 --port <port> \
    --worker-host 127.0.0.1 --worker-port 8421
```

## Storage

Each service keeps its data in a named volume of the project:

| volume | service | mounted at | holds |
|---|---|---|---|
| `control-data` | `control` | `/var/lib/robinauts` | `data/`: `robinauts.db`, `oneberth.db`, `neorc.db` |
| `code-claude` | `code` | `/var/lib/claude` | Claude Code's transcripts |
| `code-workspaces` | `code` | `/workspace` | a directory per conversation |
| `files` | `files` | `/agents-fs` | the folder of the files tool |
| `todos` | `todo` | `/data` | the to-do list |

- A volume mounted on a folder of the image takes the folder's owner. Each service writes its
  volume as the image's own user.
- No service mounts a host folder or the Docker socket.
- `control` and `code` mount `robinauts.toml` of `compose/`, read-only. The app writes it from the
  setup folder at each start ([setup-folder.md](setup-folder.md)). A change recreates `control`
  and `code`, since both read it as they start.

## Secrets

The app writes the secrets to `secrets/` in its folder. The folder is readable by the person
alone, and its files by every user, so the containers' users read them.

| file | read by | as |
|---|---|---|
| `launch` | `control` | standard input, from `/run/secrets/launch` |
| `worker_token` | `code` | the file `ONEBERTH_TOKEN_FILE` names, `/run/secrets/worker_token` |
| `control.env` | `control` | variables: the Anthropic API key, the files server's key |
| `code.env` | `code` | variables: the Claude Code token, the GitHub token, the Git author |
| `files.env` | `files` | variables: the files server's key |

- Docker shows a container's variables to `docker inspect`. Mode 2 accepts it.
- The worker refuses an empty `GITHUB_TOKEN`. Without a GitHub token, `code.env` leaves the line
  out.

## Starting

1. The app writes the secrets files. `worker_token` starts empty.
2. `docker compose up` for `control` and the MCP servers. The app waits for `/auth/session`.
3. The app lists the service tokens with `GET /auth/services`. A listed id equal to
   `worker_token_id` keeps the worker's token. Otherwise the app makes a new one, as below.
4. `docker compose up` for `code`. With a new token, `--force-recreate` starts a new container,
   since the worker reads its token as it starts.
5. `/health` answers `ok` once `code` reaches the worker listener. The app asks for a ticket and
   opens Robinauts.

A token the launch secret makes lives in the memory of `control`, so a stop of `control` ends it.
The app makes a new token in two requests:

1. `DELETE /auth/services/<id>` for each token named `fa1-code` the list holds.
2. `POST /auth/services` for a token named `fa1-code`, with the role `robinauts/worker` and the
   resource `claude`. The app writes its secret to `worker_token` and its id to
   `worker_token_id`.

A new token restarts `code` alone. `control` keeps running, with its conversations and turns.

## The code worker

- It runs Claude Code with `bypassPermissions`.
- It runs as a user without root, in its own container.
- It reaches the internet, the worker listener and the MCP servers.

## Removal

- `docker compose down --volumes --rmi all` removes the containers, the network, the volumes and
  the images.
- Docker keeps its build cache. `docker builder prune` clears it for every project on the host,
  so the last screen shows it as a choice.

## Docker on each platform

| platform | engine |
|---|---|
| Linux | Docker Engine with the Compose plugin, from the distribution or Docker's packages |
| macOS | Colima, with the Docker CLI and the Compose plugin |

The app uses the engine the `docker` command reaches. The person installs it.

## Open

- Secrets files on macOS, where Colima shares only some host folders with its VM.
- A container reaches the host and the LAN. Mode 2 accepts it.
