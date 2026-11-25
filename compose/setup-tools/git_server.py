"""The designer's git server: the reference MCP git server, with one tool of FA1's own.

The reference server cannot remove a file, and neither can the filesystem server. A flow or an
agent that the person no longer wants must go from the setup folder too. `git_rm` removes files
from the working copy and stages their removal. The removal reaches the setup folder only as a
commit of a changelist that the person approves (docs/specs/review-app.md).

The tool opens the repository as the reference server's own tools do, so the same confinement to
the working copy and the same hardening apply. It runs under the same lock.
"""

import asyncio
import sys
from pathlib import Path
from typing import Annotated

import git
from mcp_server_git import server as reference
from pydantic import Field


def git_rm(repo: git.Repo, paths: list[str]) -> str:
    """Removes tracked files and folders from the working tree and the index."""
    root = Path(repo.working_dir).resolve()
    for path in paths:
        try:
            resolved = (root / path).resolve()
        except (OSError, RuntimeError):
            raise ValueError(f"Invalid path: '{path}'")
        if resolved == root:
            raise ValueError("The whole repository cannot be removed. Name files or folders.")
        try:
            inside = resolved.relative_to(root)
        except ValueError:
            raise ValueError(f"Path '{path}' is outside the repository '{root}'")
        if inside.parts[0] == ".git":
            raise ValueError(f"Path '{path}' is inside .git")
    # A file with changes that are not committed stays, and git says so: commit or reset first.
    removed = repo.git.rm("-r", "--", *paths)
    return f"Removed and staged:\n{removed}" if removed else "Nothing was removed."


def create_server(repository: Path | None) -> reference.MCPServer:
    server = reference.create_server(repository)

    def open_repo(repo_path: str) -> git.Repo:
        # The reference server's own `open_repo`, which it keeps inside `create_server`.
        path = Path(repo_path)
        reference.validate_repo_path(path, repository)
        repo = git.Repo(path)
        try:
            reference.harden_repo(repo)
            reference.validate_opened_repo(repo, path, repository)
        except Exception:
            repo.close()
            raise
        return repo

    @server.tool(
        name="git_rm",
        description=(
            "Removes files or folders from the working tree and stages their removal, like "
            "`git rm -r`. Paths are relative to the repository. A file with changes that are "
            "not committed is refused. git_commit records the removal."
        ),
        annotations=reference.writes(destructive=True, idempotent=False),
        structured_output=False,
    )
    @reference.reports_failures
    def rm(repo_path: str, paths: Annotated[list[str], Field(min_length=1)]) -> str:
        return git_rm(open_repo(repo_path), paths)

    return server


def main(arguments: list[str]) -> None:
    if len(arguments) != 2 or arguments[0] != "--repository":
        sys.exit("usage: git_server.py --repository <path>")
    repository = Path(git.Repo(arguments[1], search_parent_directories=True).working_dir)
    asyncio.run(reference.run(create_server(repository), "stdio"))


if __name__ == "__main__":
    main(sys.argv[1:])
