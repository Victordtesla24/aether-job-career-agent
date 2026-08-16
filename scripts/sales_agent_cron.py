#!/usr/bin/env python3
"""Scheduled Sales Agent run — invoked by ``aether-sales-agent.timer`` every
30 minutes (in-process CLI: no HTTP, no login, no credentials beyond the repo
``.env`` the API itself uses).

Behaviour:
* Loads the repo-root ``.env`` (existing environment wins — same convention
  as ``scripts/discovery_cron.sh`` / ``start-api.sh``), so the feature flags
  ``AETHER_SALES_AGENT_ENABLED`` / ``AETHER_SALES_AGENT_DRY_RUN`` are read
  fresh on EVERY run — flipping shadow mode off needs no service restart.
* Calls :func:`app.agents.sales_agent.run_sales_agent` directly and prints
  the structured result as JSON (systemd journal + log file friendly).
* Exit codes: 0 = ran (or honest no-op while disabled); 1 = fatal error.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "apps" / "api"


def load_env(env_file: Path) -> None:
    """Repo .env loader — existing environment variables win (no override)."""
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def main() -> int:
    load_env(REPO_ROOT / ".env")
    sys.path.insert(0, str(API_DIR))
    from app.agents.sales_agent import run_sales_agent  # noqa: PLC0415

    try:
        result = run_sales_agent(trigger="timer")
    except Exception as exc:  # noqa: BLE001 — fatal: exit non-zero for systemd
        print(
            json.dumps({"ran": False, "fatal": str(exc)}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, default=str))
    # The structured payload is for machines; this one line is for the human
    # reading the journal — a run of zeros must say why it is zero.
    if result.get("explanation"):
        print(f"[sales-agent-cron] {result['explanation']}")
    if result.get("ran") and result.get("errors"):
        # Partial errors are logged but the run itself completed — exit 0 so
        # systemd doesn't mark the unit failed for a single bad message.
        print(
            f"[sales-agent-cron] completed with {len(result['errors'])} "
            "non-fatal error(s)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
