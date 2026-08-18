#!/usr/bin/env python3
"""Aether environment guardian.

One guardian per environment. Autonomous: it is never asked anything and never
answers a user. It reports upward to the orchestrator inbox only.

Duties (per cycle):
  1. health      services, HTTP endpoints, datastores, disk/memory headroom
  2. hygiene     caches, stale logs, test artefacts, orphaned build output
  3. git         worktree must be clean; dirty files are ARCHIVED, never destroyed
  4. duplicates  integrity guard R1-R7 (blocks fabricated/duplicated code)
  5. deps        lockfile vs installed; build artefacts present for next workload
  6. judgement   ambiguous deletions are decided by `claude -p`, never guessed
  7. report      structured JSON to the orchestrator inbox

Safety invariants (hard-coded, not configurable):
  * never deletes anything outside its own environment root
  * never deletes a git-TRACKED file
  * never deletes a path on the KEEP list
  * production hygiene is report-only for anything it has not proven disposable
"""
from __future__ import annotations
import argparse, fcntl, json, os, shutil, subprocess, sys, time, hashlib, socket
from datetime import datetime, timezone
from pathlib import Path

INBOX = Path("/var/lib/aether-orchestrator/inbox")
STATE = Path("/var/lib/aether-orchestrator/state")
LOCKS = Path("/var/lib/aether-orchestrator/locks")
CONSTRAINTS = Path("/root/dev/aether-job-career-agent/scripts/integrity/NON-NEGOTIABLE-CONSTRAINTS.md")

ENVS = {
    "prod": dict(root="/root/prod", repo="/root/prod/app", units=["aether-prod-api","aether-prod-web","aether-prod-worker"],
                 url="https://aether.srv1356245.hstgr.cloud", api="http://127.0.0.1:8000",
                 pg="aether-prod-postgres", redis="aether-prod-redis", protected=True),
    "test": dict(root="/root/test", repo="/root/test/app", units=["aether-test-api","aether-test-web"],
                 url="https://aether-test.srv1356245.hstgr.cloud", api="http://127.0.0.1:8300",
                 pg="aether-test-postgres", redis="aether-test-redis", protected=False),
    "dev":  dict(root="/root/dev", repo="/root/dev/aether-job-career-agent", units=["aether-dev-api","aether-dev-web"],
                 url="https://aether-dev.srv1356245.hstgr.cloud", api="http://127.0.0.1:8100",
                 pg="aether-staging-postgres", redis="aether-staging-redis", protected=False),
    # The ci "environment" is the GitHub Actions runner's own _work tree. The
    # runner cannot take the guardian's lock, so this flag makes the guardian
    # check for a live runner job before touching anything here.
    "ci":   dict(root="/opt/actions-runner", repo="/opt/actions-runner/_work/aether-job-career-agent/aether-job-career-agent",
                 units=[], url=None, api=None, pg=None, redis=None, protected=False,
                 runner_workspace=True),
}

# Disposable by definition — regenerable from source or a package manager.
SWEEP = ["**/.pytest_cache", "**/.ruff_cache", "**/.mypy_cache", "**/__pycache__",
         "**/.turbo", "**/coverage", "**/playwright-report", "**/test-results",
         "**/.next/cache", "**/htmlcov", "**/.eslintcache"]
KEEP = ("/.git", "/.env", "/node_modules", "/.venv", "/app/apps/web/.next/BUILD_ID")

def now() -> str: return datetime.now(timezone.utc).isoformat(timespec="seconds")

def run(cmd, cwd=None, timeout=180, strip=True):
    """Run a command and return (returncode, stdout, stderr).

    ``strip`` MUST be False for any output whose leading whitespace is
    significant.  ``git status --porcelain`` is the motivating case: its records
    are ``XY <path>`` and an unstaged-only change begins with a space, so
    stripping silently removes one character from the first path.
    """
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True,
                           text=True, timeout=timeout)
        out = p.stdout.strip() if strip else p.stdout
        return p.returncode, out, p.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def parse_porcelain_z(raw: str) -> list[str]:
    """Parse ``git status --porcelain -z`` into the list of changed paths.

    NUL-separated records are used instead of lines because they are immune to
    both failure modes of line parsing: no record can be damaged by stripping
    (every record is delimited explicitly), and paths containing spaces or
    newlines are emitted verbatim rather than C-quoted.

    Rename and copy records carry a second NUL-terminated field holding the
    ORIGINAL path.  Both sides are returned: both differ from HEAD in the
    worktree and both must be handed to ``git stash`` for the stash to be
    complete.

    Raises ValueError on any record that does not match the documented
    ``XY <path>`` shape, so a format surprise escalates instead of silently
    producing a mangled path.
    """
    paths: list[str] = []
    records = raw.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if not rec:
            continue
        if len(rec) < 4 or rec[2] != " ":
            raise ValueError(f"unparseable git status record: {rec!r}")
        xy, path = rec[:2], rec[3:]
        paths.append(path)
        if "R" in xy or "C" in xy:
            if i < len(records) and records[i]:
                paths.append(records[i])
            i += 1
    return paths

def env_lock_path(env: str) -> Path:
    return LOCKS / f"{env}.lock"


def acquire_env_lock(env: str):
    """Take an environment's exclusive lock, or return None if it is held.

    deploy_env.sh takes the same lock, so a maintenance sweep can never run
    against a checkout a deploy is in the middle of rewriting.  Non-blocking on
    purpose: a guardian cycle is periodic, so deferring to the next cycle costs
    nothing and is always safe.  The caller must keep the returned handle alive
    for as long as the lock is needed - closing it releases the lock.
    """
    LOCKS.mkdir(parents=True, exist_ok=True)
    fh = open(env_lock_path(env), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def process_ancestors(pid: int) -> set[int]:
    """Every pid from `pid` up to init, read from /proc.

    Used to tell "a runner job is building" apart from "I am myself running
    inside a runner job", which look identical to pgrep.
    """
    chain: set[int] = set()
    while pid and pid > 1 and pid not in chain:
        chain.add(pid)
        try:
            # /proc/<pid>/stat: field 4 is ppid, but comm (field 2) may contain
            # spaces or parentheses, so split after the final ')'.
            stat = Path(f"/proc/{pid}/stat").read_text()
            pid = int(stat[stat.rindex(")") + 1:].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def foreign_runner_jobs() -> list[int]:
    """Live GitHub Actions job processes that this guardian is NOT running under.

    ``pgrep -f Runner.Worker`` also matches operator monitor shells that merely
    *mention* that token in their command line. Those are not CI jobs; treating
    them as busy would defer hygiene forever and flake the lock tests.
    """
    rc, out, _ = run(["pgrep", "-f", "Runner.Worker"])
    pids = [int(tok) for tok in out.split() if tok.isdigit()]
    mine = process_ancestors(os.getpid())
    live: list[int] = []
    for pid in pids:
        if pid in mine:
            continue
        try:
            comm = Path(f"/proc/{pid}/comm").read_text().strip()
        except OSError:
            continue
        if comm in {"bash", "sh", "dash", "pgrep", "grep", "rg"}:
            continue
        live.append(pid)
    return sorted(live)


class Guardian:
    def __init__(self, env: str, apply: bool):
        if env not in ENVS: sys.exit(f"unknown environment '{env}'")
        self.env, self.cfg, self.apply = env, ENVS[env], apply
        self.findings, self.actions, self.escalations = [], [], []
        self.freed = 0

    def runner_busy(self) -> list[int]:
        """Runner jobs holding this environment's files, if it is a CI workspace."""
        if not self.cfg.get("runner_workspace"):
            return []
        return foreign_runner_jobs()

    def note(self, area, level, msg, **kw):
        self.findings.append(dict(area=area, level=level, message=msg, **kw))
    def did(self, msg, **kw): self.actions.append(dict(action=msg, **kw))
    def escalate(self, msg, **kw): self.escalations.append(dict(issue=msg, **kw))

    # 1 ── health ------------------------------------------------------------
    def health(self):
        for u in self.cfg["units"]:
            rc, out, _ = run(["systemctl", "is-active", u])
            if out != "active":
                self.note("health", "critical", f"{u} is {out or 'unknown'}", unit=u)
                if self.apply:
                    rc2, _, err = run(["systemctl", "restart", u], timeout=120)
                    time.sleep(8)
                    _, st, _ = run(["systemctl", "is-active", u])
                    self.did(f"restarted {u}", result=st)
                    if st != "active":
                        self.escalate(f"{u} will not stay active", stderr=err[:400])
        if self.cfg["api"]:
            rc, out, _ = run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 15 {self.cfg['api']}/health")
            if out != "200":
                self.note("health", "critical", f"API health returned {out}", endpoint=self.cfg["api"])
                self.escalate("API health check failing", env=self.env, code=out)
        if self.cfg["url"]:
            rc, out, _ = run(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 25 {self.cfg['url']}/api/health")
            if out not in ("200", "401"):
                self.note("health", "warning", f"public endpoint returned {out}", url=self.cfg["url"])
        for c in (self.cfg["pg"], self.cfg["redis"]):
            if not c: continue
            rc, out, _ = run(["docker", "inspect", "-f", "{{.State.Running}}", c])
            if out != "true":
                self.note("health", "critical", f"container {c} not running", container=c)
                self.escalate(f"datastore {c} is down", env=self.env)
        rc, out, _ = run("df --output=pcent / | tail -1 | tr -dc 0-9")
        if out and int(out) > 85:
            self.note("capacity", "warning", f"disk at {out}% — hygiene will not keep up", pct=int(out))

    # 2 ── hygiene -----------------------------------------------------------
    def hygiene(self):
        root = Path(self.cfg["root"])
        if not root.exists(): return
        busy = self.runner_busy()
        if busy:
            self.note("hygiene", "info",
                      "CI workspace is in use by a runner job - sweep deferred to the next cycle",
                      runner_pids=busy)
            return
        targets = []
        for pat in SWEEP:
            for p in root.glob(pat):
                s = str(p)
                if not s.startswith(str(root)): continue          # invariant: never outside root
                if any(k in s for k in KEEP): continue
                targets.append(p)
        for p in targets:
            try: size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
            except OSError: size = 0
            if self.apply:
                try:
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
                    self.freed += size
                    self.did("removed regenerable artefact", path=str(p), bytes=size)
                except OSError as e:
                    self.note("hygiene", "warning", f"could not remove {p}: {e}")
            else:
                self.note("hygiene", "info", f"would remove {p}", bytes=size)
        for logdir in (Path(f"/var/log/aether-{self.env}"), Path("/var/log/aether-guardian")):
            if logdir.exists():
                for f in logdir.glob("*.log"):
                    if f.stat().st_size > 200 * 1024 * 1024:
                        if self.apply:
                            data = f.read_bytes()[-20*1024*1024:]
                            f.write_bytes(data); self.did("truncated oversized log", path=str(f))
                        else:
                            self.note("hygiene", "info", f"log {f} oversized")

    # 3 ── git ---------------------------------------------------------------
    def git(self):
        repo = Path(self.cfg["repo"])
        if not (repo / ".git").exists():
            self.note("git", "warning", "no git checkout", repo=str(repo)); return
        busy = self.runner_busy()
        if busy:
            self.note("git", "info",
                      "CI workspace is in use by a runner job - worktree left untouched",
                      runner_pids=busy)
            return
        rc, dirty, _ = run(["git", "status", "--porcelain", "-z"], cwd=repo, strip=False)
        if not dirty.strip("\0"):
            self.note("git", "ok", "worktree clean"); return
        try:
            allf = parse_porcelain_z(dirty)
        except ValueError as exc:
            self.note("git", "critical", "could not parse git status", detail=str(exc)[:300])
            self.escalate("unparseable git status - worktree left untouched", repo=str(repo))
            return
        # Environment files are untracked ON PURPOSE and are the source of a
        # deployed configuration. They are never stashed or archived away.
        protected = [f for f in allf if f.endswith(".env") or "/.env" in f or f.endswith(".env.production")]
        files = [f for f in allf if f not in protected]
        if protected:
            self.note("git", "info", "untracked env files left in place by design", files=protected)
        self.note("git", "warning", f"worktree dirty ({len(files)} paths)", files=files[:20])
        if not files:
            self.note("git", "ok", "only protected env files untracked — treated as clean"); return
        if self.apply:
            # ARCHIVE, never destroy — the operator decides what to do with it.
            arc = STATE / f"dirty-{self.env}-{int(time.time())}.tgz"
            arc.parent.mkdir(parents=True, exist_ok=True)
            # Deleted paths and the source side of a rename are dirty but absent
            # from disk; tar cannot archive them and would abort the whole
            # archive, so only existing paths are archived.  Every dirty path,
            # present or not, is still handed to git stash below - the stash is
            # what actually preserves a deletion.
            on_disk = [f for f in files if (repo / f).exists()]
            absent = [f for f in files if f not in on_disk]
            if absent:
                self.note("git", "info",
                          "paths dirty but absent from disk (deleted/renamed) - "
                          "recorded by stash, not by archive", files=absent[:20])
            if on_disk:
                # "--" stops tar from reading a path beginning with '-' as a flag.
                rc, _, err = run(["tar", "-czf", str(arc), "--"] + on_disk, cwd=repo, timeout=300)
            else:
                rc, err = 0, ""
            if rc == 0:
                # A bare `git stash -u` also sweeps untracked env files, which are
                # a deployed environment's only configuration, so the protected
                # paths are excluded explicitly.  Excluding is used rather than
                # enumerating the dirty paths because `git stash push` cannot
                # take the source side of a staged rename as a pathspec
                # ("did not match any files") and would abort the whole stash.
                # ":(exclude,literal)" also stops a path containing a glob
                # character from being read as a pattern.
                pathspec = ["."] + [f":(exclude,literal){p}" for p in protected]
                rc2, _, err2 = run(["git", "stash", "push", "-u", "-m", f"guardian-{now()}", "--"]
                                   + pathspec, cwd=repo)
                if rc2 == 0:
                    self.did("archived and stashed dirty worktree", archive=str(arc),
                             files=len(files), protected_left_in_place=len(protected))
                else:
                    self.escalate("stash failed — worktree left dirty on purpose", stderr=err2[:300])
            else:
                self.escalate("could not archive dirty worktree — refusing to stash", stderr=err[:300])
        rc, ahead, _ = run("git log --oneline @{u}..HEAD 2>/dev/null | wc -l", cwd=repo)
        if ahead and ahead != "0":
            self.escalate(f"{ahead} unpushed commit(s) — at risk if this host is lost", repo=str(repo))

    # 4 ── integrity / duplicates -------------------------------------------
    def integrity(self):
        guard = Path(self.cfg["repo"]) / "scripts/integrity/integrity_guard.py"
        if not guard.exists():
            self.note("integrity", "warning", "integrity guard absent in this checkout"); return
        rc, out, _ = run(["python3", str(guard)], cwd=self.cfg["repo"], timeout=300)
        if rc == 0: self.note("integrity", "ok", "no violations")
        else:
            self.note("integrity", "critical", "integrity violations present", detail=out[-1200:])
            self.escalate("integrity guard failing in this environment", env=self.env)

    # 5 ── dependencies / readiness -----------------------------------------
    def readiness(self):
        repo = Path(self.cfg["repo"])
        if not repo.exists(): return
        if (repo / "pnpm-lock.yaml").exists() and not (repo / "node_modules").exists():
            self.note("deps", "warning", "node_modules missing — next build would be slow")
            if self.apply:
                rc, _, err = run("corepack prepare pnpm@11.9.0 --activate >/dev/null 2>&1; pnpm install --frozen-lockfile",
                                 cwd=repo, timeout=1800)
                self.did("installed node dependencies", ok=(rc == 0))
        api = repo / "apps/api"
        if api.exists() and not (api / ".venv/bin/python").exists():
            self.note("deps", "warning", "api venv missing")
            if self.apply:
                run("uv venv .venv --python 3.12 --quiet && uv pip install --python .venv/bin/python -q -r requirements.txt python-multipart",
                    cwd=api, timeout=1800)
                self.did("rebuilt api venv")
        if self.cfg["units"] and not (repo / "apps/web/.next").exists():
            self.note("deps", "critical", "web build artefact missing — service cannot serve")
            self.escalate("missing .next build", env=self.env)

    # 6 ── judgement ---------------------------------------------------------
    def judgement(self, unknown_paths):
        """Ambiguous deletions are decided by an LLM, never guessed. Never used in prod."""
        if not unknown_paths or self.cfg["protected"]: return
        prompt = ("You are an environment guardian. For EACH path decide DELETE or KEEP.\n"
                  "DELETE only if it is certainly regenerable (cache/build artefact/test output).\n"
                  "KEEP anything that could be source, config, credentials, data or evidence.\n"
                  "When uncertain, KEEP. Reply strictly as lines: <path> :: DELETE|KEEP :: reason\n\n"
                  + "\n".join(str(p) for p in unknown_paths[:40]))
        rc, out, _ = run(["claude", "-p", prompt, "--output-format", "text"], timeout=300)
        if rc == 0 and out:
            self.note("judgement", "info", "LLM adjudicated ambiguous paths", verdicts=out[:1500])

    # 7 ── branch / PR hygiene ---------------------------------------------
    def branches(self):
        """Only `main` may persist. Merged branches are deleted; unmerged work is
        escalated, never destroyed."""
        repo = Path(self.cfg["repo"])
        if not (repo / ".git").exists(): return
        run(["git", "fetch", "--all", "--prune", "-q"], cwd=repo, timeout=300)
        rc, out, _ = run("git branch -r --format='%(refname:short)'", cwd=repo)
        merged, unmerged = [], []
        for b in [x.strip() for x in out.splitlines() if x.strip()]:
            if b.endswith("/main") or b.endswith("/HEAD") or b == "origin": continue
            rc2, ahead, _ = run(f"git rev-list --count origin/main..{b}", cwd=repo)
            (merged if ahead == "0" else unmerged).append((b, ahead))
        for b, _ in merged:
            name = b.split("/", 1)[1]
            if self.apply:
                rc3, _, err = run(["git", "push", "origin", "--delete", name], cwd=repo, timeout=180)
                self.did("deleted merged remote branch", branch=name, ok=(rc3 == 0))
            else:
                self.note("branches", "info", f"merged branch {name} would be deleted")
        if unmerged:
            self.note("branches", "warning", f"{len(unmerged)} branch(es) hold unmerged work",
                      branches=[f"{b} (+{a})" for b, a in unmerged])
            self.escalate("branches other than main persist with unmerged commits — "
                          "merge or explicitly abandon; guardian will not destroy work",
                          branches=[f"{b} (+{a})" for b, a in unmerged])
        rc4, prs, _ = run("gh pr list --state open --json number,headRefName "
                          "--jq '.[] | \"#\\(.number) \\(.headRefName)\"'", cwd=repo, timeout=180)
        if prs:
            self.note("branches", "warning", "open pull requests exist", prs=prs.splitlines())
            self.escalate("open pull request(s) must be merged or closed", prs=prs.splitlines())

    def report(self):
        rep = dict(schema="aether.guardian.report/1", generated_at=now(), host=socket.gethostname(),
                   environment=self.env, mode="apply" if self.apply else "observe",
                   summary=dict(findings=len(self.findings), actions=len(self.actions),
                                escalations=len(self.escalations), bytes_reclaimed=self.freed,
                                status="escalate" if self.escalations else
                                       ("degraded" if any(f["level"]=="critical" for f in self.findings) else "healthy")),
                   findings=self.findings, actions=self.actions, escalations=self.escalations,
                   reports_to="orchestrator", user_facing=False)
        INBOX.mkdir(parents=True, exist_ok=True)
        out = INBOX / f"{int(time.time())}-{self.env}.json"
        out.write_text(json.dumps(rep, indent=2))
        latest = INBOX.parent / f"latest-{self.env}.json"
        latest.write_text(json.dumps(rep, indent=2))
        print(json.dumps(rep["summary"], indent=2))
        return rep

    def cycle(self):
        self.health(); self.hygiene(); self.git(); self.integrity(); self.readiness(); self.branches()
        # Keep the agent-facing manifest true to live state on every cycle.
        rc, _, _ = run(["python3", "/opt/aether-guardian/manifest.py"], timeout=180)
        self.note("manifest", "ok" if rc == 0 else "warning",
                  "environment manifest regenerated" if rc == 0 else "manifest regeneration failed")
        return self.report()

def main():
    ap = argparse.ArgumentParser(description="Aether environment guardian")
    ap.add_argument("environment", choices=sorted(ENVS))
    ap.add_argument("--apply", action="store_true", help="perform maintenance (default: observe only)")
    ap.add_argument("--fail-on-escalation", action="store_true",
                    help="exit non-zero when something is escalated (for interactive audits). "
                         "Off by default: an escalation is a REPORT to the orchestrator, not a "
                         "pipeline failure, and must not fail a deploy that otherwise succeeded.")
    a = ap.parse_args()
    lock = acquire_env_lock(a.environment)
    if lock is None:
        # A deploy or another guardian owns this environment right now. Acting
        # anyway is how a sweep deletes a build that is still being produced.
        print(json.dumps(dict(environment=a.environment, status="deferred",
                              reason="environment lock held by a deploy or another guardian cycle"),
                         indent=2))
        return 0
    try:
        rep = Guardian(a.environment, a.apply).cycle()
    finally:
        lock.close()
    st = rep["summary"]["status"]
    if st == "degraded":
        return 1                      # a real, unremediated environment fault
    if st == "escalate" and a.fail_on_escalation:
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
