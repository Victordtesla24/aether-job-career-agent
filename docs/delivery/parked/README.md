# Parked WIP — 2026-07-29

This directory holds a WIP tree that was reverted per binding orchestrator rulings
R-1/R-2/R-3 in `docs/delivery/PRODUCTION-HARDENING-RUN-2026-07-29.md`, based on the
adversarial audit `docs/delivery/WIP-BRANCH-AUDIT-2026-07-29.json` (verdict: FAIL,
recommendation: REVERT).

## What's here

- `wip-parked-2026-07-29.patch` — full `git diff` of the 8 reverted files, captured
  before revert, so the work can be re-landed cleanly instead of re-derived from
  scratch:
  - `apps/api/app/db.py`
  - `apps/api/app/repositories/story.py`
  - `apps/api/app/routers/agents.py`
  - `apps/api/app/services/dedup.py`
  - `apps/web/src/app/dashboard/analytics/page.tsx`
  - `apps/web/src/app/dashboard/analytics/__tests__/page.test.tsx`
  - `apps/web/src/components/subscription-gate.tsx`
  - `apps/web/src/__tests__/dashboard/subscription-gate.test.tsx`
- `test_story_dedup.py.parked` — the untracked `apps/api/tests/test_story_dedup.py`
  (6/6 green against the WIP code), moved rather than copied because it imports
  symbols only the reverted `repositories/story.py`/`services/dedup.py` provide;
  leaving it in `apps/api/tests/` after the revert would break pytest collection.
- `wip-parked-2026-07-29-applications-banner.patch` — `git diff` of
  `apps/web/src/app/dashboard/applications/page.tsx` and
  `apps/web/src/app/dashboard/applications/__tests__/page.test.tsx`, captured
  before revert per orchestrator ruling R-6 (`uat/reports/evidence/models-live/web-fixes-review-verdict.json`,
  verdict FAIL). See blocker #4 below.

## Why this was reverted (4 proven blockers, across two adversarial reviews)

1. **`apps/api/app/routers/agents.py` — proven production-breaking (BLOCKER API-1).**
   The added `except FabricationError` / `except StructuralError` clauses (lines
   785, 805) reference names that are never bound at module scope — the only
   imports of `FabricationError`/`StructuralError` are function-local, elsewhere
   in the file. Because Python evaluates `except` clauses in raise order, every
   handler below those two (including `QuotaExhaustedError` → 429 and
   `LLMUnavailableError` → 503) becomes unreachable, so `NameError` fires
   instead. Concretely this orphans the `AgentRun` audit row in `'running'`
   forever, and — the billing-critical part — **`_refund_once()` never runs**,
   so a paying user's reserved run is consumed and never refunded on failure.
   Proven, not theorized: two pre-existing, untouched tests
   (`tests/test_llm_resilience.py::TestRouter503Mapping::test_tailor_returns_503_not_500_when_llm_unavailable`
   and `::test_failed_run_is_audited`) fail with
   `NameError: name 'FabricationError' is not defined` at `agents.py:785`.

2. **`apps/api/app/repositories/story.py` — latent 500 + internal-value leak.**
   `update()` appends `"contentHash" = %s` to its `UPDATE SET` clause but never
   calls `ensure_story_dedup_column()` (only `create()` does, at `story.py:31`).
   Production's `aether` schema has never run that DDL, so the first
   `PUT /stories/{id}` touching a STAR field on a freshly restarted api process
   raises `psycopg2.UndefinedColumn` → HTTP 500. Separately, the insert path's
   `_COLUMNS` includes the internal `contentHash` sha256 in the JSON response
   while the dedup-hit path's `_READ_COLUMNS` omits it — an internal dedup
   token leaks on first insert, and the response shape is inconsistent between
   the two paths. No test exercises `PUT /stories/{id}` at all (only 6 tests
   exist, none of them the update path), so neither defect is caught.

3. **`apps/web/src/app/dashboard/analytics/page.tsx` + its test — fabricated
   user-facing copy on a green "fake" test.** The new Applications-card tooltip
   claims "Distinct jobs submitted to an employer ... drafts in progress are
   excluded," but the card renders `dashboard.totalApplications`, which the
   backend (`apps/api/app/routers/analytics.py:631`) builds from
   `get_application_counts(...)['total']` — `COUNT(DISTINCT "jobId")` with **no**
   status filter, i.e. drafts ARE included. `apps/api/tests/test_analytics.py`
   (lines 219-234, untouched, still green) seeds 3 drafts + 4 non-draft
   applications and asserts the card shows 7 while the funnel's `applied` count
   is 4 — proving the tooltip's claim is false on the exact fixture the suite
   already exercises. The accompanying test edit in
   `apps/web/src/app/dashboard/analytics/__tests__/page.test.tsx` asserts the
   false string rather than the underlying semantics, so it locks the falsehood
   in as a protected regression instead of catching it. This also silently
   reverses a documented data-consistency ruling (MV-analytics-005, encoded in
   `analytics.py:40-42` and `:625-630`) with no ADR.

   (`subscription-gate.tsx` + its test were reverted alongside these under the
   same ruling batch — see R-3 below; not itself one of the three proven
   blockers, but an un-authorized paywall exemption.)

4. **`apps/web/src/app/dashboard/applications/page.tsx` + its test — applications
   safety-banner rewrite asserts `approvalGate`/`autoApply` control agent
   behavior; both fields are persisted-but-inert (no backend consumer; the real
   gate is `_APPROVAL_GATED` in `apps/api/app/routers/agents.py:77`, applied
   unconditionally regardless of either toggle).** Proven by ruling R-6
   (`uat/reports/evidence/models-live/web-fixes-review-verdict.json`, findings
   MF-1..MF-4): `grep agentConfig` over `apps/api/app` shows `approvalGate` and
   `autoApply` appear only in the settings-payload DDL/read/write path
   (`db.py`, `routers/workspaces.py`) — no worker, agent, or router ever
   branches on either field. Turning the Settings toggle off disables no gate;
   turning it back on enables none. The banner's red-branch copy ("Approval
   gate is OFF — generated proposals can be submitted without your review" /
   "Auto-apply is also on — agents will process AND submit without any human
   in the loop") therefore invents a risk state that cannot occur. Its 3 new
   tests (added in the same session that made this un-authorized rewrite) pin
   those exact false strings as protected regressions — the identical
   fake-green anti-pattern already rejected in blocker #3 above, now applied
   inconsistently by not also being caught here the first time.

   **Record correction:** the original `WIP-BRANCH-AUDIT-2026-07-29.json`
   entry for this file claimed it was "Already live in the running web build."
   That premise is **false** — `git log -S "approvalGateOn" -- apps/web/src/app/dashboard/applications/page.tsx`
   returns empty, i.e. this code was never committed and never shipped. It was
   uncommitted work-in-progress the whole time, exactly like the other three
   blockers above, not a live production surface. The audit's other premise
   for this file — "Correctly wired to a real, defaulted backend field" — is
   true only in the trivial sense that the field is persisted; it drives no
   backend behavior (see MF-1/MF-2 above).

## What a re-land must fix

- **`agents.py` (GAP-P4-002):** add a **module-level**
  `from app.agents.cover_letter_agent import FabricationError, StructuralError`
  import (not function-local), plus a **failing-before test** asserting that a
  `FabricationError`/`StructuralError` guard rejection produces `AgentRun`
  `status='completed'` with `coverLetterUnavailable=true` — today there is zero
  coverage of the intended new behaviour. Also resolve the open async
  double-terminal-transition question (API-6: the handler writes a terminal
  `'completed'` status *and* re-raises, while the async worker independently
  writes its own terminal transition — unproven whether that double-writes).

- **`story.py` (G-P4-STORY-DEDUP-004):** call `ensure_story_dedup_column()` at
  the top of `update()`, not just `create()`. Align `_COLUMNS` (insert path,
  includes `contentHash`) and `_READ_COLUMNS` (dedup-hit path, excludes it) so
  `POST /stories` returns the same response shape either way, and drop the
  internal sha256 hash from both — it should never reach the client. Add a
  `PUT /stories/{id}` test covering the hash-refresh path. Restore the missing
  trailing newline at EOF.

- **`analytics/page.tsx` (G-P4-FUNNEL-INCONSISTENCY-002):** the tooltip must
  only claim "drafts excluded" if paired with a **matching backend status
  filter** — i.e. either switch the card to
  `get_application_counts(...)['submitted']` (which itself reverses
  MV-analytics-005 across Dashboard/Tracker/Market Pulse and needs its own
  **ADR**, not a copy-only edit), or leave the backend as `'total'` and restore
  honest copy that says the count includes drafts. Do not ship copy and number
  that disagree.

- **`subscription-gate.tsx` (G-P4-EMAIL-RENDER-001):** the `/dashboard/email`
  paywall exemption is a pricing/packaging decision, not a rendering bug fix —
  it needs an **owner decision** (filed human-gated per the run doc) and, if
  approved, **real backend entitlement enforcement** on
  `apps/api/app/routers/emails.py` first (it currently has zero
  subscription/quota/entitlement references — grep confirms). Shipping the
  frontend exemption alone opens a live paywall hole.

- **`applications/page.tsx` (G-P4-AUTOAPPLY-CONTRACT-006):** re-land only
  together with real wiring of `approvalGate`/`autoApply` into the backend
  (a worker/router that actually branches on them), with failing-before tests
  proving gate-OFF changes server behavior — **or**, if the toggles are meant
  to stay cosmetic/future-facing, rewrite the copy to honestly describe the
  real, always-on `_APPROVAL_GATED`/`ApprovalRequest` gate
  (`apps/api/app/routers/agents.py:77`, `apps/api/app/routers/approvals.py:178`)
  instead of claiming the Settings toggle controls it. Either way, replace the
  3 tests that pin the literal fabricated sentences with tests that assert
  which branch renders for which config (semantics), not the false copy
  itself.
