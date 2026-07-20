# TESTING-OUTCOME-REPORT — Pricing Screen

- **Screen id:** `pricing`
- **Screen name:** Pricing
- **Route:** `/pricing`
- **Wireframe ref:** none — `screens/SCREEN-MATRIX.json` marks this screen `coverage_gap: "route-without-wireframe"`. Expectations were formed from product sense (a REVENUE-CRITICAL SaaS pricing page: tiers, GST-inclusive AUD pricing, interval toggle, honest CTAs, honest checkout failure) and cross-checked against the page's own source (`apps/web/src/app/pricing/page.tsx`) and backing router (`apps/api/app/routers/billing.py`).
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Repo / commit context:** `/home/ubuntu/github_repos/aether-job-career-agent` (canonical-login.md pinned commit `53f0e084da5b460835c32d3e07d496e6e67a8616`; no local commits made — read-only testing)
- **Session window (UTC):** 2026-07-17T13:38:06Z → 2026-07-17T13:50:43Z (code/context review preceded this, ~13:28Z onward)
- **Tester:** screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1

---

## 1. Element inventory

| # | Element | Selector | Tested | Result |
|---|---|---|---|---|
| 1 | Monthly interval toggle | `data-testid=interval-month` | Yes | Switches all 4 cards to monthly pricing; `aria-pressed` correct |
| 2 | Annual interval toggle | `data-testid=interval-year` | Yes | Switches all 4 cards to annual pricing + "/ year" label; GST recomputed correctly |
| 3 | GST info tooltip (×4, one per plan) | `[data-testid=gst-<plan>] [data-testid=metric-tooltip-trigger]` | Yes (Starter sampled; same component instance for all 4) | Hover/focus reveals accessible popover with exact net+GST breakdown, matches formula |
| 4 | Free "Get started free" CTA | `data-testid=subscribe-free` | Yes | Signed-out → `/signup`; Signed-in (Free acct) → `/signup` (no session awareness — MV-pricing-005) |
| 5 | Starter "Subscribe to Starter" CTA | `data-testid=subscribe-starter` | Yes | Signed-out → `/login` (client-side guard, no network call); Signed-in → `POST /billing/checkout`, honest failure (400/429) surfaced |
| 6 | Pro "Subscribe to Pro" CTA | `data-testid=subscribe-pro` | Yes | Same pattern as Starter |
| 7 | Power "Subscribe to Power" CTA | `data-testid=subscribe-power` | Yes | Same pattern as Starter, tested monthly and annual |
| 8 | "Sign in" footer link | `a:has-text("Sign in")` | Yes | → `/login`, works both signed-in/out |
| 9 | Loading state | `data-testid=pricing-loading` | Yes (via throttled reload) | Honest "Loading plans…" shown, no flash of empty/broken UI |
| 10 | Error state (`pricing-error`) | `data-testid=pricing-error` | Not triggered | `GET /billing/plans` never failed during testing — no way to force a client-visible load error without server-side fault injection (out of scope: no service restarts permitted) |
| 11 | Checkout error banner | `data-testid=checkout-error` | Yes | Renders on 400/429 checkout failures; generic message only (MV-pricing-004) |
| 12 | Brand mark ("A" logo + "Aether" text) | header, no `<a>`/`<Link>` | Yes | Confirmed non-interactive by design (plain `<div>`/`<span>`), not a dead link |

All 12 discovered interactive/stateful elements were exercised. No hidden/undiscovered controls found on inspection of the full page source.

---

## 2. Visual conformance (§3.2 step 1)

No wireframe exists for this screen (coverage gap, noted above). Judged against product-sense expectations for a SaaS pricing page:

- Loads with real, non-placeholder content: 4 named tiers (Free/Starter/Pro/Power), real AUD prices, real GST breakdown, real feature bullets — **no lorem-ipsum, no `TODO`, no `$X.XX` placeholders**. PASS.
- Monthly/Annual toggle present and functional. PASS.
- GST-inclusive AUD framing stated in the subhead and per-card. PASS.
- Responsive: full desktop (1440×900) and mobile (390×844) both render cleanly, cards stack vertically on mobile with no overflow/clipping. PASS.
- Footer "Already have an account? Sign in" present. PASS.

Screenshots: `test-artifacts/01-unauth-load-full.png` (desktop, unauth), `test-artifacts/09-auth-pricing-load.png` (desktop, authenticated — **pixel-identical to unauth**, see MV-pricing-003), `test-artifacts/14-mobile-390x844.png` (390×844 mobile).

---

## 3. GST / pricing adjudication (independent computation)

Formula under test (per code + CLM-094): `gst = round(total / 11, 2)`, `net = total - gst`.

Source of truth for displayed values: `GET /billing/plans` raw response, captured in `test-artifacts/network-events-step1.json`, cross-checked against on-screen text in `test-artifacts/01-monthly-tier-text.json` / `02-annual-tier-text.json`.

| Plan | Interval | Total (AUD) | Displayed GST | `round(total/11,2)` | Displayed Net | `total - gst` | Match |
|---|---|---|---|---|---|---|---|
| Free | month | $0 | — (No card required) | 0.00 | — | 0.00 | N/A, correct (no GST line for $0) |
| Starter | month | $19 | $1.73 | 19/11=1.7272…→**1.73** | $17.27 | 19−1.73=**17.27** | MATCH |
| Starter | year | $179 | $16.27 | 179/11=16.2727…→**16.27** | $162.73 | 179−16.27=**162.73** | MATCH |
| Pro | month | $39 | $3.55 | 39/11=3.5454…→**3.55** | $35.45 | 39−3.55=**35.45** | MATCH |
| Pro | year | $359 | $32.64 | 359/11=32.6363…→**32.64** | $326.36 | 359−32.64=**326.36** | MATCH |
| Power | month | $69 | $6.27 | 69/11=6.2727…→**6.27** | $62.73 | 69−6.27=**62.73** | MATCH |
| Power | year | $649 | $59.00 | 649/11=**59.0000** (exact) | $590.00 | 649−59=**590.00** | MATCH |

**All 6 non-zero GST figures independently recomputed and matched exactly, both on-screen and in the raw API response.** Tooltip popover text (`test-artifacts/04b-gst-tooltip-hover.png`) also states the identical net/GST split and cites the formula verbatim ("computed as round(total ÷ 11, 2)") — consistent, no discrepancy anywhere in the presentation chain (API → React render → tooltip copy).

Annual "save more" claim verified: Starter 19×12=228 vs 179 (saves $49, ~21%); Pro 39×12=468 vs 359 (saves $109, ~23%); Power 69×12=828 vs 649 (saves $179, ~22%) — genuine discount in all three cases, label is accurate.

**Tier names/prices vs CLM-094 ("Free A$0 / Starter A$19 / Pro A$39 / Power A$69 monthly; A$179/359/649 annual"): exact match.**

---

## 4. UI↔backend wiring (§3.2 step 4)

- Page load fires `GET /billing/plans` (public, no auth header) — 200, drives all 4 cards. Confirmed via `network-events-step1.json`, `step2.json`, `step3.json`.
- Interval toggle is pure client-side state (no network call) — re-renders from the already-fetched `plans` array's `.monthly`/`.annual` sub-objects. Correct: no redundant refetch.
- Unauthenticated "Subscribe to X" click: **no network call is made at all** — `getToken()` in `apps/web/src/lib/api/client.ts` detects the missing `localStorage` token client-side and calls `window.location.replace("/login")` before any fetch. Confirmed via `network-events-step2.json` (only `/billing/plans` calls present, zero `/billing/checkout` attempts despite 3 CTA clicks while signed out). This is correct, honest behavior — not a defect.
- Authenticated "Subscribe to X" click: fires `POST /billing/checkout {planId, interval}` with bearer auth. Response drives the UI: on failure, `checkoutError` state renders the banner; on hypothetical success, `window.location.href = result.checkoutUrl` (not reachable in this environment — see §6 human gate).
- `GET /billing/entitlement` / `GET /billing/subscription` were exercised directly (curl) to establish ground truth for the authenticated admin account — **not** called by the `/pricing` page itself (see MV-pricing-003: no subscription-state UI on this screen).

**Console/network hygiene:** zero uncaught JS exceptions (`pageerror`) across all 7 recorded sessions (`page-errors-step1/2/3.json` — all empty arrays). Two `console.error`-level entries were recorded in step 3 (`console-events-step3.json`), both of the form `"Failed to load resource: the server responded with a status of 429"` — these are the browser's own network-status logging for the checkout rate-limit hits I deliberately triggered (see §6), **not unsurfaced failures**: the corresponding checkout-error banner rendered in the UI in the same interaction (`test-artifacts/11-auth-starter-checkout-error.png`). Zero same-origin 5xx observed on any endpoint this screen calls (`/billing/plans`, `/billing/checkout`, `/billing/entitlement`, `/billing/subscription`, `/billing/portal`) — confirmed both from live capture and a targeted `grep` of `/var/log/aether/api.log` for these paths (zero `" 500 "` / `" 503 "` lines among 236 billing-endpoint log lines).

---

## 5. Agent integration

`/pricing` itself wires no AI agents (matrix `agents: []`). However, its content and CTAs make direct promises about agent capability (tailoring, ATS scoring, cover letters, email agent), so those promises were spot-checked against the real paywalled agent endpoints — see MV-pricing-001. No agent was actually run to completion (all attempts correctly 402'd before reaching any LLM call, which is itself the expected/honest behavior under the active paywall — no fixture/fabricated output was ever at risk of being returned).

---

## 6. Error / edge states, human-gate boundary

- **Unauthenticated access:** `/pricing` is correctly public — loads fully, 200, real content, no redirect (`test-artifacts/01-unauth-load-full.png`). Confirms CLM-097.
- **Checkout — human gate boundary:** `POST /billing/checkout` is exactly where the human gate begins. For every purchasable plan (Starter, Pro, Power; monthly and annual) the endpoint returns an **honest** failure — never a fabricated Stripe URL:
  - First 5 attempts/hour/user → HTTP 400 `{"detail":"This plan is not yet available for purchase (no Stripe price configured)"}` (price-ID resolution fails before ever reaching the Stripe-configured check — `apps/api/app/routers/billing.py:139-144`).
  - After 5 attempts/hour/user → HTTP 429 `{"detail":"Too many checkout attempts, retry later"}` (rate limiter, confirmed working correctly).
  - This is **consistent with CLM-068** ("Stripe billing round-trip is BLOCKED-ON-HUMAN pending operator-supplied Stripe Price IDs/keys") — reproduced live, degrades honestly, no payment UI was ever reached, **no payment data was entered or requested at any point** (§9 compliance).
  - Full request/response evidence: `test-artifacts/curl-evidence-billing-endpoints.md`.
  - Screenshots of the exact UI moment the human gate is hit: `test-artifacts/11-auth-starter-checkout-error.png`, `12-auth-pro-checkout-error.png`, `21-auth-power-checkout-result.png`, `22-auth-power-annual-checkout-result.png`.
- **Throttled reload (slow 3G emulation, 150kbps/800ms latency):** honest "Loading plans…" text shown mid-load (`16-throttled-loading-state.png`), page settles correctly once the response arrives (`17-throttled-settled-state.png`); a separate 500kbps run completed in 7.5s with no error. No broken/partial render observed at any point.
- **Back/forward:** `/pricing` → toggle Annual → `/login` → back → returns to `/pricing` correctly (`18-back-navigation-result.png`), though the Annual selection is **not preserved** (resets to Monthly — client-only React state, not URL-encoded; minor, not filed as a formal finding since this is standard SPA behavior and not misleading). Forward → returns to `/login` correctly (`19-forward-navigation-result.png`). Zero console errors during this sequence (`console-events-backforward.json` — empty).
- **Boundary/invalid checkout payloads:** invalid `interval` value, missing `planId`, unknown `planId`, and the Free plan's `planId` were all POSTed directly — every case returned a clean 4xx with a structured, non-leaking error body (no stack trace, no raw SQL/Python exception surfaced). An XSS-probe `planId` (`<script>alert(1)</script>`) was attempted but landed on the already-exhausted rate limiter (429) before validation could run; the prior "unknown plan" test (plain bogus string) confirms the endpoint returns a generic `"Unknown or inactive plan"` message rather than echoing the input, so reflected-XSS risk on this field is not present by construction. Evidence: `curl-evidence-billing-endpoints.md`.

---

## 7. Findings summary

| id | severity | category | summary |
|---|---|---|---|
| MV-pricing-001 | BLOCKER | defect | Free-tier card advertises agent features that are 100% blocked by the production paywall for every Free account |
| MV-pricing-002 | HIGH | defect | Per-plan "model tier" / "Full model access" marketing has no backing model-routing implementation |
| MV-pricing-003 | HIGH | coverage-gap | No subscription-management / downgrade / Stripe-portal UI exists anywhere in the product |
| MV-pricing-004 | MEDIUM | wiring | Checkout 429/400 failures collapse into one generic message; Retry-After ignored |
| MV-pricing-005 | LOW | coverage-gap | "Get started free" CTA is not session-aware for already-authenticated users |

Full finding rows (schema per §4.1): `findings.json`.

---

## 8. Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-024** — 27 Phase-7 gates VERIFIED-CLOSED (0 console errors/20 routes, 0 same-origin 5xx, pytest/vitest counts, E2E green) | **PARTIALLY-TRUE** | My scope covers only `/pricing`, not the other 19 routes or the test-suite counts. On the `/pricing` slice specifically: 0 uncaught console errors, 0 same-origin 5xx observed across 7 sessions (`page-errors-step1/2/3.json` all empty; the only `console.error` entries are the browser's own 429-status logging for my deliberate rate-limit probe, not unsurfaced app failures). Cannot independently verify the pytest-676/vitest-297 counts or the remaining 19 routes from this single-screen scope — **UNVERIFIABLE-FROM-UI** for those portions. |
| **CLM-049** — All users backfilled to Free plan with a quota row (GATE-34) | **CONFIRMED** | `GET /billing/subscription` for admin/admin123 returned a real quota row: `{"runsAllowed":5,"runsUsed":3,"spendCapUsd":1.0,...}` on plan `free`, status `active`. Verified twice (two independent login sessions, `curl-evidence-billing-endpoints.md`). Scoped to the one account tested — "all users" not independently enumerable from the UI. |
| **CLM-053** — Subscription paywall ACTIVE; unpaid agent run → 402 subscription_required | **CONFIRMED** | Reproduced twice in fresh sessions: `POST /agents/tailor/run`, `/agents/scout/run`, `/agents/cover-letter/run` all returned HTTP 402 `{"error":"subscription_required","upgradeUrl":"/pricing",...}` for the Free-plan admin account. See MV-pricing-001 and `curl-evidence-billing-endpoints.md`. |
| **CLM-062** — Playwright sweep of 14 dashboard routes + /pricing + /admin **as a paid admin**: 0 console/failed-request/page errors (GATE-03) | **PARTIALLY-TRUE** | On `/pricing` alone: 0 console errors / 0 unsurfaced failed requests / 0 page errors, consistent with the claim. **However**, the claim's stated precondition — testing "as a paid admin" — does not hold in current production: `GET /billing/entitlement` for admin/admin123 returns `active_paid:false`, plan `free`. Either the account's paid status has since reverted, or the original claim's precondition was inaccurate/stale. I cannot verify the other 14+1 routes from this single-screen scope. |
| **CLM-068** — Stripe round-trip BLOCKED-ON-HUMAN pending Stripe keys/Price IDs/webhook secret/ABN-Tax | **CONFIRMED** | `POST /billing/checkout` for Starter and Pro (monthly) both returned honest HTTP 400 "no Stripe price configured"; no fabricated checkout URL was ever produced. Human-gate boundary precisely located at this endpoint — see §6. |
| **CLM-094** — 4 tiers, Free $0/Starter $19/Pro $39/Power $69 monthly, $179/359/649 annual, GST-inclusive with `gst=round(total/11,2)` | **CONFIRMED** | Exact match on every tier name, every price, and all 6 non-zero GST figures — independently recomputed in §3 and cross-checked against the raw API response and the on-page tooltip copy. (Note: the underlying *feature-list* accuracy for these tiers is separately challenged by MV-pricing-001/002 — the pricing/GST numbers themselves are fully correct.) |
| **CLM-097** — `/pricing` exists and is publicly viewable (unauthenticated) | **CONFIRMED** | Unauthenticated load returns 200 with full real content, no redirect (`test-artifacts/01-unauth-load-full.png`). |

---

## 9. UNSURE items

None requiring escalation. One item is explicitly labeled at a lower epistemic tier rather than filed as UNSURE: the Power-plan monthly checkout's specific HTTP 400 body was not independently re-observed (it hit the already-exhausted 429 rate limit instead — see §6); its expected 400 "no Stripe price configured" response is **[INFERRED]** from the identical code path confirmed live for Starter and Pro, not **[VERIFIED-WITH-FRESH-EVIDENCE]** for Power specifically. This does not change any finding or claim verdict — CLM-068 is already independently confirmed via Starter/Pro.

---

## 10. Screenshot index

| # | File | Description |
|---|---|---|
| 1 | `01-unauth-load-full.png` | Desktop, unauthenticated, full page load, monthly |
| 2 | `02-annual-toggle-full.png` | Desktop, unauthenticated, after Annual toggle click |
| 3 | `03-back-to-monthly-full.png` | Desktop, toggle back to Monthly (reversibility check) |
| 4 | `04-gst-tooltip-hover.png` | Initial (unsuccessful) tooltip hover attempt on wrong element |
| 5 | `04b-gst-tooltip-hover.png` | Correct GST tooltip popover, hovering the info-icon trigger — shows exact net/GST breakdown |
| 6 | `05-before-signin-click.png` | Pre-click state before Sign-in link test |
| 7 | `06-unauth-free-cta-result.png` | Unauth "Get started free" → `/signup` |
| 8 | `07-unauth-starter-cta-result.png` | Unauth "Subscribe to Starter" → `/login` |
| 9 | `08-unauth-signin-link-result.png` | Unauth "Sign in" link → `/login` |
| 10 | `09-auth-pricing-load.png` | Authenticated (Free admin) page load — pixel-identical to unauth (MV-pricing-003) |
| 11 | `10-auth-starter-submitting.png` | Transient "Starting checkout…" button state |
| 12 | `11-auth-starter-checkout-error.png` | Checkout error banner after Starter subscribe (human-gate boundary) |
| 13 | `12-auth-pro-checkout-error.png` | Checkout error banner after Pro subscribe |
| 14 | `13-auth-free-cta-result.png` | Authenticated "Get started free" → full `/signup` form (MV-pricing-005) |
| 15 | `14-mobile-390x844.png` | Mobile responsive capture, 390×844, full page |
| 16 | `15-throttled-load-result.png` | Result after 500kbps throttled load (7.5s, succeeded) |
| 17 | `16-throttled-loading-state.png` | Honest "Loading plans…" state under heavy throttle |
| 18 | `17-throttled-settled-state.png` | Settled state after heavy throttle resolves |
| 19 | `18-back-navigation-result.png` | Browser back → returns to `/pricing` correctly |
| 20 | `19-forward-navigation-result.png` | Browser forward → returns to `/login` correctly |
| 21 | `20-dashboard-paywall-evidence-fresh-session2.png` | Fresh session #2: Free admin hitting the full-dashboard paywall (corroborates MV-pricing-001/003) |
| 22 | `21-auth-power-checkout-result.png` | Power monthly checkout → rate-limited (429) generic error |
| 23 | `22-auth-power-annual-checkout-result.png` | Power annual checkout → rate-limited (429) generic error |

Supporting JSON/MD: `01-monthly-tier-text.json`, `02-annual-tier-text.json`, `console-events-step{1,2,3}.json`, `network-events-step{1,2,3}.json`, `page-errors-step{1,2,3}.json`, `console-events-backforward.json`, `curl-evidence-billing-endpoints.md`.

---

## 11. Console / network / server-log summaries

- **Console:** 0 uncaught exceptions (`pageerror`) across all sessions. 2 `console.error` entries total, both benign browser-native "Failed to load resource: 429" logs correlating to my own deliberate checkout rate-limit probes (not unsurfaced app failures — the UI showed a corresponding error banner in the same interaction).
- **Network:** Every request this screen makes (`GET /billing/plans`, `POST /billing/checkout`, plus directly-probed `GET /billing/entitlement`, `GET /billing/subscription`, `POST /billing/portal`, `POST /agents/{tailor,scout,cover-letter}/run`) returned a status code consistent with its documented contract — 200/202/400/401/402/409/422/429 as appropriate. Zero 5xx observed from this screen's own traffic.
- **Server log (`/var/log/aether/api.log`, file-based per DEPLOYMENT-RUNBOOK.md §4, no timestamps in the uvicorn access-log format so exact session-window correlation isn't possible):** grepped for all billing-endpoint and tested-agent-endpoint lines across the full log — 0 `" 500 "` responses, 0 `" 503 "` responses on any `/billing/*` line (154× `/billing/entitlement` 200, 34× 401, 33× `/billing/plans` 200, 5× `/billing/checkout` 400, 4× 429, 1× 401, 1× `/billing/portal` 409 — all expected). The wider log does contain unrelated 500/503 entries and Python tracebacks (e.g. `FabricationError`, LLM budget-timeout errors, a Wellfound-adapter 403) attributable to concurrent testers exercising other screens' agent flows during the shared-environment run — none traced to `/pricing` or its endpoints.

---

## 12. NOT-TESTED (HUMAN-GATED reasons only)

- **Completing a live Stripe Checkout / entering payment details** — HUMAN-GATED per §9 of the protocol and CLM-068 (Stripe not configured in this deployment; even if it were, live payment entry is explicitly prohibited for this run). The exact human-gate boundary (`POST /billing/checkout` → honest 400/429/503, never a fabricated redirect) is documented in §6.
- **Verifying "all users" backfilled to Free plan (CLM-049) beyond the one canonical admin account** — no UI/API surface on this screen enumerates other users' billing state; would require DB-level access out of scope for a screen-tester (no `git`/service/DB writes permitted, and cross-user enumeration isn't part of this screen's contract).
- **Confirming Power plan's checkout 400 body independently of Starter/Pro** — blocked by the 5/hr/user checkout rate limiter hit during legitimate testing of the other 3 plans; not re-attempted to avoid an artificial 1-hour wait. Marked [INFERRED] in §9, not a gap in claim coverage (CLM-068 independently confirmed via Starter/Pro).
- **The other 19 routes referenced by CLM-024/CLM-062** — out of this screen's scope by design (`pricing` screen-tester assignment); those routes are each other screen-testers' responsibility per the Stage-1 matrix.

---

## Sign-off

Tested by: screen-tester agent (role: MANUAL-VERIFICATION Stage 1 screen-tester), model: Claude Sonnet 5.
All findings and claim verdicts above are [VERIFIED-WITH-FRESH-EVIDENCE] against production at the session window stated, with artifact paths and reproduction steps recorded inline; the one exception is explicitly labeled [INFERRED] in §9. Every BLOCKER/HIGH finding was reproduced a second time in an independent session per §3.2 step 9 ("verify twice") before filing — see the reproduction lists in `findings.json` and the "VERIFY TWICE" / "verify twice" annotations throughout this report.
