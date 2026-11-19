"""Reviews: an application of FA1, beside Robinauts and neorc (docs/specs/review-app.md).

A submitter proposes changes to registered folders in a changelist, and an approver applies
them. `reviews` below gives the component, which ../backend.py composes. The records are in
`reviews.db`, in the control plane's data directory, beside `robinauts.db`. The changelists'
copies of their files are in `reviews/` beside it. The module imports the standard library,
FastAPI and oneberth, which the control image holds.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter
from oneberth.identity import Role, RoleTable
from oneberth.web import Component, Context, permit
from pydantic import BaseModel, Field

NAME = "reviews"
FILE_NAME = "reviews.db"
WORK_FOLDER = "reviews"
"""The changelists' copies, in the data directory: `<changelist>/before/` holds each file as
the folder had it, and `<changelist>/after/` the new version."""

READ = "reviews/changelists:read"
SUBMIT = "reviews/changelists:submit"
APPROVE = "reviews/changelists:approve"
REGISTER = "reviews/folders:register"

SUBMITTER = "reviews/submitter"
APPROVER = "reviews/approver"

ROLES = RoleTable(
    app=NAME,
    permissions=frozenset({READ, SUBMIT, APPROVE, REGISTER}),
    roles=(
        Role(SUBMITTER, frozenset({READ, SUBMIT}), people=True),
        Role(APPROVER, frozenset({READ, APPROVE, REGISTER}), people=True),
    ),
    default=APPROVER,
)
"""Two general roles. The local user holds both, since a person may hold either."""

OPEN, SUBMITTED, APPROVED = "open", "submitted", "approved"
PENDING = (OPEN, SUBMITTED)
CLOSED = (APPROVED,)

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE folders (
    path TEXT PRIMARY KEY,
    registered_at TEXT NOT NULL
) STRICT;
CREATE TABLE changelists (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('open', 'submitted', 'approved')),
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    approved_at TEXT
) STRICT;
CREATE TABLE baselines (
    changelist TEXT NOT NULL REFERENCES changelists (name),
    folder TEXT NOT NULL REFERENCES folders (path),
    hash TEXT NOT NULL,
    PRIMARY KEY (changelist, folder)
) STRICT;
CREATE TABLE files (
    changelist TEXT NOT NULL REFERENCES changelists (name),
    path TEXT NOT NULL,
    folder TEXT NOT NULL REFERENCES folders (path),
    existed INTEGER NOT NULL,
    PRIMARY KEY (changelist, path)
) STRICT;
"""

BUSY_SECONDS = 10.0
"""How long a statement waits for a lock, as Robinauts' own file does."""

CHANGELIST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


class Invalid(ValueError):
    """A request whose values the review app refuses."""


class NotFound(LookupError):
    """A folder, a changelist or a file the review app does not hold."""


class Conflict(RuntimeError):
    """A request the changelist's state, or a folder's, refuses."""


class FolderChanged(Conflict):
    """A folder that changed since the changelist opened."""


class Folder(BaseModel):
    path: str


class Opened(BaseModel):
    name: str


class Named(BaseModel):
    changelist_name: str


class Replaced(BaseModel):
    changelist_name: str
    path: str
    new_contents: str = Field(max_length=4_000_000)


class Reverted(BaseModel):
    changelist_name: str
    path: str


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def relative(text: str, what: str) -> PurePosixPath:
    """`text` as a relative path of plain segments, or `Invalid`."""
    path = PurePosixPath(text)
    if (
        not text
        or text != str(path)
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or "\\" in text
        or "\0" in text
    ):
        raise Invalid(f"{what} {text!r} is not a relative path of plain segments")
    return path


def inside(base: Path, path: Path) -> bool:
    """Whether `path` is `base` or under it, with the links of both resolved."""
    base, real = Path(os.path.realpath(base)), Path(os.path.realpath(path))
    return real == base or base in real.parents


def folder_hash(folder: Path) -> str:
    """The SHA-256 of a folder's content: each file's path and bytes, each link's target."""
    digest = hashlib.sha256()
    for top, folders, files in os.walk(folder):
        folders.sort()
        for name in sorted(files + [f for f in folders if os.path.islink(os.path.join(top, f))]):
            path = os.path.join(top, name)
            digest.update(os.path.relpath(path, folder).encode() + b"\0")
            if os.path.islink(path):
                digest.update(b"link\0" + os.readlink(path).encode() + b"\0")
            else:
                with open(path, "rb") as file:
                    digest.update(hashlib.file_digest(file, "sha256").digest())
    return digest.hexdigest()


def write_file(path: Path, text: str) -> None:
    """Writes `text` to `path` through a file beside it, so a reader sees one version or the
    other."""
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_name(f".{path.name}.reviews")
    spare.write_text(text, encoding="utf-8", newline="")
    os.replace(spare, path)


class Reviews:
    """The records and the copies, behind one lock."""

    def __init__(self, data_dir: Path, root: Path) -> None:
        self.file = data_dir / FILE_NAME
        self.work = data_dir / WORK_FOLDER
        self.root = root
        self.lock = threading.Lock()

    def set_up(self) -> None:
        """Makes the file and its schema, or checks the version of the one found."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.work.mkdir(exist_ok=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = Path(os.path.realpath(self.root))
        with closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            found = connection.execute("PRAGMA user_version").fetchone()[0]
            if found == 0:
                with connection:
                    connection.executescript(SCHEMA)
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif found != SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.file} is at schema version {found}, and this build of reviews needs"
                    f" {SCHEMA_VERSION}"
                )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.file, timeout=BUSY_SECONDS)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self.lock, closing(self.connect()) as connection, connection:
            yield connection

    # Folders.

    def folders(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT path, registered_at FROM folders ORDER BY path")
            return [dict(row) for row in rows]

    def register_folder(self, text: str) -> dict[str, Any]:
        path = relative(text, "the folder")
        target = self.root / path
        if not inside(self.root, target):
            raise Invalid(f"{text!r} leads outside the starting folder")
        if not target.is_dir():
            raise NotFound(f"the starting folder holds no folder {text!r}")
        with self.writing() as connection:
            known = [row[0] for row in connection.execute("SELECT path FROM folders")]
            if text in known:
                return {"path": text}
            for other in known:
                if PurePosixPath(other) in path.parents or path in PurePosixPath(other).parents:
                    raise Conflict(f"{text!r} overlaps the registered folder {other!r}")
            connection.execute(
                "INSERT INTO folders (path, registered_at) VALUES (?, ?)", (text, now())
            )
        return {"path": text}

    def split(self, connection: sqlite3.Connection, text: str) -> tuple[str, PurePosixPath]:
        """A file's registered folder, and its path in that folder."""
        path = relative(text, "the file")
        for (folder,) in connection.execute("SELECT path FROM folders"):
            if PurePosixPath(folder) in path.parents:
                return folder, path.relative_to(folder)
        raise NotFound(f"{text!r} is in no registered folder")

    # Changelists.

    def changelists(self, state: Literal["pending", "closed"]) -> list[dict[str, Any]]:
        statuses = PENDING if state == "pending" else CLOSED
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT name, status, created_at FROM changelists"
                f" WHERE status IN ({', '.join('?' * len(statuses))})"
                " ORDER BY created_at DESC, name",
                statuses,
            )
            return [dict(row) for row in rows]

    def status(self, connection: sqlite3.Connection, name: str) -> str:
        row = connection.execute("SELECT status FROM changelists WHERE name = ?", (name,))
        found = row.fetchone()
        if found is None:
            raise NotFound(f"no changelist is named {name!r}")
        return str(found[0])

    def changelist(self, name: str) -> dict[str, Any]:
        with closing(self.connect()) as connection:
            self.status(connection, name)
            row = connection.execute(
                "SELECT name, status, created_at, submitted_at, approved_at FROM changelists"
                " WHERE name = ?",
                (name,),
            ).fetchone()
            files = connection.execute(
                "SELECT path, existed FROM files WHERE changelist = ? ORDER BY path", (name,)
            ).fetchall()
        copies = self.work / name
        listed = []
        for path, existed in files:
            old = None
            if existed:
                old = (copies / "before" / path).read_bytes().decode("utf-8", "replace")
            new = (copies / "after" / path).read_text(encoding="utf-8")
            listed.append({"path": path, "old": old, "new": new})
        return {**dict(row), "files": listed}

    def open_changelist(self, name: str) -> dict[str, Any]:
        if not CHANGELIST_NAME.fullmatch(name):
            raise Invalid(
                f"{name!r} is not a changelist name: letters, digits, '.', '_' and '-', up to 100"
            )
        with self.writing() as connection:
            if connection.execute("SELECT 1 FROM changelists WHERE name = ?", (name,)).fetchone():
                raise Conflict(f"a changelist is already named {name!r}")
            created = now()
            connection.execute(
                "INSERT INTO changelists (name, status, created_at) VALUES (?, ?, ?)",
                (name, OPEN, created),
            )
            for (folder,) in connection.execute("SELECT path FROM folders").fetchall():
                connection.execute(
                    "INSERT INTO baselines (changelist, folder, hash) VALUES (?, ?, ?)",
                    (name, folder, folder_hash(self.root / folder)),
                )
        return {"name": name, "status": OPEN, "created_at": created}

    def open_for_changes(self, connection: sqlite3.Connection, name: str) -> None:
        status = self.status(connection, name)
        if status != OPEN:
            raise Conflict(f"changelist {name!r} is {status}: its files change only while open")

    def replace_contents(self, name: str, text: str, contents: str) -> dict[str, Any]:
        with self.writing() as connection:
            self.open_for_changes(connection, name)
            folder, path = self.split(connection, text)
            if not connection.execute(
                "SELECT 1 FROM baselines WHERE changelist = ? AND folder = ?", (name, folder)
            ).fetchone():
                raise Conflict(
                    f"{folder!r} was registered after changelist {name!r} opened, so it has no"
                    " hash to approve against"
                )
            target = self.root / folder / path
            if not inside(self.root / folder, target):
                raise Invalid(f"{text!r} leads outside its folder")
            if target.exists() and not target.is_file():
                raise Invalid(f"{text!r} is not a file")
            copies = self.work / name
            known = connection.execute(
                "SELECT 1 FROM files WHERE changelist = ? AND path = ?", (name, text)
            ).fetchone()
            if not known:
                existed = target.is_file()
                if existed:
                    before = copies / "before" / text
                    before.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, before)
                connection.execute(
                    "INSERT INTO files (changelist, path, folder, existed) VALUES (?, ?, ?, ?)",
                    (name, text, folder, int(existed)),
                )
            write_file(copies / "after" / text, contents)
        return {"changelist_name": name, "path": text}

    def revert_changes(self, name: str, text: str) -> dict[str, Any]:
        with self.writing() as connection:
            self.open_for_changes(connection, name)
            deleted = connection.execute(
                "DELETE FROM files WHERE changelist = ? AND path = ?", (name, text)
            )
            if deleted.rowcount == 0:
                raise NotFound(f"changelist {name!r} holds no change to {text!r}")
            for side in ("before", "after"):
                (self.work / name / side / text).unlink(missing_ok=True)
        return {"changelist_name": name, "path": text}

    def submit_changelist(self, name: str) -> dict[str, Any]:
        with self.writing() as connection:
            self.open_for_changes(connection, name)
            if not connection.execute(
                "SELECT 1 FROM files WHERE changelist = ?", (name,)
            ).fetchone():
                raise Conflict(f"changelist {name!r} holds no change")
            connection.execute(
                "UPDATE changelists SET status = ?, submitted_at = ? WHERE name = ?",
                (SUBMITTED, now(), name),
            )
        return {"name": name, "status": SUBMITTED}

    def approve_changelist(self, name: str) -> dict[str, Any]:
        with self.writing() as connection:
            status = self.status(connection, name)
            if status != SUBMITTED:
                raise Conflict(
                    f"changelist {name!r} is {status}: an approval needs a submitted one"
                )
            files = connection.execute(
                "SELECT path, folder FROM files WHERE changelist = ? ORDER BY path", (name,)
            ).fetchall()
            for folder in sorted({row["folder"] for row in files}):
                (held,) = connection.execute(
                    "SELECT hash FROM baselines WHERE changelist = ? AND folder = ?",
                    (name, folder),
                ).fetchone()
                if folder_hash(self.root / folder) != held:
                    raise FolderChanged(
                        f"{folder!r} changed since changelist {name!r} opened, so the changelist"
                        " is not applied"
                    )
            for row in files:
                after = self.work / name / "after" / row["path"]
                write_file(self.root / row["path"], after.read_text(encoding="utf-8"))
            connection.execute(
                "UPDATE changelists SET status = ?, approved_at = ? WHERE name = ?",
                (APPROVED, now(), name),
            )
        return {"name": name, "status": APPROVED}


def reviews(data_dir: Path, root: Path) -> Component:
    """Reviews' component: its records in `data_dir`, its folders under `root`, the starting
    folder."""
    store = Reviews(data_dir, root)
    router = APIRouter()

    @asynccontextmanager
    async def lifespan(context: Context) -> AsyncIterator[None]:
        store.set_up()
        yield

    @router.get("/api/folders", dependencies=[permit(READ)])
    def folders() -> dict[str, Any]:
        """The registered folders."""
        return {"items": store.folders()}

    @router.post("/api/register_folder", dependencies=[permit(REGISTER)])
    def register_folder(body: Folder) -> dict[str, Any]:
        return store.register_folder(body.path)

    @router.get("/api/changelists", dependencies=[permit(READ)])
    def changelists(state: Literal["pending", "closed"] = "pending") -> dict[str, Any]:
        """The pending or the closed changelists, newest first."""
        return {"items": store.changelists(state)}

    @router.get("/api/changelists/{name}", dependencies=[permit(READ)])
    def changelist(name: str) -> dict[str, Any]:
        """A changelist, with each file's old and new version."""
        return store.changelist(name)

    @router.post("/api/open_changelist", dependencies=[permit(SUBMIT)])
    def open_changelist(body: Opened) -> dict[str, Any]:
        return store.open_changelist(body.name)

    @router.post("/api/replace_contents", dependencies=[permit(SUBMIT)])
    def replace_contents(body: Replaced) -> dict[str, Any]:
        return store.replace_contents(body.changelist_name, body.path, body.new_contents)

    @router.post("/api/revert_changes", dependencies=[permit(SUBMIT)])
    def revert_changes(body: Reverted) -> dict[str, Any]:
        return store.revert_changes(body.changelist_name, body.path)

    @router.post("/api/submit_changelist", dependencies=[permit(SUBMIT)])
    def submit_changelist(body: Named) -> dict[str, Any]:
        return store.submit_changelist(body.changelist_name)

    @router.post("/api/approve_changelist", dependencies=[permit(APPROVE)])
    def approve_changelist(body: Named) -> dict[str, Any]:
        return store.approve_changelist(body.changelist_name)

    return Component(
        name=NAME,
        roles=ROLES,
        router=router,
        lifespan=lifespan,
        errors={Invalid: 422, NotFound: 404, Conflict: 409},
        title="Reviews",
    )
