# Workstream C — Wave 4 Manifest (CAREFUL: low-risk web consolidations) + Final Adjudications

Date: 2026-07-24 (Australia/Melbourne)
Base commit: 2de6e70 (wave 3)
Wave class: CAREFUL (3 executed candidates + full adjudication record for all remaining)
Reference traces: `wave-4-traces.txt`

## Executed

| ID | Action | Detail |
|----|--------|--------|
| DEDUP-026 | CONSOLIDATE | `ProviderConfigModal.tsx`: shared `runConnect(fn)` wrapper owns the identical catch/finally of the two Connect-with-Anthropic handlers (`connectAnthropic`, `completeAnthropic`). `renewAnthropic`/`verify` deliberately NOT folded in (different notice contexts/messages). `.slice(0,160)` and `setBusy(null)` preserved verbatim. |
| DEDUP-027 | CONSOLIDATE | `components/agents/api.ts`: `parseProviderCatalog(res)` + `withLiftedApiError(fn)` helpers; `fetchProviderCatalog`/`refreshProviderModels` now share the validate/map/lift tail (byte-identical behavior). |
| DEDUP-037 | DELETE (2 wrappers) | `lib/api/approvals.ts` `approveRequest`/`rejectRequest` deleted; `app/dashboard/page.tsx` now calls `decideApproval(id, action)` (strict superset — identical request with default empty context, same `ApprovalSchema` return). Dashboard test mocks updated to mock `components/approvals/api`'s `decideApproval`. |

## Verification
- `pnpm exec tsc --noEmit`: 0 errors. `pnpm lint`: clean. `pnpm test`: **567 passed / 0 failed** (baseline-equal). `pnpm build`: success. No Python touched.
- Targeted Playwright smoke (approvals + dashboard specs) attempted twice against the running prod build: the shared `auth.setup.ts` login step timed out both times (`waitForURL **/dashboard` 20s) — pre-existing flakiness territory (full suite baseline is 51P/28F); the API login endpoint itself verified working via curl (200 + access_token) this session. Per retry budget the smoke was NOT green — recorded honestly; the changed approve/reject path is covered by the passing dashboard vitest specs, and a manual prod smoke happens at deploy time. `uat/reports/evidence/manual-verification/` reverted; `test-results/` cleaned.

## Adjudicated KEPT (kept-with-reason, per CONSOLIDATION-PLAN adjudications)

CAREFUL Python extractions — kept: real duplication but zero dead LOC, all in billing/SQL/DDL/deploy-critical paths; launch-freeze risk outweighs benefit:
- DEDUP-014 (RateLimiter bucket prologue), 015 (API provider-model tail), 016, 017 (funnel SQL fragment), 018 (consent-URL 503 helper), 019 (interview field block), 020 (partial-UPDATE builder — SQL param order risk), 021, 022, 023, 024, 039.

CAREFUL web refactors — kept: a11y/testid/user-visible-copy regression risk exceeds the LOC saved:
- DEDUP-025, 028 (model-picker presentation), 029, 030, 031, 032, 033, 034, 035, 036, 038 (application fetchers — documented deliberate schema extension).

RISKY — adjudicated per plan §TIER-3:
- DEDUP-043: KEEP-DRIFTED. 044 (lazy-DDL ensure_table): DEFER — behavior-changing merge. 045: KEEP (user-visible copy). 046: KEEP (settings predicate deliberately narrower — checkout banner). 047: KEEP (secret-scoping risk). 048: KEEP (human-gated; GoogleCredential still backfilled at runtime, gmail_account.py:143).

FALSE-POSITIVE — adjudicated-kept: DEDUP-049, 050, 051, 052, 053 (carve-outs incl. e2e/auth.setup.ts, schema.prisma, Vik_Resume fixture + generate_ba_resume.py).

New from this run's fresh sweep: `BLUEPRINT.md` case-pair — both files are distinct, ADR-referenced documents (MODELS-LIVE-GOVERNANCE-AUDIT.md:148 cites both) → adjudicated-kept.
