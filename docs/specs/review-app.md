# The review app

The review app holds proposed changes to the setup folder until a person approves them. A
submitter proposes a branch as a changelist, and an approver's yes takes it to the setup folder
at the next Refresh.

## Scope

- The review app stands on its own. It touches the other apps at few points.
- The review app keeps its records in a database of its own, and its commits in a git
  repository of its own.
- The review app reviews changes to the setup folder ([setup-folder.md](setup-folder.md)).
  The person reviews a GitHub pull request on GitHub.
- A changelist is a git branch. The review app tracks commits, and git tracks the files.

## The parts

| part | where | holds |
|---|---|---|
| the setup folder | the host | what FA1 deploys: the one place a change counts |
| the published HEAD | `compose/setup/main.bundle`, in the app's folder | the setup folder's HEAD, as a git bundle |
| the working copy | the volume `setup-work`, at `/work/setup` | a clone the designer edits |
| the review app's repository | `reviews/setup.git`, in the data directory | `main`, and each changelist's commit |

- The app writes the published HEAD at each start and refresh. `control` and the designer's git
  server mount its folder read-only ([containers.md](containers.md)).
- A change moves one way: the working copy, the review app's repository, the setup folder.
- The app alone writes the setup folder. No container mounts it.

## Main

`main` is the setup folder's HEAD, plus the changelists a person approved and the setup folder
lacks yet.

- The review app reads the published HEAD before each request that needs `main`.
- `main` keeps its approved commits while the published HEAD is their ancestor. Any other
  difference is the setup folder's to decide: `main` follows it.
- A setup folder with no commit publishes nothing. A changelist then has nothing to start
  from, and a submit says so.

## The working copy

The designer edits the working copy through two tool servers, the reference MCP servers, each
behind supergateway ([flows.md](flows.md), "Authoring").

| service | server | the designer does |
|---|---|---|
| `setup-files` | `@modelcontextprotocol/server-filesystem`, on `/work` | reads and writes files |
| `setup-git` | `mcp-server-git`, on `/work/setup` | makes a branch, stages, commits, merges |

- The two services are one image and one user, so both write the volume. Each runs read-only,
  with no capability.
- One key opens them: `FA1_SETUP_KEY`, which `control` holds. The code worker holds none of it.
- The git server brings the working copy's `main` to the published HEAD as it starts. A new
  HEAD starts it anew.
- The designer's branches and its files not yet committed stay as they are. Work left on `main`
  moves to a branch `kept/<time>`.
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
4. The review app fetches the branch, pins its commit, and checks that commit.
5. The person opens the changelist under Reviews, reads each file's change, and approves.
   `main` moves to the commit.
6. The person presses Refresh on FA1's Status screen. The app fetches `main`, fast-forwards the
   setup folder, and deploys it.

A changelist is submitted, approved or rejected.

## Submitting

- A submit fetches the branch into the review app's repository. The changelist is that commit,
  whatever the branch does next.
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
| each step is on the queue `default`, and names a handler that a module of `handlers/` has | FA1 |
| each handler module is Python, and imports the standard library and its neighbours alone | FA1 |
| a changed flow has a higher version than the flow that runs | FA1 |

- The checks run in a process of their own, with no key and a time limit.
- The checks find a setup the server would refuse at its start. They cannot tell whether a
  handler does what its flow needs.
- The app's own reader checks the setup folder again at each deploy
  ([setup-folder.md](setup-folder.md), "Deploying it").

## Approval

- An approval moves `main` to the changelist's commit. It needs `main` to be that commit's
  ancestor still.
- A changelist submitted before another approval no longer starts from `main`. The submitter
  merges `main` into its branch, and submits it again.
- A rejection closes the changelist, and changes nothing else.

Submitting, approving and fetching `main` are three roles in oneberth.

| role | holds | may |
|---|---|---|
| `reviews/submitter` | a person | read, submit |
| `reviews/approver` | a person | read, approve, reject |
| `reviews/host` | the app's service token | fetch the approved commits |

- The roles are general: a role covers every changelist.
- The local user holds the two roles of a person.

## Applying

Refresh takes the approved changelists to the setup folder ([setup-folder.md](setup-folder.md),
"Deploying it").

1. The app makes a service token of `reviews/host` with the launch secret.
2. The app fetches `GET /reviews/api/approved.bundle`: a git bundle of `main`, from the
   published HEAD on. It ends the token.
3. The app runs `git fetch` on the bundle in the setup folder, then `git merge --ff-only`.
4. The app publishes the new HEAD, and deploys the setup folder.

- git checks each object of the bundle as it fetches. A setup folder that moved elsewhere
  refuses the fast-forward, and the refresh stops.
- A setup folder with changes not yet committed takes no approved change. The person is
  editing it by hand.
- The control plane holds the approved commits until the setup folder has them. A stop keeps
  them.

## The API

| endpoint | role | what it does |
|---|---|---|
| `GET /api/changelists?state=pending\|closed` | any | the submitted changelists, or the approved and the rejected |
| `GET /api/changelists/<name>` | any | a changelist, with each file's old and new version, and what was checked |
| `POST /api/submit_changelist` | submitter | `{name, branch, title, description}`: as the tool |
| `POST /api/approve_changelist` | approver | `{changelist_name}`: moves `main` |
| `POST /api/reject_changelist` | approver | `{changelist_name}` |
| `GET /api/approved.bundle` | host | the approved commits the setup folder lacks; 204 for none |

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
  setup folder holds it yet, and names Refresh.
- **Back** returns to the list.

## Open

- A worktree per conversation, so that two designer turns work at once. The reference git
  server has no worktree tool.
- A trial run of a handler before the review. The designer has no shell.
- A changelist that applies on a moved `main` without the designer, when the two changes touch
  different files.
- The review of a GitHub pull request in the review app.
- An approval that deploys by itself. A deploy starts the control plane anew, under the App tab
  the person reads.
