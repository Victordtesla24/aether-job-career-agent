# TESTING-OUTCOME-REPORT — approval-modal (DESKTOP)

**Screen id:** approval-modal
**Screen name:** Approval Modal (Approvals inbox + review dialog)
**Route under test:** `/dashboard/approvals` (production)
**Wireframe:** `design/screens/approval-modal.html`
**Backing endpoints (matrix):** `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`, `POST /approvals/{id}/execute`
**Environment:** Production — `https://5cb5f0620.abacusai.cloud` (app at `/dashboard`)
**Repo / commit context:** `/home/ubuntu/github_repos/aether-job-career-agent`, brief generated at git SHA `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Tester:** screen-tester agent role, Claude Sonnet 5 (model id `claude-sonnet-5`), MANUAL-VERIFICATION Stage 1
**Session window (UTC):** Session 1: 2026-07-17T16:32:47Z – 2026-07-17T16:35:14Z (+ agent-trigger probes 16:16Z–16:31Z); Session 2 (fresh, verify-twice): 2026-07-17T16:37:49Z – 2026-07-17T16:38:06Z; Session 3 (type coverage): ~2026-07-17T16:41Z; Session 4 (modal UX): ~2026-07-17T16:42Z; report finalized 2026-07-17T16:45Z.
**Concurrency note:** admin/admin123 is a SHARED account being exercised by multiple concurrent screen-testers in this run (evidence: pre-existing `MV-mobile-approval-`, `mv-apptracker-guard-test`, `MV-coverletter-` prefixed rows observed at session start). All mutations in this report are scoped to approval ids I personally created or captured from my own API responses; the one pre-existing >48h-old approval I inspected (`cc5ff0a565fc2d055ab042009`, `InterEx Group`) was viewed read-only for the CLM-077 expiry check and never approved/rejected/modified.

---

## 1. What this screen SHOULD do (formed before testing, from the wireframe)

`design/screens/approval-modal.html` depicts a modal overlay over a dimmed dashboard: a header ("Approval Needed" + which agent/action), an action-summary row (role/company/source + confidence %), a "Why approval is needed" explanation box, an "AI reasoning" checklist (checks + one flagged/unverified caveat), a "Generated cover letter" text preview, a "Trust this agent" checkbox, and a three-button footer (Reject / Edit & Approve / Approve). The implied product intent: this is the human-in-the-loop safety gate — nothing is sent/submitted without the user being able to actually **read and judge** the AI's proposed action here. The accompanying inbox (not separately wireframed but implied by "Approvals" nav + the endpoint matrix) should list pending/approved/rejected requests, support filtering, and reflect approve/reject decisions immediately and durably.

## 2. Element inventory

| # | Element | Tested | Result |
|---|---|---|---|
| 1 | `/dashboard/approvals` page load | Yes | OK — loads, heading "Approvals", subtitle, pending count |
| 2 | Filter tabs: Pending / Approved / Rejected / All | Yes | OK — `aria-pressed` toggles, list updates, correct counts (7/6/4/17 at test time) |
| 3 | Approval card (title, status pill, confidence badge, meta line, preview snippet) | Yes | OK when payload has the fields; degrades to omitting sections when payload is sparse (see Finding 001) |
| 4 | Card "Review"/"View" button | Yes | OK — opens modal; label switches Review→View once resolved |
| 5 | Card "Approve" button | Yes | OK — fires `POST /approvals/{id}/approve`, list updates in place |
| 6 | Card "Reject" button | Yes | OK — fires `POST /approvals/{id}/reject`, list updates in place |
| 7 | Expired-badge + disabled card actions | Yes | OK — confirmed live on a real >48h-old row (read-only) |
| 8 | Modal open (Review click, and deep-link `?review=`) | Yes | OK both paths |
| 9 | Modal close: × button | Yes | OK |
| 10 | Modal close: Escape key | Yes | OK |
| 11 | Modal close: backdrop click | Yes | OK |
| 12 | Modal focus trap (Tab cycling) | Yes | OK — focus stays within dialog across 12 Tab presses |
| 13 | Modal "Why approval is needed" box | Yes | Renders correctly when payload.why present; absent (not an error state, just missing) when not — see Finding 001 |
| 14 | Modal "AI reasoning" checklist | Yes | Renders correctly (check/warning icons) when payload.reasoning present; absent otherwise — Finding 001 |
| 15 | Modal confidence badge | Yes | Renders when present; mishandles out-of-range values — Finding 004 |
| 16 | Modal "Generated cover letter" preview | Yes | Renders when payload.preview present; **absent for every real agent-generated approval** — Finding 001 |
| 17 | "Trust this agent" checkbox | Yes | OK — toggles, value round-trips into `trust_agent` on decide |
| 18 | Modal "Edit & Approve" button + textarea | Yes | OK for rich payloads (toggle, fill, discard all work); **permanently disabled for real agent-generated approvals** — Finding 002 |
| 19 | Modal "Reject" button | Yes | OK — fires `POST /approvals/{id}/reject`, closes modal, list updates |
| 20 | Modal "Approve" button | Yes | OK — fires `POST /approvals/{id}/approve`, closes modal, list updates, linked Application synced |
| 21 | Resolved-state modal (view-only: disabled buttons + "already {status}" note) | Yes | OK |
| 22 | Expired-state modal (disabled buttons + expiry note) | Yes | OK — live, on real data |
| 23 | Idempotency: double-approve | Yes | OK server-side — clean `409` both times tested |
| 24 | Empty state (`data-testid="approvals-empty-state"`) | Not reproducible | See NOT-TESTED |
| 25 | Unauthenticated access to `/dashboard/approvals` | Yes | OK — clean redirect to `/login` |
| 26 | Browser Back/Forward through modal-open state | Yes | Back exits the whole Approvals page rather than closing the modal — Finding 005 |
| 27 | Deep-link with a valid id | Yes | OK — modal opens directly |
| 28 | Deep-link with an invalid id | Yes | 404 correctly fired, but the resulting error message is never shown to the user — Finding 006 |
| 29 | Throttled reload (slow 3G-ish emulation) | Yes | OK — loading skeleton (`aria-busy` pulse cards) shown honestly, then real content; no broken/half-rendered state |
| 30 | Invalid `?status=` filter (API-level) | Yes | OK — clean `422` with a descriptive message, not a raw 500 |
| 31 | `email_send` approval type rendering | Yes | Mostly OK; minor cover-letter-specific label leakage — Finding 007 |
| 32 | `offer_response` approval type rendering | Yes | OK — correct subtitle "Negotiation Agent wants to respond to an offer" |
| 33 | `POST /approvals/{id}/execute` | Yes (API only — no UI caller exists) | Server-side correct (200/403/409 per state); zero UI wiring — Finding 008 |
| 34 | XSS-echo safety (`<script>`, `onerror=`, `onload=` in payload text fields) | Yes | Safe — rendered as literal escaped text everywhere; no injected `<script>` element, no `alert()` dialog fired |
| 35 | Unicode rendering (café, 你好, 🚀 emoji) | Yes | OK — renders correctly |
| 36 | Long/unbroken string boundary | Yes | Breaks page layout app-wide — Finding 003 |
| 37 | AI-agent integration: `POST /agents/cover-letter/run` (the gated agent) | Yes | Real generation confirmed (see §5); 1 success / 1 guard-rejection / 3 transient 503s across 5 live attempts |

## 3. Findings summary

See `findings.json` for the exact schema. Table:

| id | severity | category | summary |
|---|---|---|---|
| MV-approval-modal-001 | BLOCKER | wiring | Real agent-generated approvals show an almost-empty modal — no why/reasoning/confidence, and critically **no letter preview**, so the human can't actually review content before approving |
| MV-approval-modal-002 | HIGH | coverage-gap | "Edit & Approve" is permanently disabled for every real agent-generated approval (payload never has `preview`) |
| MV-approval-modal-003 | HIGH | visual | Long/unbroken job_title text breaks the whole page layout (horizontal overflow), bleeding into the Dashboard's "Needs Approval" widget too |
| MV-approval-modal-004 | LOW | validation | Out-of-range confidence (e.g. 1.5) renders as a nonsensical "2%" instead of being treated as invalid |
| MV-approval-modal-005 | MEDIUM | defect | Browser Back while the review modal is open navigates away from Approvals entirely instead of closing the modal |
| MV-approval-modal-006 | MEDIUM | defect | A failed deep-link (bad id) sets an error message that is immediately clobbered by a concurrent effect — the 404 is silently swallowed from the user's perspective |
| MV-approval-modal-007 | LOW | visual | `email_send` approvals keep cover-letter-specific "Generated cover letter"/"CV" copy |
| MV-approval-modal-008 | LOW | coverage-gap | `POST /approvals/{id}/execute` is correct server-side but has zero UI wiring anywhere |
| MV-approval-modal-009 | HIGH | agent-integration | A real generated letter shipped with a grammatically broken opening sentence ("...as an I am a direct match...") caused by a pronoun-rewrite bug colliding with the seeded account's name/title; invisible to review because of Finding 001 |

## 4. Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-024** — "27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors/20 routes, 0 same-origin 5xx, pytest/vitest/E2E counts" | **UNVERIFIABLE-FROM-UI** (as a whole claim) / **PARTIALLY-TRUE** for the approval-modal slice | I tested exactly 1 of the 20 routes and did not re-run the pytest/vitest suites myself (out of scope for a screen tester). For MY route across 2 full sessions: 0 unexpected console errors, 0 organic same-origin 5xx from any `/approvals*` call I made (`session1-part2-console.json`, `session2-verify-console.json` — the only console errors present are ones I deliberately triggered via 404/409/422 negative-path tests). **Counter-observation escalated separately (see UNSURE-1 below):** the shared production `api.log` shows 4 raw `500` responses on `GET /approvals?status=pending` from a different concurrent session, which I could not reproduce myself and cannot attribute with confidence — filed as UNSURE, not used to refute this claim. |
| **CLM-062** — "Playwright sweep of 14 dashboard routes + /pricing + /admin: 0 console errors/failed requests/page errors (GATE-03)" | **PARTIALLY-TRUE** for the approval-modal slice; **UNVERIFIABLE-FROM-UI** for the other 15 routes (not my scope) | Same evidence as CLM-024: 0 page errors (`pageErrors` arrays empty in both sessions), 0 unexpected console errors, 0 unexpected failed requests across normal navigation, filtering, and modal interactions on `/dashboard/approvals`. |
| **CLM-073** — "Approve/reject synchronizes the linked application's status (approve→submitted, reject→rejected), with a draft-only guard" | **CONFIRMED** for approve→submitted (fresh, live, verified twice); **PARTIALLY-TRUE / INFERRED** for reject→rejected-with-linked-application | Approve path: real agent-created approval `c3df4494103f796021d8aae69`, linked Application `c597b074bbd6214c31dcf75ec` was `draft` before (`application-before-approve.json`), approved via the live UI, confirmed `submitted` immediately after (session1-part2 step D) **and again in a fresh session** (session2-verify step V2). Reject path: I confirmed the approval's own status transitions `pending→rejected` live and twice (rich synthetic approval `cc33bf03f2796ec37e4b0ecc5`), but that approval had `applicationId: null` by construction (created directly via `POST /approvals`, not through the cover-letter agent), so I could not independently observe the Application-row side of the reject branch with fresh evidence — 4 consecutive real-agent attempts to generate a second linked letter for a true reject-test failed with transient `503: LLM backend unavailable` (see §5). The reject branch shares identical code (`apps/api/app/repositories/approval.py:135-161`) with the verified approve branch, so this half is **[INFERRED]** from code, not independently reproduced live. |
| **CLM-077** — "48-hour expiry badge, actions disabled once expired" | **CONFIRMED** (fresh, live, verified twice) | Read-only inspection of a genuinely >48h-old pre-existing approval (`cc5ff0a565fc2d055ab042009`, not mine, never mutated): `expired` badge visible on card, Approve/Reject disabled on card, "This request is older than 48h..." note + all three action buttons disabled in the modal. Reproduced identically in the fresh verify-twice session. |
| **CLM-093** — "Guard catches JD-echoed/capitalized-entity claims but not narrative embellishment; the human-approval gate is the backstop" | **PARTIALLY-TRUE** | (a) **CONFIRMED**: the automated FabricationGuard/claim-checker does hard-reject in production — one of my 5 real `POST /agents/cover-letter/run` attempts failed with `FabricationError: Fabricated entities detected: ['AI-first']`, and no approval was created for that run (`cover-letter-run1-poll-final.json`). (b) **CONFIRMED**: a mandatory, blocking human-approval gate exists — no letter is auto-submitted; every successful generation created a `pending` `ApprovalRequest`. (c) **NOT independently tested**: I did not construct/observe a narrative-/causal-embellishment-style hallucination bypassing the guard (would require broad adversarial content probing beyond this screen-test's scope/budget). (d) **Significant counter-evidence** to the "backstop" framing: Finding MV-approval-modal-001 shows the approval-modal itself does not display the letter text for real approvals — a human relying on this screen literally cannot review content for embellishment before approving (they would have to separately open Cover Letter Studio). Finding MV-approval-modal-009 is a live, concrete instance of a defective letter (broken grammar) that sailed through this exact gate unnoticed because of (d). |

## 5. AI-agent integration (§3.2.5)

The approval-gated agent for this screen is the Cover Letter Agent (`POST /agents/cover-letter/run`, async — enqueue + poll `GET /agents/jobs/{id}`). I ran it for real, 5 times, against real discovered jobs (via `POST /agents/scout/run` + `GET /jobs`), using jobs not already claimed by other concurrent testers' pending approvals:

| Attempt | Job | Outcome |
|---|---|---|
| 1 | GTM Technology Product Owner @ harvey | `FabricationError: Fabricated entities detected: ['AI-first']` — guard correctly rejected, no approval created |
| 2 | **Innovation Product Manager, Australia @ harvey** | **Success** — real letter generated (`deepseek/deepseek-v4-pro`, cost $0.00151, tokensIn 414/tokensOut 548, `billingAudit.quotaPath: "metered_api"`), approval `c3df4494103f796021d8aae69` created |
| 3 | Senior Agent Product Manager - Sydney @ decagon | `503: LLM backend unavailable` |
| 4 | Staff Product Manager, Onboarding @ airwallex | `503: LLM backend unavailable` |
| 5 | Technical Product Manager, Energy Storage @ Voltus | `503: LLM backend unavailable` |

- **Real vs fixture check:** compared attempt 2's output against `apps/api/tests/fixtures/llm/cover_letter/default.json` — the fixture's `hook_reason` ("shipping reliable, measurable delivery outcomes...") and body ("sprint cadence, PI Planning...") are **completely absent** from the real output. The real letter is grounded in the actual job posting (quotes "translate messy, high-value legal work into AI-powered workflows", "diagnose pain points, map high-value opportunities" — real JD language) and the real resume/story bank (ATO COBOL/mainframe test-automation harness, ANZ WebSocket telemetry). The one overlapping factual detail ("cut evidence effort from ~3 hours to ~15 minutes per scenario") is phrased differently in each and is a real, evidence-grounded resume fact — not a copy-pasted fixture string. **Fixture fingerprint: ABSENT. Real generation: CONFIRMED.**
- **Quota/audit:** `runsUsed` went 15→18 and `spendUsedUsd` 0.074688→0.077747 across the 5 attempts (quota decrements even on a guard-rejected run) — confirmed via `GET /billing/subscription` before/after (`quota-before-run1.json`, `quota-after-all-agent-attempts.json`). Every attempt (success and failure) appeared in the Dashboard's live "Agent Activity" feed with an honest status ("Cover Letter Agent run failed — LLM backend unavailable...", "...Fabricated entities detected: ['AI-first']") — visible in `21-back-forward-after-back.png`.
- **Honest progress/error states:** the async job-status contract (`processing` → `completed`/`failed` with a real `error` string) worked correctly every time; no hang, no silent failure, no fake success.
- **Output quality:** attempt 2's letter contains a real content-quality bug — see Finding MV-approval-modal-009 (grammatically broken hook sentence from a pronoun-rewrite regex bug).
- **3 consecutive `503`s** are treated as an environment/scale observation, not a screen defect — flagged as UNSURE-2 below since I could not isolate root cause and it plausibly reflects concurrent LLM load from the many parallel MV-* screen-testers active in this same swarm run.

## 6. UNSURE items (escalated, not filed as owned findings)

- **UNSURE-1 (shared auth-config 500):** The shared production `/var/log/aether/api.log` contains 4 occurrences of `GET /approvals?status=pending` → raw `500 Internal Server Error`, traceback `RuntimeError: JWT_SECRET / NEXTAUTH_SECRET is not configured` inside `apps/api/app/middleware/auth.py:get_current_user` → `apps/api/app/security.py:get_jwt_secret`. Client IP `101.188.17.71` — **not my session** (my Playwright sessions used a different IPv6 address visible in the same log; my direct curl calls used `208.122.8.11`). This is auth-middleware-wide (would affect every authenticated endpoint during that window), not approvals-router code, and I could not reproduce it in either of my two full sessions (identical calls always returned `200`). Screenshots/interpretations: (a) a transient env-var misconfiguration during a concurrent deploy/restart elsewhere in this swarm run — most likely, given the narrow, clustered occurrence and my inability to reproduce it; (b) a genuine intermittent JWT-secret-loading race in the app itself. I cannot distinguish (a) from (b) from the UI/log alone — escalating for the orchestrator to correlate against deploy timestamps rather than guessing. Not counted against CLM-024/CLM-062 above.
- **UNSURE-2 (LLM backend 503 rate):** 3 of 5 real cover-letter-generation attempts failed with `503: LLM backend unavailable` in a ~6-minute window (see §5). Two interpretations: (a) transient upstream/shared-capacity contention from the many concurrent MV-* screen-testers in this run all exercising LLM-backed agents simultaneously (most likely, given `api.log` shows the same `503` on `/agents/tailor/run` and `/agents/pipeline/run` from other client IPs in the same window); (b) a standing reliability issue with the cover-letter agent's LLM budget/retry handling. Not enough independent signal to adjudicate from this screen alone — flagged for the orchestrator/agents-screen tester to correlate.
- **Empty-state visual (`approvals-empty-state`):** could not be reproduced live — see NOT-TESTED below. Code path read (`apps/web/src/app/dashboard/approvals/page.tsx:163-172`) shows a "Queue clear" message + description, which is `[INFERRED]` only, not `[VERIFIED-WITH-FRESH-EVIDENCE]`.

## 7. Console / network / server-log summary

- **Console (browser):** 0 uncaught exceptions, 0 unexpected `console.error` across all 4 sessions. The only `console.error` entries present are `Failed to load resource: 409/404/422`, all from negative-path tests I deliberately triggered (idempotent double-approve, bogus deep-link, invalid status filter) — every one of these was a clean, well-formed JSON error response, never a raw stack trace. Zero `pageerror` events. Zero `dialog` events (confirms no `alert()` fired from the XSS-payload test).
- **Network:** every `/approvals*` call I made returned the documented status code for its scenario (200/201/403/404/409/422). No ignored errors, no optimistic-success-on-failure observed (all UI state changes were response-driven, confirmed via `page.waitForResponse` matched to the actual decide button clicks).
- **Server log (`/var/log/aether/api.log`, read-only, per `docs/delivery/DEPLOYMENT-RUNBOOK.md` §Logs):** zero `5xx` on any `/approvals*` line correlated to my own request markers (my execute/approve/reject calls and the `nonexistent-id-mv-verify2` 404 all appear exactly as expected, no server-side exception attached to them). See UNSURE-1 for a 500 found elsewhere in the same shared log, not attributable to my session.

## 8. Screenshot index

All paths relative to `uat/reports/evidence/manual-verification/screens/approval-modal/test-artifacts/`.

| # | File | What it shows |
|---|---|---|
| 1 | `01-unauth-access.png` | Unauthenticated `/dashboard/approvals` → redirected to `/login` |
| 2 | `02-approvals-page-load.png` | Full page load, Pending filter (also shows overflow bug + 2% confidence bug live) |
| 3-6 | `03..06-filter-*.png` | Pending/Approved/Rejected/All filter states |
| 7 | `11-xss-modal-open.png` | XSS/unicode/long-string payload rendered safely as literal text in the modal |
| 8 | `12-real-approval-card.png` | Real agent-generated approval's card |
| 9 | `13-real-approval-modal-open.png` | Real approval's sparse modal (Finding 001/002) |
| 10 | `14-real-approval-after-approve.png` | Immediately after approving |
| 11 | `15-real-approval-resolved-view.png` | Post-reload, Approved filter, view-only resolved modal ("already approved on...") |
| 12 | `16-rich-modal-open.png` | Fully-populated synthetic payload — wireframe-conformant rendering |
| 13 | `17-rich-modal-editing.png` | Edit & Approve textarea open |
| 14 | `18-rich-after-reject.png` | After rejecting the rich synthetic approval |
| 15 | `19-expired-card.png`, `20-expired-modal.png` | Real >48h-old approval — expired badge + disabled actions (CLM-077) |
| 16 | `21-back-forward-after-back.png` | Back button leaving the Approvals page entirely (Finding 005); also shows overflow bug on Dashboard |
| 17 | `22-deep-link-open.png` | Valid deep link opens modal directly |
| 18 | `23-deep-link-bogus-id.png` | Bogus deep link — no error shown (Finding 006) |
| 19 | `24-throttled-loading-state.png`, `25-throttled-loaded.png` | Throttled reload: skeleton then real content |
| 20 | `31-email-send-type-modal.png` | `email_send` type modal (Finding 007) |
| 21 | `32-offer-response-type-modal.png` | `offer_response` type modal |
| 22 | `v2-01..05-*.png` | Fresh-session (verify-twice) re-checks of unauth redirect, sparse-modal, overflow, back-nav, bogus deep-link |

Raw JSON evidence, transcripts, and the exact Playwright scripts used are also under `test-artifacts/` (see `test-artifacts/scripts/`).

## 9. NOT-TESTED (HUMAN-GATED / environment-constrained only)

- **True empty state** (`data-testid="approvals-empty-state"`): the shared production account always has approvals from concurrent testers in every status bucket (pending/approved/rejected) throughout my session window — reproducing a genuine zero-row state would require resolving or deleting other testers' pending data, which is explicitly prohibited by the shared-environment rules. Not reproducible without violating protocol; code path read only (`[INFERRED]`, not `[VERIFIED-WITH-FRESH-EVIDENCE]`).
- **A second real, linked-application reject-path generation** for full fresh-evidence coverage of CLM-073's reject→rejected Application sync: 4 consecutive `POST /agents/cover-letter/run` attempts on 4 different jobs all failed with `503: LLM backend unavailable` in the same window (see §5, §6 UNSURE-2) — an environment/capacity constraint, not a decision to skip. The approval-state half of the reject path (pending→rejected) WAS verified live and twice; only the Application-row sync half of reject specifically remains `[INFERRED]` from code.
- **Full 20-route / 14-route console-error sweeps** referenced by CLM-024/CLM-062: out of this screen-tester's scope by design (one screen per tester); only the approval-modal slice was exercised.
- **Root-cause correlation for UNSURE-1 and UNSURE-2**: requires cross-session/deploy-timeline correlation that is outside a single screen-tester's tool access — escalated to the orchestrator.

## 10. Epistemic labeling note

Every claim/finding above marked "CONFIRMED", "live", "verified twice", or citing a specific artifact path + this session's timestamps is **[VERIFIED-WITH-FRESH-EVIDENCE]** (this run only — no prior-phase report was treated as evidence). Anything described as following from reading source code without a corresponding live reproduction is explicitly marked **[INFERRED]** above. No item in this report is **[ASSUMED-PENDING-PROBE]** — everything assumed going in was either probed and confirmed/refuted, or moved to §6/§9.

## Sign-off

Tested by: screen-tester agent (role: screen-tester), model: Claude Sonnet 5 (`claude-sonnet-5`), MANUAL-VERIFICATION Stage 1, screen `approval-modal` (desktop viewport 1440×900), production `https://5cb5f0620.abacusai.cloud`. All 9 points of the §3.2 protocol executed; every finding reproduced in a fresh session before filing (§3.2.9); zero findings required FLAKY status (all reproduced identically on first and second attempt). Only own `MV-approval-modal-*`-scoped data was created/mutated; one pre-existing, non-mine approval was inspected read-only for CLM-077 and never actioned.
