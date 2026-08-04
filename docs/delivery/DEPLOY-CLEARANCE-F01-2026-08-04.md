# Deploy clearance for the F-01 fix — 2026-08-04T02:35Z

**Purpose.** F-01 (any authenticated customer can read/overwrite/DELETE the operator's deployment-wide LLM
provider credentials) is LIVE and must be deployed the moment its fix is verified. Earlier in this campaign I
HELD a deploy because a concurrent session's uncommitted work would ride along on the restart. This records
why that hold no longer applies, so the F-01 deploy is not blocked by a stale rationale.

## Mechanics (orchestrator-verified, first-hand)

All three backend units serve **directly from the working tree** — there is no build/copy step for the API:

| unit | WorkingDirectory |
| --- | --- |
| `aether-api` | `/home/ubuntu/github_repos/aether-job-career-agent` (via `start-api.sh`) |
| `aether-worker` | `.../apps/api` |
| `aether-discovery` | repo root |

**Consequence, and the thing I had wrong:** uncommitted edits are not "pending deploy" — they go live at the
next restart, and edits older than the last restart are *already serving*. `aether-api` last entered active
state at **2026-08-03 13:58:52 UTC**.

## What a restart right now would actually change

Of the API files dirty in the tree, only two post-date the 13:58:52Z restart. Everything else
(`email_agent.py` 08-03 02:30, `gmail_service.py` 08-03 02:27, `llm_client.py` 08-03 10:23,
`story_dedup_migration.py`/`story_paraphrase.py`/`story_dedup_sweep.py` 08-01) is **already live**.

1. `apps/api/app/routers/agents.py` (08-04 02:11) — the F-01 fix itself, in flight. Intended.
2. `apps/api/app/services/discovery/base_adapter.py` (08-04 02:10) — another session's work, +15 lines,
   `py_compile` clean. It removes a silent fallback: in fixture mode with no recorded fixture for a source,
   the adapter used to fall through to `_fetch_live` and make **real third-party HTTP calls** while `main.py`
   advertised canned fixtures and the module docstring promised no network I/O. It now raises
   `AdapterFetchError` instead.

**Risk of (2) in production: ZERO, and this is the load-bearing check.** The new raise sits inside the
`if fixture_dir:` branch. `AETHER_DISCOVERY_FIXTURE_DIR` is **absent from `.env` (count 0)** and **absent from
the running API process environment (`/proc/<MainPID>/environ`, count 0)**. The branch is unreachable in
production, so the file is behaviourally inert there. It is also a strict improvement for the test suite.

## Ruling

**CLEARED to restart `aether-api` for the F-01 fix**, subject to the fix passing its own tests and review.
This clearance is scoped to the tree state described above — re-verify the two mtime facts immediately before
restarting, because other agents are actively editing this tree and a third post-restart file could appear.

Post-restart verification (all required before declaring F-01 closed):
1. a NON-admin token gets **403** — not 404, not 200 — from GET/PUT/DELETE/verify on `/api/agents/providers*`
2. the owner (isAdmin=true) still gets 200 and can still manage credentials
3. `/api/agents/user/providers` still works for an ordinary user
4. discovery cron still succeeds on its next 30-minute tick (it authenticates as the operator)
5. no new 5xx in the API log window following the restart
