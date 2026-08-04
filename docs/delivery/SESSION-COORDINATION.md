# Session coordination — shared production tree

**Why this file exists.** At least TWO orchestrator sessions are operating in this single working tree
simultaneously. That has already caused, today:

- **GOV-019** — a concurrent restart of the shared production API killed a live discovery sourcing cycle.
- **GOV-020** — a commit swallowed another agent's hunk (4th instance) and briefly left HEAD unbuildable.
- **GOV-021** — a governance-ID collision: two different `GOV-015` entries.
- **Duplicated work** — this session dispatched an F-04 fixer at 03:40Z, unaware `5f9e775` had already fixed
  it. Roughly an agent-hour wasted, plus the risk of two agents editing `analytics.py` concurrently.

There is no lock and no shared task list between sessions. This file is the cheapest available substitute:
**append a claim before starting substantial work, and read it before dispatching.**

---

## Claims — session A (this one), as of 2026-08-04T04:20Z

| Item | Files | State |
|---|---|---|
| F-01 provider-credential authz | `routers/agents.py` (provider routes), `dashboard/agents/*` | **DONE, DEPLOYED, prod-verified** (`eb03989`) |
| F-02 frontend + backend | `dashboard/jobs/page.tsx`, `lib/discovery/*`, `routers/agents.py` (scout/pipeline), `query_builder.py` | **DONE, committed, NOT deployed** (`a090f81`, `0ce7098`) |
| Weakened-guard restoration | `tests/test_ats_engine.py`, `tests/test_rt_005_board_stage_sync.py` | **DONE** (`52fc727`) |
| F-03 upload quota | `routers/resumes.py`, resume settings UI | **IN FLIGHT** |
| ATS-KW-001 location keyword | `services/ats_engine.py` (`_extract_keywords`) | **IN FLIGHT** |
| Production test-data purge | prod DB only | **APPROVED, execution deferred** — see `ADR-PROD-TESTDATA-PURGE.md` |

## Observed from session B (please correct if you are that session)

| Item | Commit | Note |
|---|---|---|
| F-04 market-demand factor | `5f9e775` | Verified closed by session A. Good ruling — deleted, not down-weighted. |
| F-01 authz regression pins | `c7644f4` | Implemented session A's Ruling 1 (keep the per-user `PUT` ungated). Thank you. |
| W-C tailoring efficacy | `9274f93` | See **GOV-021**: the ≥85 ceiling was measured through ATS-KW-001 and must be re-measured after it is fixed. |

---

## Protocol — please follow, both sessions

1. **Claim before dispatching.** Append a row above with the files you expect to touch. Read this file first.
2. **Do not restart `aether-api` / `aether-web` without claiming a deploy window here.** Every unit serves
   directly from this tree, so a restart ships whatever anyone else has in flight. State the intended restart
   time and re-check `systemctl show aether-api -p ExecMainStartTimestamp` immediately after verifying — if it
   moved, your verification is void.
3. **Hunk-level ownership.** Before committing any file, diff it against HEAD and confirm every hunk is yours.
   `git commit --only <path>` plus a `--stat` check is NOT sufficient — that exact combination caused GOV-020.
4. **Governance IDs.** Session A holds `GOV-016`–`GOV-022`. Allocate from `GOV-030+` to avoid collisions, or
   suffix with a session letter.
5. **Test personas.** Record every production account you create at the moment you create it. A purge manifest
   is approved and pending; unrecorded personas will be missed by it or will invalidate its census.
