"""The engine: a turn is one run of Cursor's CLI in print mode; a conversation is one Cursor
chat, in a working directory of its own.

The CLI keeps the chats, under its home: ``~/.cursor/chats/<the workspace's MD5>/<chat>``. A
checkpoint names the chat, and the next turn resumes it. The CLI answers a chat it does not hold
as a new one, so the engine looks for the chat first, and refuses a turn whose chat is gone.

The CLI continues a chat from its end alone, with no fork. The engine keeps each session's
latest checkpoint in a file of its own, beside the sessions' directories, and refuses a turn
from an earlier one, which an edit or a regenerate asks for. A turn from no checkpoint starts a
new chat, as a conversation's first turn does.

``init_cursor`` is the engine's factory, registered under the ``robinauts.engines`` entry-point
group as ``cursor``. The storage it is handed is not used: the worker is handed no database.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import uuid
from collections import deque
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import Any

from robinauts.agent_engines.contract.domain import (
    AgentDefinition,
    CheckpointNotFoundError,
    EngineError,
    Event,
    ProviderKind,
    SessionExistsError,
    SessionNotFoundError,
    UnknownModelError,
)
from robinauts.agent_engines.contract.ports import (
    AgentEngine,
    EngineSettings,
    StorageConfig,
)
from robinauts_worker_common.clone import GitError
from robinauts_worker_common.tasks import TaskPayloadError, code_task_starts
from robinauts_worker_common.worktrees import Repositories

from fa1_cursor_worker import checkpoints, tools
from fa1_cursor_worker.events import Translation
from fa1_cursor_worker.functions import FunctionsServer
from fa1_cursor_worker.settings import Settings, settings_from

_log = logging.getLogger(__name__)

ENGINE = "cursor"
"""The engine's name in a configuration: ``engine = "cursor"``."""

API_KEY_VARIABLE = "CURSOR_API_KEY"
"""Where the CLI reads its key. The worker fills it from the model's provider."""

REPOSITORIES_FOLDER = "repos"
LATEST_FOLDER = ".latest"
"""Where each session's latest checkpoint is kept, under the workspaces: a file per session."""
NO_FORK = (
    "Cursor's CLI continues a chat from its end alone: an edit or a regenerate of an earlier"
    " message is not possible on this agent. Send a new message instead"
)
STOP_SECONDS = 5.0
"""How long a stopped CLI gets to end before it is killed."""
EXIT_SECONDS = 15.0
"""How long the CLI gets to exit after its result."""
LINE_LIMIT = 64 * 1024 * 1024
"""The longest line the CLI may print: a written file comes whole, in one line."""
STDERR_LINES = 20
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
"""The colours the CLI writes on its standard error."""


def cursor_home() -> Path:
    """Where the CLI keeps its state: ``.cursor`` of its home."""
    return Path.home() / ".cursor"


def chats_of(workspace: Path) -> Path:
    """The folder of a workspace's chats, one folder per chat."""
    return cursor_home() / "chats" / hashlib.md5(str(workspace).encode()).hexdigest()


def project_of(workspace: Path) -> Path:
    """The CLI's own folder for a workspace: its trust, its approvals, its transcripts."""
    return cursor_home() / "projects" / str(workspace).strip("/").replace("/", "-")


def init_cursor(settings: EngineSettings, storage: StorageConfig) -> AgentEngine:
    """The engine, with the worker's own settings read from the environment."""
    container = settings_from(os.environ)
    root = container.workspaces / REPOSITORIES_FOLDER
    return CursorEngine(settings, container, Repositories.from_environ(root))


def arguments(
    container: Settings, workspace: Path, model_name: str, chat: str | None, prompt: str
) -> list[str]:
    """The CLI's command line for one turn."""
    line = [container.cli, "--print", "--output-format", "stream-json"]
    if container.partial_output:
        line.append("--stream-partial-output")
    # Nobody answers a prompt: the workspace is trusted and the agent's tool servers approved.
    line += ["--trust", "--approve-mcps"]
    if container.force:
        line.append("--force")
    line += ["--workspace", str(workspace), "--model", model_name]
    if chat is not None:
        line.append(f"--resume={chat}")
    # A prompt that opens with a dash would read as an option.
    line.append(prompt if not prompt.startswith("-") else "\n" + prompt)
    return line


class CursorEngine(AgentEngine):
    def __init__(
        self,
        settings: EngineSettings,
        container: Settings,
        repositories: Repositories | None = None,
    ) -> None:
        self._settings = settings
        self._container = container
        self._repositories = repositories
        self._functions = FunctionsServer()

    def kinds(self) -> frozenset[ProviderKind]:
        # The CLI reaches Cursor alone, whatever kind its provider's table names.
        return frozenset(ProviderKind)

    def workspace(self, session_id: uuid.UUID) -> Path:
        return self._container.workspaces / str(session_id)

    def latest(self, session_id: uuid.UUID) -> Path:
        """The file that holds the session's latest checkpoint: the one its chat ends on."""
        return self._container.workspaces / LATEST_FOLDER / str(session_id)

    async def setup(self) -> None:
        self._container.workspaces.mkdir(parents=True, exist_ok=True)

    async def create(self, session_id: uuid.UUID) -> None:
        workspace = self.workspace(session_id)
        if workspace.exists():
            raise SessionExistsError(f"session {session_id} exists")
        workspace.mkdir(parents=True)

    async def exists(self, session_id: uuid.UUID) -> bool:
        return self.workspace(session_id).is_dir()

    def stream(
        self,
        session_id: uuid.UUID,
        agent: AgentDefinition,
        prompt: str,
        *,
        model: str,
        checkpoint_id: str | None,
        timeout_seconds: float,
        resume: bool = False,
        task_payload: Mapping[str, Any] | None = None,
    ) -> AsyncGenerator[Event, None]:
        return self._stream(
            session_id, agent, prompt, model, checkpoint_id, timeout_seconds, task_payload
        )

    async def _stream(
        self,
        session_id: uuid.UUID,
        agent: AgentDefinition,
        prompt: str,
        model: str,
        checkpoint_id: str | None,
        timeout_seconds: float,
        task_payload: Mapping[str, Any] | None,
    ) -> AsyncGenerator[Event, None]:
        workspace = self.workspace(session_id)
        if not workspace.is_dir():
            raise SessionNotFoundError(f"session {session_id} was not created")
        model_config = self._settings.models.models.get(model)
        if model_config is None:
            raise UnknownModelError(f"model {model!r} is not configured")
        chat = None if checkpoint_id is None else checkpoints.decode(checkpoint_id).chat
        latest = self.latest(session_id)
        if chat is not None and latest.is_file() and latest.read_text() != checkpoint_id:
            raise EngineError(NO_FORK)
        if chat is not None and not (chats_of(workspace) / chat).is_dir():
            raise CheckpointNotFoundError(
                f"the Cursor chat {chat} of checkpoint {checkpoint_id!r} is gone"
            )
        known = () if self._repositories is None else self._repositories.repositories
        try:
            starts = code_task_starts(task_payload, known)
        except TaskPayloadError as refused:
            raise EngineError(str(refused)) from None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        if self._repositories is not None:
            # Before the agent: the session's worktrees, decided at its first turn.
            try:
                async with asyncio.timeout_at(deadline):
                    await self._repositories.add_worktrees(
                        str(session_id), workspace, starts=starts, first=checkpoint_id is None
                    )
            except GitError as failed:
                raise EngineError(str(failed)) from None
        key = self._settings.keys.key_for(model_config.provider)
        translation = Translation(partial=self._container.partial_output)
        async with self._functions.serving(agent.functions) as functions_url:
            environment = {
                **os.environ,
                **tools.write(
                    workspace,
                    agent,
                    self._settings.models,
                    self._settings.tool_secrets,
                    functions_url,
                ),
                API_KEY_VARIABLE: key,
                "NO_COLOR": "1",
            }
            line = arguments(self._container, workspace, model_config.name, chat, prompt)
            try:
                process = await asyncio.create_subprocess_exec(
                    *line,
                    cwd=workspace,
                    env=environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=LINE_LIMIT,
                    start_new_session=True,
                )
            except OSError as error:
                raise EngineError(f"Cursor's CLI did not start: {error}") from None
            said: deque[str] = deque(maxlen=STDERR_LINES)
            listening = asyncio.create_task(_collect(process.stderr, said))
            try:
                assert process.stdout is not None
                while translation.result is None:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError
                    try:
                        raw = await asyncio.wait_for(process.stdout.readline(), remaining)
                    except TimeoutError:
                        raise TimeoutError from None
                    if not raw:
                        break
                    try:
                        parsed = json.loads(raw)
                    except ValueError:
                        _log.debug("cursor: %s", raw[:200])
                        continue
                    if isinstance(parsed, Mapping):
                        for event in translation.translate(parsed):
                            yield event
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), EXIT_SECONDS)
            finally:
                await _stop(process)
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(listening, STOP_SECONDS)
        failure = translation.failure()
        if failure is not None:
            # The CLI says why on its standard error, and ends with a code that is not 0.
            heard = ANSI.sub("", " ".join(text for text in said if text)).replace(
                key, "[the key]"
            )
            code = process.returncode
            _log.warning("Cursor's CLI ended a turn badly, with code %s", code)
            raise EngineError(f"{failure} (exit code {code}): {heard}" if heard else failure)
        if translation.chat is None:
            raise EngineError("Cursor's CLI answered without naming its chat")
        if chat is not None and translation.chat != chat:
            _log.warning("the CLI answered in chat %s, asked to resume %s", translation.chat, chat)
        ended = checkpoints.encode(checkpoints.new(translation.chat))
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(ended)
        yield translation.done(ended)

    async def fork(self, source_id: uuid.UUID, target_id: uuid.UUID, *, checkpoint_id: str) -> None:
        raise NotImplementedError("the platform forks sessions by checkpoint, at the next turn")

    async def forget(self, session_id: uuid.UUID) -> None:
        workspace = self.workspace(session_id)
        if self._repositories is not None:
            try:
                await self._repositories.remove_worktrees(str(session_id), workspace)
            except GitError as failed:
                _log.warning("the worktrees of session %s were not removed: %s", session_id, failed)
        self.latest(session_id).unlink(missing_ok=True)
        shutil.rmtree(chats_of(workspace), ignore_errors=True)
        shutil.rmtree(project_of(workspace), ignore_errors=True)
        shutil.rmtree(workspace, ignore_errors=True)

    async def close(self) -> None:
        await self._functions.close()


async def _collect(stream: asyncio.StreamReader | None, into: deque[str]) -> None:
    """Reads the CLI's standard error to its end, and keeps its last lines."""
    if stream is None:
        return
    while True:
        try:
            raw = await stream.readline()
        except ValueError:
            continue
        if not raw:
            return
        into.append(raw.decode(errors="replace").strip())


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Ends the CLI and the commands it started, when it still runs: a signal to its group, a
    bounded wait, then a kill."""
    if process.returncode is not None:
        # A command the CLI left running ends with the turn.
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signal.SIGKILL)
        return
    for signum in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(OSError):
            os.killpg(process.pid, signum)
        try:
            await asyncio.wait_for(asyncio.shield(process.wait()), STOP_SECONDS)
            return
        except (TimeoutError, asyncio.CancelledError):
            continue
