# For coding agents working in this repository

Every session starts by reading these docs in full:

- [docs/specs/core.md](docs/specs/core.md)
- [docs/specs/app.md](docs/specs/app.md)
- [docs/specs/containers.md](docs/specs/containers.md)
- [docs/specs/vms.md](docs/specs/vms.md)

## Scope

FA1 is a project of its own. It takes from Robinauts only what it needs, and treats Robinauts
as a part. A new layer, dependency or abstraction needs a reason in the specs.

## Docs

- Write a rule as two short sentences, each opening with its subject: the fact, then the rule.
- State the positive alone. Add a negative only for the most common assumption.
- Use plain verbs, and at most one pronoun per clause.

## Commits and pull requests

- A commit mentions no AI: no `Co-Authored-By` line for an AI, no session link, no "generated
  with" line. The author is the developer.
- A pull request description ends with a line holding `---`, then `Generated with <tools>`, with
  no link.
