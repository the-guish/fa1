# Setup folder

Everything permanent about how I work with FA1: its settings, the agents, the models, the
knowledge and the flows. FA1 reads this folder at each start; **Refresh** on its Status screen
pulls it and deploys it. Keys are never here: FA1 keeps them in its own folder.

| path | holds |
|---|---|
| `fa1.toml` | FA1's settings: the git author of the agents' commits |
| `models.toml` | the models the agents may use: `[models.<id>]` |
| `agents/<id>.toml` | one agent each: title, engine, models, tools, instructions |
| `knowledge/` | Markdown the agents read: how I work, my projects, my conventions |
| `flows/` | reusable flows: neorc YAML, their handlers, `flows.toml` |

Agents change this folder through pull requests: they clone this repository, push a branch and
open a PR. I merge it on GitHub, then press Refresh.
