# For coding agents working in this repository

Every session starts by reading these docs in full:

- [docs/specs/core.md](docs/specs/core.md)
- [docs/specs/app.md](docs/specs/app.md)
- [docs/specs/containers.md](docs/specs/containers.md)
- [docs/specs/vms.md](docs/specs/vms.md)

A change to `workers/cursor/` reads [docs/specs/cursor-worker.md](docs/specs/cursor-worker.md)
first.

## Scope

FA1 is a project of its own. It takes from Robinauts only what it needs, and treats Robinauts
as a part. A new layer, dependency or abstraction needs a reason in the specs.

## Tests

- `cargo test --manifest-path app/Cargo.toml` runs the unit tests of the core's pure functions.
- `tests/e2e/run.sh` runs the person's journey on the real app and Docker. A change to a screen,
  an action or the Compose project runs it before it is done. A new feature adds steps to the
  journey.
- `tests/apps/run.sh` builds the interface of `apps/` and runs its backend's tests, on real git
  and outside Docker. A change to `apps/` runs it before it is done.
- `tests/workers/run.sh` runs the Cursor worker's tests on a stand-in for Cursor's CLI, then
  builds the worker's image and holds a conversation with it. A change to `workers/` runs it
  before it is done.

## Docs

- Write a rule as two short sentences, each opening with its subject: the fact, then the rule.
- State the positive alone. Add a negative only for the most common assumption.
- Use plain verbs, and at most one pronoun per clause.

## Commits and pull requests

- A commit mentions no AI: no `Co-Authored-By` line for an AI, no session link, no "generated
  with" line. The author is the developer.
- A commit is signed off by its author, with `git commit -s`.
- `scripts/check-commits.sh` checks the commits of a branch for both rules. CI runs it on every
  pull request.
- A pull request description ends with a line holding `---`, then `Generated with <tools>`, with
  no link.
