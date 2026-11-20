# Flows: how to write one

A flow is a reusable series of tasks. Each task is a handler: a Python function that usually opens
a conversation with an agent and a model, waits for its answer, and hands a result to the next
task. Flows live in `flows/` of this setup folder. FA1 deploys them at each start and refresh;
the person runs them from the flow's form in Robinauts.

## A first flow

`flows/hello.yaml` greets whoever its form names, with one handler and no model
(`handlers/examples.py`). Run it from Flows in Robinauts to see a run end to end.

## Files

```
flows/
    flows.toml                  code_location = "handlers"; [repositories] for code tasks
    <name>.yaml                 the flow: neorc's format
    <name>.form.toml            optional: the form that starts it
    handlers/<module>.py        the handlers its steps name as <module>:<function>
```

## The flow

```yaml
name: fix_one_issue          # the file name, without .yaml
version: 0.1.0               # raise it at every change: the server keeps a version's first content

inputs:                      # what the form or the caller gives
  task: string

output: tasks.review         # the run's result: a step's output

steps:
  pick:
    queue: default           # the handlers' queue; a person's queue is below
    handler: my_tasks:pick   # handlers/my_tasks.py, function pick
    params:                  # the handler's arguments, by reference
      task: inputs.task
      run: neorc.flow_run_id # pass it to every handler that opens a conversation
    fixed_params:            # the handler's arguments, as they are
      agent: claude-code
      model: haiku           # matched in the agent's models' ids and titles

  fix:
    queue: default
    handler: my_tasks:fix
    params:
      picked: tasks.pick     # the output of the step pick
      run: neorc.flow_run_id
    fixed_params:
      agent: claude-code
      model: sonnet
```

- Steps run once the steps they reference have finished. Two steps that reference nothing of
  each other run at once.
- `inputs.<x>`, `tasks.<step>`, `neorc.flow_run_id` and `neorc.loop_count` are the references.
- A step may also be a `loop`, a `fan_out` or a `flow` (a sub-flow).

### Loops

```yaml
  rounds:
    loop:
      max_cycles: 5                 # reaching it while still looping fails the run
      exit_condition: approved      # a step of the loop that returns true or false
    steps:
      fix: { queue: default, handler: my_tasks:fix, params: { ... } }
      approved: { queue: default, handler: my_tasks:approved, params: { verdict: tasks.review } }
      review: { queue: default, handler: my_tasks:review, params: { fixed: tasks.fix } }
```

- A step cannot read a later step of the same loop from an earlier round: that is a cycle. Carry
  the review's feedback to the next fix through the conversation or the pull request: the fix
  handler reads the latest review comment.
- There is no if/else. A decision is a step that returns a value, and the next steps act on it:
  for example a last step that marks the pull request ready when the review approved it.

## Handlers

- One module per area in `handlers/`, the standard library alone.
- `handlers/robinauts_tasks.py` (Robinauts' own) has the helpers: `_open(text, model=, agent=,
  task_payload=)` opens a conversation and waits for its first answer; `_say(conversation, text)`
  continues one; `result_of(answer)` reads the answer's last `RESULT {json}` line;
  `acting_in(run)` makes the server act for the person who started the run;
  `code_task(repo, branch)` gives the conversation a worktree of a repository of `flows.toml`.
  Import them: `from robinauts_tasks import _open, acting_in, result_of`.
- Ask each agent to end its answer with one line `RESULT {"...": ...}`, and read it with
  `result_of`. An answer without it fails the task, with what the agent said.
- A task may run twice: make each handler safe to repeat (check before opening a second pull
  request).
- The agents reach GitHub with the token of their worker. A handler holds no token.

## Models

A step names its model in `fixed_params` by a word of its id or title: `haiku`, `sonnet`, `opus`.
The model must be one of the agent's `models` in `agents/<agent>.toml`; add it there, and in
`models.toml` when it is new.

## Running a flow

- **On demand:** the flow's form in Robinauts (`<name>.form.toml`). A `lov` of `repo_branch`,
  `agent` or `model` offers the setup's choices.
- **A repository, its branch and a project:** `lov = "repository"` offers the repositories of
  `flows.toml`. `lov = "branch"` with `of = "<the repository's input>"` offers that
  repository's branches as its server has them now, and the person searches them as they type.
  `lov = "project"` offers the person's projects in Robinauts. The run gets the repository's
  id, the branch's name and the project's id.

  ```toml
  [inputs.repo]
  lov = "repository"

  [inputs.branch]
  lov = "branch"
  of = "repo"
  ```

  A repository's `branches` in `flows.toml` holds names or patterns: `["main", "release/*"]`.
  A branch input offers those that match; `["*"]` offers every branch.
- **On a schedule, or from a webhook:** not yet. Say so to the person; FA1 plans it.
- **A person's answer in the middle:** a step on an external queue (below).

## A step a person answers

A flow may wait for a person: an approval, a triage of a review's issues, a choice.

- `flows/queues.toml` names the queue, once for all the flows: `[queues.editors]` with
  `kind = "external"`. FA1 takes external queues there, and `default` stays the handlers'.
- The step is on that queue. Its `handler` is a short text for the person, and no function.
- The step may name a form, `form: <file>.form.json`, beside the flow. The form reads the
  step's inputs, and its result is what the next steps read. Without a form the person
  answers with a text.
- The person answers under Queues in neorc's screens. The run waits until then.
- A loop whose `exit_condition` reads the answer sends the work back: "re-work" runs another
  round, and "ready" ends it. A sub-flow per round keeps each round's answer apart.

neorc's own examples are the reference: `examples/approval` and `examples/review_loop`, with
their flows, their forms and what a form may hold (`docs/architecture/forms.md`,
`docs/specs/task-completion.md`). Read them in your own directory, at `./neorc`, when it is
there. A raised `version` covers a changed form too.

## Changing a flow

1. Edit the files on a branch of your own, and raise the flow's `version`.
2. Ask for the person's review, in the way your instructions name:
   - with `validate_setup` and `submit_changelist`, when you work in the working copy at
     `/work/setup`: the person reviews the changelist under Reviews and approves it;
   - with a pull request that says what changed and how to run it, when you work in a clone
     from GitHub: the person merges it there.
3. The person presses Refresh. A refresh restarts the server: a run in progress ends.

`validate_setup` reads the files and runs none: it finds a flow the server would refuse, a
handler that is not Python or that a step names and no module has, and a changed flow whose
version did not rise. It cannot tell whether a handler does what the flow needs.
