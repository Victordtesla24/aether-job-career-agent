# TESTING-OUTCOME-REPORT — screen: `terms`

**Screen name:** Terms of Service (public static legal page)
**Route:** `/terms` → `https://5cb5f0620.abacusai.cloud/terms`
**Wireframe:** none — `SCREEN-MATRIX.json` flags `coverage_gap: "route-without-wireframe"`
**Backing endpoints:** none (matrix `endpoints: []`) — server-rendered static content, no client-side API calls
**Agents:** none (matrix `agents: []`)
**Tester:** screen-tester agent role, model Claude Sonnet 5 (`claude-sonnet-5`)
**Repository commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Production URL under test:** `https://5cb5f0620.abacusai.cloud`
**Session 1 (initial pass) window (UTC):** 2026-07-17T13:38:xx — 2026-07-17T13:45:54Z
**Session 2 (fresh-session re-verification) window (UTC):** 2026-07-17T13:41:50Z — 2026-07-17T13:42:01Z
**Tooling:** Playwright (Chromium) driven via ad-hoc Node scripts, plus `curl` for raw SSR/API cross-checks. All navigation against production only; no localhost used.

---

## 0. Tester's own expectation (formed before observing behavior)

Before reviewing the live page, my expectation for a "Terms & Conditions" screen on a paid, AUD/GST subscription SaaS product was: (a) full, specific, non-generic legal copy consistent with the actual product's real features and actual billing mechanics; (b) a "last updated" date that is plausible and recent; (c) discoverable from account creation and other public marketing surfaces (signup, pricing) since users need to be able to find and be presented with the terms that bind them; (d) internally consistent currency/jurisdiction; (e) a working path to actually contact the operator for anything the document says to "contact us" about (refunds, cancellation, tax invoices); (f) zero console errors / broken links; (g) accessible whether or not the user is logged in, since Terms & Conditions must not be gated behind auth.

---

## 1. Load & visual conformance

No wireframe exists for this screen (`design/screens/` has no terms wireframe; matrix confirms `wireframe_files: []`), so a design-source comparison was not possible — logged as `MV-terms-005` (LOW, coverage-gap, informational). Visual/content review was instead performed against the product-sense expectations above.

- Desktop (1440×900), unauthenticated: **200 OK**, full 18-section document rendered, dark theme consistent with rest of app, header logo + "Back to Dashboard" footer link present. Screenshot: `test-artifacts/01-unauth-desktop-full.png`.
- Mobile (390×844), unauthenticated: **200 OK**, single-column responsive layout, no horizontal overflow, all text legible. Screenshot: `test-artifacts/02-unauth-mobile-390x844-full.png`.
- Server-rendered: confirmed via raw `curl` (no JS) that full content — including headings and the placeholder brackets discussed below — is present in the initial HTML (`test-artifacts/raw-ssr.html`, `test-artifacts/headers.txt`). Edge-cached (`x-nextjs-cache: HIT`, `cache-control: s-maxage=31536000`).
- No lorem-ipsum text anywhere (`containsLorem: false` in both sessions).
- "Last updated: July 16, 2026" — plausible (one day before this test session, and matches the Phase-6 EXECUTION-REPORT's "legal-page honesty" fix dated 2026-07-16).
- Content genuinely reflects real product features (job discovery, resume tailoring, cover letters, email/Gmail OAuth, interview prep, application tracking, networking CRM, analytics) — all independently confirmed to exist as screens/features elsewhere in the app.
- **Pricing/quota figures in §5 and §7 cross-checked against the live `GET /api/billing/plans` endpoint and matched exactly**: Free $0/5 runs, Starter $19/mo·$179/yr/30 runs, Pro $39/mo·$359/yr/100 runs, Power $69/mo·$649/yr/300 runs, GST-inclusive AUD. Evidence: `test-artifacts/billing-plans-live.json`.
- **Billing-not-yet-live claim in §6 cross-checked live**: `POST /api/billing/checkout` against production with a valid auth token returned `400 {"detail":"This plan is not yet available for purchase (no Stripe price configured)"}` — an honest error, not a fake success, exactly matching the Terms' own description ("starting checkout... returns an honest error rather than pretending to process a payment"). Evidence: `test-artifacts/checkout-attempt-response.txt`.
- Deviations found: unfilled placeholder brackets (`MV-terms-002`), a non-functional promised contact channel (`MV-terms-003`), and a currency/jurisdiction inconsistency (`MV-terms-004`) — see Findings.

## 2. Every interactive element

Element inventory — this is a static content page with exactly **two** interactive elements (no forms, tabs, dropdowns, modals, or pagination exist; matrix confirms `endpoints: []`, `agents: []`):

| # | Element | Type | Tested | Result |
|---|---|---|---|---|
| 1 | Header logo ("Aether / Career Agent") | Link → `/dashboard` | Clicked, unauthenticated | Navigates `/terms` → `/dashboard` → client-side AuthGuard redirect → `/login`. Clean, no dead-end, no console error. Traced with frame-navigation timestamps; reproduced in session 2. |
| 2 | Footer "← Back to Dashboard" | Link → `/dashboard` | Clicked, unauthenticated | Same clean `/terms` → `/dashboard` → `/login` redirect chain, confirmed via `framenavigated` event trace (`test-artifacts/session1-backlink-trace.json`) showing the full navigation sequence with no visible flash of unauthenticated dashboard content. |

Both links were also confirmed reachable when authenticated (logged in as admin/admin123): clicking navigates straight to `/dashboard` with no redirect, as expected.

No other clickable elements exist on the page (no in-page anchor/TOC navigation was built, consistent with no wireframe promising one).

## 3. Every form

**N/A — no forms exist on this screen.** The page is pure static legal content with two navigation links (see §2). Confirmed via full source read of `apps/web/src/app/terms/page.tsx` and DOM enumeration in the browser (no `<input>`, `<textarea>`, `<select>`, or `<form>` elements present). Item 3 of the §3.2 protocol is not applicable to this screen.

## 4. UI↔backend wiring

**N/A — no backend endpoints are wired to this screen** (matrix `endpoints: []`). The page is fully server-rendered static content with zero client-side fetch calls; confirmed via network capture during page load (zero non-2xx responses, zero failed requests, `test-artifacts/session1-results.json` step A `networkStatusesNon2xx: []`, `failedRequests: []`). The only "wiring" tested was the two navigation links (§2), which behave correctly.

Note: while `/terms` itself has no endpoints, several of its *claims* reference other endpoints (billing plans, checkout). Those were cross-checked live for claim-verification purposes (§8 below) even though they are not endpoints of this screen per the matrix.

## 5. AI-agent integration

**N/A — no agents are wired to this screen** (matrix `agents: []`). Nothing to run.

## 6. Error & edge states

- **Unauthenticated access:** `/terms` returns **200** and full content with no login wall — this is the *correct, intentional* behavior (confirmed by the source comment: "Standalone public terms & conditions page. It is intentionally NOT wrapped in the dashboard layout so it is reachable without authentication"). A public legal document should never require login. PASS.
- **Authenticated access:** Logged in as admin/admin123, `/terms` returns 200 with identical content, no auth-state-dependent rendering differences. PASS. Screenshots: `test-artifacts/05-authenticated-terms.png`, `test-artifacts/10-s2-authenticated-terms.png`.
- **Throttled reload:** Simulated ~500kbps/400ms-latency network via CDP `Network.emulateNetworkConditions`; page still loaded fully in 7.4s with no error state, no partial/broken render, no hang. `test-artifacts/throttle-result.json`, `test-artifacts/11-throttled-reload.png`.
- **Back/forward:** Verified `/terms` → click "Back to Dashboard" (unauth) → `/dashboard` → auto-redirect `/login` → browser back → forward, all transitions clean with no console errors, no stuck/blank states. `test-artifacts/session1-results.json` step D, `test-artifacts/03-after-clicking-back-to-dashboard.png`, `04-after-browser-back.png`.
- **Forced backend error:** not applicable — no backend calls originate from this screen to force-fail.

## 7. Console/log hygiene

- **Zero console errors, zero console warnings, zero page errors** across all passes: unauthenticated desktop, unauthenticated mobile, authenticated desktop, both session 1 and session 2 (`consoleMsgs: []` in every captured step across `session1-results.json` and `session2-results.json`).
- **Zero failed network requests** during page load (fonts, Font Awesome CDN, and the document itself all resolved 2xx).
- **Zero non-2xx responses** observed in the network trace.
- Server-side: this screen makes no API calls, so there is no server endpoint traffic to check for 5xx from this screen specifically. The page's own HTTP response was 200 in every one of ~8 direct loads performed across both sessions plus the raw curl check.

## 8. Claim verification

| Claim ID | Claim | Verdict | Evidence |
|---|---|---|---|
| CLM-098 | "Privacy policy and terms pages contain honest, accurate legal copy as part of a 'legal-page honesty' fix — not placeholder/lorem-ipsum content" | **PARTIALLY-TRUE** (for the `terms` portion of this claim; `privacy-policy` is a separate screen/tester's scope) | The document is substantively genuine, not lorem-ipsum, and its factual claims (feature list, pricing, GST math, quota numbers, "checkout returns an honest error") were independently verified live against `GET /api/billing/plans` and `POST /api/billing/checkout` and matched exactly — this part of the claim holds (`test-artifacts/billing-plans-live.json`, `checkout-attempt-response.txt`). However, the page is **not free of placeholder content**: §5 and §9 contain live, unfilled bracketed placeholders (`[Operator ABN]`, `[Business Name]`, and a full bracketed refund-policy placeholder sentence) reachable by real users — see `MV-terms-002`. Additionally, §18/§5/§9 promise a contact mechanism ("Settings page or in-app support channel") that does not exist anywhere in the product — see `MV-terms-003`, which is itself a form of inaccuracy in the legal copy. Net: mostly honest and accurate, but demonstrably contains placeholder text and one materially inaccurate/unactionable claim. |

## 9. UNSURE items

None requiring escalation as pure UNSURE — the currency/jurisdiction inconsistency (USD liability cap + Delaware governing law vs. an otherwise entirely AUD/GST/ABN-Australian commercial framework) was filed as a concrete finding (`MV-terms-004`) rather than an UNSURE item, because the *inconsistency itself* is objectively verifiable from the text regardless of what the operator's true legal domicile turns out to be. I could not determine from the UI alone whether Delaware/USD is a real, intentional choice by a US-incorporated operator (in which case the clause is *correct but confusing*) or a leftover from an unlocalized template (in which case it's a defect) — that adjudication requires operator input, which is why it's filed as a MEDIUM finding with both interpretations left open for the orchestrator/operator rather than closed by guessing.

## 10. Screenshots index

| # | File | Description |
|---|---|---|
| 1 | `test-artifacts/01-unauth-desktop-full.png` | Unauthenticated, desktop 1440×900, full page |
| 2 | `test-artifacts/02-unauth-mobile-390x844-full.png` | Unauthenticated, mobile 390×844, full page |
| 3 | `test-artifacts/03-after-clicking-back-to-dashboard.png` | State immediately after clicking "Back to Dashboard" (unauth) |
| 4 | `test-artifacts/04-after-browser-back.png` | State after browser back button |
| 5 | `test-artifacts/05-authenticated-terms.png` | Authenticated (admin/admin123), desktop |
| 6 | `test-artifacts/06-after-back-to-dashboard-click-settled.png` | Settled state after back-link navigation trace |
| 7 | `test-artifacts/07-s2-unauth-desktop-full.png` | Session-2 fresh re-verification, unauth desktop |
| 8 | `test-artifacts/08-s2-after-logo-click.png` | Session-2, after header-logo click (unauth) |
| 9 | `test-artifacts/09-s2-mobile-full.png` | Session-2, mobile re-verification |
| 10 | `test-artifacts/10-s2-authenticated-terms.png` | Session-2, authenticated re-verification |
| 11 | `test-artifacts/11-throttled-reload.png` | Throttled-network reload (~500kbps/400ms latency) |
| 12 | `test-artifacts/12-settings-page-full.png` | Settings page (evidence for MV-terms-003 — no support/contact affordance) |

## 11. Console/network/server-log summaries

- **Console:** 0 errors, 0 warnings, 0 page errors across 8 page loads (2 sessions × unauth-desktop, unauth-mobile, authenticated, plus link-click traces). Raw dumps: `test-artifacts/session1-results.json`, `test-artifacts/session2-results.json`.
- **Network:** 0 failed requests, 0 non-2xx responses on `/terms` itself in any load. Raw dumps as above.
- **Server logs:** this screen has no backing endpoints (matrix `endpoints: []`); the only server-side traffic is the page request itself (consistently 200, edge-cached) and the out-of-scope billing endpoints hit solely for claim cross-verification (`GET /api/billing/plans` → 200, `POST /api/billing/checkout` → 400 with a structured, honest error body — not a 5xx, not a stack trace).

## 12. NOT-TESTED list (HUMAN-GATED reasons only)

None. Every applicable protocol item for this screen was executed twice against production. Items 3, 4, and 5 of §3.2 (forms, backend wiring, AI agents) are not HUMAN-GATED omissions — they are genuinely not applicable to this screen (it has no forms, no backend endpoints, and no agents per the matrix and per direct source/DOM inspection), and this is documented in §3, §4, §5 above rather than silently skipped.

## 13. Findings summary

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-terms-001 | HIGH | defect | No public page links to `/terms`; unreachable from signup/login/pricing nav |
| MV-terms-002 | MEDIUM | claim-refuted | Live unfilled placeholder brackets in §5/§9 (`[Operator ABN]`, `[Business Name]`, refund-policy placeholder) |
| MV-terms-003 | HIGH | claim-refuted | Terms promise a "Settings page or in-app support channel" contact path that does not exist anywhere in the product |
| MV-terms-004 | MEDIUM | defect | USD liability cap + Delaware governing law inconsistent with the otherwise entirely AUD/GST/ABN-Australian document |
| MV-terms-005 | LOW | coverage-gap | No wireframe exists for this screen; visual-conformance check performed against product-sense expectations only |

Full findings with reproduction steps and evidence: `findings.json`.

## 14. Sign-off

All applicable §3.2 protocol items executed and independently reproduced in two fresh browser sessions (VERIFY TWICE satisfied — no FLAKY items). Zero code changes made. Zero destructive/account-level actions taken (read-only testing throughout; login used only the canonical admin/admin123 credential per protocol). All artifacts filed under `uat/reports/evidence/manual-verification/screens/terms/test-artifacts/`.

— screen-tester agent (role: screen-tester, model: claude-sonnet-5), session end 2026-07-17T13:45:54Z UTC.
