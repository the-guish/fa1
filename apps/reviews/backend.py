"""Reviews: an application of FA1, beside Robinauts and neorc (docs/specs/review-app.md).

A changelist is a branch of the setup folder that a submitter asks a person to review. The
review app fetches the branch from the designer's working copy into the setup folder's own
repository, pins the commit, checks it, and shows its changes. An approver's yes fast-forwards
the setup folder to that commit.

`reviews` below gives the component, which ../backend.py composes. The records are in
`reviews.db`, in the control plane's data directory, beside `robinauts.db`. The repository is
the setup folder, which the control plane mounts. The module imports the standard library,
FastAPI and oneberth, and runs `git`, which the control image holds.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter
from oneberth.identity import Role, RoleTable
from oneberth.web import Component, Context, permit
from pydantic import BaseModel, Field

log = logging.getLogger("fa1.reviews")

NAME = "reviews"
FILE_NAME = "reviews.db"
WORK_FOLDER = "reviews"
"""The review app's own folder, in the data directory: its temporary trees."""

READ = "reviews/changelists:read"
SUBMIT = "reviews/changelists:submit"
APPROVE = "reviews/changelists:approve"

SUBMITTER = "reviews/submitter"
APPROVER = "reviews/approver"

ROLES = RoleTable(
    app=NAME,
    permissions=frozenset({READ, SUBMIT, APPROVE}),
    roles=(
        Role(SUBMITTER, frozenset({READ, SUBMIT}), people=True),
        Role(APPROVER, frozenset({READ, APPROVE}), people=True),
    ),
    default=APPROVER,
)
"""Two general roles for people. The local user holds both, since a person may hold either."""

SUBMITTED, APPROVED, REJECTED = "submitted", "approved", "rejected"
PENDING = (SUBMITTED,)
CLOSED = (APPROVED, REJECTED)

SCHEMA_VERSION = 3
SCHEMA = """
CREATE TABLE changelists (
    name TEXT PRIMARY KEY,
    branch TEXT NOT NULL,
    commit_id TEXT NOT NULL,
    base TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted', 'approved', 'rejected')),
    created_at TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    closed_at TEXT
) STRICT;
"""
BEFORE = ("reviews", "files", "baselines", "changelists", "folders")
"""The tables of the schema versions 1 and 2. At version 1 the file held a list of reviews, or
changelists with copies of files, and at version 2 a changelist's commit was in a repository of
the review app's own. No release had them, so a file at either version starts again."""

BUSY_SECONDS = 10.0
"""How long a statement waits for a lock, as Robinauts' own file does."""

GIT_SECONDS = 60.0
"""How long one git command may take."""
CHECK_SECONDS = 60.0
"""How long the checks of one tree may take."""

MOST_FILES = 300
"""The most files a changelist changes: a person reads each one."""
MOST_BYTES = 1_000_000
"""The most bytes of a file a changelist adds or changes, and of a file the checks read."""
MOST_TREE_FILES = 5_000
"""The most files of a tree the checks are given."""
MOST_TITLE = 200
MOST_DESCRIPTION = 10_000

CHANGELIST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
MAIN = "HEAD"
"""The commit a changelist starts from: the one the setup folder is at."""
BRANCHES = "refs/heads/changelists/"
"""Where a changelist shows in the setup folder: the branch `changelists/<name>`, which
`git branch` lists. The record holds the commit a person reviews, whatever the branch does."""
BEFORE_BRANCH_REFS = "refs/changelists/"
"""Where a changelist's commit was named before it was a branch."""

STEERING = frozenset({".gitattributes", ".gitmodules", ".lfsconfig"})
"""Files that steer git on the person's computer. A changelist changes none of them."""
FILE_MODES = frozenset({"100644", "100755"})
"""A plain file's two modes. A link, and a repository inside the repository, have others."""

NO_MAIN = (
    "the setup folder has no commit yet, so a changelist has nothing to start from: the person"
    " commits the setup folder first"
)
NOT_ON_MAIN = (
    "branch {branch!r} does not start from the commit the setup folder is at: check it out,"
    " merge main into it with git_merge, and submit it again"
)
MAIN_MOVED = (
    "the setup folder moved since changelist {name!r} was submitted, so it is not applied: the"
    " submitter merges main into {branch!r} and submits it again"
)
HAS_CHANGES = (
    "the setup folder has changes not yet committed, so changelist {name!r} is not applied:"
    " commit them or put them aside, then approve again"
)

GIT_SETTINGS = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
    ("protocol.ext.allow", "never"),
)
"""What git is told on each command, over the setup folder's own settings: no program the
folder's settings name runs in the control plane."""


class ReviewsError(Exception):
    """A file of records that reviews refuses. oneberth ends the start with its sentence."""


class Invalid(ValueError):
    """A request whose values the review app refuses."""


class Refused(Invalid):
    """A branch the review app does not take: each problem is a line."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


class NotFound(LookupError):
    """A changelist or a branch the review app does not find."""


class Conflict(RuntimeError):
    """A request the changelist's state, or main's, refuses."""


class GitFailed(RuntimeError):
    """A git command that failed, with what it wrote to its standard error."""


class Submitted(BaseModel):
    name: str
    branch: str
    title: str = Field(default="", max_length=MOST_TITLE)
    description: str = Field(default="", max_length=MOST_DESCRIPTION)


class Named(BaseModel):
    changelist_name: str


@dataclass(frozen=True)
class Change:
    """One file a commit changes from its base."""

    path: str
    status: Literal["added", "changed", "deleted"]
    old: str | None
    """The blob before, `None` for an added file."""
    new: str | None
    """The blob after, `None` for a deleted file."""
    mode: str
    """The mode after, all zeros for a deleted file."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def plain_path(text: str) -> bool:
    """Whether `text` is a relative path of plain segments, as a person can read it."""
    path = PurePosixPath(text)
    return (
        bool(text)
        and text == str(path)
        and not path.is_absolute()
        and all(part not in ("", ".", "..") for part in path.parts)
        and "\\" not in text
        and text.isprintable()
    )


def snapshot(source: Path, into: Path) -> int:
    """Copies the plain files under `source` into `into`, and answers how many. A link is left
    out, and so are `.git`, a file over `MOST_BYTES` and what is past `MOST_TREE_FILES`. Each
    folder is opened from its parent, without following a link, so a folder swapped for a link
    during the copy leads nowhere."""
    copied = 0

    def copy(folder: int, target: Path, top: bool) -> None:
        nonlocal copied
        with os.scandir(folder) as entries:
            names = sorted((entry.name, entry.is_dir(follow_symlinks=False)) for entry in entries)
        for name, is_folder in names:
            if copied >= MOST_TREE_FILES or (top and name == ".git"):
                continue
            flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if is_folder else 0)
            try:
                opened = os.open(name, flags, dir_fd=folder)
            except OSError:
                continue
            try:
                if is_folder:
                    (target / name).mkdir(parents=True, exist_ok=True)
                    copy(opened, target / name, False)
                    continue
                found = os.fstat(opened)
                if not stat.S_ISREG(found.st_mode) or found.st_size > MOST_BYTES:
                    continue
                with os.fdopen(os.dup(opened), "rb") as file:
                    (target / name).write_bytes(file.read(MOST_BYTES + 1))
                copied += 1
            finally:
                os.close(opened)

    into.mkdir(parents=True, exist_ok=True)
    try:
        root = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    except OSError:
        return 0
    try:
        copy(root, into, True)
    finally:
        os.close(root)
    return copied


class Reviews:
    """The records and the setup folder, behind one lock."""

    def __init__(
        self,
        data_dir: Path,
        *,
        work: Path,
        setup: Path,
        config: Path | None = None,
        flows: Path | None = None,
    ) -> None:
        self.file = data_dir / FILE_NAME
        self.home = data_dir / WORK_FOLDER
        self.work = work
        """The designer's working copy of the setup folder, which the review app fetches
        branches from and never runs git in."""
        self.setup = setup
        """The person's setup folder, a git repository. A submit pins a commit in it, and an
        approval fast-forwards it."""
        self.config = config
        self.flows = flows
        self.lock = threading.RLock()

    # The store.

    def set_up(self) -> None:
        """Makes the file and its schema, or checks the version of the file found.

        The tables and the version are one transaction. A start that is cut between the two
        leaves the file as it was, and the next start makes it again."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(exist_ok=True)
        # Python's own mode opens no transaction for a `CREATE TABLE`, so this connection opens
        # its transaction itself.
        with closing(sqlite3.connect(self.file, timeout=BUSY_SECONDS, isolation_level=None)) as (
            connection
        ):
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                found = connection.execute("PRAGMA user_version").fetchone()[0]
                if found == 0:
                    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                    held = sorted(row[0] for row in rows)
                    if held:
                        raise ReviewsError(
                            f"{self.file} holds tables and no schema version ({', '.join(held)}):"
                            " this build of reviews did not make it. Move it away and start again"
                        )
                if found < SCHEMA_VERSION:
                    for old in BEFORE:
                        connection.execute(f"DROP TABLE IF EXISTS {old}")
                    connection.execute(SCHEMA)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                elif found != SCHEMA_VERSION:
                    raise ReviewsError(
                        f"{self.file} is at schema version {found}, and this build of reviews"
                        f" needs {SCHEMA_VERSION}"
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        # The repository the review app kept for itself, before it used the setup folder's.
        shutil.rmtree(self.home / "setup.git", ignore_errors=True)
        # A changelist named outside the branches becomes a branch.
        listed = self.git(
            "for-each-ref", "--format=%(objectname) %(refname)", BEFORE_BRANCH_REFS, check=False
        )
        for line in listed.decode("utf-8", "replace").splitlines():
            commit, _, old = line.partition(" ")
            name = old.removeprefix(BEFORE_BRANCH_REFS)
            if self.rev(BRANCHES + name) is None:
                self.git("update-ref", BRANCHES + name, commit, check=False)
            self.git("update-ref", "-d", old, check=False)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.file, timeout=BUSY_SECONDS)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self.lock, closing(self.connect()) as connection, connection:
            yield connection

    # git, in the setup folder.

    def run_git(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        """Runs git in the setup folder, as FA1, with `GIT_SETTINGS` over the folder's own
        settings and no other configuration."""
        environ = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "FA1",
            "GIT_AUTHOR_EMAIL": "fa1@localhost",
            "GIT_COMMITTER_NAME": "FA1",
            "GIT_COMMITTER_EMAIL": "fa1@localhost",
            "GIT_CONFIG_COUNT": str(len(GIT_SETTINGS)),
            "LC_ALL": "C",
        }
        for at, (key, value) in enumerate(GIT_SETTINGS):
            environ[f"GIT_CONFIG_KEY_{at}"] = key
            environ[f"GIT_CONFIG_VALUE_{at}"] = value
        try:
            return subprocess.run(
                ["git", "-C", str(self.setup), *arguments],
                env=environ,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=GIT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as slow:
            raise GitFailed(f"git {arguments[0]} took over {GIT_SECONDS:.0f} seconds") from slow

    def git(self, *arguments: str, check: bool = True) -> bytes:
        """The standard output of git in the setup folder, or `GitFailed`."""
        done = self.run_git(*arguments)
        if check and done.returncode != 0:
            raise GitFailed(done.stderr.decode("utf-8", "replace").strip())
        return done.stdout

    def rev(self, name: str) -> str | None:
        """The commit `name` is at, `None` for a name that is at none."""
        found = self.git("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}", check=False)
        return found.decode().strip() or None

    def descends(self, commit: str, ancestor: str) -> bool:
        """Whether `ancestor` is `commit` or one of its ancestors."""
        return self.run_git("merge-base", "--is-ancestor", ancestor, commit).returncode == 0

    def changes(self, base: str, commit: str) -> list[Change]:
        """The files `commit` changes from `base`. A renamed file is one deleted and one
        added."""
        raw = self.git(
            "diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-abbrev", base, commit
        )
        fields = raw.decode("utf-8", "surrogateescape").split("\0")
        found = []
        for head, path in zip(fields[0::2], fields[1::2], strict=False):
            _, mode, old, new, status = head.lstrip(":").split(" ")
            found.append(
                Change(
                    path=path,
                    status="added" if status == "A" else "deleted" if status == "D" else "changed",
                    old=None if status == "A" else old,
                    new=None if status == "D" else new,
                    mode=mode,
                )
            )
        return found

    def text(self, blob: str | None) -> str | None:
        """A blob as text a person reads. One over `MOST_BYTES` is a line that says so."""
        if blob is None:
            return None
        size = int(self.git("cat-file", "-s", blob).decode().strip())
        if size > MOST_BYTES:
            return f"(a file of {size} bytes, too large to show)\n"
        return self.git("cat-file", "blob", blob).decode("utf-8", "replace")

    def rules(self, changes: list[Change]) -> list[str]:
        """What stops a person from reading a changelist whole, or reaches past the setup
        folder's files once applied."""
        if len(changes) > MOST_FILES:
            return [
                f"the branch changes {len(changes)} files, and a changelist {MOST_FILES} at most"
            ]
        problems = []
        for change in changes:
            if not plain_path(change.path):
                problems.append(f"{change.path!r}: a path of plain, printable segments")
                continue
            if PurePosixPath(change.path).name in STEERING:
                problems.append(
                    f"{change.path}: a file that steers git, which no changelist changes"
                )
            if change.new is None:
                continue
            if change.mode not in FILE_MODES:
                problems.append(
                    f"{change.path}: a link or a repository, and a changelist holds plain files"
                )
                continue
            size = int(self.git("cat-file", "-s", change.new).decode().strip())
            if size > MOST_BYTES:
                problems.append(
                    f"{change.path}: {size} bytes, over the {MOST_BYTES} a person reviews"
                )
                continue
            content = self.git("cat-file", "blob", change.new)
            try:
                if "\0" in content.decode("utf-8"):
                    raise ValueError
            except ValueError:
                problems.append(
                    f"{change.path}: not text, and every file of the setup folder is text"
                )
        return problems

    def export(self, commit: str, into: Path) -> None:
        """Writes the plain files of `commit` under `into`, as the checks read them."""
        listed = self.git("ls-tree", "-r", "-z", commit).decode("utf-8", "surrogateescape")
        written = 0
        for entry in filter(None, listed.split("\0")):
            head, path = entry.split("\t", 1)
            mode, kind, blob = head.split(" ")
            if kind != "blob" or mode not in FILE_MODES or not plain_path(path):
                continue
            if written >= MOST_TREE_FILES:
                break
            if int(self.git("cat-file", "-s", blob).decode().strip()) > MOST_BYTES:
                continue
            target = into / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.git("cat-file", "blob", blob))
            written += 1

    # The checks.

    def checked(self, tree: Path) -> tuple[list[str], list[str]]:
        """The problems and the summary of the setup folder under `tree`, from checks.py in a
        process of its own, which is handed no key."""
        program = Path(__file__).with_name("checks.py")
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1"}
        if self.config is not None:
            environ["ROBINAUTS_CONFIG"] = str(self.config)
        if self.flows is not None:
            environ["ROBINAUTS_FLOWS_DIR"] = str(self.flows)
        try:
            done = subprocess.run(
                [sys.executable, str(program), str(tree)],
                env=environ,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=CHECK_SECONDS,
                check=False,
            )
            answer = json.loads(done.stdout)
            return [str(p) for p in answer["problems"]], [str(s) for s in answer["summary"]]
        except subprocess.TimeoutExpired:
            return [f"the checks took over {CHECK_SECONDS:.0f} seconds"], []
        except (ValueError, KeyError, TypeError):
            log.warning(
                "the checks ended without an answer: %s", done.stderr.decode("utf-8", "replace")
            )
            return ["the checks did not finish, so the setup folder is not checked"], []

    @contextmanager
    def tree(self) -> Iterator[Path]:
        """A temporary folder of the review app's own, gone at the end."""
        folder = Path(tempfile.mkdtemp(prefix="tree-", dir=self.home))
        try:
            yield folder
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def validate_setup(self) -> tuple[list[str], list[str]]:
        """The checks of the working copy as it is now, committed or not."""
        if not self.work.is_dir():
            return [f"the working copy is not there yet: {self.work}"], []
        with self.tree() as folder:
            snapshot(self.work, folder)
            return self.checked(folder)

    # Changelists.

    def changelists(self, state: Literal["pending", "closed"]) -> list[dict[str, Any]]:
        statuses = PENDING if state == "pending" else CLOSED
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT name, title, branch, commit_id, status, created_at, submitted_at"
                f" FROM changelists WHERE status IN ({', '.join('?' * len(statuses))})"
                " ORDER BY submitted_at DESC, name",
                statuses,
            ).fetchall()
        return [self.listed(row) for row in rows]

    def listed(self, row: sqlite3.Row) -> dict[str, Any]:
        found = dict(row)
        found["commit"] = found.pop("commit_id")
        found["applied"] = self.applied(found["status"], found["commit"])
        return found

    def applied(self, status: str, commit: str) -> bool:
        """Whether the setup folder holds an approved changelist's commit."""
        main = self.rev(MAIN)
        return status == APPROVED and main is not None and self.descends(main, commit)

    def row(self, connection: sqlite3.Connection, name: str) -> sqlite3.Row:
        found = connection.execute("SELECT * FROM changelists WHERE name = ?", (name,)).fetchone()
        if found is None:
            raise NotFound(f"no changelist is named {name!r}")
        return found  # type: ignore[no-any-return]

    def changelist(self, name: str) -> dict[str, Any]:
        """A changelist, with each file's old and new version."""
        with closing(self.connect()) as connection:
            row = self.row(connection, name)
        found = self.listed(row)
        found["summary"] = json.loads(found["summary"])
        found["files"] = [
            {
                "path": change.path,
                "status": change.status,
                "old": self.text(change.old),
                "new": self.text(change.new),
            }
            for change in self.changes(row["base"], row["commit_id"])
        ]
        return found

    def submit(
        self, name: str, branch: str, title: str = "", description: str = ""
    ) -> dict[str, Any]:
        """Fetches `branch` from the working copy, pins its commit as the changelist `name`,
        and checks it. A changelist that is submitted or rejected takes the new commit."""
        if not CHANGELIST_NAME.fullmatch(name) or ".." in name or name.endswith((".", ".lock")):
            raise Invalid(
                f"{name!r} is not a changelist name: letters, digits, '.', '_' and '-', up to 100"
            )
        if (
            not BRANCH_NAME.fullmatch(branch)
            or ".." in branch
            or "//" in branch
            or branch.endswith(("/", ".lock"))
        ):
            raise Invalid(f"{branch!r} is not a branch name")
        title = " ".join(title.split()) or name
        if len(title) > MOST_TITLE or len(description) > MOST_DESCRIPTION:
            raise Invalid(
                f"a title holds {MOST_TITLE} characters at most, and a description"
                f" {MOST_DESCRIPTION}"
            )
        with self.writing() as connection:
            main = self.rev(MAIN)
            if main is None:
                raise Conflict(NO_MAIN)
            before = connection.execute(
                "SELECT status, created_at FROM changelists WHERE name = ?", (name,)
            ).fetchone()
            if before is not None and before["status"] == APPROVED:
                raise Conflict(
                    f"changelist {name!r} is approved: give the next change another name"
                )
            shown = BRANCHES + name
            if self.git("symbolic-ref", "--quiet", "HEAD", check=False).decode().strip() == shown:
                raise Conflict(
                    f"the setup folder has the branch changelists/{name} checked out: the person"
                    " checks out another branch, then the submit goes through"
                )
            incoming = f"refs/incoming/{name}"
            try:
                self.git(
                    "-c", "fetch.fsckObjects=true",
                    "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
                    "--no-write-fetch-head", str(self.work),
                    f"+refs/heads/{branch}:{incoming}",
                )  # fmt: skip
            except GitFailed as failed:
                if "couldn't find remote ref" in str(failed):
                    raise NotFound(
                        f"the working copy has no branch {branch!r}: create it and commit on it"
                    ) from failed
                log.warning("branch %s was not fetched: %s", branch, failed)
                raise Conflict(
                    f"branch {branch!r} could not be fetched from the working copy"
                ) from failed
            try:
                commit = self.rev(incoming)
                if commit is None or commit == main:
                    raise Conflict(
                        f"branch {branch!r} holds no change: it is at the setup folder's commit"
                    )
                if not self.descends(commit, main):
                    raise Conflict(NOT_ON_MAIN.format(branch=branch))
                problems = self.rules(self.changes(main, commit))
                summary: list[str] = []
                if not problems:
                    with self.tree() as folder:
                        self.export(commit, folder)
                        problems, summary = self.checked(folder)
                if problems:
                    raise Refused(problems)
                try:
                    self.git("update-ref", shown, commit)
                except GitFailed as failed:
                    raise Conflict(
                        f"the setup folder did not take the branch changelists/{name}: {failed}"
                    ) from failed
            finally:
                self.git("update-ref", "-d", incoming, check=False)
            stamp = now()
            created = before["created_at"] if before is not None else stamp
            connection.execute(
                "INSERT INTO changelists (name, branch, commit_id, base, title, description,"
                " summary, status, created_at, submitted_at, closed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)"
                " ON CONFLICT (name) DO UPDATE SET branch = excluded.branch,"
                " commit_id = excluded.commit_id, base = excluded.base, title = excluded.title,"
                " description = excluded.description, summary = excluded.summary,"
                " status = excluded.status, submitted_at = excluded.submitted_at,"
                " closed_at = NULL",
                (name, branch, commit, main, title, description, json.dumps(summary),
                 SUBMITTED, created, stamp),
            )  # fmt: skip
        return {"name": name, "status": SUBMITTED, "commit": commit, "summary": summary}

    def submitted(self, connection: sqlite3.Connection, name: str, what: str) -> sqlite3.Row:
        row = self.row(connection, name)
        if row["status"] != SUBMITTED:
            raise Conflict(f"changelist {name!r} is {row['status']}: {what} needs a submitted one")
        return row

    def approve(self, name: str) -> dict[str, Any]:
        """Fast-forwards the setup folder to the changelist's commit. The folder is still at
        one of that commit's ancestors, and holds no change of its own."""
        with self.writing() as connection:
            row = self.submitted(connection, name, "an approval")
            main = self.rev(MAIN)
            if main is None or not self.descends(row["commit_id"], main):
                raise Conflict(MAIN_MOVED.format(name=name, branch=row["branch"]))
            if self.git("status", "--porcelain", "--untracked-files=no").strip():
                raise Conflict(HAS_CHANGES.format(name=name))
            try:
                self.git("merge", "--quiet", "--ff-only", row["commit_id"])
            except GitFailed as failed:
                raise Conflict(
                    f"the setup folder did not take changelist {name!r}: {failed}"
                ) from failed
            # The folder's own branch holds the commit now. The changelist's branch goes,
            # unless the person moved it.
            self.git("update-ref", "-d", BRANCHES + name, row["commit_id"], check=False)
            connection.execute(
                "UPDATE changelists SET status = ?, closed_at = ? WHERE name = ?",
                (APPROVED, now(), name),
            )
        return {"name": name, "status": APPROVED}

    def reject(self, name: str) -> dict[str, Any]:
        with self.writing() as connection:
            self.submitted(connection, name, "a rejection")
            connection.execute(
                "UPDATE changelists SET status = ?, closed_at = ? WHERE name = ?",
                (REJECTED, now(), name),
            )
        return {"name": name, "status": REJECTED}


def reviews(
    data_dir: Path,
    *,
    work: Path,
    setup: Path,
    config: Path | None = None,
    flows: Path | None = None,
    tools_key: str = "",
    tools_port: int = 8422,
) -> Component:
    """Reviews' component: its records in `data_dir`, the designer's working copy at `work`,
    and the person's setup folder at `setup`. With `tools_key`, the two tools of the designer
    are served on `tools_port` of the loopback address (tools.py)."""
    store = Reviews(data_dir, work=work, setup=setup, config=config, flows=flows)
    router = APIRouter()

    @asynccontextmanager
    async def lifespan(context: Context) -> AsyncIterator[None]:
        store.set_up()
        if not tools_key:
            log.warning("FA1_SETUP_KEY holds no key: the designer's tools are not served")
            yield
            return
        from reviews.tools import serve_tools

        with serve_tools(store, key=tools_key, port=tools_port):
            yield

    @router.get("/api/changelists", dependencies=[permit(READ)])
    def changelists(state: Literal["pending", "closed"] = "pending") -> dict[str, Any]:
        """The pending or the closed changelists, the last submitted first."""
        return {"items": store.changelists(state)}

    @router.get("/api/changelists/{name}", dependencies=[permit(READ)])
    def changelist(name: str) -> dict[str, Any]:
        """A changelist, with each file's old and new version."""
        return store.changelist(name)

    @router.post("/api/submit_changelist", dependencies=[permit(SUBMIT)])
    def submit_changelist(body: Submitted) -> dict[str, Any]:
        return store.submit(body.name, body.branch, body.title, body.description)

    @router.post("/api/approve_changelist", dependencies=[permit(APPROVE)])
    def approve_changelist(body: Named) -> dict[str, Any]:
        return store.approve(body.changelist_name)

    @router.post("/api/reject_changelist", dependencies=[permit(APPROVE)])
    def reject_changelist(body: Named) -> dict[str, Any]:
        return store.reject(body.changelist_name)

    return Component(
        name=NAME,
        roles=ROLES,
        router=router,
        lifespan=lifespan,
        errors={Invalid: 422, NotFound: 404, Conflict: 409},
        title="Reviews",
    )
