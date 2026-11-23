"""The worker's process, ``python -m fa1_cursor_worker``: the image's command.

The worker is Robinauts' own worker module, ``robinauts.cli.worker_process``, with the engine
``cursor`` plugged in through its entry point. This module runs in front of it, to check what
that module cannot know: that the configuration gives this worker agents on its engine, that
each of their models has its key, that the CLI is here, and what every extra worker checks
(the GitHub token and the flows' repositories). It says every problem at once on its standard
error and exits 2, before the worker's token is read.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from robinauts.cli.composition import load
from robinauts.cli.worker_process import BROKER_URL_VARIABLE, WORKER_URL_VARIABLE, worker_name
from robinauts.cli.worker_process import main as run_worker
from robinauts.controller.contract.domain import ConfigError
from robinauts.shared_domain.domain import Config
from robinauts_worker_common.__main__ import problems_of as shared_problems

from fa1_cursor_worker.engine import ENGINE
from fa1_cursor_worker.settings import SettingsError, settings_from

CONFIG_VARIABLE = "ROBINAUTS_CONFIG"


def environment_problems(environ: Mapping[str, str]) -> list[str]:
    """The supervisor's variables the worker module cannot start without."""
    problems = []
    if not environ.get(CONFIG_VARIABLE, "").strip():
        problems.append(f"{CONFIG_VARIABLE} is not set: the configuration the server reads too")
    if not any(environ.get(v, "").strip() for v in (WORKER_URL_VARIABLE, BROKER_URL_VARIABLE)):
        problems.append(f"{BROKER_URL_VARIABLE} is not set: the server's worker listener")
    return problems


def configuration_problems(name: str, config: Config, environ: Mapping[str, str]) -> list[str]:
    """What the configuration says against running this worker here."""
    problems = []
    if name not in config.workers():
        problems.append(f"no agent of the configuration names worker {name!r}")
    agents = config.for_worker(name).agents.values()
    for agent in agents:
        if agent.engine != ENGINE:
            problems.append(
                f"agent {agent.id!r} runs on engine {agent.engine!r}, and this worker runs"
                f" {ENGINE!r} alone: give it another worker"
            )
    providers = sorted({config.models[m].provider for agent in agents for m in agent.models})
    for provider_id in providers:
        variable = config.providers[provider_id].api_key_env
        if not environ.get(variable, "").strip():
            problems.append(
                f"the Cursor API key of provider {provider_id!r} is read from {variable}, which"
                " is unset or empty"
            )
    return problems


def problems_of(environ: Mapping[str, str]) -> list[str]:
    """Everything that keeps this worker from starting: one line each."""
    problems = environment_problems(environ) + shared_problems(environ)
    try:
        settings = settings_from(environ)
    except SettingsError as refused:
        problems.extend(str(refused).splitlines())
    else:
        if shutil.which(settings.cli, path=environ.get("PATH")) is None:
            problems.append(f"Cursor's CLI, {settings.cli!r}, is not on this worker's path")
    if problems:
        return problems
    try:
        config, _ = load(Path(environ[CONFIG_VARIABLE]), environ)
    except (ConfigError, OSError, ValueError) as refused:
        return [f"{CONFIG_VARIABLE}: {refused}"]
    return configuration_problems(worker_name(environ), config, environ)


def main() -> int:
    problems = problems_of(os.environ)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    run_worker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
