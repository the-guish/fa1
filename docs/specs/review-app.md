# The review app

The review app holds proposed changes to local folders until a person approves them. A
submitter proposes the changes in a changelist, and an approver applies the changelist to the
folders.

## Scope

- The review app stands on its own. It touches the other apps at few points.
- The review app keeps its records in a database or schema of its own.
- The review app reviews changes to local folders. Remote GitHub pull requests come in a later
  release.

## Folders

The review app runs in a starting folder. Each registered folder is a path relative to it.

For example, the review app starts in `/home/happy-dev/workspace/`. A call to
`register_folder("project-m")` maps `project-m` to `/home/happy-dev/workspace/project-m`. From
then on, the API names that folder `project-m`, and its files `project-m/<path>`.

## The API

| endpoint | what it does |
|---|---|
| `register_folder(path)` | maps a path, relative to the starting folder, to a folder the API names by that path |
| `open_changelist(name)` | opens a changelist with that name, and hashes the content of each registered folder |
| `replace_contents(changelist_name, path, new_contents)` | holds `new_contents` as the changelist's copy of the file |
| `revert_changes(changelist_name, path)` | drops the changelist's copy of the file |
| `submit_changelist(changelist_name)` | submits the changelist for review |
| `approve_changelist(changelist_name)` | applies the changelist's files to their folders |

The changelist's copies live in the review app's own working folder. The target folders stay as
they are until approval.

## A changelist, step by step

1. The submitting system calls `open_changelist("improve-readme")`.
2. `project-m/README.md` holds `Hello`. The submitting system calls
   `replace_contents("improve-readme", "project-m/README.md", "Hello World!")`.
3. The submitting system calls `submit_changelist("improve-readme")`.
4. An approver calls `approve_changelist("improve-readme")`. `project-m/README.md` now holds
   `Hello World!`.

A changelist is open, submitted or approved. Its files change only while it is open.

## Approval

The review app hashes each folder's content when a changelist opens. An approval applies the
changelist only if each folder it changes still matches that hash.

The hash shows whether anyone edited a folder outside the changelist. A folder then changes only
by the edits the submitter planned.

## Roles

Submitting and approving are two roles in oneberth.

- The roles are general: a role covers every folder and every changelist.
- Roles per folder or per changelist come in a later version.

## Screens

- A left panel has two entries: **Pending** and **Closed**. Pending holds the open and the
  submitted changelists. Closed holds the approved ones.
- Each entry shows its changelists in the main panel, with their name, their creation date and
  their status.
- A click on a changelist shows its changes in the main panel. Each file has a panel of its own,
  with the old and the new version side by side, as in GitHub's review of a pull request. Each
  file's panel collapses.
- **Back** returns to the list.
- **Approve** applies a submitted changelist.
