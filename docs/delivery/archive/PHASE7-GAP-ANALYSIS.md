# PHASE-7 GAP ANALYSIS

Seeded 2026-07-17 by fable-5 (orchestrator) from fresh Phase-7 probe artifacts (`uat/reports/evidence/phase7/`) and the approved claim ledger (`PHASE7-CLAIM-LEDGER.md`). Machine-parseable mirror (single source of truth for statuses): `phase7-gap-analysis.json`.

## Rulings (ADRs)

| ADR | Ruling |
|---|---|
| ADR-P7-01 | **DEF-A stands (CRITICAL).** Phase-7 operator brief (§14) supersedes ADR-P6-OAUTH: pasting one's own `claude setup-token` output (`sk-ant-oat01-`) is a different mechanism than the prohibited in-app OAuth flow. Phase-5/6 oat-rejection compliance tests are superseded by §14.7 tests. qa's format-only-validation finding folds into DEF-A (§14.4 test-connection). No silent credential fallthrough; token never logged. |
| ADR-P7-02 | **DEF-B stands (CRITICAL).** Stored `admin@aether.local` fails its own validator on save (observed 422). §15 allowlist (`AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`, default `aether.local`) is mandated. |
| ADR-P7-03 | Async design against **observed** infra: Redis/arq not installed; venv is `/opt/abacus-python`. arch blueprint + fable-5 approval before build. |
| ADR-P7-04 | Pre-seeded SRC-001 / REPO-001 / NONPROD-001 / FIXTURE-001 **rejected/not-triggered** on fresh evidence; real sourcing risk reassigned to GAP-P7-DISCOVERY-001. |

## Active gaps (priority order)

| # | Gap | Sev | Status | Fixer | Gates |
|---|---|---|---|---|---|
| 1 | GAP-P7-DEF-A — oat01 token rejected; validation format-only, no live test | CRITICAL | TRIAGED | fixer-hard (opus-4) | 02–06 |
| 2 | GAP-P7-DEF-B — settings 422 on stored `aether.local` email | CRITICAL | TRIAGED | fixer-medium (sonnet-4) | 07–09 |
| 3 | GAP-P7-ASYNC-001 — no async generation; pipeline/run >150s timeout | CRITICAL | TRIAGED | fixer-hard (opus-4) | 11–13 |
| 4 | GAP-P7-DISCOVERY-001 — aether-discovery unit failing (exit 22) | HIGH | TRIAGED | fixer-medium | 10 |
| 5 | GAP-P7-WEBLOG-001 — web log webpack TypeError (live routes clean) | LOW | TRIAGED | deployer/fixer-medium | 16–17 |
| 6 | GAP-P7-DIR-001 — §17 consolidation (43 dup-doc candidates) | MEDIUM | TRIAGED | fixer-medium | 23 |
| 7 | GAP-P7-DOCS-001 — §18 docs refresh (+ stale figures, lift hedging) | MEDIUM | TRIAGED | doc-updater | 24, 27 |
| 8 | GAP-P7-VERIFY-COVER — CL-08 verify-only (J4 cover leg) | LOW | TRIAGED | qa | 14 |

## Rejected pre-seeds (fresh evidence)

- **GAP-P7-FIXTURE-001** — NOT-TRIGGERED: 0/60 fixture fingerprints in live responses (probe-p7-04e empty); CL-09 CONFIRMED.
- **GAP-P7-SRC-001** — REJECTED: 32 jobs / 5 sources (3 ≥ 5 each), 0 dup, 0 stale, 10/10 live.
- **GAP-P7-REPO-001** — REJECTED: exactly `refs/heads/main`, 0 open PRs.
- **GAP-P7-NONPROD-001** — REJECTED: 0 suspicious hits; replay-guard at `apps/api/app/main.py:59`.

## Blocked-on-human snapshot

H-01/02/03 (Stripe) BLOCKED · H-04 (admin env) BLOCKED · H-05 (Gmail) BLOCKED · H-06 (Adzuna) OPTIONAL (floor exceeded) · **H-07 (operator Claude token) SATISFIED** (present on exec machine, probe-p7-08e).

## Dependency order

DEF-A blueprint (arch + fable-5 approval) → DEF-A build ∥ DEF-B build ∥ DISCOVERY-001 RCA; ASYNC-001 blueprint (arch + approval) → ASYNC build; DIR-001 strictly after all code merges; DOCS-001 last.
