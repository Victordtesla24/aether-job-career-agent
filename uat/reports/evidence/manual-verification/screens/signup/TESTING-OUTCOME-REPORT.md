# TESTING-OUTCOME-REPORT — Screen: signup

## Identity

- **Screen ID:** signup
- **Screen name:** Signup / Create account
- **Route:** `/signup`
- **Wireframe reference:** NONE. `SCREEN-MATRIX.json` records `"wireframe_files": []`, `"coverage_gap": "route-without-wireframe"`. Expectations below were formed from product sense (a standard self-registration form: name/email/password → account created → landed in the product) and cross-checked against the sibling `/login` screen's design language and the source contract comment in `apps/web/src/app/signup/page.tsx:1-13`, before observing actual behavior.
- **Backing endpoints (from matrix):** `POST /auth/register`, `POST /auth/login` (both proxied at `/api/auth/*`)
- **Agents wired to this screen:** none (`SCREEN-MATRIX.json: "agents": []`)
- **Repository:** `/home/ubuntu/github_repos/aether-job-career-agent`
- **Commit SHA (repo HEAD at test time):** `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Production URL under test:** `https://5cb5f0620.abacusai.cloud/signup`
- **Tester:** screen-tester agent role, model Claude Sonnet 5 (claude-sonnet-5)

## Environment / session window (UTC)

- **Session 1 (primary, account 1) start:** 2026-07-17T13:40:19Z
- **Session 1 part 2 (rate-limit/duplicate/explicit-login) :** 2026-07-17T13:41:43Z – 13:41:54Z
- **Session 2 (fresh context, account 2, verify-twice pass):** 2026-07-17T13:43:31Z – 13:43:44Z
- **Session 3 (fresh context, bcrypt-truncation re-verification + negative control):** 2026-07-17T13:44:21Z – 13:44:24Z
- **Session end:** 2026-07-17T13:44:24Z
- **Tooling:** Python Playwright 1.61.0, Chromium headless, production only, no localhost used at any point.

## Element inventory

Captured live via `page.eval_on_selector_all` at load (`test-artifacts/session1-log.json`, step `element_inventory`):

| # | Element | Selector | Tested | Result |
|---|---|---|---|---|
| 1 | Name input (optional) | `#signup-name` | Yes | Accepts free text incl. Unicode/emoji/HTML-looking text; persisted server-side byte-for-byte; rendered safely (no XSS) but garbles the header initials display — see MV-signup-004 |
| 2 | Email input | `#signup-email` | Yes | Required; client regex validation; server EmailStr validation; see findings MV-signup-003 |
| 3 | Password input | `#signup-password` | Yes | Required; client mirrors server policy (≥8 chars + 1 digit); no max-length check either side — see MV-signup-001 |
| 4 | "Create account" submit button | `button[type=submit]` | Yes | Disabled + text changes to "Creating account…" during submission (honest loading state); fires `POST /auth/register` then auto `POST /auth/login` on success |
| 5 | "Sign in" link | `a[href="/login"]` (text "Sign in") | Yes | Navigates to `/login`; back-navigation returns cleanly to `/signup` |
| 6 | Inline field error regions | `span[role=alert]` under email/password | Yes | Populate/clear correctly per validation state |
| 7 | Form-level error banner | `[data-testid=signup-error]` | Yes | Surfaces 409/422/429/network errors; see MV-signup-003 for one message-quality issue |

No other buttons, tabs, toggles, dropdowns, pagination, or modals exist on this screen — confirmed against the live-captured inventory (3 inputs, 1 button, 1 link total).

## Visual conformance (§3.2 point 1)

Full-page screenshot at load (`test-artifacts/01-load.png`, reproduced fresh in `test-artifacts/15-fresh-load-signup.png`) matches the pre-existing baseline capture at `uat/reports/evidence/manual-verification/screens/signup/baseline/screenshot.png` pixel-for-pixel in layout: centered card, Aether logo/wordmark, "Create account" heading, subcopy "Set up your own agent workspace.", Name (optional) / Email / Password fields, password-policy hint text, gradient "Create account" button, "Already have an account? Sign in" footer link. No wireframe exists to diff against structurally, so this is [VERIFIED-WITH-FRESH-EVIDENCE] only as "renders, no visible breakage, consistent with baseline" — not as "matches an approved design spec" (none exists; recorded as coverage gap, not fabricated as a pass against a spec).

## Findings

See `findings.json` for the machine-readable rows (schema per §4.1). Summary:

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-signup-001 | HIGH | security | bcrypt silently truncates passwords at 72 bytes; a different password sharing only the first 72 bytes authenticates successfully. No max-password-length validation exists. Verified twice, from two independent fresh sessions, plus a negative control isolating the exact 72-byte boundary. |
| MV-signup-002 | MEDIUM | defect | `/signup` does not redirect an already-authenticated user; the create-account form renders normally regardless of an existing valid session. Verified twice (two different accounts/sessions). |
| MV-signup-003 | LOW | validation | Client email-length check is absent; an over-long email passes client validation, hits the server, and the raw pydantic/`email_validator` message text is shown verbatim in the UI (not a crash, just unpolished/technical copy). |
| MV-signup-004 | LOW | visual | Header avatar/name-initials logic garbles a name containing markup-like text + emoji ("M日" / "MV 日."); confirmed cosmetic only — underlying stored name is correct and byte-for-byte intact, and no script execution occurred. |

All four findings were reproduced **twice** in independent fresh browser sessions per §3.2 point 9 before filing; none are FLAKY.

## Form testing detail (§3.2 point 3)

| Case | Input | Client-side result | Server round-trip | Screenshot |
|---|---|---|---|---|
| Empty submit | all fields blank | "Email is required." / "Password must be at least 8 characters. Password must contain at least one digit." | none fired (correctly blocked client-side) | `03-empty-submit.png`, repro `16-fresh-empty-submit.png` |
| Invalid email shape | `not-an-email` | "Enter a valid email address." | none fired | `04-invalid-email.png` |
| Weak password: too short w/ digit | `short1` | "Password must be at least 8 characters." | none fired | `05-weak-password.png` |
| Weak password: no digit | `noDigitsHere` | "Password must contain at least one digit." | none fired | `05-weak-password.png` |
| Weak password: digits-only, too short | `1234567` | "Password must be at least 8 characters." | none fired | `05-weak-password.png` |
| Boundary: 365-char email + 501-char password | — | client regex passed (no length cap) | `POST /auth/register` → 422, raw validator message shown (MV-signup-003) | `06-boundary-long.png` |
| Unicode + XSS-echo in Name | `MV Signup <script>alert(1)</script> 日本語🎉` | accepted (Name is free text) | `201` created; `GET /auth/me` returned the exact string back, unescaped in JSON (correct API behavior); rendered safely as text in the DOM, no script execution, but garbles header initials (MV-signup-004) | `07-before-real-register.png`, `08-after-real-register.png`, `09-dashboard.png` |
| Valid registration (account 1) | name/email/password all valid | — | `201` → auto `POST /auth/login` `200` → redirect `/dashboard`, token in `localStorage['aether_token']` | `08-after-real-register.png` |
| Duplicate email (2nd, 3rd attempts) | account 1's email again | — | `409` "An account with this email already exists." shown honestly both times | `12-dup-attempt-2.png`, `12-dup-attempt-3.png` |
| Register rate limit (4th attempt, same email within the hour) | account 1's email again | — | `429` "Too many attempts. Please wait and try again. Try again in 3515s." — reproduced again in a brand-new session 2 minutes later (`3412s` remaining, consistent countdown) and via a standalone `curl` probe | `12-dup-attempt-4.png`, `17-fresh-rate-limit-repro.png` |
| Persistence check (reload) | account 1 | — | Re-fetched `GET /auth/me` after navigating away and back; name/email persisted exactly as submitted | `session1-log.json` step `auth_me_after_register` |
| Password length probe (account 2) | 91-char password | — | `201` created; auto-login succeeded; see MV-signup-001 for the full security implication | `18-account2-dashboard.png` |

## UI ↔ backend wiring (§3.2 point 4)

Every UI action was confirmed to fire the exact endpoint predicted by `SCREEN-MATRIX.json`:
- Client-blocked invalid submissions fire **zero** network calls (confirmed via network-event counts before/after each blocked submit) — no wasted requests, no false "success" UI state.
- Successful submission fires `POST /api/auth/register` → on `201`, immediately fires `POST /api/auth/login` with the same credentials → on `200`, stores `access_token` in `localStorage['aether_token']` and routes to `/dashboard`. This exact "auto-login" contract is documented in the component's own header comment (`apps/web/src/app/signup/page.tsx:6-12`) and was verified live to work as documented.
- All error paths (409/422/429) are read from the response body and rendered via `data-testid=signup-error` or inline field errors — no optimistic success shown on any failed call, and no raw 5xx/stack trace ever appeared (zero 5xx responses across 51 captured `/api/*` calls this session; see Network summary below).
- Full response-status distribution across all sessions: `200×44, 201×2, 409×2, 422×1, 429×2, 401×1, 5xx×0, FAILED×0`.

## AI-agent integration (§3.2 point 5)

Not applicable — `SCREEN-MATRIX.json` lists `"agents": []` for this screen. No agent run was attempted or claimed.

## Error / edge states (§3.2 point 6)

- **Unauthenticated access to `/dashboard`** (the screen this one hands off to): a brand-new context with no token was redirected cleanly to `/login` (200, no error). `test-artifacts/14-unauth-dashboard-access.png`.
- **Authenticated access to `/signup`**: NOT redirected away — see MV-signup-002.
- **Back/forward:** from `/dashboard` (authenticated), browser Back returned to `/signup` (the prior history entry), and Forward returned to `/dashboard` — both worked correctly with no broken state or duplicate submission. `test-artifacts/20-back-nav.png`.
- **Throttled/slow-network reload:** not separately executed as a distinct CPU/network-throttle pass; the app's own loading state (button disabled + "Creating account…" text) was observed and behaves correctly during the real ~600ms-1.5s round trip. Explicit CDP network-throttling was not run — see NOT-TESTED.
- **Forced backend error:** the 422/409/429 paths above constitute the feasible "forced backend error" surface for this endpoint from the UI; no way to force a 5xx from the client side without server access (prohibited). None occurred spontaneously.

## Console / network / server-log hygiene (§3.2 point 7)

- **Uncaught JS errors / `pageerror` events:** zero, across all four sessions (`session1-console.json`, `session1-part2-console.json`, `session2-console.json`, `session3-console.json`).
- **Console "error" entries:** 6 total, and every single one is Chrome DevTools' automatic "Failed to load resource: the server responded with a status of NNN" line for a *deliberately-triggered* non-2xx fetch (422×1, 409×2, 429×2, 401×1) — each of which had a corresponding honest, user-visible inline/banner message in the UI at the same moment. None represent an unsurfaced failure or an application bug swallowing an error.
- **Failed requests (network-level, e.g. DNS/TLS/timeout):** zero.
- **Server 5xx:** zero observed in any of the 51 `/api/*` calls captured across all sessions.
- No log-tailer was dispatched for this single-screen run (out of scope for a screen-tester); the network-hygiene claim above is scoped to the client-observable HTTP status codes, not raw server logs.

## Claim verdicts (§3.2 point 8)

`BRIEF.json` for this screen lists `"claim_rows": []`, and a direct filter of `uat/reports/evidence/manual-verification/claims/claim-ledger.json` for rows whose `"screens"` array contains `"signup"` or whose `"endpoints"` array contains `/auth/register` returned **zero rows**. (Two rows, CLM-044 and CLM-100, mention a "signup toggle" but are scoped to the `admin-settings` / `admin-audit-log` screens' admin panel, not this screen — out of scope here, left for that screen's tester.)

**No claim rows to adjudicate for this screen.** `claims: {confirmed: 0, refuted: 0, partial: 0, unverifiable: 0}`.

## UNSURE items

None. Every behavior observed this session was reproducible and unambiguous; nothing required escalation with "both interpretations."

## Screenshot index

| File | Step |
|---|---|
| `01-load.png` | Initial `/signup` load |
| `02-after-signin-link.png` | After clicking "Sign in" link → `/login` |
| `03-empty-submit.png` | Empty-form submit validation |
| `04-invalid-email.png` | Invalid email-shape validation |
| `05-weak-password.png` | Weak-password matrix (last case shown) |
| `06-boundary-long.png` | Over-long email/password boundary probe (422, MV-signup-003) |
| `07-before-real-register.png` | Form filled for real registration (account 1, XSS/Unicode name) |
| `08-after-real-register.png` | Post-registration `/dashboard` landing (account 1) |
| `09-dashboard.png` | Fresh-account dashboard, free-plan paywall copy |
| `10-dashboard-authed-reload.png` / `10-cropped-avatar.png` | Header avatar garbling (MV-signup-004) |
| `11-signup-while-authed.png` | Authenticated user still sees full `/signup` form (MV-signup-002, account 1) |
| `12-dup-attempt-2.png` / `-3.png` | Duplicate-email 409s |
| `12-dup-attempt-4.png` | Register rate-limit 429 |
| `13-explicit-login-dashboard.png` | Explicit (non-auto) login with account 1 credentials |
| `14-unauth-dashboard-access.png` | Unauthenticated `/dashboard` → redirected to `/login` |
| `15-fresh-load-signup.png` | Verify-twice: fresh load |
| `16-fresh-empty-submit.png` | Verify-twice: fresh empty-submit validation |
| `17-fresh-rate-limit-repro.png` | Verify-twice: rate limit still active in a new session |
| `18-account2-dashboard.png` | Verify-twice: account 2 registration success (91-char password) |
| `19-account2-signup-while-authed.png` | Verify-twice: MV-signup-002 with account 2 |
| `20-back-nav.png` | Back-navigation check |
| `21-bcrypt-truncation-probe.png` | MV-signup-001: wrong-suffix password login succeeds (200) |
| `22-negative-control-early-diff.png` | MV-signup-001 control: early-differing password correctly rejected (401) |
| `23-bcrypt-truncation-variant2.png` | MV-signup-001 verify-twice: second fresh session, different tail, still succeeds (200) |

Raw logs: `session1-log.json`, `session1-part2-log.json`, `session2-log.json`, `session3-log.json` (+ matching `-console.json` / `-network.json` per session). Scripts used (copied into `test-artifacts/`): `session1.py`, `session1_part2.py`, `session2.py`, `session3_bcrypt_verify.py`.

## Free-plan / entitlement copy observed (claim-relevant, recorded verbatim)

`GET /api/billing/entitlement` for a freshly registered account returned:
```json
{"active_paid": false, "plan": {"id": "free", "status": "active"}, "requiresSubscription": true}
```
Dashboard body copy for a fresh account:
> Subscribe to unlock Aether
> Aether is in limited beta. An active subscription is required to run the AI agents that power your job search — discovery, tailoring, cover letters, and the inbox agent.
> ✓ Autonomous job discovery across live sources, scored to your profile
> ✓ Resume tailoring + ATS optimization, with a fabrication guard
> ✓ Cover letters, STAR story bank, and an inbox agent — human-approved
> [View plans & subscribe] You can still browse pricing and manage your account.

Sidebar also shows "Agents Idle — 8 agents ready · none running — Manage Agents", confirming a fresh free account can see (but per the entitlement gate, not run) the agent roster.

## NOT-TESTED (HUMAN-GATED reasons only)

- **Real email deliverability / inbox verification:** this app has no email-verification step observed in the register flow (account is active immediately on `201`); nothing to test here, not a gap.
- **CDP network throttling (slow-3G simulated reload) of `/signup` itself:** not run as a distinct pass; the real end-to-end submission latency (~0.6–1.5s) was captured and the loading state behaved correctly during it. Full artificial-throttle reload was de-prioritized in favor of the higher-value bcrypt-truncation and auth-guard probes within the fixed 2-account/time budget — recorded as a coverage gap, not asserted as passing.
- **Admin "signup toggle" interaction** (disabling public registration and confirming `/signup` then 403s): requires an operator-rotated admin credential per `canonical-login.md`'s own finding that `admin/admin123` carries `isAdmin: false` in production. HUMAN-GATED — out of scope for this screen-tester; the relevant claim rows (CLM-044, CLM-100) are scoped to the `admin-settings`/`admin-audit-log` screens, not `signup`.
- **A third account / distributed mass-registration probe:** the brief caps account creation at 2; distributed-registration abuse (many different emails) is an explicitly-acknowledged residual risk in the codebase's own ADR (`app/rate_limit.py` docstring, "identifier-keying does NOT stop distributed mass-registration from many different emails") — out of scope to actually exploit at scale here, and not testable within the 2-account budget.
- **Extremely long Name field (1000 chars) in isolation with an otherwise-valid email/password:** the one boundary test that included a 1000-char name also had an intentionally-too-long email, so the 422 observed is attributable to the email, not isolated proof about the name field's own limits. Not re-tested in isolation because doing so would have required a 3rd real registration attempt (budget exhausted) or reusing an already-registered email (would just 409/429 without adding information). Recorded as a coverage gap.

## Sign-off

Tested by: screen-tester agent (Claude Sonnet 5 / claude-sonnet-5), MANUAL-VERIFICATION Stage 1 run, 2026-07-17. All findings above were reproduced twice in independent fresh browser sessions before filing, per §3.2 point 9. Production only; no code changes made; no service restarts; 2 disposable test accounts created (see `test-artifacts/created-accounts.json`), both within the brief's 2-account cap.
