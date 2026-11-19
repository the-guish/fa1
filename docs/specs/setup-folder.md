# The setup folder

The setup folder holds everything permanent about how the person works with FA1: FA1's settings,
the agents, the models, the knowledge, and the flows ([flows.md](flows.md)). It is one folder,
and a git repository the person owns. FA1's installation, its containers and its conversations
can be lost at any time; the setup folder is what the person keeps.

On a new computer the person clones the repository, installs FA1, points it at the folder,
enters the keys, and continues where they were.

## What it holds

```
<setup folder>/
    fa1.toml                 FA1's settings: the git author
    models.toml              the models the agents may use
    agents/<id>.toml         one agent each: title, engine, models, tools, instructions
    knowledge/               the knowledge base: Markdown the agents read
    flows/                   the flows, in Robinauts' format, and their handlers (flows.md)
    README.md                what the folder is, for the person and for the agents
```

- The folder holds no secret. The keys stay in the app's folder, readable by the person alone
  ([app.md](app.md), "The folder"). A new computer asks for them again.
- Every file is text, so a change is a commit, and a pull request can be reviewed.
- A file FA1 does not know is left alone. The person may keep notes, scripts and anything else
  beside FA1's files.

### `fa1.toml`

```toml
[git]
name = "Ada Lovelace"
email = "ada@example.com"
```

### `models.toml` and `agents/<id>.toml`

They hold Robinauts' own tables, `[models.<id>]` and the keys of `[agents.<id>]`, with the id
taken from the file name. FA1 adds what the person does not choose: the model providers, the
tool servers and the workers ([containers.md](containers.md)).

```toml
# agents/reviewer.toml
title = "Reviewer"
engine = "claude-code"
models = ["cc-opus"]
worker = "claude"
tools = ["sessions"]
system_prompt = """
You review the pull request you are given. Say "ready" or "not ready", and why.
"""
```

- A model's provider is one FA1 names: `anthropic` (the API key) or `claude-code` (the Claude
  Code token).
- An agent's tools are the tool servers FA1 runs: `fetch`, `browser`, `files`, `todo`,
  `diagrams`, and Robinauts' own `sessions`.

### `knowledge/`

Markdown files: how the person works, their projects, their conventions. The coding agents read
them in their clone of the setup folder (below). An agent's instructions may point at them.

## Choosing the folder

- The Welcome screen asks for the folder's location. The location may be an existing setup
  folder, an empty folder, or a folder that does not exist yet.
- An empty or new folder gets the starter, `setup-starter/` in this repository: FA1's default
  models (Haiku, Sonnet and Opus), the agents Assistant, Claude Code and Flow designer, a
  knowledge page on flows, Robinauts' example flow and handlers, and a README. FA1 runs
  `git init` in it when it is not a repository.
- A folder with other files and no `fa1.toml` is refused.
- The app keeps the location in `settings.toml`, in its own folder. The Status screen shows it,
  and the person may change it there, after moving the folder.
- The folder must be one the person can write. FA1 refuses a folder inside its own app folder,
  which "Remove everything" deletes.

## Deploying it

FA1 reads the setup folder at each start and at each refresh:

1. FA1 reads and checks every file it knows. A problem stops the deploy, names the file and the
   line, and keeps what runs.
2. FA1 writes Robinauts' configuration (`robinauts.toml`) in `compose/`: FA1's fixed part,
   `compose/robinauts.base.toml`, then the folder's models and agents.
3. When it changed, `control` and `code` start anew: both read it as they start.

The folder's `flows/` is deployed with the flows ([flows.md](flows.md)).

**Refresh** is a button on the Status screen: it pulls the setup folder, then deploys it.

- The pull is `git pull --ff-only` on the folder's current branch, with the GitHub token when the
  remote is on GitHub. The token goes through git's credential helper and never into the log.
- A folder with uncommitted changes is deployed as it is, without a pull: the person is editing
  it by hand.
- A pull that cannot fast-forward stops the refresh, and says so.
- A refresh restarts `control` and `code` when the setup changed. A turn that runs then ends.
- A restart of `control` ends the App tab's sign-in. After every start and refresh, an open App
  tab loads Robinauts again with a new ticket.

## Changing it through the agents

The coding agents reach GitHub with the person's token, so they can change the setup folder the
way they change any repository:

1. The person asks an agent for a change: a new agent, a flow, a page of knowledge, and names
   the setup folder's repository.
2. The agent clones it in its conversation's directory, writes the files on a branch of its
   own, pushes the branch and opens a pull request.
3. The person reviews and merges the pull request on GitHub.
4. The person presses Refresh.

A setup folder with no GitHub remote works the same way without steps 2 and 3: the person edits
the files, and Refresh deploys them.

## Open

- A secret a flow or an agent needs beyond the app's keys, such as a SonarQube token.
- The Assistant reading the knowledge base, through the files tool.
- Robinauts reloading its configuration without a restart, so a refresh keeps running turns.
