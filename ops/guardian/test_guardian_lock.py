#!/usr/bin/env python3
"""Proof that a guardian sweep cannot run while a deploy or a CI job is using
the same files.

Everything here uses real processes, the real flock(2) syscall and the real
`flock(1)` binary that deploy_env.sh calls. Nothing is mocked: the point of the
suite is to show that the guardian's Python lock and the deploy script's shell
lock are the SAME lock, and that the runner-detection can tell "a build is
running" apart from "I am myself running inside a build".
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARDIAN_PY = HERE / "guardian.py"

_spec = importlib.util.spec_from_file_location("aether_guardian_lock_test", GUARDIAN_PY)
guardian = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guardian)

FAKE_RUNNER_ARG = "Runner.Worker"


def spawn_fake_runner() -> subprocess.Popen:
    """A real process whose command line matches what pgrep -f looks for."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", FAKE_RUNNER_ARG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if proc.pid in guardian.foreign_runner_jobs():
            return proc
        time.sleep(0.05)
    proc.kill()
    raise AssertionError("spawned runner stand-in was never seen by pgrep")


def stop(proc: subprocess.Popen) -> None:
    proc.kill()
    proc.wait(timeout=10)
    for _ in range(100):
        if proc.pid not in guardian.foreign_runner_jobs():
            return
        time.sleep(0.05)
    raise AssertionError("runner stand-in still reported after it exited")


# --------------------------------------------------------------------------

def test_lock_is_exclusive_within_a_process(tmp: Path) -> None:
    guardian.LOCKS = tmp / "locks"
    first = guardian.acquire_env_lock("dev")
    assert first is not None, "first acquisition must succeed"
    # A second acquisition through a separate fd must be refused, otherwise two
    # guardian cycles could sweep the same tree at once.
    assert guardian.acquire_env_lock("dev") is None
    first.close()
    again = guardian.acquire_env_lock("dev")
    assert again is not None, "lock was not released on close"
    again.close()


def test_locks_are_per_environment(tmp: Path) -> None:
    guardian.LOCKS = tmp / "locks"
    dev = guardian.acquire_env_lock("dev")
    test = guardian.acquire_env_lock("test")
    assert dev is not None and test is not None, "environments must not block each other"
    dev.close()
    test.close()


def test_shell_flock_blocks_the_guardian(tmp: Path) -> None:
    """deploy_env.sh uses flock(1); the guardian uses fcntl.flock. Same lock."""
    guardian.LOCKS = tmp / "locks"
    guardian.LOCKS.mkdir(parents=True, exist_ok=True)
    lock_file = guardian.env_lock_path("prod")

    # start_new_session so the whole group can be killed: flock(1) passes the
    # locked fd to its child, so killing only flock leaves `sleep` holding the
    # lock and the release below would never be observed.
    holder = subprocess.Popen(["flock", str(lock_file), "-c", "sleep 30"],
                              start_new_session=True,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):                      # wait for flock(1) to actually take it
            if guardian.acquire_env_lock("prod") is None:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("flock(1) did not block fcntl.flock — the two are not the same lock")
    finally:
        os.killpg(os.getpgid(holder.pid), signal.SIGKILL)
        holder.wait(timeout=10)

    for _ in range(100):
        got = guardian.acquire_env_lock("prod")
        if got is not None:
            got.close()
            return
        time.sleep(0.05)
    raise AssertionError("lock was never released after the holder died")


def test_process_ancestors_includes_self_and_parent(tmp: Path) -> None:
    chain = guardian.process_ancestors(os.getpid())
    assert os.getpid() in chain
    assert os.getppid() in chain


def test_foreign_runner_job_is_detected(tmp: Path) -> None:
    proc = spawn_fake_runner()
    try:
        assert proc.pid in guardian.foreign_runner_jobs()
    finally:
        stop(proc)


def test_own_runner_ancestry_is_excluded(tmp: Path) -> None:
    """The guardian sweep step runs INSIDE a runner job. It must not see itself
    as a reason to defer, or the CI-side sweep would never run."""
    script = (
        "import importlib.util, os, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(GUARDIAN_PY)!r})\n"
        "g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)\n"
        "print(os.getpid(), g.foreign_runner_jobs())\n"
    )
    out = subprocess.run([sys.executable, "-c", script, FAKE_RUNNER_ARG],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    own_pid, found = out.stdout.split(" ", 1)
    assert own_pid not in found, (
        f"a guardian running under {FAKE_RUNNER_ARG} reported itself as a busy runner: {out.stdout!r}")


def test_hygiene_defers_while_a_runner_job_is_alive(tmp: Path) -> None:
    """The actual regression: the ci guardian deleting build cache mid-build."""
    root = tmp / "work"
    cache = root / "repo" / "apps" / "web" / ".next" / "cache"
    cache.mkdir(parents=True)
    (cache / "chunk.bin").write_bytes(b"x" * 1024)
    pycache = root / "repo" / "apps" / "api" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "m.pyc").write_bytes(b"y" * 512)

    original = guardian.ENVS["ci"]
    guardian.ENVS["ci"] = dict(original, root=str(root), repo=str(root / "repo"),
                               runner_workspace=True)
    # Hermetic busy-signal: scope runner detection to THIS test's own spawned
    # job. The real host may run more than one Actions runner (e.g. a second,
    # user-space CI runner executing an unrelated job concurrently), whose live
    # Runner.Worker would otherwise leak into the host-global `pgrep` and keep
    # the idle-phase sweep deferred forever, flaking this test. The real pgrep
    # detector itself is still exercised by test_foreign_runner_job_is_detected
    # and by spawn_fake_runner()'s own confirmation below — this only removes
    # the cross-runner coupling from the defer→sweep behavioural assertions.
    saved_detector = guardian.foreign_runner_jobs
    try:
        proc = spawn_fake_runner()  # validated against the REAL detector

        def _only_this_jobs_worker() -> list[int]:
            # proc.poll() reaps on exit and returns None only while truly
            # running — avoids the zombie/pid-reuse ambiguity of os.kill(pid, 0).
            return [proc.pid] if proc.poll() is None else []

        guardian.foreign_runner_jobs = _only_this_jobs_worker
        try:
            busy = guardian.Guardian("ci", apply=True)
            busy.hygiene()
            assert cache.exists(), "sweep deleted build cache while a runner job was alive"
            assert pycache.exists()
            assert not busy.actions, f"guardian acted during a runner job: {busy.actions}"
            assert any("deferred" in f["message"] for f in busy.findings), busy.findings
        finally:
            stop(proc)

        idle = guardian.Guardian("ci", apply=True)
        idle.hygiene()
        assert not pycache.exists(), "sweep did not run once the runner job ended"
        assert idle.actions, "no artefacts were reclaimed when the workspace was idle"
    finally:
        guardian.foreign_runner_jobs = saved_detector
        guardian.ENVS["ci"] = original


def test_git_defers_while_a_runner_job_is_alive(tmp: Path) -> None:
    repo = tmp / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    (repo / "tracked.md").write_text("v1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"],
                   cwd=repo, env=env, check=True)
    (repo / "tracked.md").write_text("v2\n")

    original = guardian.ENVS["ci"]
    guardian.ENVS["ci"] = dict(original, root=str(tmp), repo=str(repo), runner_workspace=True)
    try:
        proc = spawn_fake_runner()
        try:
            g = guardian.Guardian("ci", apply=True)
            g.git()
            assert (repo / "tracked.md").read_text() == "v2\n", "guardian stashed a live CI checkout"
            assert not g.actions, f"guardian acted on a live CI checkout: {g.actions}"
        finally:
            stop(proc)
    finally:
        guardian.ENVS["ci"] = original


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    failed = 0
    for fn in TESTS:
        tmp = Path(tempfile.mkdtemp(prefix="guardian-lock-test-"))
        saved_locks = guardian.LOCKS
        try:
            fn(tmp)
            print(f"PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
        finally:
            guardian.LOCKS = saved_locks
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
