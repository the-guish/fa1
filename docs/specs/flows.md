# Flows

A flow is a reusable series of tasks: each task done by an agent and a model, each handing its
result to the next. The person designs flows by chatting with an agent, keeps them in the setup
folder ([setup-folder.md](setup-folder.md)), and runs them on demand, on a schedule or from a
trigger.

FA1 adds little of its own. Robinauts and neorc run the flows; FA1 gives them the setup folder's
flows, the agents the instructions to write them, and the person a review of each change.

## An example

> We will work on a new flow. In the first task Haiku pulls the list of pending SonarQube
> issues, checks none is in progress, and picks one. In the next task Sonnet prepares a fix as a
> draft pull request. Then Opus reviews it and says whether it is ready. When it is, the pull
> request moves from draft to ready; otherwise it goes back to Sonnet.

The flow designer turns this into `flows/sonar_fix.yaml` and its handlers:

| step | handler | agent, model | hands on |
|---|---|---|---|
| `pick` | opens a conversation: list the open issues, drop those in progress, pick one | `claude-code`, Haiku | the issue |
| `rounds` | a loop, at most 3 rounds, until `approved` | | |
| `rounds.fix` | opens or continues a conversation: fix the issue on the PR's branch, as a draft PR | `claude-code`, Sonnet | the PR's URL |
| `rounds.review` | opens a conversation: review the PR against the issue, say ready or not, comment why | `claude-code`, Opus | the verdict |
| `rounds.approved` | reads the verdict | | true or false |
| `ready` | marks the PR ready for review | | the PR's URL |

The review's comments reach the next round's fix through the pull request: a step of a loop
cannot read a later step of an earlier round.

## Authoring: a chat and a review

The person chats with the Flow designer, reads the change it proposes, and approves it. The
setup folder's starter holds:

- the agent **Flow designer** (`agents/flow-designer.toml`): its instructions say to read
  `knowledge/flows.md`, agree the flow with the person step by step, write it on a branch of
  the working copy, raise its version, check it, and ask for the person's review;
- `knowledge/flows.md`: the format, the handlers' helpers, the rules, and what is not possible
  yet, for any agent;
- `flows/handlers/robinauts_tasks.py`: Robinauts' own handlers and helpers, to open a
  conversation with an agent and a model, wait for its answer and read its `RESULT` line;
- `flows/code_and_review.yaml`: Robinauts' example flow, with its form.

The Flow designer reaches the setup folder through three tool servers alone
([review-app.md](review-app.md)):

| tool server | gives the designer |
|---|---|
| `setup-files` | the files of its working copy of the setup folder, at `/work/setup` |
| `setup-git` | git on that working copy: a branch, a commit, a merge |
| `setup-review` | `validate_setup`, the checks, and `submit_changelist`, the request for a review |

1. The designer writes the flow on a branch, and commits.
2. The person reads the changelist under Reviews, and approves or rejects it.
3. The person presses Refresh. The approved change reaches the setup folder, and FA1 deploys
   it.

- The designer runs on Claude Code by default, with the Claude Code token. Its own directory in
  the code worker holds no file of the setup folder.
- The designer's own directory there holds a worktree of each repository of `flows.toml`. Its
  instructions say to read them for a fact about a project, such as neorc's flow format.
- The person chooses the designer's engine in `agents/flow-designer.toml`. On `pydantic-ai` it
  runs on the server's own worker, with the Anthropic API key, and has no shell.
- The code worker holds the key of the three tool servers only while an agent of its own uses
  them ([containers.md](containers.md), "Secrets").
- A flow's handler is code that runs in the control plane. The review shows each file whole,
  and marks the handlers.
- A setup folder on GitHub takes changes the other way too: the agent Claude Code clones it,
  pushes a branch and opens a pull request ([setup-folder.md](setup-folder.md), "Changing it
  through the agents").

## The format

Robinauts' and neorc's own, unchanged ([knowledge/flows.md](../../setup-starter/knowledge/flows.md)):

- `flows/<name>.yaml`: neorc's flow. Steps name a handler, `<module>:<function>`, on the queue
  `default`, with `params` by reference (`inputs.x`, `tasks.<step>`, `neorc.flow_run_id`) and
  `fixed_params` as they are. A step may be a `loop` with `max_cycles` and an
  `exit_condition`.
- `flows/<name>.form.toml`: Robinauts' form that starts the flow.
- `flows/handlers/<module>.py`: the handlers, with the standard library alone.
- `flows/queues.toml`: neorc's file of the queues a person answers, each of kind `external`. A
  step on such a queue waits for the person, who answers it under Queues in neorc's screens. The
  step may name a form, a JSON file beside the flow.
- `flows/flows.toml`: `code_location = "handlers"`, and the `[repositories]` a code task may
  name.

A flow's `version` rises at each change. The server keeps the first content of each version.

## Deploying

- FA1 writes the setup folder's `flows/` to `compose/flows/` at each start and refresh
  ([setup-folder.md](setup-folder.md), "Deploying it").
- `control` mounts that folder read-only at `/etc/fa1/flows`, with
  `ROBINAUTS_FLOWS_DIR` naming it.
- `control` then uploads the flows at its start, and runs neorc's worker beside the server: the
  handlers run there, and reach Robinauts' API with a token the server makes.
- A refresh restarts `control`: a run in progress ends, and a new version of a flow cancels the
  runs of the old one.

## Running a flow

| how | today |
|---|---|
| on demand, from the flow's form in Robinauts | works |
| on demand, from a script: `POST /robinauts/api/flows/<name>/runs` | works, with a person's token |
| on a schedule | planned: a `schedules.toml` in the setup folder, run by FA1 |
| from a trigger: a webhook, a CI job | planned, after the schedule |

### Planned: schedules and triggers

- `schedules.toml` in the setup folder names a flow, its inputs, and when: `every day at 09:00`,
  `every monday at 08:00`, `every 30 minutes`.
- FA1 runs the schedule while it runs: a service of the Compose project that starts the run at
  its time through `POST /robinauts/api/flows/<name>/runs`.
- A run must belong to the person: Robinauts' handlers refuse a run a service started. The
  schedule needs either a token the person makes for it, or a change in Robinauts that lets a
  service start a run for the person.
- A trigger is the same request from outside, through a URL FA1 publishes. FA1 keeps the front
  listener on the host's loopback, so a trigger from the internet needs a relay: it waits for
  the schedule.

## Not possible yet

- A trial run of a new handler in the control plane before its review. The checks read a
  handler without running it, and a designer on Claude Code runs a handler's own logic in its
  directory at most.
- Branches other than a loop's exit: a decision is a step whose value the next steps act on.
- Reloading flows without a restart.

## Tests

- The journey deploys the starter's flows and starts a run of a flow whose handler needs no
  model, from Robinauts' page, and waits for its result.
- The journey plays the Flow designer through its three tool servers: a branch, a file, a
  commit, the checks and a changelist. The person approves it and presses Refresh, and
  Robinauts serves the change.
- The unit tests read the setup folder's `flows/`.
