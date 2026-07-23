# Workstream C — Wave 2 Manifest (SAFE: Python dead symbols, one-off scripts, shared web formatters)

Date: 2026-07-24 (Australia/Melbourne)
Base commit: b005f2c (wave 1)
Wave class: SAFE (7 candidates)
Reference traces: `wave-2-traces.txt` (fresh grep proofs captured this session, post-wave-1 HEAD)

## Candidates executed

| ID | Action | Detail |
|----|--------|--------|
| DEDUP-001 | DELETE (9 symbols) | Dead Python symbols, each with fresh 0-external-ref trace: `mark_refunded` (repositories/background_jobs.py), `set_approval_status` (repositories/resume.py), `purge_expired` + `clear` (repositories/user_provider_credential.py), `is_clean` (services/fabrication_guard.py), `automatic_tax_enabled` (services/stripe_gateway.py), `_job_summary` (agents/cover_letter_agent.py), `gmail_connected` + `create_draft` (services/gmail_service.py), `InterviewResponse` class (routers/interviews.py). Note: `all_sources` was on the inventory but had ALREADY been deleted by Workstream A — recorded as no-op here. Name-collision checks done: the live `purge_expired`/`clear`/`create_draft` hits elsewhere in the codebase belong to different classes/modules (verified in traces). |
| DEDUP-007 | CONSOLIDATE | New `apps/web/src/lib/format.ts` with `formatAud`; duplicate local copies removed from `app/pricing/page.tsx` and `app/dashboard/settings/settings-client.tsx` (now import the shared helper). |
| DEDUP-008 | CONSOLIDATE | `formatDateTime` / `formatDate` added to `lib/format.ts`; 3 local `fmtDate` copies replaced in `app/admin/audit-log/page.tsx`, `app/admin/users/[id]/page.tsx` (→ formatDateTime), `app/admin/users/page.tsx` (→ formatDate). |
| DEDUP-009 | CONSOLIDATE | `lib/agents-feedback.ts`: `extractApiDetail` now delegates to the shared JSON core of `extractApiJsonDetail` — behavior identical; the two remain separate exports because their contracts differ deliberately (NF-final-closure-002). |
| DEDUP-010 | CONSOLIDATE | `settings-client.tsx` local `EMAIL_RE` deleted; now imports `emailLooksValid` from `components/auth/validation`. |
| DEDUP-011 | CONSOLIDATE | `app/forgot-password/page.tsx`: two identical support-phone JSX snippets replaced with a single local `<SupportPhoneLine>` component. |
| DEDUP-013 | DELETE (3 files) | One-off scripts hard-deleted (`git rm`): `scripts/verify_phase0.py`, `scripts/ingest_ba_resume.py`, `apps/api/scripts/purge_demo_jobs.py`. Traces: only self/docs references; the `_ingest_ba_resume` symbol in tests is an unrelated local helper. `scripts/generate_ba_resume.py` NOT touched (DO-NOT-TOUCH list). |

## Incidents (honest record)

1. **interviews.py over-deletion, fixed pre-commit:** the scripted removal of the `InterviewResponse` class also consumed the adjacent `_INTERVIEW_COLUMNS` constant and the "Helpers" section header. Caught immediately by `ruff check` (F821). Both were restored via targeted insert; `ruff check app` now passes clean. Docstring referencing the deleted class updated.
2. **`@/lib/format` alias not resolvable in vitest:** first version of the DEDUP-007/008 imports used the `@/` tsconfig alias; vitest config has no matching alias, causing 5 test-file transform failures. Imports converted to relative paths (repo convention). vitest back to green.

## Verification (all run after final state of the wave)

- `ruff check app` (apps/api): All checks passed.
- `python -m ast` parse of all 8 edited Python files: OK.
- `pnpm exec tsc --noEmit` (apps/web): 0 errors.
- `pnpm lint`: ✔ No ESLint warnings or errors.
- `pnpm test` (vitest): **567 passed / 0 failed** — matches baseline.
- `pnpm build`: success.
- Full pytest suite (`scripts/run-tests.sh`): run kicked off this wave; result recorded below before commit.
- Playwright: wave touched pricing/settings/admin/forgot-password UI markup minimally (formatting helpers + one extracted local component, no testid/copy changes except none); full suite not re-run per baseline policy (51P/28F pre-existing).

### pytest result
- RESULT: **1173 passed, 0 failed** (29m28s, full suite via scripts/run-tests.sh) — matches baseline exactly.

## Net effect
- 16 files changed, +39 / −203 (web+python edits) plus 3 files hard-deleted.
