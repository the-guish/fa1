"""Reviews: an application of FA1, beside Robinauts and neorc (docs/specs/apps.md).

The control plane composes its component: ``ROBINAUTS_COMPONENTS`` names ``component`` below.
Its records are in ``reviews.db``, in the control plane's data directory, beside
``robinauts.db``. It imports the standard library, FastAPI and oneberth, which the control
image holds.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from oneberth.identity import Role, RoleTable
from oneberth.web import Component, Context, permit

NAME = "reviews"

DATA_DIR_VARIABLE = "ROBINAUTS_DATA_DIR"
"""The control plane's data directory, as Robinauts names it for its own files."""

FILE_NAME = "reviews.db"

REVIEWS_READ = "reviews/reviews:read"
USER_ROLE = "reviews/user"

ROLES = RoleTable(
    app=NAME,
    permissions=frozenset({REVIEWS_READ}),
    roles=(Role(USER_ROLE, frozenset({REVIEWS_READ}), people=True),),
    default=USER_ROLE,
)
"""One role, for the person: the local user holds every role a person may hold."""

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
) STRICT
"""

BUSY_SECONDS = 10.0
"""How long a statement waits for a lock, as Robinauts' own file does."""


def connect(file: Path) -> sqlite3.Connection:
    return sqlite3.connect(file, timeout=BUSY_SECONDS)


def set_up(file: Path) -> None:
    """Makes the file and its schema, or checks the version of the one found."""
    file.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(file)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        found = connection.execute("PRAGMA user_version").fetchone()[0]
        if found == 0:
            with connection:
                connection.execute(SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif found != SCHEMA_VERSION:
            raise RuntimeError(
                f"{file} is at schema version {found}, and this build of reviews needs"
                f" {SCHEMA_VERSION}"
            )


def component(environ: Mapping[str, str]) -> Component:
    """Reviews' component, from the control plane's environment."""
    folder = environ.get(DATA_DIR_VARIABLE)
    if not folder:
        raise RuntimeError(f"reviews keeps its records in the data directory: set {DATA_DIR_VARIABLE}")
    file = Path(folder) / FILE_NAME
    router = APIRouter()

    @asynccontextmanager
    async def lifespan(context: Context) -> AsyncIterator[None]:
        set_up(file)
        yield

    @router.get("/api/reviews", dependencies=[permit(REVIEWS_READ)])
    def reviews() -> dict[str, list[dict[str, Any]]]:
        """The reviews, oldest first."""
        with closing(connect(file)) as connection:
            rows = connection.execute("SELECT id, title FROM reviews ORDER BY id").fetchall()
        return {"items": [{"id": row[0], "title": row[1]} for row in rows]}

    return Component(name=NAME, roles=ROLES, router=router, lifespan=lifespan, title="Reviews")
