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

---

## DEPLOY HOLD — 2026-08-04T09:20Z (session A)

**Do NOT restart `aether-api` right now.** `apps/api/app/services/ats_engine.py` carries **+405/-6 lines of
uncommitted, in-flight ATS-KW-001 work**. Every unit serves directly from this tree, so a restart would ship
that partial work into production — into the scoring engine that computes the headline number this product
sells. This is the GOV-019 hazard pointed at the worst possible file.

**Ready and waiting to deploy** (committed, pushed, unverified in prod):
- `a090f81` + `0ce7098` — F-02, discovery derived from the user or refused
- `9d3be57` — F-03, upload extraction opt-in
- `5f9e775` — F-04, self-referential market-demand factor deleted
- `52fc727` — restored degraded-semantic and board guards

**Release order once ATS-KW-001 lands:** commit or revert `ats_engine.py` → full backend suite green →
single deploy window claimed here → restart → prod-verify each fix → then the test-data purge (its census
must be taken after the last verification persona is created).

`origin/main` == local `9d3be57` as of 09:15Z — 25 commits that existed only on this VM are now pushed.

---

## DEPLOY SURFACE — measured 2026-08-04T09:45Z (session A)

The tree carries 24 dirty files, but a restart would newly ship only **TWO**. Everything else predates the
current API process (started 03:07:32Z) and is therefore **already serving in production**. Measured by
comparing each file's mtime against `ExecMainStartTimestamp` — worth doing before every deploy, because
"uncommitted" and "not live" are NOT the same thing in this tree.

| file | mtime | status |
|---|---|---|
| `app/routers/agents.py` | 04:38Z | **NEW** — session B's CRITICAL-3b fix, +52 lines, compiles |
| `app/services/ats_engine.py` | 09:40Z | **NEW** — ATS-KW-002 in flight, ACTIVELY BEING EDITED |
| `app/agents/email_agent.py` | 08-03 02:30 | already serving |
| `app/services/gmail_service.py` | 08-03 02:27 | already serving |
| `app/services/llm_client.py` | 08-03 10:23 | already serving |
| `app/services/story_dedup_migration.py` | 08-01 01:02 | already serving |
| `app/services/story_paraphrase.py` | 08-01 00:34 | already serving |

**Assessment of the two:**

1. **`agents.py` — safe and beneficial to ship.** Session B's CRITICAL-3b fix. The circuit breaker parks its
   cooldown in the same `AgentQuotaBlock` row as subscription-quota cooldowns, distinguished only by `reason`,
   and the gates did not read `reason`. So from the *second* attempt onward, an upstream HTTP 402 (**our**
   provider out of credit) was reported to the paying customer as *"Your subscription quota is exhausted…
   switch to API-key billing"* — every clause false, blaming the user for an operator failure, with a remedy
   that cannot work. `board_sweep` compounded it by mapping 429 → `quota-exhausted`, so operator telemetry
   agreed with the lie and hid the dead upstream. This is a customer-facing honesty fix of exactly the class
   this campaign exists to close. It compiles and is raised before any quota reserve, so a refused run
   consumes nothing.
2. **`ats_engine.py` — THE blocker.** Actively being edited by the ATS-KW-002 fix. It is the scoring engine
   that computes the headline number the product sells. Nothing deploys until it is committed or its author
   confirms a stable state.

**Conclusion: the deploy is gated on exactly one file.** When ATS-KW-002 lands: re-run this mtime check,
confirm the pre-deploy review verdict, then take the window.
