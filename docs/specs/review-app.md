# The review app

The review app holds proposed changes to local folders until a person approves them. A
submitter proposes the changes in a batch, and an approver applies the batch to the folder.

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
| `open_batch(name)` | opens a batch with that name, and hashes the folder's content |
| `replace_contents(batch_name, path, new_contents)` | holds `new_contents` as the batch's copy of the file |
| `revert_changes(batch_name, filepath)` | drops the batch's copy of the file |
| `submit_batch(batch_name)` | submits the batch for review |
| `approve_batch(batch_name)` | applies the batch's files to the folder |

The batch's copies live in the review app's own working folder. The target folder stays as it
is until approval.

## A batch, step by step

1. The submitting system calls `open_batch("improve-readme")`.
2. `project-m/README.md` holds `Hello`. The submitting system calls
   `replace_contents("improve-readme", "project-m/README.md", "Hello World!")`.
3. The submitting system calls `submit_batch("improve-readme")`.
4. An approver calls `approve_batch("improve-readme")`. `project-m/README.md` now holds
   `Hello World!`.

## Approval

The review app hashes the folder's content when a batch opens. An approval applies the batch
only if the folder still matches that hash.

The hash shows whether anyone edited the folder outside the batch. The folder then changes only
by the edits the submitter planned.

## Roles

Submitting and approving are two roles in oneberth.

- The roles are general: a role covers every folder and every batch.
- Roles per folder or per batch come in a later version.

## Screens

- A left panel has two entries: **Pending** and **Closed**.
- Each entry shows its batches in the main panel, with their name, their creation date and their
  status.
