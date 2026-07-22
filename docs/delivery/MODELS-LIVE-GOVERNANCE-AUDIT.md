# MODELS-LIVE Governance Audit

Run started: 2026-07-22T02:46Z. Orchestrator: claude-fable-5 (xhigh) — BRAIN ONLY (plan/decompose/spawn/triage/adjudicate/authorize; never reads whole sources, writes fix code, drives the browser, collects evidence, or self-approves).

Prompt: /home/ubuntu/aether-subscription-prompt-live-test.md (MODELS-LIVE phase).
Roster manifest (first artifact): uat/reports/evidence/models-live/governance/ROSTER-MANIFEST.md — 14 agents, exact §0.2 models, 0 `inherit`.

## Standing rulings

- **R-1 (spawn discipline):** every Agent spawn forces the model tier param (haiku/sonnet/opus) matching the roster manifest, as defense-in-depth over frontmatter. `fable` is never used for sub-agents. Zero orchestrator-tier spawns permitted.
- **R-2 (registry fallback):** if a roster subagent_type is not yet registered in the session's agent registry (files created mid-session), the orchestrator dispatches the closest registered type or general-purpose WITH the roster file's role prompt inlined verbatim AND the forced roster model tier. Logged per occurrence below. This preserves role+model separation; it is not a tier violation.
- **R-3 (always-on monitors):** continuous capture (§6) is implemented as persistent background processes (survive agent exits) created/owned by runtime-monitor + periodic monitor agent invocations for triage; the orchestrator schedules triage invocations continuously through the phase, not in end batches.

## Dispatch log

| # | time (UTC) | subagent_type (roster role) | forced model | task | outcome |
|---|---|---|---|---|---|
| 1 | 2026-07-22T02:50Z | scout | haiku | Step 1 runbook verification vs live topology | ✅ VERIFIED (RUNBOOK-VERIFICATION.md; 1 LOW drift → ML-runbook-001) |
| 2 | 2026-07-22T02:55Z | evidence | haiku | Steps 2+3 health probe + canonical-login.md | ✅ health 200 ok v0.2.0 (34ms); canonical-login.md + proof written |
| 3 | 2026-07-22T03:02Z | scout | haiku | ML-agents-cred-001 RCA (USER-REPORTED BLOCKER: anthropic credential 422) | dispatched |
| 4 | 2026-07-22T03:02Z | runtime-monitor | haiku | Step 4a: persistent log capture + baseline triage + first route sweep | dispatched |
| 5 | 2026-07-22T03:02Z | browser-monitor | haiku | Step 4b: first console/pageerror/requestfailed sweep of all routes | dispatched |

| 6 | 2026-07-22T03:05Z | evidence | haiku | ML-agents-cred-002 OAuth mechanics probe (historical anthropic_oauth.py, tables, authorize URL) | dispatched |
| 7 | 2026-07-22T03:05Z | scout | haiku | Step 5 SCREEN MATRIX + AGENT/MODEL MATRIX | dispatched |
| 8 | 2026-07-22T03:12Z | reviewer | sonnet | ML-agents-cred-001 fix-plan adversarial review (§7 step 1) | dispatched |

| 9 | 2026-07-22T03:20Z | arch | opus | ML-agents-cred-002 OAuth-page flow BLUEPRINT (R-2: registered specialist type, forced opus, blueprint-only, awaits fable-5 approval) | dispatched |
| 10 | 2026-07-22T03:20Z | evidence | haiku | Step 6 Agents-screen current-state audit (FIX-1 before-record) | ✅ CURRENT-STATE.md + 5 screenshots; per-agent picker MISSING (global only), no freshness note, no refresh → ML-catalog-001/002/003 |
| 11 | 2026-07-22T03:40Z | reviewer | sonnet | ML-agents-cred-001 fix-plan review | ✅ PASS-WITH-AMENDMENTS (caught compliance hole: anchor ^sk-ant-oat\d+-, both files, keep oat01 example) |
| 12 | 2026-07-22T03:45Z | test-author | sonnet | ML-agents-cred-001 failing tests (branch fix/ml-cred-001) | dispatched |

**Step 5 outcome (dispatch #7):** ✅ 18 wireframes / 29 routes / 22 catalog agents (8 runtime) / 337 OpenRouter models cached 1h / PUT /api/agents/config/{agent_key} / probe agent jobDiscovery. Deltas: coverLetter ERROR state (→ ML-agent-cover-001 watch), anthropic unconfigured (operator DELETEd post-422). SCREEN-MATRIX.md + AGENT-MODEL-MATRIX.md filed. Browser sweep (dispatch #5): 26 routes, 23 clean, 3 benign ERR_ABORTED prefetch (→ ML-browser-001..003 LOW, tester to confirm). Runtime monitor (#4): capture PID live, 0 baseline critical signatures, 17/17 route sweep OK, catalog endpoint /api/agents/providers/{provider}/models 200.

**RCA outcome (dispatch #3):** ✅ agents.py:2110-2121 prefix-only validation (sk-ant-api / sk-ant-oat01- exact), no whitespace strip, hardcoded oat01 in 422 text; 2×422 today 02:53Z then operator DELETE; operator on-disk token sk-ant-oat01- but EXPIRED 2026-07-21; no regression since d2df452. Fix plan authored (validation hardening only; OAuth flow = cred-002) → dispatch #8 reviews.

**INTERRUPT (2026-07-22T03:00Z):** operator reported live production defect mid-Phase-0 — PUT /agents/providers/anthropic/credential 422 "credential not recognized". Filed as ML-agents-cred-001 (BLOCKER) per §6.3 real-time dispatch; RCA scout dispatched immediately; fix pipeline (§7) will follow triage. Phase-0 Steps 5-6 proceed in parallel once monitors confirm running.

## Rulings (run-specific ADRs)

- **ADR-ML-1 (2026-07-22, binding):** Operator directive received mid-run: the Anthropic configure-credentials window MUST open Anthropic's auth web page for subscription users (in-app-initiated OAuth authorization). Precedence chain: this supersedes ADR-P6-OAUTH (prohibition, Phase-6) and EXTENDS ADR-P7-01 (which allowed paste-own-token but not in-app OAuth). Basis: explicit operator mandate for their own single-operator product, consistent with Phase-7's operator-brief override; the flow uses the operator's own Anthropic account/consent on Anthropic's own pages. Constraints carried forward unchanged: credentials never cross providers; no silent fallthrough on quota exhaustion; honest fallback to manual paste (Console API key mode) retained; token values never logged/committed (vault + masked hints only). Filed as ML-agents-cred-002 (BLOCKER, same fix cluster as ML-agents-cred-001).

## Escalations

(none yet)

## Violations

(none yet)
