"""The worker's own settings, read from its environment: where the conversations work and how
Cursor's CLI is run. Every problem is reported at once.

Robinauts' variables (``ROBINAUTS_CONFIG``, ``ROBINAUTS_WORKER_NAME``,
``ROBINAUTS_WORKER_BROKER_URL``) are the worker module's to read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from robinauts.cli.composition import DATABASE_URL_VARIABLE

PREFIX = "FA1_CURSOR_"
WORKSPACES_VARIABLE = PREFIX + "WORKSPACES"
CLI_VARIABLE = PREFIX + "CLI"
FORCE_VARIABLE = PREFIX + "FORCE"
PARTIAL_VARIABLE = PREFIX + "PARTIAL_OUTPUT"

DEFAULT_WORKSPACES = "/workspace"
DEFAULT_CLI = "cursor-agent"


class SettingsError(Exception):
    """The environment is not this worker's: every problem, one per line."""


@dataclass(frozen=True, slots=True)
class Settings:
    workspaces: Path
    """Where each conversation gets a directory of its own, the CLI's workspace."""
    cli: str
    """The CLI's program: a name on the path, or a path."""
    force: bool
    """Whether the CLI runs every command and tool its deny list leaves (``--force``). Without
    it the CLI writes the workspace's files, runs the agent's tool servers, and rejects the
    rest: nobody answers a question from the chat."""
    partial_output: bool
    """Whether the chat gets the answer's text as it is written, or per message."""


def _flag(environ: Mapping[str, str], variable: str, default: str, problems: list[str]) -> bool:
    text = environ.get(variable, default).strip().lower()
    if text not in ("yes", "no"):
        problems.append(f"{variable} must be 'yes' or 'no'; it is {text!r}")
    return text == "yes"


def settings_from(environ: Mapping[str, str]) -> Settings:
    """The settings the environment describes; ``SettingsError`` naming every problem."""
    problems: list[str] = []
    if environ.get(DATABASE_URL_VARIABLE, "").strip():
        problems.append(
            f"{DATABASE_URL_VARIABLE} is set: this worker opens no database and reaches the"
            " server over HTTP alone"
        )
    force = _flag(environ, FORCE_VARIABLE, "no", problems)
    partial = _flag(environ, PARTIAL_VARIABLE, "yes", problems)
    if problems:
        raise SettingsError("\n".join(problems))
    return Settings(
        workspaces=Path(environ.get(WORKSPACES_VARIABLE, "").strip() or DEFAULT_WORKSPACES),
        cli=environ.get(CLI_VARIABLE, "").strip() or DEFAULT_CLI,
        force=force,
        partial_output=partial,
    )
