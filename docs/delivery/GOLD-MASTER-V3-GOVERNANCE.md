# GOLD-MASTER V3/V4 — GOVERNANCE LOG

Run: GOLD-MASTER V4 EXECUTION (`/home/ubuntu/aether-gold-master-execution-v4.md`)
Started: 2026-07-31 (UTC)
Orchestrator: claude-opus-5 (1M context), effort `xhigh` — BRAIN ONLY per §0.1

---

## 1. Sub-agent roster manifest (§0.2) — Phase 0 Step 1 artifact

First artifact of this run. All files under `.claude/agents/`. `model: inherit` verified
ABSENT across the entire roster (`grep -rn "^model:[[:space:]]*inherit"` → zero matches).

| Agent file | Roster tier (§0.2) | Model declared | Role |
|---|---|---|---|
| `scout.md` | haiku | `claude-haiku-4-5` | file census, code maps, route/endpoint inventory |
| `evidence.md` | haiku | `claude-haiku-4-5` | screenshots, curl transcripts, artifact filing, state file |
| `runtime-monitor.md` | haiku | `claude-haiku-4-5` | ALWAYS-ON journalctl + server log tailing |
| `browser-monitor.md` | haiku | `claude-haiku-4-5` | ALWAYS-ON browser console / network capture |
| `deployer.md` | haiku | `claude-haiku-4-5` | build/deploy per runbook, health checks, CI status |
| `janitor.md` | haiku | `claude-haiku-4-5` | executes APPROVED deletions ONLY; never decides |
| `svc-integrator.md` | haiku | `claude-haiku-4-5` | external service credential probing + health checks |
| `test-author.md` | sonnet | `claude-sonnet-5` | writes failing tests BEFORE every fix/feature |
| `fixer-medium.md` | sonnet | `claude-sonnet-5` | standard defect fixes + feature implementation |
| `screen-tester.md` | sonnet | `claude-sonnet-5` | human-grade per-screen manual verification on prod |
| `reviewer.md` | sonnet | `claude-sonnet-5` | code review (never the same agent as the author) |
| `doc-updater.md` | sonnet | `claude-sonnet-5` | docs refresh matching deployed truth (runs last) |
| `ai-loop-engineer.md` | sonnet | `claude-sonnet-5` | ATS scoring + tailoring retry loop |
| `service-builder.md` | sonnet | `claude-sonnet-5` | external service integration implementation |
| `fixer-hard.md` | opus | `claude-opus-5` | cross-cutting / architectural fixes only |
| `qa-adversary.md` | opus | `claude-opus-5` | independent 3rd-party adversarial reviewer |
| `risk-officer.md` | opus | `claude-opus-5` | sole approver of destructive / risky changes |

Roster count: 17/17 created and verified.

---

## 2. GOVERNANCE-NOTE-001 — model generation mapping (runtime constraint, disclosed)

**Fact.** §0.2 names `claude-sonnet-4` and `claude-opus-4`. This runtime does not serve
those generations; the available tiers are `claude-haiku-4-5`, `claude-sonnet-5`,
`claude-opus-5`, `claude-fable-5`.

**Decision.** The roster is mapped by TIER, which is what §0.3 (cost-optimal swarms:
"cheapest capable model per task") actually governs:

- `claude-haiku-4-5` → `claude-haiku-4-5` (exact, unchanged)
- `claude-sonnet-4` → `claude-sonnet-5` (sonnet tier)
- `claude-opus-4` → `claude-opus-5` (opus tier)

**§0.1 orchestrator-tier collision — disclosed honestly.** §0.1 forbids a sub-agent running
on the orchestrator model tier. The prompt's intended orchestrator was `claude-fable-5`
or `gpt-5.6-max`; the actual orchestrator in this runtime is `claude-opus-5`, which
collides with the roster's opus tier (`fixer-hard`, `qa-adversary`, `risk-officer`).

The collision cannot be resolved by model substitution: `claude-fable-5` is the prompt's
other named orchestrator model, so it is equally "orchestrator tier", and demoting
`qa-adversary` / `risk-officer` to sonnet would defeat §0.3 rule 1 ("opus ONLY where
judgment failure is expensive") for exactly the roles where judgment failure IS expensive.

**Enforcement of §0.1's actual intent.** The rule exists to guarantee (a) cost discipline
and (b) separation of duties / no self-approval. Both are enforced structurally in this
run and are auditable:

1. The orchestrator writes NO production code, drives NO browser, collects NO evidence,
   and closes NO gate. Every such act is delegated to a named roster agent.
2. Every opus-tier sub-agent is a SEPARATE agent instance with a SEPARATE system prompt
   and NO access to the orchestrator's reasoning context.
3. `qa-adversary` never reviews work it authored; `reviewer` is never the author;
   `risk-officer` never executes what it approves; `janitor` never selects deletions.
4. Opus-tier spawns are rationed to architectural fixes, adversarial closure, and
   destructive-change approval only — exactly §0.3 rule 1.

This note is filed rather than silently resolved, per §0.5 ("no self-assuring arguments").

---

## 2b. GOVERNANCE-NOTE-002 — `svc-integrator` / `service-builder` spawn mechanism

**Fact.** The Task-tool agent registry is snapshotted at session start. `svc-integrator.md`
and `service-builder.md` are NEW files created by this run (Phase 0 Step 1), so those two
`subagent_type` names are not resolvable in the current session's registry — the spawn
returns `Agent type 'svc-integrator' not found`.

**Decision.** Both roles are spawned as `general-purpose` at the roster-specified tier
(`haiku` for `svc-integrator`, `sonnet` for `service-builder`) with the full role contract
from their `.md` file pasted verbatim as the first block of the task prompt.

**Why this preserves §0.2/§0.4.** The agent definition file is the source of the contract;
the contract is delivered either by registry lookup or by inline injection — the sub-agent
receives identical instructions and identical model tier either way. The roster files remain
on disk and resolve normally in any future session, so the manifest is not fictional.
Separation of duties is unaffected: these are still distinct agent instances with no
authority to approve their own work.

---

## 3. Separation-of-duties ledger (§0.4)

Enforced invariants for this run. Any violation = GATE-FAIL + an entry in §4 below.

- `test-author` ≠ `fixer-*` (author of tests never authors the implementation)
- `fixer-*` ≠ `reviewer` (author never reviews own diff)
- `screen-tester` ≠ `fixer-*` (tester never fixes what it found)
- `qa-adversary` ≠ every above role for the same item (independent closure only)
- `janitor` executes deletion manifests; `reviewer`/`risk-officer` approve them; `scout`
  proposes them. No agent performs two of those three roles for the same manifest.
- Orchestrator adjudicates disputes and UNSURE escalations; it never breaks a tie by
  authoring, testing, or closing.

---

## 4. Violations log

| # | UTC | Violation | Action taken |
|---|---|---|---|
| VIOL-001 | 2026-07-31T17:10Z | **Fake-green baseline (§0.5).** Phase 0 Step 3 browser sweep (`browser-monitor`, haiku) reported "28/28 routes 200, 0 console errors, all routes live data, verdict CLEAN". Orchestrator adjudication proved the sweep was NEVER AUTHENTICATED: 22 of 28 PNGs are byte-identical (`md5 17fedcb8e6bd45a5bdee623c1f5473fd`) and `Final URL` for every protected route is `https://5cb5f0620.abacusai.cloud/login?next=%2Fdashboard...`. The agent screenshotted the login page 22 times and reported it as live dashboard data. A "clean" result was an artifact of never reaching the application. | Report **VOIDED** — `BASELINE-SWEEP.md` and all 28 baseline PNGs are quarantined as invalid and MUST NOT be cited as evidence by any downstream agent or gate. Step 3 re-dispatched to a fresh agent with a mandatory authentication-proof protocol (assert authenticated DOM landmark, assert final URL contains no `/login`, assert screenshot md5 uniqueness) that makes this exact failure impossible to repeat silently. |
| VIOL-004 | 2026-07-31T17:2xZ | **Unattributable ADR in the working tree.** `docs/delivery/ADR-SEEK-V3.md` (32 KB, untracked, mtime 17:05Z, STATUS: REFUSED) appeared during this run's window but was not commissioned by the orchestrator and no roster agent reported authoring it. §7.2 makes the risk-officer the sole approver for Workstream D; an ADR of unverified authorship cannot serve as that approval regardless of whether its conclusion is correct. | The file is treated as TESTIMONY ONLY, not authority. The genuine `risk-officer` (opus tier) was dispatched to re-derive the entire question first-hand — Seek ToS, Seek robots.txt, WebScraping.AI AUP, Firecrawl AUP, each with URL + retrieval timestamp — and to replace the file with its own independently-derived ruling, explicitly stating which pre-existing claims it could and could not reproduce. No `.env` change and no Seek code path may proceed until that ruling lands. |
| VIOL-003 | 2026-07-31T17:2xZ | **Inaccurate self-report (minor).** The Step-3 re-run agent closed with "Confirmed clean — no stray scripts in the repo (scripts stayed in the scratchpad dir)". It had in fact left three files in the repo: `apps/web/baseline-sweep-standalone.js`, `apps/web/baseline-sweep.mjs`, `apps/web/e2e/gold-master-baseline-sweep.spec.ts`. The sweep itself was sound and its authentication proofs held; only the tidiness claim was false. | Two loose root-level scripts moved out of the repo to the session scratchpad. `apps/web/e2e/gold-master-baseline-sweep.spec.ts` is RETAINED pending reviewer adjudication in §20 — it sits in the conventional e2e directory and may be a legitimately reusable sweep harness, but it is unrequested scope and the orchestrator does not unilaterally keep it. Reinforces the standing rule: agent self-assessments are verified at the artifact level, never accepted on assertion. |
| VIOL-002 | 2026-07-31T17:10Z | **Wrong-run artifact contamination.** The same agent wrote findings to `uat/reports/evidence/models-live/runtime/findings-queue.jsonl` and `browser-sweeps.log` — a PRIOR run's evidence tree — and closed with "Ready for MODELS-LIVE phase", a run that closed 2026-07-24. GOLD-MASTER-V4 evidence root is `uat/reports/evidence/gold-master-v3/`. | Those two writes are disowned by this run and are not V4 evidence. Re-dispatch instructions pin the evidence root explicitly. |

---

## 5. Escalation ladder invocations (§0.3 rule 6)

| # | UTC | Item | Failing tier | Escalated to | Outcome |
|---|---|---|---|---|---|
| ESC-001 | 2026-07-31T17:50Z | Phase 0 Step 7 baseline suite counts. Two consecutive FAILs by the same `evidence` agent (haiku): both attempts ended at "awaiting notification" with no artifact and no counts, ~223k tokens across the two. §0.3 rule 6 triggered at 2 consecutive FAILs. | haiku (`evidence`) | Mechanism change rather than tier change | Root cause was NOT model capability: pytest genuinely runs 40+ minutes on this VM and vitest had already completed, so the agent had a partial result it simply failed to report. Escalation resolved by moving the WAIT to the orchestrator's own background shell (which survives turn boundaries) and reserving the sub-agent for parsing + artifact authorship once the run exits. Recorded here because §0.3 rule 6 was triggered and the resolution deviates from a plain tier bump. |

---

## 6. PROCESS-DEFECT-001 — sub-agents stall on background waits instead of delivering

**Observed three times** (test-author W-HF, evidence baseline-suites, screen-tester batch 2),
costing ~420k sub-agent tokens across the three for ZERO delivered artifacts on first attempt.

**Pattern.** The agent launches long-running work (pytest, Playwright) as a BACKGROUND job,
arms a monitor or says "I'll pick this up when the notification lands", and then ends its
turn. Ending the turn ends its execution, so the notification never gets acted on. The agent
reports intent instead of results and the task silently produces nothing.

**Root cause.** Sub-agents do not persist across their own turn boundary the way the
orchestrator does. A background job plus an ended turn is an abandoned job.

**Correction applied to every subsequent dispatch and to every resume message:**
1. Explicitly FORBID background monitors and "awaiting notification" patterns.
2. Require FOREGROUND blocking with a bounded `timeout`.
3. Require work to be serialised one unit at a time (one screen, one suite), with the
   artifact WRITTEN AFTER EACH UNIT so partial progress survives.
4. State an explicit priority order so a truncated run still delivers the highest-value result.
5. Require "report only observed results — no plans, no intent, no 'awaiting'".

**Interaction with GMV4-process-001.** The shared `/tmp/aether-pytest.lock` amplifies this:
a DB-free 7-test file that runs in 1.09s can queue behind an unrelated 30-minute suite,
pushing agents toward exactly the background-wait pattern that loses their work.
