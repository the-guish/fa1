# The Cursor worker

The Cursor worker runs coding agents on Cursor. It is a second code worker, beside the Claude
Code worker, in a container of its own ([containers.md](containers.md)). It lives in
[workers/cursor/](../../workers/cursor) in this repository.

## Why FA1 holds it

Robinauts ships a worker for Claude Code and none for Cursor. FA1 holds this one until Robinauts
has its own.

- The worker is Robinauts' worker module, `robinauts.cli.worker_process`, as in the Claude Code
  worker. Leases, heartbeats, cancels and timeouts are Robinauts'.
- FA1 adds one engine, `cursor`, registered under Robinauts' entry-point group
  `robinauts.engines`.
- The engine uses Robinauts' `worker-common` for the GitHub token, the repositories and the
  worktrees. A conversation gets the same worktrees on either worker.

## A turn

A turn is one run of Cursor's CLI, `cursor-agent`, in print mode:

```sh
cursor-agent --print --output-format stream-json --stream-partial-output --trust \
    --approve-mcps --force --workspace /workspace/<conversation> --model <name> \
    [--resume=<chat>] <the message>
```

- A conversation is one Cursor chat, in a directory of its own, `/workspace/<conversation>`.
- The first turn starts the chat. The CLI names it in its first line, and the engine keeps the
  name in the turn's checkpoint.
- A later turn resumes the chat with `--resume`.
- The CLI prints one JSON object per line. The engine turns each into Robinauts' events: text,
  reasoning, a tool call, a tool's result.
- A turn that the CLI fails ends with the CLI's own words, from its standard error.
- A turn past its deadline, or cancelled, ends the CLI and every command the CLI started.

### What the CLI lacks

- **A system prompt.** The CLI takes no flag for one. The engine writes the agent's
  `system_prompt` as a rule that always applies, `.cursor/rules/agent.mdc` in the
  conversation's directory.
- **A fork.** The CLI continues a chat from its end alone. The engine refuses an edit or a
  regenerate of an earlier message, and the turn's error says to send a new message. An edit of
  a conversation's first message starts a new chat.
- **A refusal of a lost chat.** The CLI answers a chat it does not hold as a new, empty one. The
  engine looks for the chat first, in `~/.cursor/chats/<the directory's MD5>/<chat>`, and
  refuses the turn when the chat is gone.

## Tools

The engine writes the agent's tools into the conversation's directory before each turn.

| file | holds |
|---|---|
| `.cursor/mcp.json` | the agent's tool servers, over HTTP |
| `.cursor/cli.json` | the permissions: the agent's tool servers allowed, a server's `exclude` denied |
| `.cursor/rules/agent.mdc` | the agent's instructions |

- A tool server's key stays out of `mcp.json`. The file names a variable, `${env:...}`, and the
  engine gives the CLI that variable.
- Robinauts' own tools, such as the search of the person's conversations, run in the worker's
  process. The engine serves them to the CLI as one more tool server, `robinauts`, over MCP on
  the worker's loopback, at an address of the turn's own.
- The CLI runs with `--force` in FA1: every command and tool runs, as Claude Code runs with
  `bypassPermissions`. `FA1_CURSOR_FORCE=no` leaves the flag out: the CLI then writes the
  directory's files, runs the agent's tool servers, and rejects shell commands.

## The key

- The person makes a Cursor API key on Cursor's dashboard, and enters it on the Keys screen.
- The app writes it to `cursor.env`, as `CURSOR_API_KEY`. The worker gives it to the CLI.
- A model on Cursor names the provider `cursor` in `models.toml`. Its `name` is one that
  `cursor-agent models` lists, such as `auto`.
- The starter holds four: Auto, Composer, a Grok and a Gemini. Cursor runs a model only when the
  person's plan includes it, and a turn on another model fails with Cursor's own words.

The Cursor worker is optional. It runs when the Keys screen holds a Cursor API key and an agent
of the setup folder names the worker `cursor`.

- Without the key, FA1 leaves the agents on Cursor out of the deploy, and says so at the start.
- With the key and such an agent, FA1 adds `[workers.cursor]` to Robinauts' configuration, makes
  the worker's token, and starts the service `cursor`.
- The review app checks a changelist as FA1 deploys it with the key
  ([review-app.md](review-app.md)). An agent on Cursor passes its checks with or without one.

```toml
# agents/cursor.toml
title = "Cursor"
engine = "cursor"
models = ["cursor-auto"]
worker = "cursor"
tools = ["sessions"]
```

## The image

- The image is built on the person's host, as every image of FA1 is. Its build context is
  `compose/workers/cursor/`, and Robinauts at the pinned commit is its build context
  `robinauts`.
- It installs Robinauts' backend and `worker-common` from the lock of Robinauts' base worker.
  FA1's engine has no dependency of its own.
- It downloads Cursor's CLI at one version, from the address Cursor's install script reads, and
  checks the package's SHA-256. The Dockerfile pins the version and one sum per platform.
- The service has the Compose profile `cursor`. A build without the worker downloads no CLI.
- The CLI's home is the volume `cursor-home`, at `/var/lib/cursor`: the chats outlive the
  container.

## Settings

Each setting is a variable of the service `cursor`.

| variable | default | meaning |
|---|---|---|
| `FA1_CURSOR_FORCE` | `no`; FA1 sets `yes` | run every command and tool |
| `FA1_CURSOR_PARTIAL_OUTPUT` | `yes` | stream the text as it is written |
| `FA1_CURSOR_WORKSPACES` | `/workspace` | a directory per conversation under it |
| `FA1_CURSOR_CLI` | `cursor-agent` | the CLI's program |

## Tests

`tests/workers/run.sh` runs the worker's checks, against Robinauts at the pinned commit.

- The pure functions are tested as rows: the CLI's lines, the files of a conversation's
  directory, the checkpoints, the start's refusals.
- The engine runs on a stand-in for the CLI, `tests/workers/stand_in/cursor-agent`: a real
  process that prints the CLI's lines and keeps chats where the CLI does. A journey of turns
  covers a resumed chat, tool calls, a failure, a deadline and a forgotten conversation.
- With Docker, a Robinauts server starts the worker from its image, on the same stand-in, and
  holds two conversations over HTTP. The second searches the first with Robinauts' own tool.
- No test reaches Cursor. The shapes in the tests are the ones CLI `2026.11.22` printed.
- The journey in `tests/e2e/` adds the key and checks that the worker joins.

## Open

- A turn on Cursor in the journey. It needs a Cursor API key.
- The CLI updates itself by default, and Cursor documents no switch. The image runs the pinned
  program; whether a newer one replaces it in the CLI's home is not known.
- The CLI's telemetry. Cursor documents no switch for it.
- A deleted conversation leaves `~/.cursor/ai-tracking` as the CLI wrote it.
- Mode 3 has no Cursor worker yet.
