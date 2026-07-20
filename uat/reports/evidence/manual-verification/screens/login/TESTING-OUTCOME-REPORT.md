# TESTING OUTCOME REPORT — Screen: `login`

## Screen identity

- **Screen id:** `login`
- **Screen name:** Login
- **Route:** `/login`
- **Backing endpoints:** `POST /auth/login`, `GET /auth/me`
- **Wireframe reference:** NONE — `SCREEN-MATRIX.json` marks this screen `coverage_gap: "route-without-wireframe"`. No wireframe file exists under `design/screens/` for login. Per protocol, I formed my own view of what a production login screen should contain (identifier field, password field, submit control, inline error slot, link to account creation, honest loading/error states) from product sense before testing, and compared observed behavior against that baseline plus the `uat/reports/evidence/manual-verification/screens/baseline/login/` Phase-0 capture.
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Commit SHA at test time:** `53f0e084da5b460835c32d3e07d496e6e67a8616` (confirmed live against repo HEAD)
- **Session start (UTC):** 2026-07-17T13:37:42Z
- **Session end (UTC):** 2026-07-17T13:46:28Z
- **Tester:** screen-tester agent role, Claude Sonnet 5 (`claude-sonnet-5`)

## Method

All testing performed with Playwright (`@playwright/test` 1.61.1, Chromium) driven from Node scripts against the live production URL — never localhost. Console events, network responses (`/auth/*`), and full-page screenshots were captured for every scenario. All negative/fuzz/rate-limit tests used synthetic ghost identifiers of the form `mv-login-ghost-*` — the shared `admin` account was used for **exactly one** successful login, per the explicit safety rule in my brief, to verify the happy path (redirect target, token storage, session persistence, `/auth/me` shape). Server-side corroboration was pulled directly from `/var/log/aether/api.log` on this VM (per `docs/delivery/DEPLOYMENT-RUNBOOK.md` §4, file-based logs at `/var/log/aether/`), scoped to the log lines emitted since the currently-running API process started, and cross-checked against my own request counts.

All test scripts are preserved under `test-artifacts/scripts/`.

## Element inventory

| # | Element | Selector / description | Tested | Result |
|---|---|---|---|---|
| 1 | Brand block (logo, "Aether", tagline) | static header | Visual only | PASS — matches baseline capture |
| 2 | Heading "Sign in" | `<h1>` | Visual | PASS |
| 3 | Subtitle "Access your agent dashboard." | static text | Visual | PASS |
| 4 | Signup-success badge | `[data-testid="signup-success"]`, conditional on `?registered=1` | Direct URL param | PASS — renders "Account created — sign in to continue." when present; absent otherwise |
| 5 | Identifier input | `#login-identifier` (type=text, required, autocomplete=username) | Empty / XSS / unicode / 5000-char / whitespace-only / SQLi-shaped payloads | PASS — HTML5 `required` blocks empty submit; all fuzzed values handled as ordinary failed credentials, no injection/leak |
| 6 | Password input | `#login-password` (type=password, required, autocomplete=current-password) | Masking check, boundary values | PASS — always renders as dots, never plaintext |
| 7 | Inline error region | `[data-testid="login-error"]`, `role="alert"` | Triggered via wrong ghost creds, rate-limit block | PASS — honest, generic copy; no stack traces or raw JSON ever surfaced |
| 8 | Submit button | `button[type=submit]`, "Sign in" | Click, Enter-key submit, loading/disabled state | PASS — becomes "Signing in…" and `disabled` during the request; re-enables after |
| 9 | "Create account" link | `a[href="/signup"]` | Click-through navigation | PASS — resolves to `/signup` |
| 10 | Session/token handling | `localStorage['aether_token']` | Successful admin login, reload | PASS — JWT (`eyJ…`) stored, survives reload, drives `/dashboard` access |
| 11 | Logout affordance | searched topbar/sidebar/settings | Full source grep | **NOT FOUND** — see MV-login-003 |
| 12 | "Forgot password" link | searched form + footer | Full source grep | **NOT FOUND** — see MV-login-004 |

## Findings

| id | severity | category | summary |
|---|---|---|---|
| MV-login-001 | MEDIUM | defect | Already-authenticated visit to `/login` does not redirect to `/dashboard`; shows empty form instead |
| MV-login-002 | MEDIUM | coverage-gap | Unauthenticated deep-link to a dashboard sub-route loses the intended destination; post-login always lands on bare `/dashboard` |
| MV-login-003 | MEDIUM | coverage-gap | No logout/sign-out affordance exists anywhere in the reachable UI |
| MV-login-004 | MEDIUM | coverage-gap | No "Forgot password" / password-reset flow exists anywhere in the app |

Full finding rows (schema per protocol §4.1) are in `findings.json`.

Every finding above was reproduced twice, in two independently-launched fresh browser sessions (screenshots and JSON evidence for both runs are cited in each finding's `evidence` list) — none are FLAKY.

## Claim verdicts

| Claim id | Claim | Verdict | Evidence |
|---|---|---|---|
| CLM-047 | admin/admin123 login shows `isAdmin=false` in production, unconditionally demoted on every boot (GATE-31) | **CONFIRMED** [VERIFIED-WITH-FRESH-EVIDENCE, this run] | Live admin login performed once; `GET /auth/me` queried twice within that single session (once via page-navigation network capture, once via explicit `fetch` call) — both returned `{"isAdmin": false, ...}`. `test-artifacts/phase3-results.json`, `test-artifacts/12-admin-login-success-dashboard.png`, `test-artifacts/server-log-excerpt.txt` (server log shows the matching `POST /auth/login 200` + `GET /auth/me 200` pair). |
| CLM-048 | Rate limiting returns HTTP 429 after 5 requests on the auth endpoint (GATE-32) | **CONFIRMED** [VERIFIED-WITH-FRESH-EVIDENCE, this run] | Reproduced twice with two different, freshly-generated ghost identifiers in two separate browser sessions: 5 consecutive failed attempts each return 401, the 6th returns 429 with a `Retry-After` header (~899s ≈ the documented 15-min window), and the UI surfaces "Too many attempts. Please wait and try again. Try again in Ns." — no raw JSON. `test-artifacts/phase4-ratelimit-results.json`, `test-artifacts/phase6-reverify-results.json`, `test-artifacts/16-rate-limit-ui-blocked.png`, `test-artifacts/20-reverify-ratelimit.png`. Cross-checked against server log: 4 total `429` responses logged for `/auth/login` since the current process started, matching exactly the 4 blocked calls I made across both rate-limit runs. |
| CLM-070 | Admin credential rotation off admin/admin123 is pending as of the source doc; GATE-17/31 formal closure blocked | **PARTIALLY-TRUE** [VERIFIED-WITH-FRESH-EVIDENCE for the testable portion; UNVERIFIABLE-FROM-UI for the rest] | The live, testable portion — admin/admin123 carries `isAdmin=false` in production, consistent with the rotation being applied — is CONFIRMED (same evidence as CLM-047). The claim's other assertion, that GATE-17/31 formal closure remains blocked / whether some *other* operator-configured admin credential (`AETHER_ADMIN_EMAIL`) is now active, cannot be verified from the UI: I was given no alternate admin credentials to test with, and as a screen-tester I have no path to independently inspect production environment-variable state (that determination in `canonical-login.md` is prior-phase testimony, not something I can reproduce live from `/login`). |

## UNSURE items

None outstanding. All ambiguous observations (already-authed redirect behavior, deep-link destination handling, logout/password-reset absence) were resolved to a definitive live-evidence conclusion (via both UI behavior and full source-code grep) rather than left as guesses, and are recorded as findings above rather than UNSURE items. I flag for the orchestrator's judgment only whether MV-login-001/003/004 are deliberate product/scope choices for this phase versus defects — my own product-sense read is that they are gaps, but I cannot rule out an intentional MVP scope cut from UI testing alone.

## Screenshot index

All under `test-artifacts/`:

| File | Scenario |
|---|---|
| 01-initial-load.png | Clean load, full page |
| 02-registered-badge.png | `?registered=1` success badge |
| 03-empty-submit.png | Empty form submit (HTML5 validation blocks) |
| 04-xss-echo-test.png | XSS payload in identifier — safely echoed as plain text, no execution |
| 05-unicode-test.png | Unicode identifier |
| 06-long-string-test.png | 5000-char identifier |
| 07-wrong-password-ghost.png | Wrong password, ghost identifier |
| 08-enter-key-submit.png | Enter-key submit |
| 09-signup-link-nav.png | "Create account" navigation to `/signup` |
| 10-unauth-dashboard-redirect.png | Unauthenticated `/dashboard` → redirected to `/login` |
| 11-already-authed-visit-login.png | Fake-token session visiting `/login` (no redirect) — MV-login-001 |
| 12-admin-login-success-dashboard.png | The one permitted admin/admin123 login → `/dashboard` |
| 13-admin-reload-persistence.png | Reload after admin login — session persists |
| 14-authed-visit-login-real-token.png | Real admin token, visiting `/login` (no redirect) — MV-login-001 |
| 15-back-forward.png | Browser back/forward through the auth flow |
| 16-rate-limit-ui-blocked.png | Rate-limit 429 surfaced in the UI |
| 17-throttled-load.png | Throttled (500kbps/400ms) load |
| 18-whitespace-only.png | Whitespace-only identifier/password |
| 19-sqli-payload.png | SQLi-shaped payload, ghost identifier |
| 20-reverify-ratelimit.png | Fresh-session re-verification of rate limiting |
| 21-reverify-authed-visit-login.png | Fresh-session re-verification of MV-login-001 |
| 22-reverify-unauth-dashboard.png | Fresh-session re-verification of unauth redirect |
| 23-reverify-xss.png | Fresh-session re-verification of XSS safety |
| 24-deeplink-subroute-redirect.png | Unauth deep-link to `/dashboard/resume-studio` — MV-login-002 |
| 25-loading-state-mid-submit.png | "Signing in…" disabled-button loading state |

JSON evidence: `phase1-results.json` … `phase8-loading-results.json`, `phase1-console-messages.json`, `phase1-failed-requests.json`, `phase1-network-log.json`, `server-log-excerpt.txt`.

## Console / network / server-log summary

- **Console (client):** Zero uncaught JavaScript exceptions (`pageerror`) across all ~20 test scenarios. The only `console.error` entries observed are Chrome's automatic "Failed to load resource: the server responded with a status of 401/429" lines for intentionally-triggered auth failures — every one of these was surfaced to the user via the inline `[data-testid="login-error"]` message, so none is an *unsurfaced* failure per the protocol's hygiene bar.
- **Network:** Every login attempt fired the expected `POST /auth/login` (or `GET /auth/me` post-login); response status/body directly drove the UI in all cases (401 → inline error, 429 → inline rate-limit copy with countdown, 200 → redirect + token storage). No optimistic-success-on-failure and no silently-dropped errors observed.
- **Server (`/var/log/aether/api.log`, current process only):** 63 `/auth/login` requests logged during/around my session — 39×200, 19×401, 4×429, 1×422 (my direct malformed-body probe) — exactly matching my own client-side request counts (including the 4 rate-limit blocks). **Zero 5xx responses** logged since the current API process started. Note: the log file (spanning ~83 historical process restarts) does contain three stale `POST /auth/login 500` tracebacks from a much earlier deployment (calling a since-renamed `UserRepository.get_by_email`, superseded by `get_by_username_or_email` in the current `auth.py`) — confirmed these predate the current running process by ~17,000 log lines / dozens of restarts and are not reproducible against the deployed commit; excerpt at `test-artifacts/server-log-excerpt.txt` documents the current-process-only window used for the zero-5xx conclusion.

## NOT-TESTED (HUMAN-GATED only)

- **A second admin/admin123 login for independent re-verification of CLM-047/CLM-070** — explicitly withheld per my brief's safety rule limiting this screen's tester to exactly one successful admin login (to avoid tripping the identifier-keyed rate limiter for the shared account across concurrent testers). Substituted with two independent `GET /auth/me` reads inside that single permitted session.
- **Confirming whether an alternate operator-configured admin credential (`AETHER_ADMIN_EMAIL`) is active** — no such credentials were provided in my brief, and inspecting production environment-variable state is outside a screen-tester's authority/tooling (operator-only, per `canonical-login.md`).
- **Full signup → login round trip with a freshly created account** — creating new accounts is the `signup` screen tester's scope; this report tested only the `/login?registered=1` rendering contract on the login side of that boundary.

## Sign-off

Tested by: screen-tester agent (Claude Sonnet 5 / `claude-sonnet-5`), MANUAL-VERIFICATION Stage 1, screen `login`. All findings reproduced twice in independent fresh sessions; all claim verdicts backed by fresh live evidence captured in this run (paths above), cross-corroborated against production server logs. No code changes, no service restarts, no destructive actions taken.
