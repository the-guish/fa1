# The review app

The review app holds proposed changes to the setup folder until a person approves them. A
submitter proposes a branch as a changelist, and an approver's yes puts it in the setup folder.

## Scope

- The review app stands on its own. It touches the other apps at few points.
- The review app keeps its records in a database of its own. Its repository is the setup
  folder's.
- The review app reviews changes to the setup folder ([setup-folder.md](setup-folder.md)).
  The person reviews a GitHub pull request on GitHub.
- A changelist is a git branch. The review app tracks commits, and git tracks the files.

## The parts

| part | where | holds |
|---|---|---|
| the setup folder | the host; `/setup` in `control` and in the designer's git server | what FA1 deploys, and the review app's repository |
| the working copy | the volume `setup-work`, at `/work/setup` | a clone the designer edits |

- `control` mounts the setup folder, and writes it. The designer's git server mounts it
  read-only ([containers.md](containers.md), "The setup folder").
- A change moves one way: from the working copy to the setup folder.
- The setup folder's files change at an approval alone. A submit adds a commit and a branch to
  its repository, and leaves its files and its checked-out branch as they are.

## Main

`main` is the commit the setup folder is at: its HEAD, on the branch the person keeps.

- The review app reads it at each request. A commit the person makes by hand counts at once.
- A setup folder with no commit gives a changelist nothing to start from, and a submit says
  so.
- The review app runs git in the setup folder with settings of its own over the folder's. No
  hook and no program the folder's settings name runs in the control plane.

## The working copy

The designer edits the working copy through two tool servers, the reference MCP servers, each
behind supergateway ([flows.md](flows.md), "Authoring").

| service | server | the designer does |
|---|---|---|
| `setup-files` | `@modelcontextprotocol/server-filesystem`, on `/work` | reads and writes files |
| `setup-git` | `mcp-server-git`, on `/work/setup`, with FA1's `git_rm` | makes a branch, stages, removes files, commits, merges |

- Neither reference server removes a file. FA1 adds the tool `git_rm` to the git server
  (`compose/setup-tools/git_server.py`).
- `git_rm` removes files and folders of the working copy, and stages their removal. A removal
  reaches the setup folder as part of a changelist, like any other change.

- The two services are one image, and run as the setup folder's owner, so both write the
  volume. Each runs read-only, with no capability.
- One key opens them and the designer's two tools: `FA1_SETUP_KEY`, which `control` holds.
- The code worker holds that key only while an agent of its own uses one of the three tool
  servers ([containers.md](containers.md), "Secrets"). The starter's Flow designer is such an
  agent.
- An agent with the key writes the working copy and submits a changelist. It approves
  nothing.
- The git server brings the working copy's `main` to the setup folder's commit as it starts.
  Work left on `main` then moves to a branch `kept/<time>`.
- The git server looks at the setup folder's commit every two seconds while it runs. A new
  commit moves `main` to it, as at the start, and nothing else.
- The person may rewrite the setup folder's history, with a rebase or a force push. `main` then
  follows to the new commit. A branch of the designer that started from the old `main` is
  refused at its next submit, and the designer makes it again from `main`.
- The designer's branches and its files not yet committed stay as they are.
- The designer's commits are by `Flow designer`. The setup folder's history then shows the
  changes the designer wrote.
- The working copy is one folder. One designer turn works in it at a time.
- The designer writes every file of the working copy, its git settings included. The review
  app fetches from it, and runs no other git command in it.

## The designer's tools

The review app serves two tools to the designer, over MCP.

| tool | what it does |
|---|---|
| `validate_setup` | checks the working copy as it is, committed or not, and answers every problem with its file |
| `submit_changelist(name, branch, title, description)` | asks a person to review `branch`, as the changelist `name` |

- The tools are at `http://127.0.0.1:8422/mcp`, on the loopback address of `control`. Every
  request carries `FA1_SETUP_KEY`.
- An approval is no tool. A person gives it on the review app's screens.

## A changelist, step by step

1. The designer makes the branch `proposals/add-helper` from `main` in the working copy, writes
   `agents/helper.toml`, and commits.
2. The designer calls `validate_setup`, and fixes what it names.
3. The designer calls `submit_changelist("add-helper", "proposals/add-helper", "A helper", ...)`.
4. The review app fetches the branch into the setup folder's repository, pins its commit, and
   checks that commit.
5. The person opens the changelist under Reviews, reads each file's change, and approves. The
   setup folder fast-forwards to the commit.
6. The person presses Refresh on FA1's Status screen. The app deploys the setup folder.

A changelist is submitted, approved or rejected.

## Submitting

- A submit fetches the branch into the setup folder's repository, as the branch
  `changelists/<name>`. `git branch` in the setup folder lists it.
- The changelist is the commit of the submit, whatever either branch does next. The review app
  keeps that commit in its record.
- A person who has `changelists/<name>` checked out gets no new commit under it. The submit
  is refused until another branch is checked out.
- The branch starts from the current `main`. A branch that does not is refused, and the
  submitter merges `main` into it.
- A changelist holds text a person can read: plain files, each of 1 MB at most, 300 files at
  most. A link, a repository inside the repository and a file that is not UTF-8 are refused.
- A changelist changes no file that steers git on the person's computer: `.gitattributes`,
  `.gitmodules`, `.lfsconfig`.
- A commit that fails the checks is refused, with every problem. The person reviews only what
  the server would start with.
- A changelist that is submitted or rejected takes a new commit under its name. An approved
  one keeps its name for good.

## Checks

The checks read the setup folder's files, and run none of them.

| check | by |
|---|---|
| `fa1.toml`, `models.toml` and `agents/<id>.toml` have FA1's layout | FA1 |
| the models and the agents fit FA1's providers, tool servers and workers | Robinauts' own check of its configuration |
| each flow, and the flows as a set | neorc's own loader |
| each form fits its flow, and `flows.toml` its keys | Robinauts' own checks |
| each step is on the queue `default`, and names a handler that a module of `handlers/` has; or on an external queue of `queues.toml`, which a person answers | FA1 |
| a step that fixes `agent` or `model` in `fixed_params` names an agent of `agents/`, and a model that agent has | FA1 |
| each handler module is Python, and imports the standard library and its neighbours alone | FA1 |
| a changed flow has a higher version than the flow that runs | FA1 |

- The checks run in a process of their own, with no key and a time limit.
- The checks find a setup the server would refuse at its start. They cannot tell whether a
  handler does what its flow needs.
- The app's own reader checks the setup folder again at each deploy
  ([setup-folder.md](setup-folder.md), "Deploying it").

## Approval

- An approval fast-forwards the setup folder to the changelist's commit: `git merge --ff-only`
  in the folder, on the branch the person keeps. It needs `main` to be that commit's ancestor
  still.
- A changelist submitted before another approval no longer starts from `main`. The submitter
  merges `main` into its branch, and submits it again.
- A setup folder with changes not yet committed takes no approval. The person is editing it
  by hand, and the changelist stays submitted.
- The files an approval writes belong to the setup folder's owner: `control` runs as that
  user.
- An approval deletes the branch `changelists/<name>`, since the folder's own branch holds the
  commit. A branch the person moved stays.
- A rejection closes the changelist, and changes nothing else. Its branch stays, for the
  person to delete.
- A plain `git push` leaves these branches on this computer. `git push --all` sends them.

Submitting and approving are two roles in oneberth.

| role | holds | may |
|---|---|---|
| `reviews/submitter` | a person | read, submit |
| `reviews/approver` | a person | read, approve, reject |

- The roles are general: a role covers every changelist.
- The local user holds both roles.

## Deploying

An approved changelist is in the setup folder, and runs after a deploy. Refresh deploys the
setup folder ([setup-folder.md](setup-folder.md), "Deploying it").

## The API

| endpoint | role | what it does |
|---|---|---|
| `GET /api/changelists?state=pending\|closed` | any | the submitted changelists, or the approved and the rejected |
| `GET /api/changelists/<name>` | any | a changelist, with each file's old and new version, and what was checked |
| `POST /api/submit_changelist` | submitter | `{name, branch, title, description}`: as the tool |
| `POST /api/approve_changelist` | approver | `{changelist_name}`: fast-forwards the setup folder |
| `POST /api/reject_changelist` | approver | `{changelist_name}` |

## Screens

- A left panel has two entries: **Pending** and **Closed**. Pending holds the submitted
  changelists. Closed holds the approved and the rejected.
- Each entry shows its changelists in the main panel, with their name, their title, the time
  of their submit and their status.
- A click on a changelist shows its branch, its commit, its description and what was checked.
  Each file has a panel of its own, with the old and the new version side by side, as in
  GitHub's review of a pull request. Each file's panel collapses.
- A file under `flows/handlers/` carries a mark: its code runs in the control plane.
- **Approve** and **Reject** close a submitted changelist. An approved one says whether the
  setup folder still holds it, and names Refresh.
- **Back** returns to the list.

## Open

- A worktree per conversation, so that two designer turns work at once. The reference git
  server has no worktree tool.
- A trial run of a handler in the control plane before the review. A designer on Claude Code
  runs a handler's own logic in its directory, and no more.
- A changelist that applies on a moved `main` without the designer, when the two changes touch
  different files.
- The review of a GitHub pull request in the review app.
- An approval that deploys by itself. A deploy starts the control plane anew, under the App tab
  the person reads.
