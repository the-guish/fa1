"""The checks of a setup folder, before a person reviews it (docs/specs/review-app.md, "Checks").

A program of its own: `python checks.py <tree>` reads the setup folder's files under `<tree>`
and prints `{"problems": [...], "summary": [...]}`. It reads the files and runs none of them.
The review app runs it in a process of its own, with two variables and no key:

    ROBINAUTS_CONFIG     the configuration that runs: FA1's fixed part, and the last setup
    ROBINAUTS_FLOWS_DIR  the flows that run, which a changed flow's version is compared with

The checks are FA1's own, of the folder's layout, then Robinauts' and neorc's, the functions
their start runs. The module imports the standard library, Robinauts and neorc, which the
control image holds.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AGENT_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
"""An agent's id, which is its file's name: as the app's own reader has it."""

QUEUE = "default"
"""The handlers' queue, which FA1's one worker serves (docs/specs/flows.md, "The format")."""
QUEUES_FILE = "flows/queues.toml"
"""neorc's file of the flows' other queues. In FA1 each is one a person answers."""

HANDLERS_RULE = "handlers use the standard library alone"


@dataclass
class Result:
    problems: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)


def table(tree: Path, name: str, into: Result) -> dict[str, Any] | None:
    """A TOML file of the tree, as its tables. A file that is missing or is not TOML is a
    problem, and `None`."""
    try:
        return tomllib.loads((tree / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        into.problems.append(f"{name}: no such file")
    except (OSError, UnicodeDecodeError) as unreadable:
        into.problems.append(f"{name}: {unreadable}")
    except tomllib.TOMLDecodeError as malformed:
        into.problems.append(f"{name}: {malformed}")
    return None


def settings(tree: Path, into: Result) -> None:
    """`fa1.toml`: the git author, as two strings."""
    found = table(tree, "fa1.toml", into)
    if found is None:
        return
    git = found.get("git", {})
    if not isinstance(git, Mapping):
        into.problems.append("fa1.toml [git]: a table")
        return
    for key in ("name", "email"):
        if key in git and not isinstance(git[key], str):
            into.problems.append(f"fa1.toml [git] {key}: a string")


def models_and_agents(tree: Path, into: Result) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """`models.toml` and `agents/<id>.toml`, as Robinauts' two tables: the agents whose files
    read. `None` without the models or without any agent: the configuration is then not
    checked."""
    found = table(tree, "models.toml", into)
    if found is None:
        return None
    for key in sorted(found.keys() - {"models"}):
        into.problems.append(f"models.toml: {key}: only [models.<id>] tables")
    held = found.get("models", {})
    if not isinstance(held, Mapping):
        into.problems.append("models.toml: [models.<id>] tables")
        return None
    models = dict(held)
    agents: dict[str, Any] = {}
    folder = tree / "agents"
    files = sorted(folder.glob("*.toml")) if folder.is_dir() else []
    for path in files:
        name = f"agents/{path.name}"
        if not AGENT_ID.fullmatch(path.stem):
            into.problems.append(
                f"{name}: an agent's file name is its id: lowercase letters, digits and -"
            )
            continue
        agent = table(tree, name, into)
        if agent is None:
            continue
        chosen = agent.get("models")
        for model in chosen if isinstance(chosen, list) else []:
            if isinstance(model, str) and model not in models:
                into.problems.append(f"{name} models: {model} is not in models.toml")
        agents[path.stem] = agent
    if not files:
        into.problems.append("agents/: no agent")
        return None
    return models, agents


def configuration(
    models: dict[str, Any], agents: dict[str, Any], deployed: Path | None, into: Result
) -> None:
    """Robinauts' own check of its configuration: FA1's fixed part, as the configuration that
    runs holds it, with the tree's models and agents."""
    if deployed is None or not deployed.is_file():
        into.summary.append("no configuration runs yet: the agents are checked at the deploy")
        return
    from robinauts.cli.composition import configure
    from robinauts.controller.contract.domain import ConfigError

    try:
        fixed = tomllib.loads(deployed.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as unreadable:
        into.summary.append(f"the configuration that runs cannot be read: {unreadable}")
        return
    tables = {key: value for key, value in fixed.items() if key not in ("models", "agents")}
    try:
        configure({**tables, "models": models, "agents": agents}, {})
    except ConfigError as refused:
        into.problems += [f"Robinauts' configuration: {line}" for line in str(refused).split("\n")]


def bound_names(module: ast.Module) -> set[str]:
    """The names a module binds at its top level: what a flow's step may name as a handler."""
    names: set[str] = set()
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def handlers(code: Path, where: str, into: Result) -> dict[str, set[str]]:
    """The handlers' modules, read and never run: by module, the names it binds. A module that
    is not Python, or that imports past the standard library and its neighbours, is a
    problem."""
    found: dict[str, set[str]] = {}
    if not code.is_dir():
        return found
    files = sorted(code.glob("*.py"))
    neighbours = {path.stem for path in files}
    for path in files:
        name = f"{where}/{path.name}"
        try:
            module = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        except SyntaxError as wrong:
            into.problems.append(f"{name}: line {wrong.lineno}: {wrong.msg}")
            continue
        except (OSError, UnicodeDecodeError, ValueError, RecursionError, MemoryError) as wrong:
            into.problems.append(f"{name}: {type(wrong).__name__}")
            continue
        found[path.stem] = bound_names(module)
        imported: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        for root in sorted(imported - neighbours - sys.stdlib_module_names):
            into.problems.append(f"{name}: imports {root}: {HANDLERS_RULE}")
    return found


def fixed_agent_and_model(
    fixed: Mapping[str, Any], models: Mapping[str, Any], agents: Mapping[str, Any]
) -> list[str]:
    """What is wrong with the agent and the model a step fixes, in `fixed_params`: Robinauts'
    handlers send both as ids, and the server refuses a pair it does not hold."""
    problems = []
    agent, model = fixed.get("agent"), fixed.get("model")
    if isinstance(agent, str) and agent not in agents:
        known = ", ".join(sorted(agents))
        problems.append(f"agent {agent!r} is not an agent of agents/ ({known})")
    if isinstance(model, str) and model not in models:
        known = ", ".join(sorted(models))
        problems.append(f"model {model!r} is not in models.toml ({known})")
    elif isinstance(model, str) and isinstance(agent, str) and agent in agents:
        allowed = agents[agent].get("models")
        allowed = [m for m in allowed if isinstance(m, str)] if isinstance(allowed, list) else []
        if model not in allowed:
            problems.append(
                f"model {model!r} is not a model of the agent {agent!r}"
                f" ({', '.join(allowed) or 'none'})"
            )
    return problems


def queues(folder: Path, into: Result) -> set[str]:
    """The queues a person answers: the external queues of `queues.toml`, as neorc reads it.
    The server declares them at its start. `default` stays the handlers' queue, and FA1 has no
    worker for another worker queue."""
    from neorc_core import NeorcError, QueueKind
    from neorc_core.flows import read_queues

    try:
        named = read_queues(folder)
    except NeorcError as refused:
        lines = getattr(refused, "problems", None) or [str(refused)]
        into.problems += [f"flows/{line}" for line in lines]
        return set()
    external = set()
    for name, kind in named.items():
        here = f"{QUEUES_FILE} [queues.{name}]"
        if name == QUEUE and kind is not QueueKind.WORKER:
            into.problems.append(f"{here}: {QUEUE!r} is the handlers' queue, of kind worker")
        elif name != QUEUE and kind is not QueueKind.EXTERNAL:
            into.problems.append(
                f"{here}: FA1 has one worker, on {QUEUE!r}: a queue a person answers has the"
                " kind external"
            )
        elif name != QUEUE:
            external.add(name)
    return external


def flows(
    tree: Path,
    deployed: Path | None,
    into: Result,
    known: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None,
) -> None:
    """The flows' folder: its settings and forms as Robinauts reads them, each flow as neorc
    reads it, each step's queue and handler, the agent and the model a step fixes, and each
    changed flow's version. `known` holds the tree's models and agents, when they read."""
    folder = tree / "flows"
    if table(tree, "flows/flows.toml", into) is None:
        return
    from neorc_core import NeorcError
    from neorc_core.flows import flow_files, load_flow_file, validate_flow_set
    from robinauts.controller.contract.domain import ConfigError
    from robinauts.orchestrator.adapters.flows_folder import read_forms, read_settings
    from robinauts.orchestrator.core.config import parse_flows_settings
    from robinauts.orchestrator.core.forms import check_forms, parse_form

    definitions = {}
    for path in flow_files(folder):
        try:
            definitions[path] = load_flow_file(path)
        except NeorcError as refused:
            lines = getattr(refused, "problems", None) or [str(refused)]
            into.problems += [f"flows/{path.name}: {line}" for line in lines]
        except (OSError, UnicodeDecodeError) as unreadable:
            into.problems.append(f"flows/{path.name}: {unreadable}")
    if len(definitions) == len(flow_files(folder)):
        try:
            validate_flow_set(definitions.values())
        except NeorcError as refused:
            lines = getattr(refused, "problems", None) or [str(refused)]
            into.problems += [f"flows/: {line}" for line in lines]

    forms = {}
    try:
        for flow, form_table in read_forms(folder).items():
            form, wrong = parse_form(flow, form_table)
            into.problems += [f"flows/: {line}" for line in wrong]
            if form is not None:
                forms[flow] = form
        declared = {
            d.name: {name: str(kind) for name, kind in d.inputs.items()}
            for d in definitions.values()
        }
        into.problems += [f"flows/: {line}" for line in check_forms(forms, declared)]
        described = parse_flows_settings(
            read_settings(folder), folder=folder, default_code=folder / "handlers", forms=forms
        )
    except ConfigError as refused:
        into.problems += [f"flows/: {line}" for line in str(refused).split("\n")]
        return

    code = described.code_location
    try:
        where = code.resolve().relative_to(tree.resolve()).as_posix()
    except ValueError:
        into.problems.append("flows/flows.toml code_location: a folder of the setup folder")
        return
    if not code.is_dir():
        into.problems.append(f"flows/flows.toml code_location: no folder at {where}")
    modules = handlers(code, where, into)
    answered = queues(folder, into)
    for path, definition in definitions.items():
        for task in definition.tasks():
            here = f"flows/{path.name}: {task.name}"
            if known is not None:
                into.problems += [
                    f"{here}: fixed_params: {line}"
                    for line in fixed_agent_and_model(task.fixed_params, *known)
                ]
            if task.queue in answered:
                # A person answers it: its handler is a text for them, and no function.
                continue
            if task.queue != QUEUE:
                into.problems.append(
                    f"{here}: queue {task.queue!r}: FA1 has the queue {QUEUE!r}, and the queues"
                    f" a person answers, which {QUEUES_FILE} names"
                )
                continue
            module, _, function = task.handler.partition(":")
            if not function:
                into.problems.append(f"{here}: handler {task.handler!r}: <module>:<function>")
            elif module not in modules:
                if not (code / f"{module}.py").is_file():
                    into.problems.append(f"{here}: handler {task.handler}: no {where}/{module}.py")
            elif function not in modules[module]:
                into.problems.append(
                    f"{here}: handler {task.handler}: {where}/{module}.py has no {function}"
                )

    running = {}
    if deployed is not None and deployed.is_dir():
        for path in flow_files(deployed):
            try:
                held = load_flow_file(path)
                running[held.name] = (held.version, uploaded(path))
            except (NeorcError, OSError, UnicodeDecodeError):
                continue
    for path, definition in definitions.items():
        if definition.name not in running:
            continue
        version, content = running[definition.name]
        same = uploaded(path) == content
        if definition.version < version:
            into.problems.append(
                f"flows/{path.name}: version {definition.version} is below {version}, the"
                " version that runs"
            )
        elif definition.version == version and not same:
            into.problems.append(
                f"flows/{path.name}: the flow changed and its version is still {version}:"
                " raise it, since the server keeps a version's first content"
            )
    listed = ", ".join(f"{d.name} {d.version}" for d in definitions.values())
    into.summary.append(f"{len(definitions)} flows: {listed}" if definitions else "no flow")
    into.summary.append(f"{len(modules)} handler modules, read and not run")
    if answered:
        into.summary.append(f"queues a person answers: {', '.join(sorted(answered))}")


def uploaded(path: Path) -> Any:
    """One flow file as the structure an upload sends, which is what a server compares."""
    from neorc_core.flows import read_flow_json, read_flow_yaml
    from neorc_core.forms import inline_form

    return inline_form(
        read_flow_yaml(path.read_text(encoding="utf-8")), path.parent, read_flow_json
    )


def check(tree: Path, config: Path | None, deployed_flows: Path | None) -> Result:
    """Every check of the setup folder under `tree`."""
    result = Result()
    settings(tree, result)
    found = models_and_agents(tree, result)
    if found is not None:
        models, agents = found
        configuration(models, agents, config, result)
        result.summary.insert(0, f"{len(agents)} agents, {len(models)} models")
    flows(tree, deployed_flows, result, found)
    return result


def main(arguments: list[str], environ: Mapping[str, str]) -> int:
    if len(arguments) != 1:
        print("usage: checks.py <the setup folder's tree>", file=sys.stderr)
        return 2
    config = environ.get("ROBINAUTS_CONFIG")
    deployed = environ.get("ROBINAUTS_FLOWS_DIR")
    result = check(
        Path(arguments[0]),
        Path(config) if config else None,
        Path(deployed) if deployed else None,
    )
    json.dump({"problems": result.problems, "summary": result.summary}, sys.stdout)
    return 0


if __name__ == "__main__":
    import os

    sys.exit(main(sys.argv[1:], os.environ))
