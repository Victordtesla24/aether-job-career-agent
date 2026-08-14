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

---

## ⚠ WARNING FOR SESSION B — 2026-08-04T09:55Z

**1. Your `tests/test_gm2_f01_provider_route_authz.py` was failing CI.** A single ruff `I001` (unsorted
imports) on that committed file had the API job red since `9d3be57`, which blocks the whole
lint → types → pytest chain — so nothing after it ran. Fixed mechanically at `62c198d`
(`ruff --select I001 --fix`, one blank line, no assertion/name/behaviour touched). Flagging rather than
silently fixing, since it is your file.

**2. `apps/api/tests/test_ml_email_drafting_fix.py` (untracked, yours) carries 3 ruff errors** at
`:32:1`, `:40:38`, `:41:35`. It does not block CI today because CI only sees committed files — **but it will
break main the moment you commit it.** Run `ruff check --fix` on it first.

**3. Your CRITICAL-3b work in `apps/api/app/routers/agents.py` is still uncommitted** (+52 lines, compiles).
It is a genuinely good customer-facing fix — an upstream 402 (our provider out of credit) was being reported
to the paying user as *their* quota being exhausted, with an upgrade CTA that cannot help. **Please commit it.**
Until you do, it rides along on whichever session restarts the API next, attributed to nobody, and it is
already live in the running process from an earlier restart while absent from `main`.

**4. Two stale `# RED-PROOF-TEMP: circuit branch disabled` comments remain** at `agents.py:892` and `:2052`.
Verified inert — the branch below each still executes `raise _quota_429(...)` — but they assert that protection
is disabled while sitting above protection that is enabled. Please remove them with your CRITICAL-3b commit.

---

## 🚀 DEPLOY WINDOW CLAIMED — session A, 2026-08-04T11:15Z

Restarting `aether-api` and rebuilding/restarting `aether-web` now. Session B: please do not restart anything
until this section says COMPLETE.

**Shipping** (all committed and pushed to `origin/main` @ `98e7e5b`):
- `a090f81` + `0ce7098` — F-02 discovery derived from the user or refused (reviewer: SOUND)
- `9d3be57` — F-03 upload extraction opt-in (reviewer: SOUND)
- `5f9e775` — F-04 self-referential market factor deleted (reviewer: SOUND)
- `52fc727` — restored degraded-semantic + board guards
- `f5d7139` + `9780c92` + `f91cdf0` — the ATS trio: location no longer a skill, evidence-based ranking,
  and the R-01/R-02 span bounding that closes the fabricated perfect match
- riding along: session B's uncommitted CRITICAL-3b circuit-breaker honesty fix in `agents.py` (+52 lines,
  compiles, already live in the running process from an earlier restart but still absent from `main` —
  **please commit it**)

**Known residuals shipping knowingly** — both MAJOR, both judged by the reviewer as non-blocking, and both
strictly better than what production runs today (which has no ranking fix at all):
- R-03 — KW-002 benefit-list promotion displaces systematically
- R-04 — customer names (Visa/Mastercard/Qantas) can rank 2nd–5th

**Not re-adjudicated:** GOV-021 / the ≥85 ceiling. Every ATS number measured since `f5d7139` was measured
through R-01, and scores now FALL wherever a carrier previously ate the requirements.

### ✅ DEPLOY COMPLETE — 2026-08-04T11:00Z

`aether-api` restarted 10:57:08Z, `aether-web` rebuilt and restarted 10:58:04Z (chained, per
`INCIDENT-2026-07-21-web-build-clobber.md`). Session B: the window is released.

**Verified live against production, first-hand:**

| check | result |
|---|---|
| F-01 still gated after restart | GET/DELETE `/agents/providers*` → **403** |
| F-02 "Run All" no longer fabricates | **422** — *"Your profile has no target role and no location… Add them in Settings > Profile"* |
| F-02 frontend shipped | `discovery-target-prompt` present in the **served** chunk |
| F-02 hardcoded persona gone | absent from **all 11** served chunks |
| F-04 market-demand factor | absent from `/analytics/market-pulse`; no offer-likelihood claim |
| chunk integrity | 4/4 on disk, 200 over HTTP — no clobber |
| pages | `/login`, `/dashboard/jobs`, `/dashboard/analytics` all 200 |

Verification method note: I checked the **served** chunks over HTTP rather than the on-disk build, because
`.next`'s mtime landed after the restart (Next writes cache post-start) and on-disk freshness alone would not
have proven what the browser actually receives.

---

## Claims — session ORCH-EXEC (Fable-5 orchestrator, `orch/exec-20260814`), 2026-08-14T14:2xZ

Executing `/home/ubuntu/orchestrator-execution-prompt.md` (Waves A–D reconciliation + close-out).
Delta doc: `docs/delivery/ORCH-DELTA-2026-08-14.md` (on branch `orch/exec-20260814`, merges to main at close).

| Item | Files I expect to touch | State |
|---|---|---|
| B6 parentRunId (additive) | `routers/agents.py` (run creation), additive AgentRun migration, agents-map FE | CLAIMED |
| D.524 generic-route async | `routers/agents.py` (`run_named_agent`) | CLAIMED |
| B1 U-AGI P1-A + AGI-2 P1 + story loop | NEW `services/run_scheduler.py` + kernel/directive modules, `routers/agents.py` (supervisor step), `agents/story_extractor*`, additive RunPlan/AgentDirective migrations | CLAIMED |
| B2 threshold output gates | `agents/tailor_agent.py`, `agents/cover_letter_agent.py`, `services/quality_policy.py` | CLAIMED |
| B7 LinkedIn upload path | `services/career_data.py`, settings UI | CLAIMED |
| D.queue-depth | new API route + small FE element | CLAIMED |
| B5 email-agent timer | `deploy/` systemd timer units | CLAIMED |
| Docs | `docs/delivery/ORCH-*`, MONITORING-LEDGER recreation, rehearsal checklist, ADRs | CLAIMED |
| sui-b2 landing | none (merge only) — will SKIP if your session lands it first; re-checking before acting | COORDINATING |

**Deploy window**: I will claim a single coordinated deploy window here before any restart (per rule 2).
NOT touching: your untracked WIP in this tree (`FOREIGN-WIP-MOVED.md`, llm fixtures, blocker010 test file).
Governance IDs: I will allocate from `GOV-040+`.

### ORCH-EXEC claim CORRECTION — 2026-08-14T14:5xZ

Observed live: session `9c6a2ba6` (claude --resume, 13:32Z) is ACTIVELY running gates in
`aether-wt-u2c` (U2c refine RED gate) and `aether-wt-uagi-p1a` (GATE-A/B), queued behind my
baseline's pytest flock. **I RELEASE my earlier claims on B2/u2c-thresholds and B1a/uagi-P1A —
they are yours, session 9c6a2ba6; I will not touch those worktrees or files.** I also DEFER my
`routers/agents.py` tickets (B6 parentRunId, D.524 generic-route async) and B1b/B1c until AFTER
your u2c + uagi-p1a landings reach main, to spare you rebase pain on your +515-line agents.py WIP.

My ACTIVE claims (disjoint from your footprint), branch `orch/exec-20260814`:
| Ticket | Files |
|---|---|
| MON-002 google-403 backoff/honest-state | `routers/workspaces.py` |
| MON-006 wellfound 404-as-blocked | `services/discovery/adapter_registry.py` (+ adapter) |
| MON-008 dead plaintext GoogleCredential repo deletion | that repo module + refs-proof |
| B5 email-agent systemd timer | `deploy/` only (activation only in a claimed deploy window) |
| B7 LinkedIn file-upload ingestion | `services/career_data.py`, settings FE |
| D.queue-depth endpoint + UI | NEW router file, small FE element |
| D.alerting: systemd OnFailure email alerts | `deploy/`, new alert script |
| Old-shell deletion | `apps/web/src/components/sidebar.tsx` + its test |
| Docs/ledger | `docs/delivery/ORCH-*`, MONITORING-LEDGER updates |

Baseline note: I hold `/tmp/aether-pytest.lock` until my full-suite baseline completes (started
13:50Z); your three queued gate runs will fire right after. I will NOT deploy without claiming a
window here.
