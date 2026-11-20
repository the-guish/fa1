"""Reviews' records and FA1's host of them (docs/specs/apps.md), outside Docker.

`set_up` runs on real SQLite files. The host is `apps/backend.py` as a real process, on a data
directory of the test's own. The tests run in the environment of the pinned Robinauts, which
holds FastAPI and oneberth: tests/apps/run.sh makes it.
"""

from __future__ import annotations

import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest import mock

APPS = Path(__file__).resolve().parents[2] / "apps"
sys.path.insert(0, str(APPS))

from reviews import backend  # noqa: E402


def version_of(file: Path) -> int:
    with closing(sqlite3.connect(file)) as connection:
        return connection.execute("PRAGMA user_version").fetchone()[0]


def tables_of(file: Path) -> list[str]:
    with closing(sqlite3.connect(file)) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        return sorted(row[0] for row in rows)


class SetUp(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "data" / backend.FILE_NAME

    def test_a_first_start_makes_the_file_with_its_table_and_its_version(self) -> None:
        backend.set_up(self.file)
        self.assertEqual(tables_of(self.file), ["reviews"])
        self.assertEqual(version_of(self.file), backend.SCHEMA_VERSION)

    def test_a_later_start_keeps_the_file_and_its_rows(self) -> None:
        backend.set_up(self.file)
        with closing(sqlite3.connect(self.file)) as connection, connection:
            connection.execute("INSERT INTO reviews (title) VALUES ('one')")
        backend.set_up(self.file)
        with closing(sqlite3.connect(self.file)) as connection:
            self.assertEqual(connection.execute("SELECT title FROM reviews").fetchall(), [("one",)])

    def test_a_start_that_ends_after_the_table_leaves_no_table(self) -> None:
        # The version's statement fails, as a start that is cut between the two statements.
        with mock.patch.object(backend, "SCHEMA_VERSION", "no number"):
            with self.assertRaises(sqlite3.OperationalError):
                backend.set_up(self.file)
        self.assertEqual(tables_of(self.file), [])
        self.assertEqual(version_of(self.file), 0)
        backend.set_up(self.file)
        self.assertEqual(tables_of(self.file), ["reviews"])

    def test_a_file_of_another_version_is_refused_in_reviews_own_words(self) -> None:
        self.file.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.file)) as connection:
            connection.execute("PRAGMA user_version = 7")
        with self.assertRaises(backend.ReviewsError) as refused:
            backend.set_up(self.file)
        self.assertEqual(
            str(refused.exception),
            f"{self.file} is at schema version 7, and this build of reviews needs 1",
        )

    def test_a_file_with_tables_and_no_version_is_refused_and_kept(self) -> None:
        self.file.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.file)) as connection:
            connection.execute("CREATE TABLE notes (x)")
        with self.assertRaises(backend.ReviewsError) as refused:
            backend.set_up(self.file)
        self.assertEqual(
            str(refused.exception),
            f"{self.file} holds tables and no schema version (notes): this build of reviews"
            " did not make it. Move it away and start again",
        )
        self.assertEqual(tables_of(self.file), ["notes"])


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def status_of(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return answer.status
    except urllib.error.HTTPError as refused:
        return refused.code


class Host(unittest.TestCase):
    """`apps/backend.py`, started as the image starts it."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name) / "data"
        self.data.mkdir()
        config = Path(folder.name) / "robinauts.toml"
        config.write_text("")
        self.environment = {
            **os.environ,
            "ROBINAUTS_CONFIG": str(config),
            "ROBINAUTS_DATA_DIR": str(self.data),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for variable in ("ROBINAUTS_DATABASE_URL", "ONEBERTH_CONFIG", "ROBINAUTS_FLOWS_DIR"):
            self.environment.pop(variable, None)
        self.port = free_port()
        self.command = [sys.executable, str(APPS / "backend.py"), "--port", str(self.port)]
        self.command += ["--worker-port", str(free_port())]

    def test_the_host_serves_its_three_applications_and_keeps_reviews_file(self) -> None:
        host = subprocess.Popen(
            self.command,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{self.port}"
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and host.poll() is None:
                try:
                    if status_of(f"{base}/health") == 200:
                        break
                except OSError:
                    time.sleep(0.2)
            self.assertIsNone(host.poll(), "the host ended before it served")
            self.assertEqual(status_of(f"{base}/health"), 200)
            # Each application answers under its name, and asks for a session.
            for path in ("/robinauts/api/conversations", "/neorc/flows", "/reviews/api/reviews"):
                self.assertEqual(status_of(base + path), 401, path)
        finally:
            host.send_signal(signal.SIGTERM)
            _, said = host.communicate(timeout=60)
        self.assertEqual(host.returncode, 0, said.decode()[-2000:])
        self.assertEqual(
            sorted(file.name for file in self.data.glob("*.db")),
            ["neorc.db", "oneberth.db", "reviews.db", "robinauts.db"],
        )

    def test_a_start_with_no_configuration_named_says_one_line(self) -> None:
        del self.environment["ROBINAUTS_CONFIG"]
        ended = subprocess.run(
            self.command,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=90,
        )
        self.assertEqual(ended.returncode, 1)
        said = ended.stderr.decode().strip().splitlines()
        self.assertEqual(len(said), 1, said)
        self.assertTrue(said[0].startswith("ROBINAUTS_CONFIG"), said)

    def test_a_refusal_of_reviews_is_the_last_line_with_its_sentence_alone(self) -> None:
        file = self.data / backend.FILE_NAME
        with closing(sqlite3.connect(file)) as connection:
            connection.execute("PRAGMA user_version = 7")
        ended = subprocess.run(
            self.command,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=90,
        )
        self.assertEqual(ended.returncode, 1)
        self.assertEqual(
            ended.stderr.decode().strip().splitlines()[-1],
            f"component reviews failed to start: {file} is at schema version 7, and this build"
            " of reviews needs 1",
        )


if __name__ == "__main__":
    unittest.main()
