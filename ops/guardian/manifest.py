#!/usr/bin/env python3
"""Generate the canonical environment manifest that EVERY AI agent must load.

Introspects live state (systemd, docker, traefik, git) rather than restating a
hand-written description, so the manifest cannot drift from reality. Regenerated
by every guardian cycle.

Outputs:
  /etc/aether/environments.json   machine-readable
  /etc/aether/ENVIRONMENTS.md     agent-readable briefing
"""
from __future__ import annotations
import json, subprocess, re
from datetime import datetime, timezone
from pathlib import Path

def sh(c, cwd=None, t=60):
    try:
        p = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t, cwd=cwd)
        return p.stdout.strip()
    except Exception:
        return ""

ENVS = [
    dict(name="prod", purpose="Production — real users, real data. Deployed automatically from main.",
         repo="/root/prod/app", url="https://aether.srv1356245.hstgr.cloud",
         api_port=8000, web_port=3200, pg=5434, redis=6381,
         units=["aether-prod-api","aether-prod-web","aether-prod-worker"], auth="public"),
    dict(name="test", purpose="Test/QA — schema mirrors prod, data does NOT. Safe for destructive tests.",
         repo="/root/test/app", url="https://aether-test.srv1356245.hstgr.cloud",
         api_port=8300, web_port=3300, pg=5435, redis=6382,
         units=["aether-test-api","aether-test-web"], auth="basic"),
    dict(name="dev", purpose="Development/staging — day-to-day SDLC work and feature verification.",
         repo="/root/dev/aether-job-career-agent", url="https://aether-dev.srv1356245.hstgr.cloud",
         api_port=8100, web_port=3100, pg=5433, redis=6380,
         units=["aether-dev-api","aether-dev-web"], auth="basic"),
    dict(name="ci", purpose="Ephemeral CI workspace for the self-hosted GitHub Actions runner. Do not edit by hand.",
         repo="/opt/actions-runner/_work/aether-job-career-agent/aether-job-career-agent",
         url=None, api_port=None, web_port=None, pg=None, redis=None, units=[], auth=None),
]

# The guardian timer that regenerates this file. Anything observed here is at
# most this old, and may have been false for almost all of that window.
REGENERATED_EVERY_SECONDS = 900


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe(e: dict) -> dict:
    """Observe one environment's current runtime state.

    Everything returned here is a point-in-time OBSERVATION, not a property of
    the environment: services stop, health flips, worktrees go dirty. It is
    deliberately kept out of the static fields so that a reader can tell the
    two apart, and so that a caller who needs the truth right now can simply
    call this again.
    """
    obs: dict = {"observed_at": now_iso()}
    obs["services"] = {u: sh(f"systemctl is-active {u}") for u in e["units"]}
    if e["api_port"]:
        obs["api_health"] = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://127.0.0.1:{e['api_port']}/health")
    r = Path(e["repo"])
    if (r / ".git").exists():
        obs["git"] = dict(commit=sh("git rev-parse --short HEAD", cwd=r),
                          branch=sh("git branch --show-current", cwd=r),
                          dirty_paths=len([l for l in sh("git status --porcelain", cwd=r).splitlines() if l]))
    return obs


def build():
    for e in ENVS:
        e["observed"] = probe(e)
    m = dict(
        schema="aether.environments/1",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        host="srv1356245 (Hostinger VPS, 4x EPYC, 16GB, 193GB)",
        read_this_first=(
            "You are working on a host with THREE persistent application environments plus one "
            "ephemeral CI workspace. Load this manifest BEFORE doing any work. Do not spend tokens "
            "rediscovering ports, paths, repositories or URLs — those are listed here and are "
            "stable. The `observed` block on each environment is NOT stable: it is a snapshot from "
            "when this file was last written and may be up to 15 minutes old. Never tell anyone an "
            "environment is healthy on the strength of it — re-probe first (see `observations`). "
            "Do not perform environment or server management unless explicitly asked: a guardian "
            "agent already owns that for every environment."
        ),
        observations=dict(
            what="each environment's `observed` block is a snapshot, stamped with its own observed_at",
            regenerated_every_seconds=REGENERATED_EVERY_SECONDS,
            stale_after_seconds=REGENERATED_EVERY_SECONDS,
            do_not="report an environment healthy, or a worktree clean, from this file alone",
            live_endpoint="http://127.0.0.1:9400/manifest — re-probes every environment on request",
            live_command="python3 /opt/aether-guardian/manifest.py  (rewrites this file)",
        ),
        environments=ENVS,
        guardians=dict(
            model="one autonomous guardian per environment (systemd timer, every 15 min)",
            duties=["health + auto-restart","hygiene (caches, build artefacts, oversized logs)",
                    "git worktree cleanliness (dirty work archived, never destroyed)",
                    "integrity guard R1-R7","dependency + build readiness",
                    "branch/PR hygiene R8 (merged branches deleted, unmerged escalated)"],
            reporting="guardians never talk to users; they write JSON to the orchestrator inbox only",
            inbox="/var/lib/aether-orchestrator/inbox",
            invoke="python3 /opt/aether-guardian/guardian.py <prod|test|dev|ci> [--apply]",
        ),
        realtime_logs=dict(
            why="full unfiltered runtime console output, so you never guess at a failure",
            local="http://127.0.0.1:9400/logs/<stream>?tail=200   and  /logs/<stream>/follow (SSE)",
            remote="https://aether-logs.srv1356245.hstgr.cloud (basic auth)",
            streams=sorted(["prod-api","prod-web","prod-worker","dev-api","dev-web","test-api","test-web",
                            "guardian-prod","guardian-dev","guardian-test","guardian-ci",
                            "journal-prod","journal-dev","journal-test","journal-ci"]),
            guardian_reports="/guardian/<env>",
        ),
        delivery=dict(
            pipeline=".github/workflows/vps-delivery.yml",
            flow="push to main -> verify -> deploy dev -> deploy test -> deploy production (auto)",
            rollback="production rolls back to the previous commit automatically if its smoke test fails",
            deploy_tool="/opt/aether-guardian/deploy_env.sh <env> [--rollback-on-failure]",
        ),
        constraints=dict(
            file="/root/dev/aether-job-career-agent/scripts/integrity/NON-NEGOTIABLE-CONSTRAINTS.md",
            enforced_by=["pre-commit hook","blocking CI step","systemd ExecStartPre runtime guard"],
            summary="no fabricated code/data/credentials, no masked errors, no disabled verification, "
                    "no duplicate or misplaced files, no partial work reported as complete, "
                    "main is the only long-lived branch",
        ),
        decommissioned=dict(abacus_vm="https://5cb5f0620.abacusai.cloud — migrated away 2026-08-17; "
                                      "its database was private-network only. Do not reference it."),
    )
    Path("/etc/aether/environments.json").write_text(json.dumps(m, indent=2) + "\n")

    L = ["# Aether environments — READ BEFORE ANY WORK", "",
         f"_Auto-generated {m['generated_at']}. Do not hand-edit._",
         "",
         f"> Ports, paths, URLs and purposes below are stable. Anything describing **current state** "
         f"— service status, API health, commit, dirty paths — was observed when this file was "
         f"written and is regenerated every {REGENERATED_EVERY_SECONDS // 60} minutes. "
         f"Do not report an environment healthy from this file: "
         f"`curl -s http://127.0.0.1:9400/manifest` re-probes on request.",
         "",
         m["read_this_first"], "",
         "| env | purpose | url | api | web | pg | redis |", "|---|---|---|---|---|---|---|"]
    for e in ENVS:
        L.append(f"| **{e['name']}** | {e['purpose']} | {e['url'] or '—'} | {e['api_port'] or '—'} | "
                 f"{e['web_port'] or '—'} | {e['pg'] or '—'} | {e['redis'] or '—'} |")
    L += ["", "## Repositories", "",
          "_Commit and dirty-path counts below are observations, not guarantees._", ""]
    for e in ENVS:
        obs = e.get("observed", {})
        g = obs.get("git", {})
        L.append(f"- `{e['repo']}` — {e['name']} @ {g.get('commit','?')} ({g.get('branch','?')}), "
                 f"dirty paths: {g.get('dirty_paths','?')} "
                 f"(observed {obs.get('observed_at','?')})")
    L += ["", "## Real-time runtime console logs", "",
          "Do not guess at failures — read the server's own output:", "",
          "```bash",
          "curl -s 'http://127.0.0.1:9400/logs/prod-api?tail=200'      # recent",
          "curl -sN 'http://127.0.0.1:9400/logs/prod-api/follow'       # live (SSE)",
          "curl -s  http://127.0.0.1:9400/guardian/prod                # guardian report",
          "```", "",
          "Remote (basic auth): https://aether-logs.srv1356245.hstgr.cloud", "",
          "## Guardians", "",
          "Every environment has an autonomous guardian (systemd timer, 15 min). They handle health,",
          "hygiene, git cleanliness, integrity and branch policy, and report only to the orchestrator.",
          "**Do not do environment or server maintenance yourself** unless explicitly asked — it is",
          "already owned, and duplicating it wastes tokens and causes conflicts.", "",
          "## Delivery", "",
          f"{m['delivery']['flow']}. {m['delivery']['rollback']}", "",
          "## Non-negotiable constraints", "",
          f"Read `{m['constraints']['file']}` before writing code.",
          f"Enforced by: {', '.join(m['constraints']['enforced_by'])}.", ""]
    Path("/etc/aether/ENVIRONMENTS.md").write_text("\n".join(L))
    return m

if __name__ == "__main__":
    m = build()
    print(f"manifest written: {len(m['environments'])} environments, "
          f"{len(m['realtime_logs']['streams'])} log streams")
