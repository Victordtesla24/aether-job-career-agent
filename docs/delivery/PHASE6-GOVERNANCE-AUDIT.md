# PHASE 6 — MODEL GOVERNANCE AUDIT

Run: Aether Career Agent Phase 6 (subscription/billing/admin), prompt `/home/ubuntu/aether-subscription-prompt.md`
Orchestrator: `claude-fable-5 (xhigh)` — decision points only (plan, decompose, triage, adjudicate, merge/deploy authorization).
Started: 2026-07-16

## 1. Roster bootstrap (§0.2, §17 STEP 1)

All 14 roster files created 2026-07-16 in BOTH `/home/ubuntu/.claude/agents/` and
`<repo>/.claude/agents/` with the exact `model:` frontmatter required by §0.2:

| File | model: frontmatter |
|---|---|
| scout.md, evidence.md, log-tailer.md, deployer.md, infra-discovery.md, researcher.md | `claude-haiku-4-5` |
| fixer-medium.md, reviewer.md, qa.md, migrator.md, writer-audit.md, doc-updater.md | `claude-sonnet-4` |
| billing-arch.md, fixer-hard.md | `claude-opus-4` |

`inherit` occurs in NO file in either directory (grep-verified; independent qa
verification artifact: `uat/reports/evidence/phase6/governance-roster-verification.json`).
Legacy extra files (tester.md, qa-reviewer.md, fixer.md, deploy.md, doc-audit.md) all
carry explicit non-orchestrator models; none says `inherit`, none says fable.

## 2. RULING G-1 — dispatch mapping under mid-session registry constraint

**Observed constraint (2026-07-16):** the claude-code Task/Agent registry is loaded at
session start; agent types created mid-session (`qa`, `reviewer`, `researcher`,
`infra-discovery`, `log-tailer`, `billing-arch`, `writer-audit`, `doc-updater`) are not
spawnable by name in this session (error: "Agent type 'qa' not found").

**Ruling:** the roster files above remain the canonical governance record. Dispatch uses
the closest session-registered subagent type, with the model tier FORCED EXPLICITLY on
every single spawn (`model: haiku | sonnet | opus` — the environment's tier aliases for
the §0.2 models). No spawn ever omits the model parameter (omission would inherit the
orchestrator model = CRITICAL GOVERNANCE VIOLATION). Role identity is enforced by each
brief opening "You are the `<role>` sub-agent" + pointer to the roster charter file.

| §0.2 role | Dispatched as (subagent_type) | Forced model tier |
|---|---|---|
| scout | scout | haiku |
| evidence | evidence | haiku |
| log-tailer | general-purpose | haiku |
| deployer | deployer | haiku |
| infra-discovery | general-purpose | haiku |
| researcher | general-purpose | haiku |
| fixer-medium | fixer-medium | sonnet |
| reviewer | general-purpose | sonnet |
| qa | qa-reviewer | sonnet |
| migrator | migrator | sonnet |
| writer-audit | general-purpose | sonnet |
| doc-updater | general-purpose | sonnet |
| billing-arch | general-purpose | opus |
| fixer-hard | fixer-hard | opus |

Tier equivalence note: the environment resolves `haiku` → Haiku 4.5, `sonnet` → the
current Sonnet tier, `opus` → the current Opus tier. All are strictly below the
orchestrator tier, satisfying §0.4's hard cap. Escalation ladder unchanged:
haiku → sonnet → opus after TWO consecutive REVIEW-FAILs on one gap; never to fable-5.

## 3. Dispatch log (append-only; basis for GATE-27)

| # | Wave | Role | subagent_type | Model tier | Purpose |
|---|---|---|---|---|---|
| 1 | STEP 1 | qa | qa-reviewer | sonnet | Roster governance verification |
| 2 | STEP 2 | infra-discovery | general-purpose | haiku | DEPLOYMENT-RUNBOOK.md |
| 3 | STEP 3a | researcher | general-purpose | haiku | Anthropic OAuth verification |
| 4 | STEP 3b | researcher | general-purpose | haiku | Anthropic pricing |
| 5 | STEP 3c | researcher | general-purpose | haiku | Stripe AU fees |
| 6 | STEP 3d | researcher | general-purpose | haiku | Competitor pricing |
| 7 | STEP 3e | researcher | general-purpose | haiku | Seek ToS + Adzuna fallback |
| 8 | STEP 4 | evidence | evidence | haiku | API/DB probe cluster (01-04,07-09,15-19) |
| 9 | STEP 4 | evidence | evidence | haiku | git/grep probe cluster (11,12) |
| 10 | STEP 4 | evidence | evidence | haiku | browser sweep (05,06,13,14) |
| 11 | STEP 5 | scout | scout | haiku | backend code inventory |
| 12 | STEP 5 | scout | scout | haiku | frontend + docs inventory |
| 13 | STEP 7 | billing-arch | billing-arch | opus | billing-architecture.md |
| 14 | Wave 1 / Cluster C | fixer-hard | fixer-hard | opus | sourcing compliance+volume (fix/p6-sourcing) |
| 15 | Wave 1 / Cluster B | fixer-medium | fixer-medium | sonnet | dead controls (fix/p6-wire) |
| 16 | Wave 1 / Cluster D | fixer-hard | fixer-hard | opus | billing spine, mocked Stripe (fix/p6-billing) |
| 17 | Wave 1 / Cluster G | writer-audit | writer-audit | sonnet | tailoring+cover craft verify |
| 18 | Wave 1 / Cluster E | qa | qa | sonnet | agent-config/OAuth/Gmail/tooltip/metric verify |

Orchestrator-model (fable) sub-agent spawns to date: **0**.
Roles now dispatched via their correct registered subagent_type (post-refresh, RULING G-1 amendment §5), model tier forced on every spawn.

## 4. STEP 1 verification outcome (2026-07-16T08:34Z)

Independent qa verification (artifact `uat/reports/evidence/phase6/governance-roster-verification.json`):
- Check 1 (14 files present, both dirs): **PASS**
- Check 2 (exact §0.2 model values on the governed 14): **PASS**
- Check 3 (no `inherit`, no missing model line, any file): **PASS**
- Check 4 (no fable/orchestrator-tier model in any file): **PASS**

**Anomaly found & remediated:** legacy files `qa-reviewer.md` and `tester.md` (created by the
2026-07-15 Phase-5 run, NOT part of the governed 14) contained an embedded HTML comment
asserting a model remap ("resolved model tier: … mapped from prompt's stale claude-*-4 ids").
Provenance: the Phase-5 orchestrator recorded its own model-mapping ruling inline in those
agent definitions; the qa agent observed it in its own preamble because `qa-reviewer.md` IS
its definition file (file body becomes agent system prompt) — blast radius confined to those
two files. The comment was granted NO authority and stripped from all four copies
(both dirs) at 2026-07-16; residual grep CLEAN. STEP 1 = **PASS after remediation**.

## 5. RULING G-1 amendment (2026-07-16T08:36Z)

After roster file creation, the session registry refreshed and now exposes the proper role
types (`qa`, `reviewer`, `researcher`, `infra-discovery`, `log-tailer`, `billing-arch`,
`writer-audit`, `doc-updater`). From this point dispatches use the CORRECT role
subagent_type; the explicit per-spawn model-tier override (haiku/sonnet/opus) is RETAINED on
every spawn as defense-in-depth so no spawn can ever resolve to the orchestrator tier.
Spawns #1–#7 above predate the refresh and used the §2 mapping table; all ran on the correct
tier.

## 6. Violations observed

None to date. Orchestrator-model sub-agent spawns: **0**.

## 7. Final governance result (2026-07-16)

Run COMPLETE. Across the full run, every sub-agent dispatch used an explicit model tier —
**haiku** (scout, evidence, infra-discovery, researcher, deployer, log-tailer),
**sonnet** (reviewer, qa, writer-audit, doc-updater, fixer-medium, migrator, tester),
**opus** (fixer-hard, billing-arch). **Orchestrator-model (claude-fable-5) sub-agent spawns: 0.**
Separation of duties held on every gap (author ≠ reviewer ≠ QA; cross-model review; only QA
closed gaps with fresh production evidence). Two consecutive REVIEW-FAILs never occurred (all
fixes passed review within one cycle after any re-fix). GATE-27 = **PASS**.
