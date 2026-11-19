"""Reviews: an application of FA1, beside Robinauts and neorc (docs/specs/review-app.md).

A changelist is a branch of the setup folder that a submitter asks a person to review. The
review app fetches the branch from the designer's working copy into a repository of its own,
pins the commit, checks it, and shows its changes. An approver's yes moves `main` to that
commit, and the app takes `main` to the setup folder at the next Refresh.

`reviews` below gives the component, which ../backend.py composes. The records are in
`reviews.db`, in the control plane's data directory, beside `robinauts.db`. The repository is
`reviews/setup.git` beside it. The module imports the standard library, FastAPI and oneberth,
and runs `git`, which the control image holds.
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

from fastapi import APIRouter, Response
from oneberth.identity import Role, RoleTable
from oneberth.web import Component, Context, permit
from pydantic import BaseModel, Field

log = logging.getLogger("fa1.reviews")

NAME = "reviews"
FILE_NAME = "reviews.db"
WORK_FOLDER = "reviews"
"""The review app's own folder, in the data directory: its repository, `setup.git`, its git
configuration and its temporary trees."""

READ = "reviews/changelists:read"
SUBMIT = "reviews/changelists:submit"
APPROVE = "reviews/changelists:approve"
PULL = "reviews/main:pull"

SUBMITTER = "reviews/submitter"
APPROVER = "reviews/approver"
HOST = "reviews/host"

ROLES = RoleTable(
    app=NAME,
    permissions=frozenset({READ, SUBMIT, APPROVE, PULL}),
    roles=(
        Role(SUBMITTER, frozenset({READ, SUBMIT}), people=True),
        Role(APPROVER, frozenset({READ, APPROVE}), people=True),
        Role(HOST, frozenset({PULL})),
    ),
    default=APPROVER,
)
"""Two general roles for people, and one for the app on the host. The local user holds the
first two, since a person may hold either. The app's service token holds the third."""

SUBMITTED, APPROVED, REJECTED = "submitted", "approved", "rejected"
PENDING = (SUBMITTED,)
CLOSED = (APPROVED, REJECTED)

SCHEMA_VERSION = 2
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
BEFORE_BRANCHES = ("files", "baselines", "changelists", "folders")
"""The tables of schema version 1, where a changelist held copies of files. No release had
them, so a file at that version starts again."""

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
MAIN = "refs/heads/main"
PUBLISHED = "refs/published/main"

STEERING = frozenset({".gitattributes", ".gitmodules", ".lfsconfig"})
"""Files that steer git on the person's computer. A changelist changes none of them."""
FILE_MODES = frozenset({"100644", "100755"})
"""A plain file's two modes. A link, and a repository inside the repository, have others."""

NO_MAIN = (
    "the setup folder has no commit yet, so a changelist has nothing to start from: commit the"
    " setup folder, then press Refresh in FA1"
)
NOT_ON_MAIN = (
    "branch {branch!r} does not start from the current main: check it out, merge main into it"
    " with git_merge, and submit it again"
)
MAIN_MOVED = (
    "main moved since changelist {name!r} was submitted, so it is not applied: the submitter"
    " merges main into {branch!r} and submits it again"
)


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
    """The records and the repository, behind one lock."""

    def __init__(
        self,
        data_dir: Path,
        *,
        work: Path,
        published: Path,
        config: Path | None = None,
        flows: Path | None = None,
    ) -> None:
        self.file = data_dir / FILE_NAME
        self.home = data_dir / WORK_FOLDER
        self.repo = self.home / "setup.git"
        self.gitconfig = self.home / "gitconfig"
        self.work = work
        """The designer's working copy of the setup folder, which the review app fetches
        branches from and never runs git in."""
        self.published = published
        """The setup folder's HEAD, as a bundle the app writes at each start and refresh."""
        self.config = config
        self.flows = flows
        self.lock = threading.RLock()
        self._synced: tuple[int, int] | None = None

    # The store.

    def set_up(self) -> None:
        """Makes the file, its schema and the repository, or checks the version of the file
        found."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(exist_ok=True)
        with closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            found = connection.execute("PRAGMA user_version").fetchone()[0]
            if found in (0, 1):
                with connection:
                    for old in BEFORE_BRANCHES if found == 1 else ():
                        connection.execute(f"DROP TABLE IF EXISTS {old}")
                    connection.executescript(SCHEMA)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif found != SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.file} is at schema version {found}, and this build of reviews needs"
                    f" {SCHEMA_VERSION}"
                )
        # The working copy belongs to another user, the tool servers'. git serves a fetch from
        # such a folder only when a configuration outside it says so. No hook runs here.
        self.gitconfig.write_text(
            "[safe]\n"
            f"\tdirectory = {self.work}\n"
            f"\tdirectory = {self.work / '.git'}\n"
            "[core]\n\thooksPath = /dev/null\n"
            "[gc]\n\tauto = 0\n"
            '[protocol "ext"]\n\tallow = never\n',
            encoding="utf-8",
        )
        if not (self.repo / "HEAD").is_file():
            self.repo.mkdir(parents=True, exist_ok=True)
            self.git("init", "--quiet", "--bare", "--initial-branch", "main", str(self.repo))

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.file, timeout=BUSY_SECONDS)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self.lock, closing(self.connect()) as connection, connection:
            yield connection

    # git, on the review app's own repository.

    def git(self, *arguments: str, check: bool = True) -> bytes:
        """Runs git on the review app's repository, with its own configuration and no other.
        The standard output, or `GitFailed`."""
        try:
            done = subprocess.run(
                ["git", *arguments],
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": str(self.home),
                    "GIT_DIR": str(self.repo),
                    "GIT_CONFIG_GLOBAL": str(self.gitconfig),
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_TERMINAL_PROMPT": "0",
                    "LC_ALL": "C",
                },
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=GIT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as slow:
            raise GitFailed(f"git {arguments[0]} took over {GIT_SECONDS:.0f} seconds") from slow
        if check and done.returncode != 0:
            raise GitFailed(done.stderr.decode("utf-8", "replace").strip())
        return done.stdout

    def rev(self, name: str) -> str | None:
        """The commit `name` is at, `None` for a name that is at none."""
        found = self.git("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}", check=False)
        return found.decode().strip() or None

    def descends(self, commit: str, ancestor: str) -> bool:
        """Whether `ancestor` is `commit` or one of its ancestors."""
        asked = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, commit],
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_DIR": str(self.repo)},
            capture_output=True,
            timeout=GIT_SECONDS,
            check=False,
        )
        return asked.returncode == 0

    def sync_main(self) -> None:
        """Brings `main` to the setup folder's HEAD, as the app last wrote it. `main` stays
        ahead of it only by approved changelists the setup folder does not hold yet. Any
        other difference is the setup folder's to decide."""
        with self.lock:
            try:
                found = self.published.stat()
            except OSError:
                return
            seen = (found.st_mtime_ns, found.st_size)
            if seen != self._synced:
                try:
                    self.git(
                        "fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
                        str(self.published), f"+HEAD:{PUBLISHED}",
                    )  # fmt: skip
                except GitFailed as failed:
                    log.warning("the setup folder's bundle was not read: %s", failed)
                    return
                self._synced = seen
            published = self.rev(PUBLISHED)
            main = self.rev(MAIN)
            if published is None or main == published:
                return
            if main is None or not self.descends(main, published):
                self.git("update-ref", MAIN, published)

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
        self.sync_main()
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
        published = self.rev(PUBLISHED)
        return status == APPROVED and published is not None and self.descends(published, commit)

    def row(self, connection: sqlite3.Connection, name: str) -> sqlite3.Row:
        found = connection.execute("SELECT * FROM changelists WHERE name = ?", (name,)).fetchone()
        if found is None:
            raise NotFound(f"no changelist is named {name!r}")
        return found  # type: ignore[no-any-return]

    def changelist(self, name: str) -> dict[str, Any]:
        """A changelist, with each file's old and new version."""
        self.sync_main()
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
        if not CHANGELIST_NAME.fullmatch(name):
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
            self.sync_main()
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
                    raise Conflict(f"branch {branch!r} holds no change: it is at main's commit")
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
                self.git("update-ref", f"refs/changelists/{name}", commit)
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
        """Moves `main` to the changelist's commit, when `main` is still that commit's
        ancestor."""
        with self.writing() as connection:
            row = self.submitted(connection, name, "an approval")
            self.sync_main()
            main = self.rev(MAIN)
            if main is None or not self.descends(row["commit_id"], main):
                raise Conflict(MAIN_MOVED.format(name=name, branch=row["branch"]))
            self.git("update-ref", MAIN, row["commit_id"], main)
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

    def approved_bundle(self) -> bytes | None:
        """The approved commits the setup folder lacks, as a git bundle of `main`. `None` when
        it lacks none."""
        with self.lock:
            self.sync_main()
            main, published = self.rev(MAIN), self.rev(PUBLISHED)
            if main is None or published is None or main == published:
                return None
            with self.tree() as folder:
                bundle = folder / "approved.bundle"
                self.git("bundle", "create", "--quiet", str(bundle), MAIN, f"^{published}")
                return bundle.read_bytes()


def reviews(
    data_dir: Path,
    *,
    work: Path,
    published: Path,
    config: Path | None = None,
    flows: Path | None = None,
    tools_key: str = "",
    tools_port: int = 8422,
) -> Component:
    """Reviews' component: its records in `data_dir`, the designer's working copy at `work`,
    and the setup folder's HEAD in the bundle `published`. With `tools_key`, the two tools of
    the designer are served on `tools_port` of the loopback address (tools.py)."""
    store = Reviews(data_dir, work=work, published=published, config=config, flows=flows)
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

    @router.get("/api/approved.bundle", dependencies=[permit(PULL)])
    def approved_bundle() -> Response:
        """The approved commits the setup folder lacks, for the app on the host. 204 when it
        lacks none."""
        bundle = store.approved_bundle()
        if bundle is None:
            return Response(status_code=204)
        return Response(bundle, media_type="application/octet-stream")

    return Component(
        name=NAME,
        roles=ROLES,
        router=router,
        lifespan=lifespan,
        errors={Invalid: 422, NotFound: 404, Conflict: 409},
        title="Reviews",
    )
