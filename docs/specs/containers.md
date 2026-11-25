# Mode 2: containers

Mode 2 runs the control plane and the code worker in Docker containers on the host. It protects
against accidents. A container shares the host's kernel, so mode 2 assumes no hostile actor in
the code worker.

## The project

The app runs one Compose project, `fa1`, from `compose/` in its folder. The files come from
[compose/](../../compose) in this repository.

| service | image | role |
|---|---|---|
| `control` | FA1's `apps/Dockerfile`, with Robinauts at the pinned commit | the control plane, in the local mode, on SQLite: Robinauts, neorc and FA1's applications |
| `code` | the Claude Code worker's `Dockerfile`, at the same commit | the coding agents |
| `cursor` | FA1's `workers/cursor/Dockerfile`, with Robinauts at the same commit | the coding agents on Cursor; optional ([cursor-worker.md](cursor-worker.md)) |
| `fetch`, `browser`, `files` | FA1's Dockerfiles, and Playwright MCP's image, versions pinned | MCP servers for the web and a folder |
| `todo`, `diagrams` | FA1's Dockerfiles, from Robinauts' `mcp/` | MCP servers with views in the side panel |
| `setup-files`, `setup-git` | FA1's `setup-tools/Dockerfile`: the reference filesystem and git servers, versions pinned, and FA1's tool `git_rm` | MCP servers for the designer's working copy of the setup folder ([review-app.md](review-app.md)) |

- Every image is built on the host by `docker compose build`. Compose builds through Bake.
- The Robinauts images build from a Git URL of the pinned commit. The host needs Docker alone.
- The image of `control` is FA1's own. Its build context is `compose/apps/`, and Robinauts at
  the pinned commit is its build context `robinauts` ([apps.md](apps.md)).

## Network

- The project has one network, with a way out. Every service reaches the others by name.
- `control` publishes its front listener on the host's `127.0.0.1`, at the app's port. No other
  service publishes a port.
- `code` and `cursor` share the network of `control` (`network_mode: service:control`).
- The worker listener is on the loopback of `control`. The two workers alone reach it there, at
  `http://127.0.0.1:8421/robinauts`.

The worker in the personal sign-in accepts a broker on loopback or a private address. A
service's name is neither, so `code` shares the network of `control`.

```sh
python /opt/fa1/apps/backend.py --port <port> --worker-port 8421
```

`backend.py` binds the front listener on `0.0.0.0` and the worker listener on `127.0.0.1`. It
names `127.0.0.1` as the address a browser reaches.

## Storage

Each service keeps its data in a named volume of the project:

| volume | service | mounted at | holds |
|---|---|---|---|
| `control-data` | `control` | `/var/lib/robinauts` | `data/`: `robinauts.db`, `oneberth.db`, `neorc.db`, and a file per application of FA1, such as `reviews.db`; `data/reviews/setup.git`: the review app's repository |
| `code-claude` | `code` | `/var/lib/claude` | Claude Code's transcripts |
| `code-workspaces` | `code` | `/workspace` | a directory per conversation |
| `cursor-home` | `cursor` | `/var/lib/cursor` | the home of Cursor's CLI: its chats |
| `cursor-workspaces` | `cursor` | `/workspace` | a directory per conversation |
| `files` | `files` | `/agents-fs` | the folder of the files tool |
| `setup-work` | `setup-files`, `setup-git`; `control`, read-only | `/work` | `setup/`: the designer's working copy of the setup folder |
| `todos` | `todo` | `/data` | the to-do list |

- A volume mounted on a folder of the image takes the folder's owner. Each service writes its
  volume as the image's own user, except the three that run as the setup folder's owner (below).
- No service mounts the Docker socket. The setup folder is the one folder of the person's that
  a service mounts.
- `control`, `code` and `cursor` mount `robinauts.toml` of `compose/`, read-only. The app writes
  it from the setup folder at each start ([setup-folder.md](setup-folder.md)). A change
  recreates the three, since each reads it as it starts.
- The same three mount one folder of `compose/`, read-only: `flows/` at `/etc/fa1/flows`,
  which `ROBINAUTS_FLOWS_DIR` names ([flows.md](flows.md)). The app writes it from the setup
  folder's `flows/` at each start. A change recreates them.
- `code` and `cursor` read `[repositories]` of `flows/flows.toml` there. A conversation of the code worker
  gets a worktree of each repository, and a code task names one of them.

## The setup folder

The review app works in the person's setup folder ([review-app.md](review-app.md)).

- `control` mounts the setup folder at `/setup`. `setup-git` mounts it there read-only.
- `control`, `setup-git` and `setup-files` run as the user and the group that own the setup
  folder. A file the review app writes in the folder then has the folder's owner.
- The app reads the owner from the folder, and gives it to Compose as `FA1_UID` and `FA1_GID`,
  with the folder's path as `FA1_SETUP`.
- The service `owner` gives the volumes `control-data` and `setup-work` to that user. It runs
  `chown` as root before the three services start, and ends. It has no network and two
  capabilities, `CHOWN` and `DAC_READ_SEARCH`.
- A mounted folder is one the review app can write whole. Mode 2 accepts it, as it accepts an
  agent's accidents: the review app writes the folder at an approval alone.

## Secrets

The app writes the secrets to `secrets/` in its folder. The folder is readable by the person
alone, and its files by every user, so the containers' users read them.

| file | read by | as |
|---|---|---|
| `launch` | `control` | standard input, from `/run/secrets/launch` |
| `worker_token` | `code` | the file `ONEBERTH_TOKEN_FILE` names, `/run/secrets/worker_token` |
| `control.env` | `control` | variables: the Anthropic API key, the GitHub token as `GH_TOKEN`, the files server's key, the key of the designer's tool servers |
| `code.env` | `code` | variables: the Claude Code token, the GitHub token, the Git author, and the key of each keyed tool server an agent of the code worker uses |
| `cursor_token` | `cursor` | the file `ONEBERTH_TOKEN_FILE` names, `/run/secrets/cursor_token` |
| `cursor.env` | `cursor` | variables: the Cursor API key, the GitHub token, the Git author, and the key of each keyed tool server an agent of the Cursor worker uses; empty while that worker stays out |
| `files.env` | `files` | variables: the files server's key |
| `setup.env` | `setup-files`, `setup-git` | variables: the key of the designer's tool servers |

- Docker shows a container's variables to `docker inspect`. Mode 2 accepts it.
- A worker reads a tool server's key from its own environment. The app reads each agent of the
  setup folder, and writes a tool server's key to `code.env` when an agent of the worker
  `claude` names that server in its `tools`. `cursor.env` follows the worker `cursor` the same
  way.
- The worker refuses an empty `GITHUB_TOKEN`. Without a GitHub token, `code.env` leaves the line
  out, and `control.env` leaves `GH_TOKEN` out.
- Robinauts hands the flows' handlers the variables of `control`, without the ones
  `robinauts.toml` reads a key from. `GH_TOKEN` is the one key the handlers hold.
- A handler reads GitHub with `GH_TOKEN`. One that waits for a pull request's CI needs a token
  that reads the repository's pull requests, Actions and commit statuses.

## Starting

1. The app writes the secrets files. `worker_token` starts empty.
2. `docker compose up` for `control` and the MCP servers. The app waits for `/auth/session`.
3. The app lists the service tokens with `GET /auth/services`. A listed id equal to
   `worker_token_id` keeps the worker's token. Otherwise the app makes a new one, as below.
4. `docker compose up` for `code`. With a new token, `--force-recreate` starts a new container,
   since the worker reads its token as it starts.
5. The Cursor worker, when it runs ([cursor-worker.md](cursor-worker.md), "The key"): steps 3
   and 4 again, for a token named `fa1-cursor` with the resource `cursor`, kept in
   `cursor_token` and `cursor_token_id`, and the service `cursor`. Otherwise the app removes
   the container of `cursor`.
6. `/health` answers `ok` once each worker reaches the worker listener. The app asks for a
   ticket and opens Robinauts.

A token the launch secret makes lives in the memory of `control`, so a stop of `control` ends it.
The app makes a new token in two requests:

1. `DELETE /auth/services/<id>` for each token named `fa1-code` the list holds.
2. `POST /auth/services` for a token named `fa1-code`, with the role `robinauts/worker` and the
   resource `claude`. The app writes its secret to `worker_token` and its id to
   `worker_token_id`.

A new token restarts its worker alone. `control` keeps running, with its conversations and turns.

The service `cursor` has the Compose profile `cursor`. The build names the profile only when the
Cursor worker runs. Every other command names it always, so a stop and a removal reach the
worker's container.

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

- The setup folder on macOS, where Colima shares only some host folders with its VM, and maps
  their owner.
- Secrets files on macOS, where Colima shares only some host folders with its VM.
- A container reaches the host and the LAN. Mode 2 accepts it.
