# TESTING OUTCOME REPORT — /dashboard/offers (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 4)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:36–18:39Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright/Node, headless Chromium, 1440x1200.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-cold-load.png + results.json)

- Header "Offer Comparison", `add-offer` button.
- This account had **0 offers** on load → `offers-empty-state` rendered (real empty state, not the wireframe's 3-card fixture Canva/Atlassian/ANZ $248k/$235k/$212k).
- `add-offer-modal` (`AddOfferModal.tsx`): Company/Role/Base/Bonus/Equity/Location/Currency fields, live running total, inline field-level errors.
- **Priority Weights panel is COMPLETELY ABSENT from production** — confirmed by DOM text scan (`weightsPanelTextPresent: false`) and by source: `apps/api/app/services/offers.py:91-94` — code comment states *"the UI no longer renders a weights panel (MV-offer-comparison-004: Aether has no signal for growth/culture/stability, so fabricating a 'weighted score' is not an option)"*. The backend still returns a static `weights` array (30/25/20/15/10, summing to 100) for API backward-compatibility only — grepped the entire frontend (`OfferCard.tsx`, `NegotiationCoach.tsx`, `page.tsx`) for any use of `data.weights`: **zero references**. It is fetched and immediately discarded.
- Negotiation Coach (`negotiation-coach`): insight text, suggested-counter, leverage list, "Draft counter email" toggle — present once ≥1 offer exists.

## Targeted verifications

1. **Is there offer entry/comparison? Does the weighting UI work?** Offer entry works (see below). **The weighting UI does not exist to "work" or "not work" — it was deliberately removed**, per the code comment above, specifically to avoid fabricating a weighted score Aether has no real signal for. This is an honest, documented product decision, not a defect — directly explains why `test_offers.py::test_offers_weights_sum_to_100` is a pure backend-contract test (the static 30+25+20+15+10=100 default) with **no UI counterpart to test**; its baseline ERROR is unrelated to this (same register/login test-DB flakiness signature seen on the other 3 screens in this batch — `Could not validate credentials` at the shared `conftest.py` fixture-user step). [VERIFIED-WITH-FRESH-EVIDENCE 01-cold-load.png, results.json→weightsPanelTextPresent, offers.py:91-94]
2. **No AI agent on this screen.** Grepped `NegotiationCoach.tsx`: "Draft counter email" is a pure client-side string template (`${counter.toLocaleString()}` interpolated into a fixed boilerplate) with **zero network calls** — confirmed live: `networkCallsDuringDraftClick: 0` when clicked. There is no `runAgent`/LLM call anywhere on this screen. Nothing to "actually run" here beyond the CRUD endpoints. [VERIFIED-WITH-FRESH-EVIDENCE 07-negotiation-counter-draft.png, results.json]

## Interaction / forms / persistence

- **Empty submit**: clicked `add-offer-submit` with all fields blank → inline "is required" errors shown for Company/Base/Location, `noValidate` form did not fire an unhandled native-validation bypass; **no `POST /workspaces/offers` fired**. [03-empty-submit-errors.png]
- **Adversarial submit**: company = 80×'A' + `<script>alert(1)</script>`, location = 10×unicode 𝕏 + "Remote", base = `-50000`. Result: "Keep the company name under 60 characters." fired correctly (`adversarialCompanyLenError: true`). Base did **not** show "must be greater than 0" — `parseMoney()` treats any negative input as *unparseable* (`n < 0 → return null`), so the shown error was "Enter a base salary (numbers only)." instead — a different, still-correct rejection message; submission was blocked either way (`adversarialSubmitBlocked: true`, 0 offers created from this attempt). [VERIFIED-WITH-FRESH-EVIDENCE 04-adversarial-errors.png, results.json]
- **Valid submit**: company "GOLD-MASTER-V4 TEST OFFER (safe to delete)", base $150,000, bonus $10,000, location "Remote - Test" → network: `POST /api/workspaces/offers` → **201**, followed by `GET` → 200 refresh. Card count 0→1, modal closed. [05,06-*.png, results.json→createOfferResponses]
- Negotiation Coach activated once a real offer existed: suggested counter **$165,000** (computed server-side, not fabricated — matches the code's documented behavior).
- Reload-and-re-read: card count stayed 1 after reload — real persistence, not client-only state. [08-after-reload.png]
- **Cleanup**: deleted the test offer via `offer-delete` → `DELETE /api/workspaces/offers/{id}` → **204**. Reload confirms count 0 and empty-state returned; independent fresh session (session 2) also shows 0 offers / empty-state. [09,10,12-*.png, results.json→deleteOfferResponses]

## Error / edge states

- Unauthenticated access → redirected to `/login?next=%2Fdashboard%2Foffers`. [11-unauthenticated-access.png]
- Verified twice: fresh session reproduced the (now-cleaned) empty state exactly.
- console.json / pageerrors.json: empty. requestfailed.json: 4 entries, all benign `net::ERR_ABORTED` on other-route prefetch chunks.
- Idle 60s window: `GET /api/agents` (t=28.5s) + `GET /api/approvals?status=pending` (t=58.4s) + `GET /api/agents` (t=58.5s) — same global-sidebar 30s-only pattern as the other 3 screens in this batch; **no screen-specific idle poll**.

## Findings

No BLOCKER/HIGH/MEDIUM findings. The screen is a small, honest, fully-functional CRUD surface with one deliberate, documented feature removal (weights UI) rather than a defect.

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-OFFERS-001 | /dashboard/offers | INFO | wireframe-drift (by-design) | Priority Weights panel from the wireframe intentionally removed | Compare `offer-comparison.html` to production `page.tsx` | `weights-of11` 5-slider panel | Not present; backend `weights` field fetched but never rendered (documented decision, offers.py:91-94) | 01-cold-load.png, results.json | OPEN (by-design, not a runtime defect) |
| ML-OFFERS-002 | /dashboard/offers | INFO | UX-nuance | Negative base salary shows a generic "numbers only" error instead of a "must be > 0" error | Fill Base with `-50000`, submit | A message specifically about the sign | `parseMoney()` nulls out any negative input before the `<= 0` check ever runs, so the "numbers only" message fires instead | 04-adversarial-errors.png, results.json | OPEN (cosmetic, submission still correctly blocked) |

## Not-tested (HUMAN-GATED)

None — this is a small, fully read/write-testable screen with no send/billing/real-third-party risk; every control was exercised.

## Data left behind

None. The one test offer created ("GOLD-MASTER-V4 TEST OFFER") was deleted in the same session (`DELETE` → 204) and confirmed absent on reload and in an independent fresh session.

## Sign-off

Screen tested per §3.2 protocol: cold-load screenshot (real empty state, no wireframe fixture), wireframe conformance (weights-panel absence explained and confirmed intentional), full CRUD exercised (create/delete) with network capture, empty/adversarial(script+unicode+long-string+negative-number) form submissions, negotiation-coach confirmed template-only (zero network calls, not a fabricated AI claim), idle-poll measured (30s global-sidebar only), reload + cleanup-reload persistence, unauthenticated redirect, verified twice in a fresh session. Verdict: **fully honest, functional, no fixture/placeholder content, no BLOCKER/HIGH findings; only a documented-intentional wireframe-drift and a cosmetic error-message nuance.**
