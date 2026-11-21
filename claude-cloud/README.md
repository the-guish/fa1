# claude-cloud

claude-cloud is an engine of the code worker. A conversation on it is a cloud session of Claude
Code, on claude.ai, and the code worker waits for its replies.

- A turn sends its prompt with `claude --cloud`, and returns at once.
- The cloud session's hooks write its progress and its replies to a git repository, tincan.
- The engine polls tincan, and gives each reply to Robinauts as the turn's answer.

## The parts

| part | file | where it runs |
|---|---|---|
| the engine | `src/fa1_cloud/engine.py` | the code worker |
| tincan's reader and the poller | `src/fa1_cloud/tincan.py` | the code worker |
| the worker's front | `src/fa1_cloud/__main__.py` | the code worker |
| the hooks | `environment/setup.sh`, which writes `tincan_hook.py` | the cloud session |
| the image of `code` | `Dockerfile` | the host's Docker |

- Robinauts' worker refuses an agent on an engine other than `claude-code`. The front widens that
  check to `claude-cloud`, then runs Robinauts' worker as it is.
- `claude-cloud` runs the Claude Code binary of `claude-code`, with the same token. Robinauts'
  credential checks of the worker cover it too.
- The image installs the engine without dependencies. Every version of the worker's lock stays.
- The engine registers under the entry point `robinauts.engines`. Robinauts finds it there, as it
  finds `claude-code`.

## Tincan

Tincan is a GitHub repository of the person's own, with a commit on its default branch. Each
conversation writes one branch of it, `s/<conversation id>`:

| file | written | holds |
|---|---|---|
| `session.json` | at the first prompt | the conversation, the cloud session's id and link |
| `status.json` | at each prompt, each heartbeat and each stop | `working` or `idle`, the turn, the time of the last tool call |
| `turns/NNNN.md` | at the stop of turn NNNN | the reply |

- One cloud session writes each branch. Two sessions never push to the same branch.
- The engine reads tincan alone. It clones it to `$CLAUDE_CONFIG_DIR/cloud/tincan`, and starts
  `claude --cloud` from that clone.
- A forgotten conversation keeps its branch. The person deletes the branch.

## A turn

1. The engine sends the prompt. The first line is the marker `[tincan <conversation id> turn
   <n>]`. The first turn adds the agent's system prompt, in `<instructions>`.
2. A first turn runs `claude -p --cloud <prompt>`. A later turn runs
   `claude -p <prompt> --cloud <session id>`, with the id from `session.json`.
3. The hook `UserPromptSubmit` reads the marker. It writes `session.json` and `status.json`, and
   starts the heartbeat.
4. The hook `PostToolUse` touches a local file. It runs no git, so a tool call stays fast.
5. The heartbeat writes `status.json` every 5 minutes while the turn runs, with the time of the
   last tool call. An idle session writes nothing.
6. The hook `Stop` writes `turns/<n>.md` from `last_assistant_message`, and `idle`.
7. The engine gives the reply as the answer, with a new checkpoint.

The hooks act on a marked prompt alone. A prompt typed on claude.ai into the same session gets
no turn file.

## Polling

- One poller serves every waiting turn. Each cycle runs one `git ls-remote` on tincan, for every
  branch.
- The engine fetches a branch only when its commit changed.
- The interval starts at 20 seconds. It grows by half at each cycle with no change, up to 2
  minutes. A change, or a new prompt, sets it back.
- The poller runs while a turn waits. With no turn waiting, it stops.

## When a turn fails

| case | after | the error says |
|---|---|---|
| the cloud session takes no prompt | 10 minutes | check the environment's tincan hooks |
| the branch gets no commit while the turn runs | 15 minutes, three missed heartbeats | the session has been silent |
| `claude --cloud` exits with an error | at once | the last lines it printed |
| the agent's `turn_timeout_seconds` passes | the timeout | Robinauts' timeout |

- A cloud session goes on from its latest reply. A turn from an earlier checkpoint, such as an
  edit or a regenerate, is refused.
- A fork is refused. The person starts a new conversation.
- A resumed turn that finished gives its reply again. A resumed turn still running is waited for,
  and sends nothing.
- A cancelled turn stops the wait. The cloud session goes on, and claude.ai shows it.

## Setting it up

### The cloud environment

The person sets up one cloud environment on claude.ai, by hand:

1. Add tincan to the environment's repositories, with the work repositories beside it. The
   person's GitHub connection needs push access to tincan.
2. Add the variable `TINCAN_URL`, such as `https://github.com/<owner>/tincan.git`. The line
   `TINCAN_URL_DEFAULT` of `setup.sh` is the other place for it.
3. Paste `environment/setup.sh` into the environment's setup script.
4. Make it the default environment. `claude --cloud` starts its sessions there.

The setup script writes the hook to `/opt/tincan/tincan_hook.py`. It adds four hooks to
`~/.claude/settings.json` in the container: `SessionStart`, `UserPromptSubmit`, `PostToolUse` and
`Stop`.

- The hooks act in a cloud session alone, where `CLAUDE_CODE_REMOTE` is `true`.
- A hook that fails prints to its standard error and exits 0. A failed hook never stops the
  session.
- The work repositories need no change.

### The setup folder

The setup folder names tincan in `fa1.toml`:

```toml
[cloud]
tincan = "https://github.com/<owner>/tincan.git"
```

The app writes it to `code.env` as `FA1_TINCAN_URL`. The code worker's GitHub token reads tincan
through git's credential helper.

An agent runs on the engine with a file in `agents/`, such as `agents/cloud.toml`:

```toml
title = "Claude in the cloud"
engine = "claude-cloud"
models = ["cc-opus"]
worker = "claude"
turn_timeout_seconds = 86400
system_prompt = "Say what you did."
```

The agent's model is a name in Robinauts. The cloud session runs on the model its environment
chooses.

### The code worker's variables

| variable | default | sets |
|---|---|---|
| `FA1_TINCAN_URL` | none: every turn is refused | the tincan repository |
| `FA1_CLOUD_POLL_SECONDS` | 20 | the shortest interval of the poller |
| `FA1_CLOUD_POLL_MOST_SECONDS` | 120 | the longest interval |
| `FA1_CLOUD_START_SECONDS` | 600 | the wait for the session to take a prompt |
| `FA1_CLOUD_SILENT_SECONDS` | 900 | the wait for a commit while a turn runs |
| `FA1_CLOUD_STATE` | `$CLAUDE_CONFIG_DIR/cloud` | the records and the clone of tincan |
| `ROBINAUTS_CLAUDE_CLI_PATH` | the binary the Agent SDK bundles | the `claude` the engine runs |

## Tests

`tests/run.sh` runs the engine and the hook in the environment of Robinauts' worker at the
pinned commit, on real git, outside Docker. `tests/fake_claude.py` stands in for
`claude --cloud`: it runs the real hook against a bare repository, as a cloud session would.

```sh
claude-cloud/tests/run.sh
```

The journey in `tests/e2e/` starts the code worker with an agent on `claude-cloud`, and checks
that the worker runs it.

## Open

These need a real cloud session, which no test starts:

- The output of `claude -p --cloud <prompt>`, which the docs leave out. The engine reads the
  session's id from `session.json` when the output has none.
- A cloud session started with the token of `claude setup-token`. The docs ask for a claude.ai
  sign-in.
- The hooks of `~/.claude/settings.json` in a cloud container. The docs say the hooks of the
  person's own `~/.claude` stay on their computer. The setup script writes the container's own.
- `CLAUDE_CODE_REMOTE_SESSION_ID` in a hook's environment.
- The heartbeat, a process the hook starts in a session of its own, alive after the hook ends.
- A push to tincan from a session that holds several repositories.
