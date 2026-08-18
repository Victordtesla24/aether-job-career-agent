#!/usr/bin/env python3
"""Regression proof for the guardian's git worktree handling.

Every assertion here runs against a REAL git repository created on disk and the
REAL `git` binary. Nothing is mocked, stubbed or simulated: a pass means the
shipped code produced the asserted bytes from git itself.

Covers two defects observed in production guardian output on 2026-08-18:

  D1  `run()` stripped stdout, so the leading space of the first
      `git status --porcelain` record (` M AGENTS.md`) was consumed and the
      `line[3:]` slice cut one character off the path. The dev guardian
      reported `GENTS.md` and then failed with
      `tar: GENTS.md: Cannot stat: No such file or directory`,
      leaving the worktree dirty. test_first_record_leading_space_preserved
      and test_old_line_slice_algorithm_is_still_broken pin this.

  D2  The archive step tar'd every dirty path, including deleted paths and the
      source side of a rename, which do not exist on disk. tar aborted, and the
      guardian refused to stash. test_delete_and_rename_do_not_break_archive
      drives the real Guardian.git() over a repo containing both.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARDIAN_PY = HERE / "guardian.py"

_spec = importlib.util.spec_from_file_location("aether_guardian_under_test", GUARDIAN_PY)
guardian = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guardian)

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "guardian-test",
    "GIT_AUTHOR_EMAIL": "guardian-test@localhost",
    "GIT_COMMITTER_NAME": "guardian-test",
    "GIT_COMMITTER_EMAIL": "guardian-test@localhost",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, env=GIT_ENV,
                          capture_output=True, text=True, check=True)
    return proc.stdout


def new_repo(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for name, body in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "seed")
    return repo


def porcelain_z(repo: Path) -> str:
    """Exactly what the guardian reads: raw, unstripped, NUL-separated."""
    rc, out, _ = guardian.run(["git", "status", "--porcelain", "-z"], cwd=repo, strip=False)
    assert rc == 0, "git status failed"
    return out


def old_buggy_parse(repo: Path) -> list[str]:
    """The pre-fix algorithm, reproduced verbatim, for regression contrast."""
    rc, out, _ = guardian.run(["git", "status", "--porcelain"], cwd=repo)  # strip=True default
    return [line[3:] for line in out.splitlines()]


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------

def test_first_record_leading_space_preserved(tmp: Path) -> None:
    repo = new_repo(tmp, {"AGENTS.md": "a\n", "CLAUDE.md": "c\n"})
    (repo / "AGENTS.md").write_text("a-modified\n")
    (repo / "CLAUDE.md").write_text("c-modified\n")

    parsed = guardian.parse_porcelain_z(porcelain_z(repo))
    assert parsed == ["AGENTS.md", "CLAUDE.md"], parsed
    for name in parsed:
        assert (repo / name).exists(), f"parsed path {name!r} does not exist on disk"


def test_old_line_slice_algorithm_is_still_broken(tmp: Path) -> None:
    """Pins the defect: if this ever stops failing, git changed and the
    regression test above has lost its teeth."""
    repo = new_repo(tmp, {"AGENTS.md": "a\n", "CLAUDE.md": "c\n"})
    (repo / "AGENTS.md").write_text("a-modified\n")
    (repo / "CLAUDE.md").write_text("c-modified\n")

    broken = old_buggy_parse(repo)
    assert broken == ["GENTS.md", "CLAUDE.md"], (
        f"expected the historical corruption, got {broken!r}")


def test_untracked_and_nested_paths(tmp: Path) -> None:
    repo = new_repo(tmp, {"keep.txt": "k\n"})
    (repo / "new.txt").write_text("n\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "deep.txt").write_text("d\n")

    parsed = guardian.parse_porcelain_z(porcelain_z(repo))
    assert "new.txt" in parsed, parsed
    assert any(p in ("sub/", "sub/deep.txt") for p in parsed), parsed


def test_path_with_spaces_is_not_split(tmp: Path) -> None:
    repo = new_repo(tmp, {"a file with spaces.md": "x\n"})
    (repo / "a file with spaces.md").write_text("y\n")

    parsed = guardian.parse_porcelain_z(porcelain_z(repo))
    assert parsed == ["a file with spaces.md"], parsed
    assert (repo / parsed[0]).exists()


def test_rename_returns_both_sides(tmp: Path) -> None:
    repo = new_repo(tmp, {"old_name.md": "content that is long enough to be detected\n"})
    git(repo, "mv", "old_name.md", "new_name.md")

    parsed = guardian.parse_porcelain_z(porcelain_z(repo))
    assert "new_name.md" in parsed, parsed
    assert "old_name.md" in parsed, parsed


def test_delete_is_reported(tmp: Path) -> None:
    repo = new_repo(tmp, {"doomed.md": "x\n", "safe.md": "y\n"})
    (repo / "doomed.md").unlink()

    parsed = guardian.parse_porcelain_z(porcelain_z(repo))
    assert parsed == ["doomed.md"], parsed
    assert not (repo / "doomed.md").exists()


def test_malformed_record_raises(tmp: Path) -> None:
    try:
        guardian.parse_porcelain_z("XX\0")
    except ValueError:
        return
    raise AssertionError("a malformed record must raise, never yield a mangled path")


def test_delete_and_rename_do_not_break_archive(tmp: Path) -> None:
    """End-to-end over the real Guardian.git() in apply mode."""
    repo = new_repo(tmp, {
        "AGENTS.md": "a\n",
        "gone.md": "g\n",
        "moved.md": "long enough content for rename detection to fire\n",
    })
    (repo / "AGENTS.md").write_text("a-modified\n")
    (repo / "gone.md").unlink()
    git(repo, "mv", "moved.md", "relocated.md")
    (repo / ".env").write_text("SECRET=stays-put\n")   # protected, must survive

    state = tmp / "state"
    orig_state, orig_envs = guardian.STATE, guardian.ENVS["dev"]
    guardian.STATE = state
    guardian.ENVS["dev"] = dict(orig_envs, root=str(repo), repo=str(repo), protected=False)
    try:
        g = guardian.Guardian("dev", apply=True)
        g.git()
    finally:
        guardian.STATE, guardian.ENVS["dev"] = orig_state, orig_envs

    assert not g.escalations, f"unexpected escalations: {json.dumps(g.escalations)}"
    stashed = [a for a in g.actions if a["action"] == "archived and stashed dirty worktree"]
    assert stashed, f"worktree was not stashed; actions={json.dumps(g.actions)}"

    # The protected env file is untouched and still untracked.
    assert (repo / ".env").read_text() == "SECRET=stays-put\n"

    # Everything tracked is back to HEAD, and the deletion was preserved by the stash.
    assert porcelain_z(repo).strip("\0") in ("", "?? .env\0".strip("\0")), porcelain_z(repo)
    assert (repo / "gone.md").exists(), "stash did not restore the deleted file"
    assert (repo / "moved.md").exists(), "stash did not undo the rename"

    # The archive holds the paths that existed on disk, and only those.
    archives = sorted(state.glob("dirty-dev-*.tgz"))
    assert len(archives) == 1, archives
    with tarfile.open(archives[0]) as tf:
        names = set(tf.getnames())
    assert "AGENTS.md" in names, names
    assert "relocated.md" in names, names
    assert "gone.md" not in names, names
    assert ".env" not in names, names

    # The stash carries the deletion the archive could not.
    assert "gone.md" in git(repo, "stash", "show", "--name-only", "stash@{0}")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    failed = 0
    for fn in TESTS:
        tmp = Path(tempfile.mkdtemp(prefix="guardian-git-test-"))
        try:
            fn(tmp)
            print(f"PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 - a test runner reports, it does not swallow
            failed += 1
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
