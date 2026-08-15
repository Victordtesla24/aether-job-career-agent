# ORCHESTRATOR EXECUTION PROMPT — Aether Career Agent: Super-Admin, Autonomous-Growth & Pristine-Reset Uplift
### (Deployment-grounded revision — 2026-08-15)

**Agent:** "Orchestrator" — Fable 5 ultracode (1M context) via the `claude-code` CLI, inside the Abacus.AI SuperComputer terminal console.
**Mode:** Fully autonomous. **No user validation, no interactivity, no prompts back to a human.** Run end to end.
**Working tree:** `/home/ubuntu/github_repos/aether-job-career-agent` (branch `main`).
**Production:** https://5cb5f0620.abacusai.cloud  (admin portal at `/admin-login`).
**Completion source of truth:** `/home/ubuntu/aether-market-performance.md` — the Acceptance Ledger (R1–R5 + G1–G7). Do **not** declare COMPLETE until every `[ ]` there is `[x]` with linked, independently-verified proof.
**Companion prior prompt (reuse its pattern, do not contradict it):** `orchestration-execution-prompt.md` (repo root).

> You are the **orchestrator, not the implementer**. You plan, dispatch sub-agents, verify, and rule. You reuse the
> **Agent-Orchestration + Sub-Agent-Swarm** pattern this program has used before (see `docs/delivery/ORCH-*`).
> You optimise **highest quality, 0 regression, and lowest cost simultaneously**. Reuse-over-rebuild is the law of
> this codebase: most "missing" features are already landed. Every rebuild you avoid is cost saved and regression
> risk removed.

---

## 0. OBSERVED DEPLOYMENT STATE — verified 2026-08-15 (read before dispatching anyone)

This section is a **snapshot captured from the live tree and production at authoring time.** Treat it as the
starting map, then have a read-only recon scout **re-verify each fact** (state drifts) and record deltas in
`docs/delivery/ORCH-DELTA-2026-08-15b.md`. Do **not** rebuild anything listed as already-present.

### 0.1 Git / shared-tree hazard — RESOLVE THIS FIRST, before any build
- `main` HEAD is `a8cb21f8` — *"feat(ui-brand WC2): opaque content surfaces"* (2026-08-15 11:13Z).
- `main` is **16 commits ahead of `origin/main`** and carries **~70 uncommitted modified files** — an in-flight
  **"ui-brand" session** is live in this shared tree (dashboards, `/admin/*` pages, `admin.py`, `admin/repositories`).
- A **second worktree** exists: `/home/ubuntu/github_repos/aether-wt-u5d4` on branch
  `feat/u5d4-verification-code-loop` (HEAD `48446945`) with its own uncommitted changes.
- **Mandatory first action (coordinator, you):** read `docs/delivery/SESSION-COORDINATION.md`, then establish a
  clean, attributed baseline. Do **not** stash, revert, or commit another session's in-flight hunks blindly.
  Reconcile via `SESSION-COORDINATION.md` claims: identify which uncommitted hunks are the ui-brand session's,
  claim only files you will touch, and **never restart a service that serves this tree while foreign uncommitted
  work sits in a file it would ship.** Push `main`→`origin/main` (or coordinate who does) so the 16-commit lead is
  durable before Wave work begins. Record the baseline (full backend suite, vitest, e2e, web build) as the
  regression datum (G1).

### 0.2 Production runtime
- `GET /api/health` → `{"status":"ok","version":"0.2.0"}`; `aether-api`, `aether-web`, `aether-worker` **active**.
- **`aether-sales-agent.timer` is `inactive (dead)`** (loaded+enabled, `Trigger: n/a`). The autonomous sales cadence
  is **not currently firing** — this is a live R3 defect to reconcile, not a new build.

### 0.3 R2 (admin super-user) — endpoints that ALREADY EXIST in `apps/api/app/routers/admin.py` (surface in UI, do NOT rebuild)
`DELETE /users/{id}` (soft) · `POST /users/{id}/restore` · `POST /users/{id}/purge` (hard) ·
`POST /users/{id}/suspend` · `/unsuspend` · `/spend-cap` · `/entitlement` · `/password` (reset) · `/identity` ·
`POST /users` (create) · `DELETE /users/{id}/subscription` · `/subscription/cancel` · `/subscription/refund` ·
`POST /users/{id}/subscription/price` (per-user price override) · `GET/POST /promos` · `DELETE /promos/{id}` ·
`GET/POST /sales-agents` · `PATCH /sales-agents/{id}` · `GET /sales-agents/{id}/report` ·
`GET /metrics/executive` · `GET /billing/summary` · `GET /spend` · `GET /audit-log` · `GET/POST /settings` ·
`GET /hygiene` · `POST /hygiene/purge-orphans`.
→ **R2 is a UI-surface + harden + audit-log task**, plus the two genuinely-missing surfaces: **catalog/plan-level
pricing** (per-user override exists; plan-level does not) and the **design-template + footer/footnote editor**.

### 0.4 R4 (networking) — the real build
- `apps/api/app/routers/networking.py` has **only manual Contact CRUD** (`/contacts`, `/outreach`) — there is
  **no Gmail contact extraction** and no auto-sourcing. This is the genuine gap.
- **Reuse, don't reinvent:** `apps/api/app/services/gmail_service.py` and `services/google_oauth.py` already provide
  authenticated Gmail access (two owner Gmail accounts are linked). LinkedIn **export-file ingest already exists**
  (ticket `B7`, `apps/api/tests/test_b7_linkedin_upload.py`) — **NO LinkedIn scraping/automation, ever** (hard rule).
- Build: a Gmail-inbox professional-contact extractor → de-duplicated `Contact` rows → hand-off into the Sales
  Agent lead set, respecting consent + suppression.

### 0.5 R3 (autonomous sales agent) — scaffolding present, autonomy gaps specific
- `apps/api/app/agents/sales_agent.py` `run()` already: `seed_default_campaigns()` (self-seeds campaigns),
  polls flagged Gmail accounts, runs lifecycle nudges, LinkedIn draft authoring, digest. Router
  `apps/api/app/routers/sales_agent.py` exposes `/overview /leads /campaigns(+preview,+PUT) /outreach-log
  /suppressions /run-now /generate /brand/documents /config /sending-accounts` — **every route `AdminUser`-gated.**
- **Genuine gaps:** (a) the **30-min timer is dead** (0.2) so nothing runs unattended; (b) `generate_marketing_content`
  produces text/creative only — there is **no branded animation/video/poster artefact generation with reuse/dedupe**
  (R3.2); (c) confirm the agent needs **zero admin-hand-created campaigns/promos/leads** to do useful work from a
  pristine state (R3.1); (d) the only legitimate remaining human step is **flagging one real sending mailbox**
  (`noSendingAccount` honest-skip today) — that is `BLOCKED-ON-OWNER`, not a design shortcut.
- Reconcile any local vs deployed agent divergence (memory notes commit `95bae7de` local-only) so prod runs the
  intended, tested agent (R3.4).

### 0.6 R1 (dashboards / UI-UX) — honesty + uplift
- Metric surfaces exist server-side (`/metrics/executive`, `/billing/summary`, `/spend`, `/health`, `/audit-log`).
  The ~70 uncommitted ui-brand edits touch nearly every dashboard + `/admin/*` page. R1 = **audit every
  visualisation for honest DB-sourced data** (no fabricated zeros/mock arrays; explicit "no data yet" states),
  add the **"what this tells you / what to do"** affordance, finish the design-system uplift, and drive
  **mobile (`S-UI-B4-MOBILE`) to PASS**, all with **0 visual regression** on approved surfaces.

### 0.7 Prior art to read before dispatching a single implementer (cheap recon swarm)
`README.md` · `docs/delivery/SESSION-COORDINATION.md` (CRITICAL — concurrent session) ·
`docs/delivery/ORCH-RUN-REPORT-2026-08-15.md` · `ORCH-DELTA-2026-08-14.md` · `ORCH-DECISION-LEDGER-2026-08-14.md` ·
`docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md` + `ADR-PROD-TESTDATA-PURGE.md` ·
`docs/delivery/SALES-AGENT-DELIVERY.md` · `docs/subscription/*` · `docs/delivery/DEPLOYMENT-RUNBOOK.md` ·
the design system at `/home/ubuntu/aether_design_system`.

**§0.4 web-build gate & e2e recipe (do not skip):** build in the served tree, confirm a fresh `BUILD_ID`, then and
only then restart; the e2e gate is `pnpm exec playwright test` (the harness server script does not self-run the suite).

---

## 1. Sub-Agent Swarm topology & roles (reuse the prior pattern)

Dispatch specialised, single-purpose sub-agents. **The implementer of a ticket is NEVER its verifier**
(implementer ≠ verifier, enforced on every ticket). Use cross-model adversarial review.

| Role | Job | Model tier (cost rule §6) |
|---|---|---|
| **Recon scouts** | read-only re-verification of §0, delta authoring, evidence gathering | cheapest |
| **Architect** | blueprints for the few genuinely new subsystems (Gmail contact-sourcing, marketing-artefact+reuse pipeline, template/footer editor, timer/autonomy reconciliation) | frontier, sparingly |
| **Implementers** | tests-first then code to green, one ticket each | sonnet-class |
| **Verifiers** | independent RED→GREEN reproduction + targeted regression; reject on any doubt | sonnet-class |
| **Adversarial reviewer** | 3rd-party / independent / honest persona; tries to break each PROD claim | cross-model |
| **Janitor** | executes the production purge ONLY, and is **never the wipe-manifest author** | sonnet-class |
| **Coordinator** | maintains `SESSION-COORDINATION.md` claims, deploy windows, hunk ownership, baseline | you (orchestrator) |

**Swarm rules:** claim files in `SESSION-COORDINATION.md` before dispatch; **hunk-level ownership** on every commit
(`git diff` — every hunk you commit is yours); never restart `aether-api`/`aether-web`/`aether-worker` without a
claimed deploy window; allocate governance/ticket IDs from a fresh range to avoid collisions with the live ui-brand
session; coordinate the `aether-wt-u5d4` worktree so its branch work is not clobbered.

---

## 2. Waves (map 1:1 to the Acceptance Ledger; purge runs LAST)

Sequence to minimise shared-file contention; parallelise within a wave only where files do not overlap with the
live ui-brand session.

- **Wave 0 — Reconcile & baseline (blocking gate, §0.1).** Read prior art, re-verify §0, author
  `ORCH-DELTA-2026-08-15b.md`, resolve the 16-ahead/70-dirty shared-tree state and the second worktree, push a
  durable `main`, and record the green regression baseline. Nothing else starts until this is clean.
- **Wave A — Admin super-user powers (R2).** Surface/complete/harden UI for the endpoints in §0.3
  (delete user soft+hard purge, delete subscription, per-user + **new plan-level** pricing, add/remove users, reset
  passwords, full nav to every `/admin/*` incl. Sales Agent). Build the two missing surfaces: **catalog price
  editor** and **design-template + footer/footnote editor** (reuse the `sales_agent.py` document registry +
  `services/sales_branding.py` / `brand_documents.py`; compliance footer stays DB-enforced, cannot be edited to an
  illegal state). Deleted/suspended users live behind explicit tabs; default view is clean. Audit-log everything.
- **Wave B — Honest dashboards & UI/UX uplift (R1).** Remove fabricated/placeholder metrics; wire every
  visualisation to a real query or an explicit `unavailable` state; add the "what this tells you / what to do"
  affordance with correct units + honest deltas + one-red danger semantics; finish the design-system uplift; drive
  `S-UI-B4-MOBILE` to PASS. 0 visual regression on approved surfaces.
- **Wave C — Autonomous Sales Agent (R3).** Fix the dead 30-min timer and prove the agent runs unattended;
  guarantee it self-authors campaigns/promos/leads from a pristine state (no admin hand-creation, grounding guard
  on); build the **branded marketing-artefact pipeline (animations/short video/posters/creatives) with asset
  reuse/dedupe** on the Aether Career Design System; drive the free→paid funnel autonomously within compliance
  rails; reconcile local vs deployed agent code (R3.4). The single legitimate human step (authorise one real
  sending mailbox) is marked `BLOCKED-ON-OWNER` with everything around it complete and staged.
- **Wave D — Networking contact sourcing (R4).** Build Gmail professional-contact extraction (reuse
  `gmail_service.py`/`google_oauth.py`, both linked owner accounts) + confirm LinkedIn export ingest (`B7`)
  → de-duplicated `Contact` set → seed the Sales Agent's initial target audience. **No LinkedIn automation.**
  Consent + suppression respected; prove the hand-off (sourced contacts become actionable Sales leads).
- **Wave E — Pristine purge (R5), LAST.** After every feature is deployed and verified, a **janitor ≠ manifest
  author** executes `docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md` after a verified backup: platform
  shows a brand-new-subscriber day-one empty state, **owner admin login intact**, billing/financial audit rows
  preserved. Apply the manifest's documented default for each flag F1–F5 and log the decision (esp. F1
  `abhikadam28@gmail.com`, F2 provider credentials KEEP so agents still run, F3 sales rows, F4 orphan subscription
  DELETE, F5 Stripe live customer). Re-verify read-only afterwards.

---

## 3. FULL DELIVERY WORKFLOW — mandatory sequence, per ticket AND per wave

```
Plan
  → Write/Execute Tests (TDD)
    → Build
      → Test (DEV)
        → Push
          → Deploy to Production
            → Verify (PROD)
              → Adversarial Review (PROD, 3rd-party / independent / honest)
```

**3.1 Stage detail**
1. **Plan** — decompose the wave into tickets sequenced from the Acceptance Ledger; record in the delta doc.
2. **Write/Execute Tests (TDD)** — author failing tests FIRST (RED), then run them.
3. **Build** — implement to satisfy the tests (smallest change that turns RED→GREEN; no gratuitous refactor).
4. **Test (DEV)** — run the *verification → error-resolution → refactoring* sub-agent loop until **0** test errors,
   **0** warnings, **0** runtime errors, **0** browser console exceptions.
5. **Push** — commit (hunk-owned) and push only once DEV is clean.
6. **Deploy to Production** — claim a deploy window, promote the verified build per `DEPLOYMENT-RUNBOOK.md`
   (pnpm build in served tree → §0.4 build gate → coordinated api→web→worker restart; re-check `ExecMainStartTimestamp`).
7. **Verify (PROD)** — re-run the same loop in production until the four zeros hold (health 3/3, services active,
   worker + logs clean). Evidence under `uat/reports/evidence/market-perf/<wave>/` (ticket id + UTC, RED and GREEN).
8. **Adversarial Review (PROD)** — an independent, honest, 3rd-party-persona reviewer tries to break each claim in
   production; then run the same loop again until the four zeros hold.

---

## 4. HARD QUALITY GATES (non-negotiable — Acceptance Ledger G1–G7)
- **Regression: 0.** Record the green baseline (backend suite, vitest, e2e, web build) BEFORE any change (Wave 0).
  Attribute every deviation (inherited-from-main / ui-brand-session vs branch-introduced); fix branch-introduced,
  fix-or-route inherited. A green baseline is the definition of "no regression."
- **Quality drift: 0.**
- Every remediation loop (DEV, PROD, Adversarial) reaches **zero** on: test errors, warnings, runtime errors,
  browser console exceptions.
- **Preserved invariants (breaking any is a regression):** owner credential `sarkar.vikram@gmail.com` **never
  rotated or printed**; **BLOCKER-001 / GATE-31 admin guard left intact** (`apps/api/app/repositories/admin.py`);
  compliance gates (unsubscribe footer, suppression list, idempotency, consent provenance) stay **DB-enforced**;
  **no LinkedIn scraping/automation ever**; never delete `sarkar.vikram@gmail.com`; `abhikadam28@gmail.com` handled
  strictly per manifest flag F1.

---

## 5. COMPLETION CRITERIA
- Do **NOT** declare the Orchestrator task **"COMPLETE"** until **every** instruction in
  `/home/ubuntu/aether-market-performance.md` (R1–R5 and G1–G7) is completed **fully and completely**, each checkbox
  flipped to `[x]` with linked, independently-verified proof (test id / commit / screenshot / prod-verify artifact).
- Partial completion, deferral, or "good enough" is **not** COMPLETE.
- The **only** acceptable non-`[x]` terminal state is `BLOCKED-ON-OWNER`: an item blocked solely on an irreducible
  operator/ownership action (authorising a real sending mailbox, a Stripe live-dashboard action, a real-card
  Checkout). It must state the exact one-line action required, with everything around it completed and staged, and
  be surfaced explicitly — never hidden.

---

## 6. EXECUTION CONSTRAINTS
- **No user validation or interactivity.** Run fully autonomously end to end.
- **Review the working-directory documentation first (§0.7) and align with the prior orchestration approach**
  before executing.
- **Cost discipline:** recon/docs/evidence on the cheapest tier; implementers/verifiers sonnet-class; frontier
  reserved for architecture + orchestration rulings. Reuse-over-rebuild rules every ticket (§0.3–0.6). **Reuse
  marketing artefacts and derived data** rather than regenerating (R3.2 dedupe). Coordinate with the concurrent
  ui-brand session and the `aether-wt-u5d4` worktree to avoid double-work.
- **Shared-tree safety:** every unit serves directly from this tree — never restart a service with uncommitted,
  in-flight work in a file it will ship. Claim deploy windows; re-check `ExecMainStartTimestamp` after verifying.
- **Purge runs last**, by a janitor ≠ the manifest author, after a verified backup, so the final delivered state is
  the pristine, brand-new-subscriber state with the owner's admin login intact.

---

## 7. Definition of Done (orchestrator self-check before writing COMPLETE)
1. Every R1–R5 checkbox `[x]` with proof, or the single `BLOCKED-ON-OWNER` exception documented.
2. G1–G7 satisfied; baseline-vs-final diff shows **0 regression**.
3. Production deployed, health 3/3, services active (incl. the **sales-agent timer now live and firing**), logs
   clean; public URL recorded.
4. Pristine wipe executed and verified; owner can log in; dashboards empty; billing audit preserved.
5. A final `docs/delivery/ORCH-RUN-REPORT-2026-08-15b.md` in the house style: **failures/unproven FIRST**, then
   completed work with proof, then the decision ledger and cost notes.
