# TESTING OUTCOME REPORT — Screen: root

**Screen ID:** root
**Screen name:** Root (Redirect)
**Route:** `/`
**Wireframe reference:** none — coverage-gap row (`route-without-wireframe`), already recorded by the orchestrator. Expected behavior for this report was derived from product sense plus `apps/web/next.config.mjs` `redirects()` (the one config file the brief authorized reading), cross-checked against `apps/web/src/components/auth-guard.tsx` and `apps/web/src/app/dashboard/layout.tsx` to understand the client-side auth gate the redirect target sits behind.
**Tester:** screen-tester agent role, model claude-sonnet-5 (Claude Agent SDK)
**Environment:** Production — `https://5cb5f0620.abacusai.cloud` (verified this VM IS the production host per `docs/delivery/DEPLOYMENT-RUNBOOK.md` — direct file-based log access at `/var/log/aether/` used for server-log corroboration)
**Repo commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616` (matches canonical-login.md and BRIEF.json)
**Session window (UTC):** 2026-07-17T13:37:26Z (start, run1) → 2026-07-17T13:44:06Z (end, edge-case curl checks). Run2 (fresh-session reproduction): 2026-07-17T13:41:01Z–13:41:37Z.

---

## 1. My own expectation of what "/" should do (formed before testing)

From `apps/web/next.config.mjs`:
```js
async redirects() {
  return [
    { source: "/", destination: "/dashboard", permanent: false },
    { source: "/dashboard/cover-letter", destination: "/dashboard/cover-letters", permanent: true },
  ];
}
```
Comment in the file: "Root forwards to the dashboard (AuthGuard bounces unauthenticated visitors to /login). A config redirect — not a page-level `redirect()` — because a statically prerendered `redirect()` ships a 307 with no Location header, stranding non-JS clients."

Expectation, before looking at live behavior:
1. `GET /` → HTTP 307 (temporary, not cached permanently) with `Location: /dashboard`, working even for non-JS/curl clients (this is exactly why they chose a config redirect over a page-level one).
2. `/dashboard` is a client-rendered shell behind `AuthGuard` (`apps/web/src/components/auth-guard.tsx`), which checks `localStorage.aether_token` on mount:
   - No token → `router.replace("/login")` (replace, not push, so no extra history entry) — user should land cleanly on the login screen, never see any dashboard chrome or data (AuthGuard renders `null` until the check resolves).
   - Token present → dashboard shell renders (sidebar/topbar/main), subject to whatever `SubscriptionGate` decides (separate screen's concern).
3. No redirect loop possible — `/login` doesn't itself check for an existing token and bounce forward, so there's no ping-pong.
4. Because the auth check is client-side only, `/dashboard`'s raw HTML (as served to an unauthenticated curl request) should be an inert hydration shell with **no user data or chrome text** — otherwise the long-TTL edge cache (`s-maxage=31536000`) on that page would be a real leak vector across sessions.

I then tested exactly this.

---

## 2. Element inventory

The root route itself renders **zero UI** — it is a pure Next.js config-level redirect (`next.config.mjs` → `redirects()`), never reaching React render for `/`. There are no buttons, links, forms, or other interactive elements that belong to this screen. The elements a user incidentally sees immediately after the redirect (login form fields, dashboard sidebar links) belong to the `/login` and `/dashboard` screens and are in those testers' scope, not re-tested here except to confirm the *handoff* (final URL, no broken/blank state, no console errors).

| Element | Owner screen | Tested here? | Result |
|---|---|---|---|
| Server-side redirect `/` → `/dashboard` | root | Yes | PASS — 307, `Location: /dashboard`, single hop, no loop |
| Client `AuthGuard` bounce `/dashboard` → `/login` (unauthenticated) | root↔dashboard boundary | Yes (handoff only) | PASS — clean landing on `/login`, no flash of chrome |
| Dashboard shell render (authenticated) | dashboard (other screen) | Handoff only | PASS — shell renders, no bounce-to-login |
| Login form / sidebar nav items | login / dashboard (other screens) | Not tested (out of scope) | N/A |

---

## 3. Findings

**Zero findings filed.** Every behavior tested matched my pre-formed expectation, reproduced identically across two independent fresh browser sessions (see §7). `findings.json` for this screen is `[]`.

Adversarial checks I specifically ran looking for a defect (all passed, none became findings):
- Query-string preservation through the redirect (`/?utm_source=test&ref=abc` → `Location: /dashboard?utm_source=test&ref=abc`) — preserved correctly.
- `POST /` and `HEAD /` — 307 preserved method to `/dashboard`; `/dashboard` then correctly returns clean `405 Method Not Allowed` for POST (no 500, no stack trace).
- Redirect-loop check via `curl -L --max-redirs 10` — exactly 1 hop, terminates at `/dashboard` 200.
- Cache-leak check: unauthenticated `GET /dashboard` returns `x-nextjs-cache: HIT`, `cache-control: s-maxage=31536000` — a long-lived edge cache. Fetched the raw cached body directly and grepped for sidebar/nav text ("Resume Studio", "Cover Letter Studio", "Subscribe to unlock", "Administrator", "Vikram") and email patterns — **zero matches**. The cached HTML is an inert 7559-byte hydration shell only; `AuthGuard` renders `null` until the client-side token check resolves, so there is nothing user-specific for the cache to leak. This was the one place I actively hunted for a data-exposure bug and it held up.
- Server-log corroboration: `/var/log/aether/web.log` (mtime 13:27:04Z, before my window) had zero new bytes appended throughout my entire test window (13:37–13:44Z) — the frontend service logs nothing per-request, consistent with clean client-side behavior. `/var/log/aether/api.log` (mtime 13:43:12Z, within my window) shows all requests from my session (`POST /auth/login`, `GET /agents`, `GET /approvals`, `GET /billing/entitlement`, `GET /workspaces/settings`) returning 200. The 80 total 5xx lines present in api.log during my session are all `POST /agents/tailor/run`, `/agents/cover-letter/run`, `/agents/pipeline/run` — concurrent traffic from other screen-testers on unrelated screens (shared prod account per protocol), not from root or its redirect target.

---

## 4. Claim verdicts

Per `claims/claim-ledger.json` (101 total rows), filtered by `screen_id == "root"` / `screen == "root"`: **0 matching rows.**

**No claim rows are mapped to root.** This section is intentionally empty — confirmed by direct query of the claim ledger, not by trusting the brief's assertion.

---

## 5. UNSURE items

None. Every behavior I could form an expectation for was directly reproducible and unambiguous. No UNSURE items filed.

---

## 6. Screenshots index

All screenshots full-page, 1440×900 viewport, Chromium via Playwright. Stored under `test-artifacts/run1/` and `test-artifacts/run2/` (fresh-session duplicate — see §7).

| # | File | Scenario |
|---|---|---|
| 1 | `01-unauth-landing.png` | Unauthenticated `GET /` final landing state — clean `/login` page |
| 2 | `02-unauth-after-back.png` | Browser back from `/login` → blank tab (no app entry before it; expected, not a defect) |
| 3 | `03-unauth-after-forward.png` | Browser forward → back to `/login`, fully rendered |
| 4 | `04-throttled-unauth.png` | Throttled network (400kbps/400kbps/400ms latency ≈ Chrome DevTools "Slow 3G") reload of `/`, unauthenticated — lands cleanly on `/login` |
| 5 | `05-post-login-dashboard.png` | Post canonical-login landing on `/dashboard` (paywall shown — `SubscriptionGate`, expected for admin/admin123 with no active subscription; not a root-route concern) |
| 6 | `06-auth-root-landing.png` | Explicit navigation to `/` while authenticated → lands on `/dashboard` shell, not bounced to `/login` |
| 7 | `07-auth-after-back.png` | Browser back while authenticated — stays on `/dashboard`, shell intact |
| 8 | `08-auth-after-forward.png` | Browser forward while authenticated — stays on `/dashboard`, shell intact |
| 9 | `09-throttled-auth.png` | Throttled network reload of `/` while authenticated — lands on `/dashboard` shell, no partial/broken render |

Additional evidence: `test-artifacts/curl/curl-unauth-root.txt` (verbose curl trace of the redirect chain), `test-artifacts/curl/edge-cases.txt` (query-string, POST/HEAD, loop-check, cache-leak probes), `test-artifacts/curl/headers.txt` + `dashboard-body.html` (raw unauthenticated `/dashboard` response used for the cache-leak check), `test-artifacts/run{1,2}/results.json` (structured Playwright capture: every console event, page error, failed request, and network response for all 4 scenarios), `test-artifacts/test_root.py` (the test script itself, for reproducibility).

---

## 7. Verify-twice (§3.2 point 9)

Ran the full 4-scenario Playwright suite twice, in two independent fresh browser contexts (no shared state), at 13:39–13:41Z (run1) and 13:41–13:41Z (run2):

| Metric | run1 | run2 | Match? |
|---|---|---|---|
| Unauth final URL | `/login` | `/login` | Yes |
| Unauth console/page errors | 0 / 0 | 0 / 0 | Yes |
| Unauth localStorage token present | false | false | Yes |
| Throttled-unauth final URL | `/login` | `/login` | Yes |
| Throttled-unauth load time | 8.26s | 8.27s | Yes (within noise) |
| Auth root final URL | `/dashboard` | `/dashboard` | Yes |
| Auth bounced-to-login | false | false | Yes |
| Throttled-auth final URL | `/dashboard` | `/dashboard` | Yes |
| All-scenario console/page errors | 0 | 0 | Yes |
| All-scenario failed requests | 0 | 0 | Yes |

**No flakiness observed.** All findings (i.e., the absence of findings) are reproduced and hold as [VERIFIED-WITH-FRESH-EVIDENCE].

---

## 8. Console / network / server-log summaries

**Console (client-side, both runs, all 4 scenarios, 8 scenario-sessions total):** 0 uncaught errors, 0 page errors, 0 console warnings, 0 failed/blocked requests (`requestfailed` listener never fired).

**Network (client-side capture):** Every navigation matched the expected chain — `307 /` → `200 /dashboard` (unauth: chrome never renders, no `/api/*` calls fire before the bounce to `/login`, confirming `AuthGuard` correctly gates rendering, not just visibility — no protected data is fetched pre-auth) → for authenticated sessions, `/dashboard` fires `GET /api/agents`, `GET /api/approvals?status=pending`, `GET /api/billing/entitlement`, `GET /api/workspaces/settings`, all 200.

**Server logs (`/var/log/aether/`, this VM being the actual production host per the runbook):**
- `web.log`: no new lines during the entire test window (Next.js `next start` does not log per-request in this deployment); the pre-existing `TypeError: Cannot read properties of undefined (reading 'call')` entries in the file predate my session by ~10 minutes (file mtime 13:27:04Z vs. my window starting 13:37:26Z) and are unrelated to root/dashboard redirect traffic — flagged here for transparency only, not filed as a root finding since they cannot be attributed to this screen or this session.
- `api.log`: all requests attributable to my session (login, `/agents`, `/approvals`, `/billing/entitlement`, `/workspaces/settings`) returned 200. The 5xx entries present in the file during my window belong to concurrent testers' agent-run endpoints (`/agents/tailor/run`, `/agents/cover-letter/run`, `/agents/pipeline/run`) — out of scope for root, called out so the orchestrator doesn't double-count them against this screen.

---

## 9. AI-agent integration

Not applicable — the matrix row for root lists zero agents (`SCREEN-MATRIX.json` / `BRIEF.json`: `"agents": []`). No agent run was attempted from this screen.

---

## 10. NOT-TESTED list (HUMAN-GATED only)

None. Every testable aspect of this screen (a pure redirect with a client-side auth gate on its landing target) was exercised: unauthenticated load, authenticated load, back/forward in both states, throttled reload in both states, query-string preservation, non-GET methods, redirect-loop absence, console hygiene, network wiring, cache-leak probing, and server-log corroboration. There is no login/payment/destructive/irreversible action gated behind this screen that would require human execution — the canonical login itself was used freely per protocol.

---

## Sign-off

Tested by: screen-tester agent (Claude Agent SDK, model `claude-sonnet-5`), acting as a 3rd-party-minded manual tester on production, per `uat/reports/evidence/manual-verification/STAGE1-TESTER-PROTOCOL.md` §3.2.
Session: 2026-07-17T13:37:26Z–13:44:06Z UTC (run1 + run2 + curl edge-case probes), production `https://5cb5f0620.abacusai.cloud`, commit `53f0e084da5b460835c32d3e07d496e6e67a8616`.
Result: **PASS — 0 findings, 0 claims mapped, 0 UNSURE items.** Root's redirect behavior fully matches the behavior encoded in `next.config.mjs` and the product-sense expectation formed from it, reproduced twice with byte-identical outcomes.
