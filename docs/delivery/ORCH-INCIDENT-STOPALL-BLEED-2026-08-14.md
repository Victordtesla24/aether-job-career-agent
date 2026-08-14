# INCIDENT — "Stop All Agents" inert for 9h; autopilot spend continued (2026-08-14)

**Severity:** P1 (real LLM spend against an explicit user stop; honesty-law surface).
**Status:** Enforcement built + independently verifying; worker stopped as interim tourniquet;
emergency stopgap guard green-lit to the concurrent session; permanent fix lands with this run.

## Timeline (UTC)

| Time | Event |
|---|---|
| 12:31 | Operator clicked "Stop All Agents" — all 22 `AgentConfig` rows `enabled=false`; UI claimed "New runs are on hold." |
| 12:31→21:2x | `board_sweep` autopilot kept dispatching tailor/coverLetter/scout/fitScorer every few minutes — **no dispatch path reads `AgentConfig.enabled`** (display-only field). Real OpenRouter spend post-stop. |
| ~20:5x | Operator reported the false success to ORCH-EXEC; root cause confirmed in minutes (inert-field class, same as the historic autoApply finding). Enforcement ticket ML-STOPALL-001 dispatched (tests-first). |
| 21:22–21:26 | A coverLetter run executed live mid-incident (id c9ea855). |
| 21:3x | Operator escalated to session 9c6a2ba6; that session `systemctl stop aether-worker` (global sweep halt, reversible; api/web untouched, health green). Run c9ea855 killed mid-flight — terminal-state honesty check owned by 9c6a2ba6. |
| 21:4x | ML-STOPALL-001 build complete: enforcement at `_execute_reserved_run` — proven single convergence point of ALL execution paths (sync API, pipeline, board_sweep, async worker direct call). 8/8 RED→GREEN, 165-test regression, refund-once, honest coded 409, `skipped_paused` sweep counter, FE copy honest ("blocked", in-flight disclosure, no force-kill claim). Independent verifier running. |
| 21:5x | ORCH-EXEC green-lit 9c6a2ba6's **interim 5-line `_dispatch` guard** (covers 100% of currently-active paths while async generation is OFF in prod) so `aether-worker` can return before the full gated landing (2–3h out). Marked "INTERIM — superseded by ML-STOPALL-001"; reconciled deliberately at the landing merge. |

## Root cause

`AgentConfig.enabled` was written by the PATCH endpoint and read ONLY by the catalog display —
never by `_dispatch`/`_record_run`/`_execute_reserved_run`, the sweep, or the async worker. The
"Stop All" success toast asserted an enforcement that did not exist.

## Permanent fix (this run)

Enforcement at the true chokepoint (`_execute_reserved_run`) with: backend→catalog-key resolution
via the shipped mapping (stale wrong-key rows inert), absent-row default enabled, honest named
409 + run-row "failed" + exactly-once quota refund, sweep skip-and-continue, async terminal-state
honesty, and truthful FE copy incl. the no-force-kill disclosure.

## Follow-ups (ledger)

1. Force-kill of in-flight runs (cancel/abort design: ARQ job abort + LLM call interruption) — not built; the UI now says so honestly.
2. Reconcile/remove the interim `_dispatch` guard at the ML-STOPALL-001 landing (keep-as-defense-in-depth vs drop — decided in the merge commit).
3. 9c6a2ba6: terminal-state honesty of the killed run c9ea855; spend-bleed quantification for the operator (12:31→21:3x window).
