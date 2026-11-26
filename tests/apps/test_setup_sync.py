"""How the git server's working copy follows the setup folder (compose/setup-tools/start.sh,
docs/specs/review-app.md, "The designer's working copy"): `start.sh sync` on real git."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = ROOT / "compose" / "setup-tools" / "start.sh"


def git(at: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(at), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(at: Path, name: str, text: str, message: str) -> str:
    (at / name).write_text(text)
    git(at, "add", "--all")
    git(at, "commit", "--quiet", "--message", message)
    return git(at, "rev-parse", "HEAD")


class Copies:
    def __init__(self, at: Path) -> None:
        self.setup = at / "setup"
        self.work = at / "work"
        self.setup.mkdir()
        git(self.setup, "init", "--quiet", "--initial-branch", "trunk")
        commit(self.setup, "a.md", "one\n", "First")

    def sync(self) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "FA1_SETUP_WORK": str(self.work), "FA1_SETUP_FOLDER": str(self.setup)}
        return subprocess.run(["sh", str(START), "sync"], env=env, capture_output=True, text=True)

    def branch(self) -> str:
        return git(self.work, "symbolic-ref", "--short", "HEAD")

    def kept(self) -> list[str]:
        return git(self.work, "branch", "--list", "kept/*", "--format=%(refname:short)").split()


def test_main_follows_a_rewritten_history_and_the_designer_stays_on_main(tmp_path: Path) -> None:
    copies = Copies(tmp_path)
    assert copies.sync().returncode == 0
    git(copies.setup, "commit", "--quiet", "--amend", "--message", "First, rewritten")
    assert copies.sync().returncode == 0
    assert copies.branch() == "main"
    assert git(copies.work, "rev-parse", "main") == git(copies.setup, "rev-parse", "HEAD")
    assert copies.kept() == []


def test_commits_on_main_move_to_a_kept_branch_and_main_stays_checked_out(tmp_path: Path) -> None:
    copies = Copies(tmp_path)
    copies.sync()
    own = commit(copies.work, "b.md", "mine\n", "The designer's")
    folder = commit(copies.setup, "c.md", "theirs\n", "The person's")
    assert copies.sync().returncode == 0
    assert copies.branch() == "main"
    assert git(copies.work, "rev-parse", "main") == folder
    [kept] = copies.kept()
    assert git(copies.work, "rev-parse", kept) == own


def test_the_designers_branch_stays_checked_out_through_a_rewrite(tmp_path: Path) -> None:
    copies = Copies(tmp_path)
    copies.sync()
    git(copies.work, "checkout", "--quiet", "-b", "changelists/x")
    work = commit(copies.work, "b.md", "mine\n", "The designer's")
    git(copies.setup, "commit", "--quiet", "--amend", "--message", "First, rewritten")
    assert copies.sync().returncode == 0
    assert copies.branch() == "changelists/x"
    assert git(copies.work, "rev-parse", "HEAD") == work
    assert git(copies.work, "rev-parse", "main") == git(copies.setup, "rev-parse", "HEAD")
    assert copies.kept() == []


def test_files_not_yet_committed_come_along_or_hold_main_back(tmp_path: Path) -> None:
    copies = Copies(tmp_path)
    copies.sync()
    (copies.work / "b.md").write_text("draft\n")
    first = commit(copies.setup, "c.md", "theirs\n", "The person's")
    assert copies.sync().returncode == 0
    assert git(copies.work, "rev-parse", "main") == first
    assert (copies.work / "b.md").read_text() == "draft\n"

    (copies.work / "c.md").write_text("draft\n")
    commit(copies.setup, "c.md", "theirs, again\n", "The person's, again")
    refused = copies.sync()
    assert refused.returncode != 0
    assert "in the way" in refused.stderr
    assert git(copies.work, "rev-parse", "main") == first
    assert (copies.work / "c.md").read_text() == "draft\n"
    assert copies.kept() == []
