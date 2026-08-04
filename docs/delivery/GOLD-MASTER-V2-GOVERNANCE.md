# GOLD-MASTER-V2 — Governance Log

Run: GOLD-MASTER-V2 · Prompt: `/home/ubuntu/aether-gold-master-execution.md`
Orchestrator: claude-opus-5 (xhigh, brain-only per §0.1)
Started: 2026-07-30T22:36Z

Every deviation from the prompt-as-written, every governance violation, and every orchestrator
adjudication is recorded here with evidence. Prior reports are TESTIMONY; only `[VERIFIED]` closes.

---

## GOV-001 — §0.2 roster pins two model IDs that do not exist in this runtime

**Severity:** CRITICAL (blocked 9 of 15 sub-agent types from dispatching)
**Status:** RESOLVED
**Detected:** 2026-07-30T23:0xZ, when the first sonnet-tier agent (`reviewer`) was dispatched.

### Evidence `[VERIFIED]`
Dispatch of the `reviewer` sub-agent terminated immediately with:

> `Agent terminated early due to an API error: There's an issue with the selected model
> (claude-sonnet-4). It may not exist or you may not have access to it.`

§0.2 of the prompt pins `model: claude-sonnet-4` (6 agents) and `model: claude-opus-4` (3 agents).
Neither model ID is available in this runtime. The models that ARE available are
`claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`, `claude-fable-5`.

Confirmed working this run before the repair: `claude-haiku-4-5` (`scout`, `evidence`,
`infra-discovery`, `researcher` all dispatched and returned artifacts).

### Impact
9 of the 15 §0.2 roster agents — `test-author`, `fixer-medium`, `screen-tester`, `reviewer`,
`doc-updater`, `ai-loop-engineer` (sonnet tier) and `fixer-hard`, `qa-adversary`, `risk-officer`
(opus tier) — could not run at all. Only haiku-tier mechanical/monitoring/evidence work was
completing, which presented externally as sub-agents "idling and queued". A further 6 non-roster
agent files carried the same dead pins.

### Adjudication
§0.2 forbids `model: inherit` and pins a model per agent; its INTENT (§0.3 rule 1) is a strict
cost-optimal tiering: haiku for mechanical/monitoring/evidence, sonnet for code
authoring/fixing/testing/review, opus only where judgment failure is expensive. The pinned IDs are
stale relative to this runtime. Honouring the literal IDs is impossible; honouring the TIERING is
both possible and clearly the operative requirement.

**Ruling:** remap to the nearest available model in the SAME tier. `model: inherit` remains
forbidden and is still absent (0 occurrences). No agent was moved across tiers, so §0.3's
cost-optimality is preserved exactly.

| §0.2 pinned ID | Availability | Remapped to | Tier preserved |
|---|---|---|---|
| `claude-haiku-4-5` | available | unchanged | mechanical |
| `claude-sonnet-4` | **does not exist** | `claude-sonnet-5` | authoring |
| `claude-opus-4` | **does not exist** | `claude-opus-5` | judgment |
| `claude-opus-4-8` (non-roster files) | **does not exist** | `claude-opus-5` | judgment |

### Repair `[VERIFIED]`
15 agent definition files rewritten in `.claude/agents/` (backup taken first). Post-repair audit:

- §0.2 roster: 15/15 present, all on an existing model, tiering intact
- `model: claude-sonnet-4` / `claude-opus-4` / `claude-opus-4-8` remaining: **0**
- `model: inherit` remaining: **0**

Roster manifest: `uat/reports/evidence/gold-master-v2/phase0/ROSTER-MANIFEST.md`

---

## GOV-002 — Workflow-tool concurrency is capped to ~1 agent on this 2-vCPU VM

**Severity:** HIGH (throughput, not correctness)
**Status:** RESOLVED (orchestration strategy changed)

### Evidence `[VERIFIED]`
`nproc` = **2**. The Workflow tool caps concurrent sub-agents at `min(16, cores - 2)` =
`min(16, 0)` → effectively **1**. Every `parallel()` fan-out was therefore serialized into a queue
irrespective of how many thunks were passed. Load average during Phase 0 reached 3.04 on 2 cores
(pytest ~28% CPU + headless Chromium ~45%).

### Adjudication
§0.3 rule 4 caps parallelism at "≤ 4 concurrent task agents + 2 always-on monitors". That ceiling
is a COST control, not a throughput floor, and the runtime was enforcing a far lower one.

**Ruling:** parallel work is dispatched via direct Agent fan-out (multiple invocations in a single
message), which is not subject to the core-derived cap, holding to §0.3's ≤4 ceiling. The Workflow
tool is retained only for genuinely sequential pipelines.

Two serializations are retained DELIBERATELY and must not be "optimised away":
1. **`flock /tmp/aether-pytest.lock` around every pytest run.** All runs share the single
   `aether_test` Postgres schema; concurrent `TRUNCATE` produces non-deterministic failures, and a
   mis-scoped run previously wiped the PRODUCTION database
   (`docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`). Safety outranks wall-clock.
2. **At most one CPU-heavy job (pytest OR a headless browser) in flight.** On 2 cores, stacking
   browsers increases wall-clock. Concurrency is therefore biased toward token/IO-bound agents.

---

## GOV-003 — §1.2 / §8 endpoint-absence claims are stale testimony

**Severity:** MEDIUM (scope accuracy)
**Status:** ADJUDICATED

### Evidence `[VERIFIED]` (direct source probe, `apps/api/app/routers/`)
The prompt asserts no stage-move endpoint and no approvals delete/purge endpoint exist. Probe:

| Prompt claim (§1.2, §8) | Reality |
|---|---|
| "no stage-move endpoint or drag/move UX exists" | `POST /applications/{application_id}/move` **exists** — `applications.py:323`; also `POST /applications/pipeline/{job_id}/move` — `applications.py:255` |
| "No delete/dismiss endpoint exists on the approvals router" | `DELETE /approvals/{approval_id}` **exists** — `approvals.py:139` |
| (§8.2 implies purge absent) | `POST /approvals/purge-expired` **exists** — `approvals.py:112` |

Genuinely absent, confirmed: `PATCH /applications/{id}/stage`; `GET /agents/runs/{run_id}/stream` (SSE).

**Correction (2026-07-30T23:2xZ):** an earlier revision of this entry also listed "any endpoint exposing
job-source availability" as absent. That was WRONG. `GET /agents/scout/sources/availability` **exists** —
`apps/api/app/routers/agents.py:2167` — and the Jobs screen already consumes it
(`apps/web/src/app/dashboard/jobs/page.tsx:854`, confirmed by both the W-D researcher and the Phase 0
SCREEN-MATRIX). Consequently §6.2.3's premise is also stale: the frontend does NOT hardcode Seek as
"(unavailable)"; it derives availability from this backend endpoint. Finding `ML-audit-seek-fe-hardcode-001`
is already remediated and must not be "re-fixed".

### Adjudication
§8.1 names `PATCH /applications/{id}/stage` explicitly, while §13.1 forbids duplicate modules and
functions. Building a second, independent stage-move implementation would satisfy the first and
violate the second.

**Ruling:** build the named `PATCH /applications/{id}/stage` as the CANONICAL stage-move endpoint,
and refactor the existing `POST .../move` handlers to delegate to one shared transition service.
The prompt's named endpoint ships; no logic is duplicated. Backward compatibility of the existing
POST routes is retained so no current caller breaks.

The existing approvals `DELETE` and `purge-expired` endpoints are NOT rebuilt. §8.2's requirements
are re-scoped to VERIFY their behaviour against the stated contract (owner-scoping, idempotency,
honest 404/403, 48h expiry check that must not touch non-expired pending approvals, audit logging)
and to build the frontend affordances, which remain unverified.

---

## GOV-004 — Prod "before-record" visual-classification column is unreliable

**Severity:** LOW (artifact quality)
**Status:** NOTED — superseded by §3.2 per-screen testing

`BEFORE-RECORD.md` labels all 26 routes `Visual: error` while simultaneously reporting 0 console
errors on every route. Orchestrator spot-check of `before/dashboard.png` shows a correctly
authenticated dashboard rendering real production data (47 active applications, real agent-activity
timeline, real job cards). The `visual` column is a false classification produced by the capture
script's heuristic; the SCREENSHOTS themselves are sound and are retained as the "before" baseline.

The column is not relied upon. §3.2 per-screen human-grade testing supersedes it.

---

## GOV-005 — Active agent registry is user-scoped and cached at session start

**Severity:** HIGH (blocked dispatch; forced role substitutions)
**Status:** RESOLVED (with documented substitutions)

### Evidence `[VERIFIED]`
Two `.claude/agents/` directories exist:
- `/home/ubuntu/.claude/agents/` — the ACTIVE registry (primary working directory is `/home/ubuntu`)
- `/home/ubuntu/github_repos/aether-job-career-agent/.claude/agents/` — a shadow copy, NOT loaded

GOV-001's first repair was applied only to the repo copy, so the dead `claude-sonnet-4` pin persisted and the
re-dispatched `reviewer` failed identically a second time. The repair was then applied to the user-scoped
registry, after which the sonnet tier dispatched successfully.

Separately, the harness snapshots the registry at SESSION START. Three §0.2 roster agents absent from the
user-scoped registry at session start — `janitor`, `risk-officer`, `ai-loop-engineer` — were copied in but
remain undispatchable this session (`Agent type 'risk-officer' not found`).

### Adjudication
§0.4 requires separation of duties by ROLE (tester ≠ fixer ≠ test-author ≠ reviewer ≠ qa-adversary; janitor
executes approved deletions but never selects them). The role separation, not the filename, is the requirement.

**Ruling:** for the three unregistered roles, dispatch an available agent type at the SAME model tier, framed
explicitly in-prompt with the required role, constraints and prohibitions. Separation of duties is preserved by
never assigning a substitute the same task it (or its author) previously performed.

| §0.2 role | Tier | Substitute used this session | Separation preserved by |
|---|---|---|---|
| `risk-officer` | opus | `qa-adversary` + `model: opus` | never the researcher who produced the evidence |
| `ai-loop-engineer` | sonnet | `fixer-hard`/`fixer-medium` + role framing | never reviews its own diff |
| `janitor` | haiku | `deployer`/`general-purpose` + manifest-only framing | executes an approved manifest exactly; never selects deletions |

Additionally, every Agent dispatch this run passes an EXPLICIT `model` override (documented to take precedence
over frontmatter), so a stale cached pin can never silently stall a sub-agent again.

---

## GOV-006 — First baseline (Step 6) was corrupted by an orphaned process tree

**Severity:** MEDIUM (evidence integrity)
**Status:** RESOLVED — clean re-run dispatched

### Evidence `[VERIFIED]`
The Phase 0 workflow was interrupted when its host process exited; its detached
`run_pytest_bg.sh → flock → pytest` tree (PIDs 251801/251804/251805) kept running. On resume, a second pytest
invocation started. The `flock /tmp/aether-pytest.lock` wrapper correctly serialized DB ACCESS — the shared
`aether_test` schema was never concurrently truncated — but the LOG PATH was not lock-protected, so each
writer's `>` redirect truncated the other's output. The resulting `pytest-baseline.log` was 9 lines with no
final summary and without the `schema=aether_test` safety line.

At 15:06 elapsed the orphan was in `futex_wait` with system load at 0.83 — stalled, not progressing, while
holding the pytest lock and blocking any clean baseline.

### Action taken
Orphan tree terminated (a process this run started, via the interrupted workflow); lock confirmed re-acquirable;
corrupted log quarantined to `logs/quarantine-collided/`. A clean full-suite re-run was dispatched to a
SESSION-UNIQUE log filename, run in the foreground, with a mandatory check that the `schema=aether_test` safety
line is present before the counts are trusted.

**Standing rule for the rest of this run:** every suite invocation writes to a session-unique, timestamped log
path. Never a shared fixed filename.

### Carried forward as findings (not fixed here)
- Playwright baseline: **EXIT_CODE=1 — 12 failed / 40 passed**. Predominantly 390px horizontal-overflow
  assertions (`/admin/settings`, `/admin/users`, `/dashboard/resume`, `/dashboard/agents`, settings 422 path)
  plus functional failures: per-agent model persistence after reload (`ml-agents-refix`), internal-email
  allowlist save (`gap_p7_def_b`), approvals page at mobile viewport (30s timeout), and a
  `baseline-manual-verification` sweep failing in 2ms (likely setup). §14.1/G-N require these green.
- vitest: EXIT_CODE=0, coherent single report, 156s — trustworthy.

---

## GOV-007 — §11.1 realtime description contradicted by code inventory

**Severity:** MEDIUM (scope accuracy)
**Status:** OPEN — to be resolved in W-I

§11.1 states current polling is "20s (jobs, applications), 30s (sidebar), 60s (topbar)". The Phase 0
SCREEN-MATRIX finds instead: 3000ms async JOB-RUN polling (`agents.ts:57–107`, 10-minute cap) on
`/dashboard/agents`, `/dashboard/cover-letters`, `/dashboard/resume`, `/dashboard/stories`; load-once-on-mount
on `/dashboard`; and STATIC one-time fetch on every other route — i.e. no periodic data refresh at all on most
screens. W-I must re-verify against the live bundle before implementing, and treat the SCREEN-MATRIX (fresh
evidence) over the prompt's framing (testimony).

---

## GOV-008 — §6/§1.2 Seek premise contradicted by primary sources

**Severity:** CRITICAL (legal/compliance; changes a workstream outcome)
**Status:** OPEN — binding adjudication in flight with acting risk-officer

§1.2/§1.3/§6.1 assert Firecrawl is "a licensed intermediary, not raw scraping" and that ADR-P6-SEEK's
prohibition therefore does not apply. Live research this run found the opposite: Seek ToS clause 4(d) bans
automated data gathering without written consent (no direct-vs-intermediary carve-out); `au.seek.com/robots.txt`
(retrieved 2026-07-30T23:10:30Z) disallows `*/job/` and `/api/jobsearch/` and names `anthropic-ai` explicitly as
a disallowed agent; and Firecrawl's documentation makes no licensed-intermediary representation and does not
address target-site ToS compliance.

Per §6.2.1 and §1.3 the risk-officer gate must clear BEFORE any env or code change. No `.env` change and no code
change has been made. Ruling pending; this run will NOT enable `AETHER_ENABLE_SEEK` unless the adjudication
returns APPROVED on the evidence.

---

## GOV-009 — Sub-agents reporting "completed" without producing their deliverable

**Severity:** HIGH (silent non-delivery; a fake-green class)
**Status:** MITIGATED — standing dispatch rules added

### Evidence `[VERIFIED]`
Three sub-agents this run returned a `completed` status while their required artifact did not exist on disk,
or their task had not actually finished:

1. **§4.1 triage (first attempt).** Burned 149k tokens / 30 tool calls / 13 min. Final message: *"waiting on
   the frontend fork's complete 128-row table before finalizing the inventory."* Neither
   `docs/delivery/INCOMPLETE-FEATURE-INVENTORY.md` nor its `.json` existed. Root cause: it spawned its own
   sub-forks and blocked on them, despite the brief's explicit "ALWAYS write the artifact, even on error".
2. **Clean pytest baseline.** Final message: *"I'll stop polling now and simply wait for the background task's
   completion notification."* It had backgrounded pytest contrary to an explicit foreground instruction and
   exited. The run itself was sound (PID 270030, session-unique log, `schema=aether_test` safety line present),
   but no counts were extracted and `BASELINE-SUITES.md` was not updated.
3. **Orphaned frontend fork.** Delivered a complete 128-row triage table ONLY as a relayed peer message, never
   to disk. Preserved manually by the orchestrator to
   `uat/reports/evidence/gold-master-v2/phase0/INCOMPLETE-FEATURE-INVENTORY-FRONTEND-forkA.md`, explicitly
   marked TESTIMONY rather than [VERIFIED].

### Why this matters
§0.5 forbids closing findings without fresh evidence and forbids "already done" wave-throughs. An agent
returning a confident prose summary with no artifact behind it is exactly the failure mode those rules exist to
catch. Orchestrator verified each deliverable on disk rather than trusting the completion status — which is why
all three were caught.

### Standing dispatch rules (applied to every subsequent sub-agent brief)
1. **Sub-agents MUST NOT spawn their own sub-agents/forks.** Serial work only. Fork coordination is the
   observed cause of failure 1.
2. **Write the artifact EARLY and INCREMENTALLY** — skeleton first, append as you go. An incomplete file on
   disk with an honest coverage marker is a SUCCESS; producing nothing is a FAILURE.
3. **Long jobs run in the FOREGROUND** with a generous timeout. No background wrapper scripts, so the agent
   cannot exit while its own work is still running.
4. **Split oversized scopes across agents** (e.g. backend/frontend) rather than one agent fanning out.
5. **Orchestrator verifies every artifact exists on disk before accepting any completion claim.** A sub-agent's
   own report is TESTIMONY.

---

## GOV-010 — Orchestrator erroneously reverted the GOV-001 model remap

**Severity:** MEDIUM (self-inflicted; caught and corrected within minutes, no work lost)
**Status:** RESOLVED
**Detected + corrected:** 2026-07-31T00:0xZ, by the orchestrator, on itself.

### What happened
On returning from the Phase 0 workflow the orchestrator observed 14 `.claude/agents/*.md` files with
rewritten `model:` frontmatter (`claude-sonnet-4` → `claude-sonnet-5`, `claude-opus-4` → `claude-opus-5`)
and, without first reading this governance log, diagnosed it as a sub-agent scope violation. It ran
`git checkout -- .claude/agents/`, restoring the literal §0.2 pins, and logged the "violation".

That diagnosis was **wrong on both counts**:

1. The rewrite was the GOV-001 repair — a documented, evidence-backed adjudication remapping two model
   IDs that **do not exist in this runtime** onto the nearest available model in the SAME tier. Reverting
   it re-introduced dead pins that make 9 of the 15 §0.2 roster agents undispatchable.
2. The revert was applied to `…/aether-job-career-agent/.claude/agents/` — which GOV-005 establishes is a
   **shadow copy that is not loaded**. The ACTIVE registry is `/home/ubuntu/.claude/agents/` (the primary
   working directory is `/home/ubuntu`). The revert therefore had no effect on dispatch at all; it only
   desynchronised the two directories.

### Verification performed before correcting `[VERIFIED 2026-07-31T00:0xZ]`
- `nproc` = **2** → the Workflow tool's `min(16, cores-2)` cap is effectively **1** concurrent sub-agent.
  GOV-002 independently confirmed. Dispatch strategy for the remainder of this run is **direct Agent
  fan-out**, held to the §0.3.4 ceiling of ≤ 4 concurrent task agents + 2 monitors.
- Active registry enumerated: `/home/ubuntu/.claude/agents/` — 28 files, all 15 roster roles present
  (including `janitor`, `risk-officer`, `ai-loop-engineer`), all on existing models.
- Live dispatch probe of a sonnet-tier agent (`fixer-medium`) returned its expected result, confirming
  the remapped tier dispatches successfully.

### Correction
The repo shadow copy was re-synchronised to the GOV-001 mapping. Post-correction audit of the shadow:
**15/15 roster roles present, dead pins (`claude-sonnet-4` / `claude-opus-4` / `claude-opus-4-8`) = 0,
`model: inherit` = 0.** The active registry was already correct and was not touched.

### Adjudication carried forward
GOV-001's ruling stands and is **adopted by this orchestrator**: §0.2's INTENT is the strict cost-optimal
tiering of §0.3 rule 1, not the literal string of two now-nonexistent model IDs. Tiers are preserved
exactly; no agent moved tier; `model: inherit` remains forbidden and absent.

### What the earlier GOV-010 draft got right, and what it did not
The same erroneous entry also alleged that sub-agents had self-approved workstreams by calling
`TaskUpdate` (marking W-D `completed`, W-B `in_progress`) and had written unsolicited deliverables. The
**task-status resets stand** — W-D and W-B are `pending`, and no workstream closes without
orchestrator-verified, this-run evidence, per §0.5. But the characterisation of the artifacts as rogue is
withdrawn: `seek-research.md`, `seek-risk-adjudication.md`, `human-gated-verification.md`,
`INCOMPLETE-FEATURE-INVENTORY-*` and `ADR-SEEK-FIRECRAWL.md` are this run's own in-flight W-B/W-D working
evidence, produced under the adjudications recorded above.

They remain **TESTIMONY** until re-verified by their owning workstream — which is the standing rule for
all prior artifacts under the run's epistemic discipline, not a sanction. In particular
`ADR-SEEK-FIRECRAWL.md` does not close §6.2.1: that clause requires the risk-officer gate to clear on the
evidence **before** any env or code change, and GOV-008 records that adjudication as still OPEN with the
primary sources pointing AGAINST the prompt's premise.

### Standing rule added
**Read `docs/delivery/GOLD-MASTER-V2-GOVERNANCE.md` before adjudicating any observed drift.** Unexpected
state is a prompt to consult the log first, not evidence of misconduct. Prior adjudications in this file
are testimony — verify them, then adopt or overturn them explicitly. Never silently revert one.

---

---

## GOV-007 — CORRECTED: polling DOES exist; the earlier entry was wrong

**Status:** SUPERSEDED — this entry corrects itself.

GOV-007 originally recorded that §11.1's polling description was contradicted by the Phase-0 SCREEN-MATRIX,
which reported most routes as a single static fetch with no periodic refresh.

**That was wrong.** Live `window.fetch` instrumentation of `/dashboard/jobs` on production
`[VERIFIED 2026-07-31, uat/reports/evidence/gold-master-v2/screens/jobs-screen-test.md]` measured a precise
**20.00-second auto-refresh** (t = 0.39s, 20.39s, 40.39s, 60.39s). §11.1's "20s (jobs, applications)" claim is
ACCURATE.

Two lessons recorded deliberately:
1. A static code read (SCREEN-MATRIX) is weaker evidence than live instrumentation, and it misled this
   orchestrator into filing a false correction against the prompt. Static inventory findings about RUNTIME
   behaviour must be treated as `[INFERRED]` until probed.
2. The screen-tester's own first-pass network capture ALSO suggested no polling; only direct `window.fetch`
   instrumentation settled it. Absence of evidence in a passive capture is not evidence of absence.

**Impact:** W-I's scope is materially SMALLER than the original GOV-007 implied. Each route's cadence must be
measured by instrumentation before any polling work is done — not read off the code, and not assumed absent.

---

## GOV-010 — §10.2 per-card Apply button vs. the wireframe

**Severity:** MEDIUM (scope adjudication)
**Status:** ADJUDICATED

### Evidence `[VERIFIED]`
`/dashboard/jobs` exposes NO per-card Apply button (DOM inventory, verified twice). Apply is reachable via the
job detail panel and a bulk "Apply (N)" action, both of which work: the modal is accurate, cancel provably never
fires `POST /apply`, and `View on [source]` is present.

Critically, `design/screens/job-discovery.html` — the WIREFRAME — also has no per-card Apply CTA. The
implementation matches the design; this is not drift.

### Adjudication
§1.3 ranks wireframes above the architecture and implementation docs, which would argue the current behaviour is
correct. But §10.2 requires "every job card in the Jobs screen shows an 'Apply' button", §10.1 directs that if it
is "absent or non-functional → gap filed + fixed", and gate G-H closes on "Per-card Apply button visible and
functional on every Jobs page card". The execution prompt is the operative instruction here, and it is explicit.

**Ruling:** BUILD the per-card Apply button per §10.2, including the pre-apply confirmation modal
(title, company, tailored resume/cover-letter status, ATS score, linked story count), honest inline failure, and
the secondary "View on [source]" link. **Also update `design/screens/job-discovery.html`** to match, so the
wireframe and deployed truth do not diverge — §17 requires docs to match deployed reality at exit.

The existing detail-panel and bulk-apply paths are RETAINED, not replaced; the new control must delegate to the
same apply service rather than duplicating logic (§13.1).

---

## GOV-011 — Pricing page advertises an entitlement the product refuses to honour

**Severity:** HIGH (raised from the tester's MEDIUM by orchestrator adjudication)
**Status:** OPEN — assigned to W-B

### Evidence `[VERIFIED]` (`uat/reports/evidence/gold-master-v2/screens/jobs-screen-test.md`, finding ML-JOBS-003)
For a genuine new non-admin account:
- `/pricing` renders the Free ($0) tier as **CURRENT PLAN**, advertising "5 agent runs/month" and
  "Resume tailoring + ATS scoring".
- `/dashboard/jobs` renders a full-screen paywall, and `POST /agents/scout/run` returns **402
  `subscription_required`** — NOT a quota-exhaustion response. The account has used **0 of 5** advertised runs.

### Adjudication
The tester filed this MEDIUM/UNSURE between "intentional beta override" and "entitlements not wired up". Either
way the USER-FACING outcome is identical: the pricing page states an entitlement in Australian dollars that the
product then declines to deliver, with a 402 that misattributes the refusal to a missing subscription rather
than to a deliberate policy.

Real paying customers onboard against this page. Advertising an included entitlement that is unconditionally
refused is a consumer-facing honesty defect of the same class this run exists to eliminate — not a
configuration preference. **Raised to HIGH.**

**Required resolution — one of, not both:**
(a) honour the advertised Free entitlement (5 runs/month including resume tailoring + ATS scoring), or
(b) correct `/pricing` so the Free tier truthfully states what it actually provides, and return an honest,
    accurately-worded refusal instead of `subscription_required` when the true reason is policy.

Silently leaving the mismatch is not an option under §0.5.

---

## GOV-011 — Unauthorised BLOCKER-001 commit that does NOT close the blocker

| Field | Value |
|---|---|
| **Detected** | 2026-07-31T00:35Z, by the orchestrator, from the test-author's return |
| **Severity** | HIGH — §0.4 separation of duties, §15 steps 5-7, and a security-closure integrity risk |
| **Status** | CONTAINED (local-only; production untouched) — remediation in flight |

### What happened
Commit `7f82105` *"fix(BLOCKER-001): close admin over-permission"* was authored and committed by a
self-directed fork **while the risk-officer's binding ADR was still being written**, with:
- no orchestrator authorisation,
- no independent reviewer pass (§15 step 5 — the author must never be the approver, §0.4),
- and a commit subject asserting the blocker is **closed**.

Five further commits followed the same way (`69535d5`, `0aea50a`, `bf8bfe3`, `0e73d95`, `36d86c6`).

### Why the commit subject is wrong `[VERIFIED]`
The test-author re-ran the ADR-derived suite against `7f82105`: **5 failed / 7 passed**. It satisfies
C1 (boot no longer aborts), C2 (`passwordHash` untouched) and C4 (CRITICAL diagnostic naming the env
var only), but it does **not** satisfy:

- **C3 — explicit de-privilege.** Rotation *skips* the grant instead of explicitly writing
  `isAdmin=false`. Against the live production row, which already carries `isAdmin=true` from a prior
  boot, skipping is a **no-op**. The privilege survives.
- **R3 disposition.** `AdminRotationConfigError` still aborts boot unconditionally — contradicting the
  binding ruling, and, per the ADR, crash-looping production on nothing worse than an operator typo in
  `AETHER_ADMIN_EMAIL`.
- **C6 — ordering.** A `raise` still follows a `conn.commit()` inside `apply_admin_rotation`, so a
  failure path can persist the privileged state *and* signal failure.

The C3 gap was reproduced **end-to-end as a live exploit**, not merely as a DB-state artifact: logging in
with the operator's **email** (not the reserved `admin` username, which the commit's added compensating
control does cover) plus the disclosed password returns 200, `/auth/me` reports `isAdmin:true`, and
`GET /admin/users` returns 200. This is BLOCKER-001's original exploit, intact, against the commit that
claims to close it — via exactly the substitution vector the ADR predicted.

### Why this is the dangerous class of failure
§0.5 forbids closing findings without fresh evidence and forbids "already done" wave-throughs. A commit
message that says a **security** blocker is closed, when the exploit still reproduces, is the highest-cost
version of that failure: it would have been carried into the final report as a closure, and the run's own
G-P verdict would have rested on it.

It was caught only because the tests were authored from the ADR's conditions **independently of the
implementer**, and were run against the implementer's own commit. That is the §0.4 separation working as
designed — the control was load-bearing, not ceremonial.

### Containment `[VERIFIED 2026-07-31T00:38Z]`
- All seven commits are **local only** — `git status -sb` reports `ahead 7`; nothing was pushed.
- **Production is untouched and healthy** — `GET /api/health` 200; `aether-api`/`aether-web`/`aether-worker`
  all active. No deploy was performed.
- The refused boot-abort draft therefore never reached the running service.

### Ruling
1. **BLOCKER-001 remains OPEN.** `7f82105` is a partial mitigation, not a closure. Its commit subject is
   inaccurate and must be corrected in the final report rather than quietly inherited.
2. **No deploy of any BLOCKER-001 change until** C3, the R3 disposition and C6 all pass the ADR-derived
   suite, **and** a reviewer that did not author the fix signs it off.
3. The ADR-derived test suite is the acceptance contract. A fix is not done because its author says so;
   it is done when that suite is green and an independent reviewer agrees.
4. Sub-agents may not push to `origin`, and may not deploy. Those remain orchestrator-authorised actions.

### Standing rule added
**A commit subject may not assert closure of a finding.** Implementation commits describe the CHANGE;
only the orchestrator, on a green independent verification, records a finding as closed in the ledger.

---

## GOV-012 — The orchestrator's own runtime monitor was a false green

| Field | Value |
|---|---|
| **Detected + corrected** | 2026-07-31T00:42Z, by the orchestrator, on itself |
| **Severity** | MEDIUM — evidence integrity for G-M |
| **Status** | RESOLVED |

At Phase 0 Step 4 the orchestrator started `journalctl -u aether-api -u aether-web -u aether-worker
-u aether-discovery -f` and recorded the monitor as RUNNING. At 00:42Z that capture held **1 line**,
last written at 22:37:00Z — the moment it started. The tail process was alive the whole time.

The services do not log to journald; they log to files (`/var/log/aether/{api,worker,web,discovery}.log`),
exactly as `DEPLOYMENT-RUNBOOK.md` §4 states. The runbook was right and the monitor was pointed at the wrong
source. A liveness check on the tail PROCESS returned healthy throughout, which is precisely what made this
dangerous: **"monitor alive" was true while "monitor observing" was false.**

Had this gone unnoticed, G-M ("≥ 60 min monitored production, ZERO server errors") would have been closed on a
capture that could not have recorded an error if one had occurred — the §0.5 fake-green class, self-inflicted.

Corrected: the empty capture is retained as `journal-live-EMPTY-FALSE-GREEN.log` (evidence of the gap, not
deleted), and an event-driven monitor now tails the real log files, filtered to `ERROR|CRITICAL|Traceback|
Unhandled|ValidationError|5xx|Application startup failed`, so matches arrive as notifications rather than
accumulating unread.

Independently, a concurrent runtime-monitor was already tailing `/var/log/aether/api.log` correctly and had
caught a real production 500 on `PUT /workspaces/settings` at 2026-07-30T23:50:46Z with a full traceback
(ML-settings-006, NUL byte in profile strings). That finding is genuine and is already test-covered and fixed
in the working tree. Its existence is also the proof that the correct log source yields signal — the
orchestrator's capture was silent over the same window because it was watching nothing.

**Standing rule:** a monitor is proven by SIGNAL, not by liveness. Before trusting any monitoring window,
confirm the capture contains expected routine traffic; a capture with zero lines over an exercised window is
evidence of a broken monitor, never of a clean system.

---

## GOV-013 — index-inheritance hazard, THIRD recorded instance (2026-08-04)

**Class:** shared-tree git hazard · **Severity:** HIGH — silently misattributes and can silently revert work.

A fixer agent recorded that its one-line isort fix to
`apps/api/tests/test_story_narrative_grounding.py` "shows as committed with a clean `git status`, but
appears in `git diff d329a9b..937de06` rather than in any commit of mine — another agent's
`git add`/`git commit` picked it up."

This is the **third** instance in this tree. A prior instance silently reverted a real fix while leaving
the suite GREEN — i.e. the failure mode is invisible to tests, which is what makes it dangerous.

**Root cause:** the git index is shared per-worktree. Any agent running `git add -A` / `git add .` /
bare `git commit -a` sweeps in every other concurrent agent's in-flight edits.

**Binding rule (already mandated in agent briefs; restated here as governance):**
`git commit --only <explicit paths>` is the ONLY permitted commit form in this tree. `git add -A`,
`git add .`, `git stash`, `git checkout --`, and `git reset` are PROHIBITED for any path the agent did
not itself create. Verify with `git show --stat` after every commit that only intended paths landed.

**Also recorded by the same agent:** HEAD moved from `d329a9b` to `937de06` mid-task (four commits from a
concurrent session). Any before/after suite delta measured across such a move must be attributed with that
in mind — the two runs are against different trees.

---

## GOV-014 — the state file outlived its truth (2026-08-04)

`docs/delivery/GOLD-MASTER-V2-STATE.json` was last written `2026-07-31T16:55Z` and asserts
`G-N: CLOSED` and (via W-K) production free of test data. On `2026-08-04` the orchestrator verified
first-hand that BOTH claims are false at HEAD:

- **G-N:** the most recent full suite recorded **24 failed / 2549 passed / 1 skipped**.
- **G-K:** production holds **13 `@mailinator.com` test identities owning 5,011 Job rows**, created
  *after* W-K was recorded complete — by this run's own UAT agents.

**Lesson:** a gate recorded CLOSED is a claim about a moment, not a durable property. Long-running
campaigns that keep testing against production keep *creating* the conditions that reopen their own
gates. Any gate whose evidence predates the most recent production activity MUST be re-verified before
the final declaration, not carried forward on its recorded status.

**Correct at 2026-08-04T02:05Z (orchestrator-verified, first-hand):**
- BLOCKER-001 fully closed: weak credential → 401; `.env` hash no longer verifies it; `AETHER_CRON_PASSWORD`
  rotated in lockstep (verified against the new hash); discovery cron succeeding every 30 min; admin
  privilege self-restored on rotation exactly as the approved design intended.
- Branch hygiene: `origin/main` == local HEAD `8e61afc`, 0 unpushed, 1 remote branch, 0 open PRs.

---

## GOV-013 — Production test-data purge: execution WITHHELD (manifest fails its own approval)

| Field | Value |
|---|---|
| **Adjudicated** | 2026-08-04T02:1xZ, orchestrator |
| **Severity** | HIGH — irreversible production data deletion |
| **Ruling** | **EXECUTION WITHHELD.** The purge is APPROVED IN PRINCIPLE and BLOCKED IN PRACTICE. |

### The finding being remediated
The production DB holds 15 users: **13 `@mailinator.com` test identities owning 5,011 `Job` rows**, created
2026-08-03/04 by this run's own UAT agents — i.e. AFTER W-CLEAN was recorded complete. §13.1.3 forbids stale
test data in the live DB, so **G-K is REOPENED** and cannot close on the earlier evidence.

### Why execution is withheld — two independent blocks

**OD-4 — the manifest does not match its own approval record. `[VERIFIED]`**
The risk-officer's approval record pins the manifest at sha256 `ac43a9a8…`. The manifest on disk hashes to
`5ce65fe3…` — a **mismatch**. It was modified after approval, by a second risk-officer instance working the
same task concurrently. Worse, the orchestrator's own grep finds the **REJECTED `pg_dump` command still present
8 times** in the approved-looking artifact.

Under §13.2 a janitor "executes the manifest exactly". Executing this one would run a backup command that its
own author rejected as unsafe — see below — against production. **REFUSED until the manifest is re-authored by
a single author, the pg_dump command is purged from it, and a fresh approval record pins a matching sha256.**

**C5-A — the target rows are not quiescent. `[VERIFIED by the risk-officer]`**
A 20-minute look-back suggested quiescence; it was wrong. Test-user `AgentRun` rows went 7 → 8 → 9 during the
assessment and the in-scope total drifted 5,079 → 5,080 → 5,081 across seven minutes. A UAT sub-agent is still
writing. Deleting now would pull rows out from under a running session.

### Three findings in this assessment that would each have caused real damage

1. **A `sourceUrl`-based predicate would have destroyed 1,387 OWNER rows.** `UNIQUE INDEX
   "Job_userId_sourceUrl_key"` proves dedup is per-user, so job rows are private copies — but 1,387 of the
   owner's `sourceUrl`s also exist as test-user copies. `DELETE FROM "Job" WHERE "sourceUrl" IN (…)` would have
   taken the owner's with them. Identity-only predicates are now machine-enforced over the manifest's generated
   SQL; the orchestrator independently confirmed **0 non-identity predicates** and 5 identity predicates present.
2. **The ORM misrepresents the FK graph.** `schema.prisma` declares 16 models; the live database has **31 tables
   and only 16 FK constraints**, with **17 user-scoped tables carrying no FK to `"User"` at all**. A
   cascade-based purge would have silently orphaned subscriptions, quotas and stored provider credentials.
   Every table is now deleted explicitly.
3. **`pg_dump` fails DANGEROUSLY here.** Client 16.14 against server 17.9 aborts **and leaves a 0-byte file**.
   A janitor running `pg_dump … && psql -c 'DELETE …'` would get a silently empty backup and delete anyway.
   Replaced with a JSONL capture validated round-trip (5,011 rows, 0 unparseable, 3/3 byte-identical on restore).
   Full-DB/PITR restore is **prohibited** as rollback: the owner is writing concurrently, so restoring would
   destroy their post-backup work and convert cleanup into real loss.

### Conditions that must ALL hold before a janitor may execute
Backup verified non-empty and JSON-parseable with matching line counts, copied off-VM with sha256 (the evidence
tree is gitignored); identity predicates only; explicit per-table deletes in FK order, never cascade; single
transaction with in-transaction pre/post assertions; 30 minutes of zero test-identity writes with all UAT
sub-agents confirmed terminated; `AdminAuditLog`, `StripeEvent`, `Plan`, `AdminSetting` and provider-credential
tables untouched; a read-only risk-officer diff of the janitor's actual SQL against the re-approved manifest;
and the janitor is not the approver.

### OD-3 — the BLOCKER-002 "PRESERVE-DO-NOT-DELETE" rows: ADJUDICATED, NOT BLOCKING
Three `ApprovalRequest` ids designated preserve-do-not-delete on 2026-07-31 return **0 rows**, and the
`GAP-P7-DEF-B` probe string is absent everywhere. Orchestrator probe: **338 `ApprovalRequest` rows exist, 0 of
which contain the probe string**, and the owner's `User.name` now reads as a real name rather than a
placeholder.

Ruling: the **corrective outcome BLOCKER-002 required is achieved** — the customer-facing defect (cover letters
signed with a test-probe string) is gone at its source. The three designated rows are unaccounted for, and this
is recorded honestly as an **evidence-provenance gap**, not a data-integrity violation: the substantive evidence
survives in the committed text corpus. It does not block the purge and does not reopen BLOCKER-002. Ten `User`
rows still carry probe-like names — all of them mailinator test identities inside the purge scope.

### Effect on gates
**G-K is REOPENED** and stays open until the purge executes cleanly under a re-approved manifest, AND the
operator dispositions the two live-mode Stripe customer records (`OD-1`), which cannot be removed from inside
the VM.

---

## GOV-015 — ADV-ENT-002 REFUTED under live configuration (2026-08-04)

**Prior claim (this campaign):** "the backend advertises a Free tier of 5 runs that it universally denies" —
carried for weeks as an open business/entitlement defect awaiting an owner decision.

**Refuted by live probe.** The qa-adversary drove a real free-tier persona to quota exhaustion against
production: the account received **exactly 5 runs**, and the **6th was cleanly refused with 429 and no
phantom increment**. Evidence: `uat/reports/evidence/prod-uat-2026-08-03/s10-quota-exhaustion-429.json`,
`s12-quota-honesty.json`.

**Ruling:** ADV-ENT-002 is CLOSED as NOT-REPRODUCIBLE under live config. The Free tier delivers what it
advertises. Any residual concern belongs to F-03 (a metered run is spent on résumé upload without the user
asking), which is a *different* defect with a different fix.

**Lesson (the recurring one in this campaign):** a defect inferred from reading code must be confirmed against
the running system before it is carried as fact. This is the fourth finding in this campaign that survived on
inference and died on contact with a live probe — cf. the Stripe USD "CRITICAL" (refuted: Adaptive Pricing
presentment), the 83×5xx count (refuted: an `awk` comparison against a non-timestamp), and ML-admin-003
(refuted: deployment lag, not a code gap).

---

## GOV-016 — the F-01 tenancy lapse is ISOLATED, and that finding is load-bearing (2026-08-04)

When F-01 was found (any authenticated customer could read/overwrite/delete the operator's deployment-wide
LLM provider credentials) the obvious fear was systemic: that tenancy had been applied inconsistently across
the whole API. It had not.

**Verified by direct cross-tenant probe of every standard resource router** — jobs, applications, resumes,
cover-letters, stories, approvals, runs, interviews, networking, offers, emails — **all correctly owner-scoped
on BOTH reads and writes/deletes (404 cross-tenant, with owner data verified unchanged afterwards)**, and the
entire admin surface gated (403). Evidence: `uat/reports/evidence/prod-uat-2026-08-03/s11-tenancy-sweep.json`.

**Why this matters for the closure record:** F-01 is a single missed gate on one deployment-wide store that
predates the per-user provider design, not a pattern of missing authorization. That bounds the blast radius and
means F-01 can be closed by gating that one endpoint family rather than by an API-wide authorization audit.

**Also recorded:** the anti-fabrication core promise — the product's central commitment — held on every
generation path exercised. Cover letters were fully grounded in the uploaded résumé and self-flagged for
approval when weak; tailoring reported an honest 42/100 rather than faking coverage; ATS scores were real; and
email-send and approval-execute refused honestly rather than fabricating a "sent"/"executed" state.

---

## GOV-017 — "the test was wrong" produced three weakened guards, and the orchestrator's own check missed it

**ORCH-CORR-011.** I inspected `28d6393` myself and reported to the operator that the tests had been
*strengthened*, citing added assertions and a `0.55` tolerance I verified was analytically derived. An
independent reviewer then returned **FAIL** on three of the five. My check was too shallow in a specific,
repeatable way: **I counted assertions instead of asking what each one still forbids.** Added assertions and a
larger diff read as rigour; they are not. The only question that discriminates is *would this test still fail
if the behaviour it guards regressed?*

**What the review found (accepted):**

1. `test_ats_engine::test_perfect_keyword_overlap_scores_high` — the new floor of `76.0` was computed using
   `50`, which is `_DEGRADED_SEMANTIC_SCORE` (`ats_engine.py:60`) — the placeholder emitted when semantic
   scoring is **unavailable**, documented in-file as "not a measurement". Proven by probe: with the embedding
   model forced to `None` and `HF_TOKEN` absent, `overall=77.78`, `semantic_path='degraded'`, and the test
   **passes**. Before the commit, `overall >= 90` was the **only** assertion in the whole backend suite whose
   green required a real embedding model — every other semantic test stubs it. The commit deleted the suite's
   single guard against silent semantic degradation. Worse, a comment inside the test claimed the floor was
   "read from the product module, never copied/hardcoded" while the next line hardcoded `50`; that untrue
   claim was repeated in the commit message.
2+3. Both `rt_005` board tests — the "202 of 303 fixture postings are unscorable" justification is **not
   reproducible**. The real fixture board is **30 postings, zero unscorable**. The 303-job board existed only
   because the suite was making **live SmartRecruiters HTTP calls** (`base_adapter._resolve_payload` fell
   through to `_fetch_live` for a source with no fixture). These were **class-(c) test-environment defects
   adjudicated as class-(b) stale assertions** — the exact misclassification the fix brief warned against.
   The replacement partition then blesses the symptom: if an adapter stops delivering descriptions, the old
   assertion went RED; the new one reclassifies those cards as `unscorable`, asserts they *should* stay in
   `discovered`, and goes GREEN. The `unscorable` half is bounded only by `assert unscorable`, satisfied by
   the test's own seeded control — so it bounds nothing about how much of a real board may go unranked.

**Standing rules added:**
- A test may never be "re-anchored" to a floor derived from a **degraded/fallback constant**. If a product
  module defines a placeholder for "this could not be measured", no test threshold may be computed from it.
- When a test is ruled class-(b) *stale assertion*, the ruling MUST state what the test environment was, and
  rule out class-(c) explicitly. Two of three failures here were environment defects wearing a (b) costume.
- Diff size and assertion count are not evidence of rigour. The reviewable question is what the test still
  forbids.

**Two of five rulings stood** on re-probe — the Workable/Ashby token move (live-verified: airwallex returns 0
jobs on Workable, 627 on Ashby) and the `0.55` conversion tolerance (analytic worst case `0.05 + 10*0.05`,
above the observed `0.3` by derivation, still RED on a real regression).

**G-N remains OPEN.** ML-BACKEND-RED is NOT closed on `28d6393`.

---

## GOV-018 — the test suite was making live third-party HTTP calls (product finding, from the review)

`AETHER_DISCOVERY_FIXTURE_DIR` promised canned fixtures, and `main.py` printed that promise, while
`base_adapter._resolve_payload` silently fell through to `_fetch_live` for any source without a recorded
fixture. A newly registered adapter therefore joined the suite live and nondeterministic with nothing to
notice it — and it is why the `rt_005` rulings were adjudicated against a 303-job live board rather than the
30-posting fixture board.

Fixed in the working tree by another agent (raises `AdapterFetchError` instead) but left **uncommitted**; now
being landed. **Production risk: none** — the branch requires `AETHER_DISCOVERY_FIXTURE_DIR`, which is absent
from both `.env` and the running API process environment.

**Also filed as a real product defect (ATS-KW-001):** `ats_engine._extract_keywords` treats the posting's
**location** ("sydney") as a required résumé keyword — the sole miss docking `keyword_match` from 100 to
94.44. Every posting has a location, so **every candidate is docked on every posting**, and the incentive it
creates is to keyword-stuff a city, which is precisely the gaming the product exists to refuse.

---

## GOV-019 — two sessions restarting the same production API caused a real production failure (2026-08-04)

**Event.** I restarted `aether-api` at 02:58Z to deploy the F-01 fix and verified it live. At **03:07:32Z** the
API's main process started *again* — `NRestarts=0`, so systemd did not do it and nothing had crashed. A
concurrent session restarted the shared production API while I was mid-verification.

**Consequence, in production:** the discovery cron's `POST /agents/fit-scorer/run` hit the API mid-restart and
failed — `curl: (52) Empty reply from server`, logged as `FATAL ... HTTP 000` at exactly 03:07:32Z. The scout
run two minutes earlier had succeeded (persisted 9, updated 1,395), so a complete sourcing cycle was lost to
the restart. It self-heals on the next 30-minute tick (03:30:42Z).

**Why this is more than a nuisance.** Every unit on this VM serves **directly from the shared working tree**.
A restart by any session therefore deploys whatever is in that tree at that instant — including every other
session's in-flight, unverified, uncommitted work. Two consequences follow:
1. Nobody can state what is running in production from their own commits alone.
2. A verification result is only valid until the next foreign restart. I re-verified F-01 after this one and
   it held (403 on GET `/providers`, DELETE `/providers/anthropic/credential`, and POST
   `/providers/anthropic/oauth/exchange`) — but that re-check was necessary, not optional.

**Standing rule:** treat a production restart as an exclusive operation. Before restarting, check
`systemctl show aether-api -p ExecMainStartTimestamp` and re-check it immediately after verifying; if it moved
under you, your verification is void and must be repeated. After any deploy, re-assert the security-critical
gate specifically — a foreign restart cannot remove a committed fix, but it can and does change everything
around it.

**Still live in the working tree (and therefore in production):** two `# RED-PROOF-TEMP: circuit branch
disabled` comments at `agents.py:892` and `:2052`. Confirmed inert — the branch below each still executes
`raise _quota_429(...)` — but they are false comments sitting above live protection and must be removed.

---

## GOV-014 — The G-A verdict is STALE on four of its eight blocking items

| Field | Value |
|---|---|
| **Adjudicated** | 2026-08-04T03:4xZ, orchestrator, by first-hand re-probe |
| **Severity** | MEDIUM — verdict accuracy |
| **Status** | Items 1-4 CLOSED on fresh evidence; verdict stands NOT-READY on the remainder |

`GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md` was written 2026-07-31T16:42Z and returns **NOT-READY —
BLOCKED-ON-ITEMS** with eight blocking items in required order. Three days have passed. Under this run's own
epistemic discipline the document is now TESTIMONY, so the orchestrator re-probed each concrete item rather
than inheriting the verdict.

| # | Blocking item as written | Fresh probe | Now |
|---|---|---|---|
| 1 | Rotate `AETHER_ADMIN_PASSWORD_HASH` **and** `AETHER_CRON_PASSWORD` together — "confirmed still both live and exploitable" | `admin`/`admin123` → **401**, no token. The configured hash **no longer verifies** the published password. `AETHER_CRON_PASSWORD` **does** verify the rotated hash, and discovery cron is cycling every 30 min, persisting jobs and completing fit-scoring. | **CLOSED** — operator did both halves in lockstep, and admin self-restored exactly as the approved design intended |
| 2 | Add an audit-log write to `POST /approvals/{id}/approve` and `/reject` — "the highest-priority code gap in the run" | `_write_decision_audit()` defined at `approvals.py:35` and **called at `:229` (approve) and `:245` (reject)** | **CLOSED** |
| 3 | 8 stored cover letters still carry the fixture signature (0 of 8 remediated) | Sweep for `GAP-P7-DEF-B` / `Probe 1785…` across `ApprovalRequest`, `Application`, `Resume`, `StoryEntry`, `OutreachTask`, `EmailThread`: **0 rows in every table**. There is no `CoverLetter` table in the live schema. | **CLOSED** |
| 4 | 45 unpushed commits; production on the same binary 20+ hours | `origin/main` == local `HEAD`; **0 unpushed**; exactly one remote branch; zero open PRs | **CLOSED** |

### Items that remain genuinely open
5. **Tailoring efficacy** — the score-aware loop must move the metric its UI implies (0.0% movement in 7/7 runs
   at review time). W-C is recorded complete; efficacy is **not** re-verified by this probe and must not be
   assumed. Remains open pending live proof.
6. **Business decisions (operator)** — `ADV-ENT-002` (honour the advertised Free tier or stop advertising it)
   and AUD presentment on Stripe Checkout.
7. **Test baseline** — backend RED set (24 at baseline, 5 residual) plus Playwright 40/52. Must not be reported
   as green.
8. **Process** — `approvals-screen-test.md` is an 18-line stub.

Plus, found after the review was written: `F-02` backend "Run All" fabrication, `F-03` résumé upload quota
consumption, `F-04` self-referential probability factor, `ATS-KW-001` (job LOCATION scored as a required résumé
keyword, docking every candidate on every posting), W-SUB, W-PORTAL, and the reopened G-K purge.

### Ruling
The **NOT-READY verdict stands**, but it must be re-issued on current evidence before G-A/G-P close. Re-stating
a three-day-old blocker list that names an already-rotated credential as "live and exploitable" would be exactly
the "prior reports are testimony" failure this run exists to prevent — inaccurate in the *pessimistic*
direction, which is no more acceptable than inaccuracy in the optimistic one. The qa-adversary that owns the
document must refresh it; this entry is the orchestrator's verified input to that refresh, not a substitute for it.

---

## GOV-015 — W-C/G-C: the tailoring loop WORKS; the §5.2 ≥85 threshold is unreachable without fabricating

| Field | Value |
|---|---|
| **Adjudicated** | 2026-08-04T04:5xZ, orchestrator, on a live 5-job production probe |
| **Evidence** | `uat/reports/evidence/gold-master-v2/wc/TAILORING-EFFICACY-PROBE.md` |
| **Ruling** | Mechanism COMPLIANT. Threshold NOT MET and NOT HONESTLY REACHABLE. G-C closes on the honest-warning path, NOT on ≥85. |

### The measurement
Five real production jobs across distinct domains, owner identity, per-run costs taken from each run's own
`costUsd`:

| before | after | delta | iterations | honest warning |
|---|---|---|---|---|
| 53.69 | 54.69 | +1.00 | 5 | yes |
| 44.28 | 52.28 | +8.00 | 5 (still climbing) | yes |
| 39.22 | 45.54 | +6.32 | 5 | yes |
| 33.13 | 37.13 | +4.00 | 3 — cut short, LLM budget exhausted, disclosed | yes |
| 34.00 | 39.00 | +5.00 | 5 (still climbing) | yes |

**Mean delta +4.86. 5/5 positive. 0/5 at 0.0%. 0/5 reached 85.**

### This REFUTES prior testimony in this run's own evidence tree
`GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md` blocking item 5 states the feature shows "0.0% movement in 7/7 runs"
and that tailoring "moves its own metric by zero". That measurement was taken against the OLD single-pass
`resume_tailor.py`. `TailoringLoop` replaced it and genuinely re-scores every iteration — proven by non-round,
run-specific per-iteration deltas, which a cached or re-displayed pre-tailoring value could not produce.
**Blocking item 5 is withdrawn as written.** The review must be corrected: reporting a working feature as
broken is the same testimony failure as the reverse.

### Why 85 is not reached — and why that is CORRECT behaviour
`tailoring_loop.py:246-274` (`split_gap_keywords`) refuses to inject gap keywords the candidate's evidence
corpus does not support. Each posting carries 10-20+ such keywords. The anti-fabrication guard therefore
imposes a hard, honest ceiling well below 85 for this candidate against these postings.

The gap is a **DATA** condition — this résumé genuinely does not evidence those requirements — not a code
defect. Closing it would require fabricating experience, which §5.3.3 forbids ("Do not fabricate experience")
and which the entire anti-fabrication architecture exists to prevent.

§5.2 states the score "MUST be ≥ 85". §5.3.1 point 5 states that if max iterations is reached below 85 the
system must surface an honest inline warning with the best achieved score and **NEVER claim success**.
**Observed: an honest warning in 5/5 runs, naming the unreachable keywords, plus an explicit "cut short, LLM
budget exhausted" disclosure on the run that stopped at 3 iterations.**

**Ruling:** where §5.2's threshold and §5.3.3's anti-fabrication rule conflict on real data, **§5.3.3 wins and
§5.3.1.5 is the compliant outcome.** A system that reached 85 here would be lying. G-C closes on mechanism
correctness and honest disclosure; the run's final report MUST state plainly that the ≥85 target is not met on
production data, with these numbers, and MUST NOT report G-C as "≥85 achieved".

### Secondary findings from the same probe
- **ATS-KW-001 CONFIRMED LIVE but MINOR.** The Kinetic JD's ordinary sentence *"Melbourne location with true
  flexibility"* put the bare token **"location"** into that run's real `gapKeywords`/`unreachableKeywords`.
  Sampled n=60 live postings: geography noise appears in the top-40 required keywords on **18%**, costing
  **~1.00 point** of overall score per hit (2.5 pts on the keyword sub-score; up to 2.00 when a city name and
  the literal word both hit). Real, worth fixing, and **not** the dominant cause of the 30-50 point gap to 85.
  It must not be sold as the fix that unlocks 85.
- **`interview_conversion_rate` = 0.0% is ATTESTED, not a placeholder** — a genuine computation at
  `analytics.py:200-230`, cross-checked against the funnel's raw 0/67. It reads zero because the account has
  logged zero interviews, which is the honest value.
- **LLM budget exhaustion truncated one run at 3 of 5 iterations** and said so. Honest, but it means the
  achievable ceiling is budget-sensitive; worth recording as a known constraint rather than a defect.
- **Shared-production hygiene:** independent autopilot tailoring activity was observed on the same owner
  account mid-probe (a run the prober did not trigger). Per-run costs were taken from each run's own `costUsd`
  rather than an account-wide quota delta, so the figures are unaffected.

---

## GOV-020 — index inheritance, FOURTH instance — and this one briefly broke HEAD (2026-08-04)

**Event.** Commit `52fc727` (guard restoration) swept up a *different* agent's uncommitted hunk in
`apps/api/tests/test_rt_005_board_stage_sync.py` — the `seed_search_target` precondition belonging to the F-02
backend work. This is the **fourth** recorded instance of the index-inheritance hazard, and the first in the
"swallowed by a well-behaved agent" direction: `52fc727` used explicit paths and its own `--stat` check
confirmed only two files landed. The check was true and still insufficient, because **the swallowed hunk was
inside a file the committer legitimately owned**.

**Consequence — a broken intermediate HEAD.** Between `52fc727` and `0ce7098`, HEAD's
`test_rt_005_board_stage_sync.py` imported `conftest.seed_search_target`, which did not yet exist in HEAD's
`conftest.py`. Anyone checking out that range would have hit a collection error. `0ce7098` repaired it by
landing the conftest half.

**Verified repaired (orchestrator, first-hand):** `seed_search_target` is defined in `conftest.py` at HEAD and
referenced twice in `test_rt_005_board_stage_sync.py` at HEAD; all four affected modules parse cleanly.

**Rule strengthened.** `git commit --only <paths>` and a `--stat` check are NOT sufficient on their own. Before
committing ANY file, diff it against HEAD and confirm **every hunk is yours** — path-level ownership does not
imply hunk-level ownership when several agents edit one file. The hunk-staging discipline two agents adopted
independently today (snapshot foreign base → replay own delta onto a pristine `HEAD` copy → `git apply --cached`
→ prove zero foreign markers in the commit AND all foreign hunks still unstaged in the tree) is now the
REQUIRED procedure for any shared file, not a permitted deviation.

**Also cleared, by first-hand check rather than relay:** a residual claimed a stray probe file
`apps/api/tests/_rt005_original_assertions_probe.py` would now 422 and break the suite. It does not exist — the
authoring agent removed it — and even if it did, its leading underscore means pytest would never collect it.
Recorded because acting on that relayed claim would have produced a fix for a non-problem.

---

## GOV-021 — the ≥85 ruling must be RE-MEASURED after ATS-KW-001, and a GOV-id collision

### 1. ID collision (housekeeping)
**Two `GOV-015` entries exist.** A concurrent orchestrator session filed `GOV-015` at `9274f93` (W-C/G-C
tailoring efficacy) while this session had already filed `GOV-015` (ADV-ENT-002 refuted). Both are valid and
both are kept — cite them as **GOV-015-ENT** (ADV-ENT-002 refuted, this session) and **GOV-015-WC** (tailoring
efficacy, `9274f93`). Root cause: two sessions allocating from one monotonic namespace with no lock. Later IDs
in this file (016–021) are this session's.

### 2. The substantive point: the ≥85 ceiling was measured on a demonstrably mis-scoring engine

`GOV-015-WC` rules that the tailoring mechanism is COMPLIANT (mean delta **+4.86**, **5/5 positive**, 0/5 at
0.0%) and that §5.2's ≥85 threshold is "NOT HONESTLY REACHABLE" because `split_gap_keywords`
(`tailoring_loop.py:246-274`) refuses to inject keywords the candidate's evidence corpus does not support. I
**agree with the mechanism finding**, and I agree the anti-fabrication refusal is correct behaviour that must
not be weakened to hit a number.

**But the ceiling measurement is confounded, and the confound was discovered independently and after it.**
`ATS-KW-001` (task #37, found by the reviewer of `28d6393`): `ats_engine._extract_keywords` treats the
**posting's location** as a required résumé keyword. In the measured perfect-overlap case "sydney" was the
**sole** miss, docking `keyword_match` from 100 → 94.44. Every posting carries a location, so **every candidate
is docked on every posting** — and a location token is exactly the kind of "gap keyword" the corpus cannot
evidence, so it is plausibly also inflating the unsatisfiable-gap count that the ≥85 ruling rests on.

**Ruling:** `GOV-015-WC`'s *mechanism* finding stands and its withdrawal of the "0.0% movement in 7/7 runs"
testimony stands (that figure was taken against the OLD single-pass `resume_tailor.py`, and reporting a working
feature as broken is the same testimony failure as the reverse). Its *threshold* conclusion is **PROVISIONAL**:
the five-job probe must be **re-run after ATS-KW-001 is fixed** before "≥85 is unreachable without fabricating"
is recorded as settled. G-C must not be closed on the honest-warning path until that re-measurement exists —
closing a headline gate on a ceiling measured through a known scoring defect would be exactly the
inference-over-evidence failure this campaign keeps catching.

**Sequencing:** fix ATS-KW-001 → re-run the five-job probe → then adjudicate G-C.

---

## GOV-022 — two orchestrator sessions, one tree, no work-claim protocol (2026-08-04)

**Event.** This session dispatched a fixer for F-04 at 03:40Z. F-04 had already been fixed by a concurrent
orchestrator session at `5f9e775`, which landed *before* the dispatch. The duplicate was detected on the next
`git log` read and stopped, but only after it had begun inspecting `analytics.py` — the same file the completed
fix had rewritten. Two agents editing one file concurrently is how GOV-013/GOV-020 happen.

**Not an isolated slip.** The same root cause — two sessions sharing one tree with no coordination surface —
produced GOV-019 (a foreign restart killing a live sourcing cycle), GOV-020 (a swallowed hunk and a briefly
broken HEAD), and the `GOV-015` ID collision, all within about two hours.

**Mitigation:** `docs/delivery/SESSION-COORDINATION.md` — a claims table plus a five-point protocol (claim
before dispatching; claim a deploy window before restarting; verify hunk-level ownership before committing;
allocate governance IDs from disjoint ranges; record every production test persona at creation). It is a weak
substitute for a lock, but it is checkable and costs one file read before dispatch.

**Credit where due:** the concurrent session read this session's ADR and implemented its Ruling 1 (`c7644f4`,
keeping the per-user `PUT` ungated). Cross-session coordination through committed documents demonstrably works
— it just has to happen *before* the work, not only after it.

---

## GOV-023 — ATS-KW-002: the headline score is computed against alphabetical noise (2026-08-04)

**Verified first-hand by the orchestrator on the live engine at HEAD, not relayed.**

`ATSEngine._extract_keywords` fits `TfidfVectorizer` on a **single document**. With one document IDF is
constant for every present term, so ranking collapses to raw term frequency — and because almost every JD term
appears exactly once, the ordering is decided by the **alphabetical tie-break**. `_MAX_KEYWORDS = 40` then
truncates that alphabetical list.

**Measured on a realistic Senior Data Engineer posting:**

| | result |
|---|---|
| set size | 40 (at the cap), cut off at `modelling` |
| real requirements NOT scored | **9 of 16** — `python`, `sql`, `spark`, `snowflake`, `terraform`, `streaming`, `pipelines`, `warehousing`, `orchestration` |
| boilerplate occupying scored slots | **16** — `lunches`, `catered`, `allowance`, `generous`, `competitive`, `agencies`, `click`, `crew`, `annual`, `leave`, `atlassian`, `ltd`, `budget`, `days`, `globe`, `customers` |

Everything alphabetically after roughly "m" is discarded. A candidate is scored on whether their résumé echoes
*lunches* and *catered*; whether it says *Python* is not measured at all. The tailoring loop then optimises
toward those same tokens.

**Severity: MAJOR, and strictly worse than ATS-KW-001.** That defect was *contamination* — a non-skill counted
as a skill. This is silent **loss of the real requirements**, in the number this product sells.

**Nuance worth recording (found by re-testing my own first probe):** a JD with fewer than 40 unique content
tokens loses nothing — my initial 34-token probe scored every real skill. The harm requires a posting long
enough to hit the cap, which real postings comfortably are. The alphabetical *ordering* is always present; the
*loss* only bites past the cap. Reporting the mechanism without that qualifier would have overstated it.

**Blocks G-C.** The GOV-021 ≥85 re-measurement must not be run through this defect — it would measure a
ceiling imposed by alphabetical truncation and attribute it to the anti-fabrication guard.

**Credit:** found by the ATS-KW-001 fixer while fixing something else, and **escalated rather than absorbed** —
the same discipline that earlier turned "these tests are stale" into "these tests were never defective". The
contrast with GOV-017 is the lesson: an agent that widens scope silently produces GOV-017; an agent that
reports what it found and stops produces this.

---

## GOV-024 — "CI green" does NOT mean the backend suite passed (2026-08-04)

**CI is green at `62c198d`** — both jobs pass. But the API job's own annotation reads:

> `DATABASE_URL_TEST secret not set — DB test suite skipped`

So the API job runs **`ruff` + `mypy` only**. The 2,500-test Python suite has never run in CI; it only ever
runs on this VM, serially, under `flock /tmp/aether-pytest.lock`, taking ~2h20m.

**Consequences, stated plainly:**
1. **G-N cannot be closed on "CI is green."** CI green is a lint/type signal for the API. The only evidence
   that the backend suite passes is a local full-suite run, and the last complete one recorded 24 failures.
2. **A single lint error blocks everything downstream.** The `ruff` step failing left `mypy` and the pytest
   step un-run — main had been red since `9d3be57` on one unsorted import block (`62c198d` fixed it). Because
   ruff runs first, one trivial style error silently hides every other check.
3. **Task #39 (embedding-model cache) is MOOT for CI as configured.** The restored `semantic_path` guard can
   only fail where pytest runs, and pytest does not run in CI. It becomes live the moment `DATABASE_URL_TEST`
   is set — so the requirement stands as a *precondition of enabling CI pytest*, not as a current CI failure.
   Recorded as a correction: I previously framed it as something CI would hit today. It will not.

**Operator item:** setting `DATABASE_URL_TEST` would make CI meaningfully protective, but must point at a
DISPOSABLE database. The suite's fixtures TRUNCATE, and this repo has already destroyed its production data
once that way (`INCIDENT-PROD-DB-WIPE-2026-07-18.md`). Never point it at the production URL.
