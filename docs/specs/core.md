# FA1: core

FA1 is a desktop app. It runs Robinauts for one person, with the coding agents kept apart
from the rest.

## Goals

1. **Easy to install.** A person with no technical background unpacks FA1 and starts it. The
   first start sets everything up.
2. **Easy to audit.** The part that runs on the host is small. Every command it runs is shown
   to the person, and logged.
3. **Small footprint.** FA1 writes to one folder on the host, plus what the chosen mode
   creates. Removing FA1 removes all of it.
4. **Few layers.** FA1 takes from Robinauts only what it needs. A layer is added only for a
   need this repository names.
5. **Linux, macOS and Windows.** Each mode states what it needs on each one.

## The parts

| part | what it is | where it runs |
|---|---|---|
| the app | FA1's own program: its screens, and the actions that set up and start the rest | the host |
| the control plane | Robinauts' server in the local mode, on SQLite, and the MCP servers | depends on the mode |
| the code worker | Robinauts' Claude Code worker, in Docker | depends on the mode |
| the Cursor worker | FA1's worker for Cursor's CLI, in Docker; optional ([cursor-worker.md](cursor-worker.md)) | mode 2 |

- The control plane holds the conversations and the model keys. It serves the interface.
- FA1 is the host of the control plane. It composes Robinauts, neorc and FA1's own
  applications on oneberth ([apps.md](apps.md)).
- The code worker runs the coding agents. It reaches the control plane's worker listener, the
  MCP servers and the internet.

## Isolation modes

The first start offers three modes. The person picks one.

| mode | the control plane | the code worker | what it protects against |
|---|---|---|---|
| 1. same host | processes on the host | a process on the host | nothing: an agent reaches all the person can |
| 2. containers | Docker containers on the host | a Docker container on the host | accidents |
| 3. VMs | a VM | Docker, in a VM of its own | a hostile agent, within the release blockers below |

- Mode 2 is built first ([containers.md](containers.md)).
- Mode 3 is specified ([vms.md](vms.md)).
- Mode 1 is named only.

A container shares the host's kernel. Mode 2 assumes no hostile actor in the code worker. A VM
has a kernel of its own, so mode 3 is the security boundary.

## The app and the control plane

The app reaches the control plane the same way in every mode:

- Robinauts' front listener is on `127.0.0.1` on the host, at the port the app chose. The app's
  App tab opens Robinauts there.
- The app makes the launch secret at the first start, and keeps it. The control plane reads it
  at each start.
- The app asks for a ticket with the launch secret (`POST /auth/tickets`). It opens the App tab
  with that ticket.
- The app creates the code worker's token with the launch secret (`/auth/services`). The token
  is bound to the worker `claude`. The control plane keeps it in memory, so each start checks it
  ([containers.md](containers.md), "Starting").
- The app starts, stops and reads logs through the mode's own tool: Docker Compose in mode 2,
  QEMU in mode 3.
- The control plane works in the person's setup folder, which mode 2 mounts
  ([review-app.md](review-app.md)). Mode 3 has no way to it yet ([vms.md](vms.md), "Open").

## Keys

- The person enters the keys in the app.
- The app keeps them in its folder, readable by the person alone.
- The model providers' keys go to the control plane.
- The GitHub token goes to the control plane too. A flow's handler reads GitHub with it there,
  such as the CI of a pull request ([flows.md](flows.md), "Deploying").
- The Claude Code token and the GitHub token go to the code worker.
- The Cursor API key and the GitHub token go to the Cursor worker.

## Builds

- FA1 builds every image on the person's host, from source. FA1 publishes no image.
- A release of FA1 pins what it builds from: one Robinauts commit, one Debian image, the
  version of each MCP server, and the version of Cursor's CLI with its checksums.
- The server and the worker are built from the same Robinauts commit. They share a wire with
  no version check.

## What FA1 takes from Robinauts

- The server's parts: `robinauts_parts`, which returns Robinauts' component and neorc's from
  the environment, with `ROBINAUTS_DATA_DIR`. FA1 composes them itself, in the local mode
  ([apps.md](apps.md)).
- The interface as a package: `@robinauts/ui`, packed by `scripts/robinauts-ui-pack.sh`.
- The external worker: `[workers.claude]` with `external = true`.
- The Claude Code worker's image, from `extra-workers/claude-code-worker`.
- The to-do list and diagrams MCP servers, from `mcp/`.
- The base worker's lock and `worker-common`, from `extra-workers/`, for the Cursor worker.

FA1 uses oneberth's `compose_app`, `run` and `Shell` directly. It uses no part of oneberth's
launcher.

## Release blockers

These are Robinauts' work, outside FA1's development. Mode 3's guarantee needs both:

- The worker routes scoped to the worker's own tasks. Today a worker's token reads every
  conversation.
- The egress proxy that puts the real keys in the code worker's requests. Today the code worker
  holds its keys.

## Open

- SQLite storage with an external worker: not run yet.
- The licence of FA1, since mode 3 ships QEMU (GPL-2.0) beside it.
- Credentials for the to-do list and diagrams MCP servers, which the code worker reaches.
- A folder the person shares with the agents, on the host.
