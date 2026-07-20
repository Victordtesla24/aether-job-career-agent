# MANUAL-VERIFICATION — Admin Cluster (admin-root, admin-health, admin-users, admin-settings, admin-audit-log, admin-spend)

**Tester role:** screen-tester (Claude Agent SDK, model claude-sonnet-5), Stage 1 MANUAL-VERIFICATION run
**Cluster:** admin — routes `/admin`, `/admin/health`, `/admin/users`, `/admin/users/[id]`, `/admin/settings`, `/admin/audit-log`, `/admin/spend`
**Screen ids:** admin-root, admin-health, admin-users, admin-settings, admin-audit-log, admin-spend
**Wireframes:** none — all six screens are flagged `coverage_gap: "route-without-wireframe"` in their BRIEF.json (pre-existing, documented gap, not something this session could remediate)
**Repo commit SHA (from BRIEF.json / canonical-login.md):** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Production URL:** https://5cb5f0620.abacusai.cloud (app at `/dashboard`, admin shell at `/admin`)
**Session window (UTC):** 2026-07-17T15:36:55Z start → 2026-07-17T15:51:13Z end (this document finalized after)
**This document covers all 6 admin-cluster screens.** Each screen's own folder (`screens/admin-<x>/`) has its own `findings.json` and a short `TESTING-OUTCOME-REPORT.md` stub that points back here for the shared methodology/evidence and adds only screen-specific findings/claims.

---

## 0. Governing constraint: HUMAN-GATED operator-admin credential

Per `uat/reports/evidence/manual-verification/governance/human-gated-admin.md` (Phase 0 probe) and independently re-confirmed live in this session: production has **no operator-admin credential configured**. `AETHER_ADMIN_EMAIL` / `AETHER_ADMIN_PASSWORD_HASH` are absent, and the seeded `admin`/`admin123` account is unconditionally demoted to `isAdmin: false` on the backend (verified live, see §2). This means **the real, authenticated-as-operator-admin admin UI could not be rendered, clicked through, or functionally tested in this session** — that entire surface is HUMAN-GATED and is listed explicitly in §9 (NOT-TESTED) for every screen. This is not a gap in tester effort; no valid credential exists to reach that state.

What **could** be fully and rigorously tested, and was:
1. Unauthenticated access to all 6 frontend routes + a no-JS raw-HTML check for server-side data leakage.
2. Authenticated-as-demoted-non-admin-user (`admin`/`admin123`, confirmed `isAdmin:false`) access to all 6 frontend routes.
3. All 10 backing `/admin/*` API endpoints, called directly, both unauthenticated and as the demoted user.
4. Edge cases: throttled-network reload, browser back/forward, malformed-body requests, non-existent-method probes.
5. Server-side log hygiene (`/var/log/aether/api.log`, `/var/log/aether/web.log`) for 5xx errors and tracebacks on any `/admin/*` path, across the full log history.

Every check below was run **twice, in fresh sessions** (separate browser contexts / separate curl invocations with fresh tokens), per §3.2 point 9. Both passes produced identical results in every case — no FLAKY items.

---

## 1. Element inventory

Because every `/admin/*` route redirects before any admin-specific chrome renders (for both unauthenticated and demoted-user sessions), the **only elements actually reachable and testable** in this session are the guard interstitial and the redirect targets:

| Element | Screen(s) | Tested | Result |
|---|---|---|---|
| Client-side "Verifying admin access…" / "Redirecting…" interstitial (`AdminGuard`, non-interactive) | all 6 | Yes | Renders briefly, then navigates away; no admin data ever present in it |
| Redirect to `/login` (unauthenticated caller, no token) | all 6 | Yes | Clean, single hop, no console errors |
| Redirect to `/dashboard` (authenticated, `isAdmin:false`) | all 6 | Yes | Clean, single hop, no console errors, no admin chrome flash |
| Server-rendered (no-JS) HTML shell | all 6 | Yes | Contains only the interstitial text + Next.js hydration scaffolding — zero admin data (users, spend, settings, audit rows) present pre-hydration |
| Login form (`/login`) reached via redirect: `#login-identifier`, `#login-password`, submit button | admin-root (redirect target) | Yes (as part of auth setup) | Functions per canonical-login.md; not independently re-tested here since it is the `login` screen's own remit |
| Dashboard shell reached via redirect (`/dashboard`) | admin-root (redirect target) | Yes (visual scan only) | Regular authenticated user dashboard renders; no admin nav items, no admin data | 

All **substantive** admin controls (nav cards on `/admin`, users table + filters + pagination on `/admin/users`, user detail panels + spend-cap input + suspend/unsuspend buttons on `/admin/users/[id]`, settings toggles on `/admin/settings`, audit-log table + pagination on `/admin/audit-log`, spend totals/table on `/admin/spend`, health/service/agent/cron status cards on `/admin/health`) exist in the source (`apps/web/src/app/admin/**`, read for inventory purposes only) but were **never rendered to a browser in this session** — they are HUMAN-GATED, listed in §9 per screen, and are explicitly **not** claimed as tested.

---

## 2. Unauthenticated access — all 6 routes (§3.2 point 6)

### 2a. Browser-level (Playwright, full client JS), verified twice

| Route | Screen | Pass A finalUrl | Pass B finalUrl | Console errors | Failed requests |
|---|---|---|---|---|---|
| `/admin` | admin-root | `/login` | `/login` | 0 | 0 |
| `/admin/health` | admin-health | `/login` | `/login` | 0 | 0 |
| `/admin/users` | admin-users | `/login` | `/login` | 0 | 0 |
| `/admin/settings` | admin-settings | `/login` | `/login` | 0 | 0 |
| `/admin/audit-log` | admin-audit-log | `/login` | `/login` | 0 | 0 |
| `/admin/spend` | admin-spend | `/login` | `/login` | 0 | 0 |
| `/admin/users/test-fake-id-mv-admin-userdetail` (dynamic sub-route) | admin-users | `/login` | `/login` | 0 | 0 |

Evidence: `test-artifacts/passA-sweep-unauth.json`, `test-artifacts/passB-sweep-unauth.json` (this folder), `screens/admin-users/test-artifacts/sweep-userid-result-passA.json` / `-passB.json`, plus full-page screenshots `passA-unauth-<screen>-fullpage.png` / `passB-unauth-<screen>-fullpage.png` in each screen's `test-artifacts/`.

### 2b. Raw HTML, no JS (curl) — confirms no server-side data leak before the client guard mounts

All 6 routes plus `/admin/users/<fake-id>` returned **HTTP 200** with a server-rendered shell containing **only** `"Verifying admin access…"` and Next.js hydration/chunk-loading scaffolding — grepped for `isAdmin`, `spendCapUsd`, `AdminAuditLog`, `@aether` (user emails), `costUsd` and found **zero** matches in every file. This is the load-bearing check for "never client-side-only trust": even before any JS executes, the server does not leak admin data into the initial HTML.

Evidence: `test-artifacts/raw-html/raw_admin.html`, `raw_admin_health.html`, `raw_admin_users.html`, `raw_admin_settings.html`, `raw_admin_audit-log.html`, `raw_admin_spend.html`, `raw_admin_users_id.html`.

---

## 3. Authenticated-as-demoted-non-admin-user access — all 6 routes (§3.2 point 6, the run brief's core ask)

Logged in via `POST /auth/login` with `admin`/`admin123` (canonical-login.md credential). Confirmed live via `GET /auth/me`:

```json
{"id":"cc29a76e324fbf19f438eb8be","email":"admin@aether.local","name":"Administrator","isAdmin":false}
```

(`access_token` redacted to first 8 chars in `test-artifacts/login-response-redacted.json` per evidence rules.)

| Route | Screen | Pass A finalUrl | Pass B finalUrl | Console errors | Failed requests | Admin data visible in body text? |
|---|---|---|---|---|---|---|
| `/admin` | admin-root | `/dashboard` | `/dashboard` | 0 | 0 | No — regular dashboard only |
| `/admin/health` | admin-health | `/dashboard` | `/dashboard` | 0 | 0 | No |
| `/admin/users` | admin-users | `/dashboard` | `/dashboard` | 0 | 0 | No |
| `/admin/settings` | admin-settings | `/dashboard` | `/dashboard` | 0 | 0 | No |
| `/admin/audit-log` | admin-audit-log | `/dashboard` | `/dashboard` | 0 | 0 | No |
| `/admin/spend` | admin-spend | `/dashboard` | `/dashboard` | 0 | 0 | No |
| `/admin/users/test-fake-id-mv-admin-userdetail` | admin-users | `/dashboard` | `/dashboard` | 0 | 0 | No |

**CONFIRMS the run brief's requirement #2 in full: every one of the 6 routes redirects a demoted non-admin authenticated user to `/dashboard`, with zero admin data rendered at any point, reproduced twice.**

Evidence: `test-artifacts/passA-sweep-authed.json`, `test-artifacts/passB-sweep-authed.json` (this folder), per-screen `passA-authed-<screen>-fullpage.png` / `passB-authed-<screen>-fullpage.png` screenshots.

---

## 4. Backing API endpoints — direct curl, unauthenticated and as demoted user (§3.2 point 4/6, run brief requirement #3)

All **10** `/admin/*` operations defined in `apps/api/app/routers/admin.py` were called directly against `https://5cb5f0620.abacusai.cloud/api`, twice each, in two independent passes with two independently-obtained tokens:

| # | Method | Path | Unauthenticated (expect 401) | Demoted user (expect 403) |
|---|---|---|---|---|
| 1 | GET | `/admin/health` | 401 `Not authenticated` ✓✓ | 403 `Admin privileges required` ✓✓ |
| 2 | GET | `/admin/users` | 401 ✓✓ | 403 ✓✓ |
| 3 | GET | `/admin/users/{id}` | 401 ✓✓ | 403 ✓✓ |
| 4 | POST | `/admin/users/{id}/spend-cap` | 401 ✓✓ | 403 ✓✓ |
| 5 | POST | `/admin/users/{id}/suspend` | 401 ✓✓ | 403 ✓✓ |
| 6 | POST | `/admin/users/{id}/unsuspend` | 401 ✓✓ | 403 ✓✓ |
| 7 | GET | `/admin/spend` | 401 ✓✓ | 403 ✓✓ |
| 8 | GET | `/admin/settings` | 401 ✓✓ | 403 ✓✓ |
| 9 | POST | `/admin/settings` | 401 ✓✓ | 403 ✓✓ |
| 10 | GET | `/admin/audit-log` | 401 ✓✓ | 403 ✓✓ |

**20/20 unauthenticated calls → 401. 20/20 demoted-user calls → 403. Zero 200s, zero 5xx, zero data disclosure, across both passes.** This is the strongest, most directly reproducible evidence in this report and fully confirms CLM-089.

Evidence: `test-artifacts/run1-api-transcript.txt`, `test-artifacts/run2-api-transcript.txt` (this folder).

### 4a. Supplementary route-surface probes (confirms CLM-100 audit-immutability and informs CLM-101)

| Probe | Result (both passes identical) |
|---|---|
| `DELETE /admin/audit-log` (unauth) | 405 Method Not Allowed — only GET is registered on this path |
| `DELETE /admin/audit-log/1` (unauth) | 404 Not Found — no id-scoped audit route exists at all |
| `PATCH /admin/audit-log/1` (unauth) | 404 Not Found |
| `GET /admin/users/{id}/export` (unauth) | 404 Not Found — no export route exists |
| `DELETE /admin/users/{id}` (unauth) | 405 Method Not Allowed — only GET is registered on this path |

Evidence: `screens/admin-audit-log/test-artifacts/pass1-audit-export-checks.txt`, `screens/admin-audit-log/test-artifacts/verify-twice-audit-export-checks.txt` (identical to `screens/admin-users/test-artifacts/`).

### 4b. Malformed-input / edge-case probes

| Probe | Result |
|---|---|
| `POST /admin/settings` unauth, valid-JSON-wrong-type body `{"signupEnabled":"not-a-bool-xyz"}` | 401 `Not authenticated` (correct — auth checked first) |
| `POST /admin/settings` unauth, syntactically-invalid JSON body | **422** JSON decode error (auth check bypassed by a parser error for this specific malformed-body case — see MV-admin-settings-002, LOW, no data disclosure) |
| `GET /admin/health` with garbage bearer token | 401 `Could not validate credentials` |
| `GET /admin/users` with malformed/bad-signature JWT | 401 `Could not validate credentials` |

---

## 5. Additional edge states (§3.2 point 6)

| Test | Result |
|---|---|
| Throttled reload (50 kbps, 400 ms latency, CDP emulation) of unauthenticated `/admin/settings` | Still redirects cleanly to `/login` (~40 s under severe throttle), 0 console errors, no partial/broken/stuck state, no admin data exposed during the slow load |
| Browser back/forward as demoted user: `/admin` → `/dashboard` (replaced) → `/admin/users` → `/dashboard` (replaced) → back → forward | Every history state resolves to `/dashboard`; no admin content ever flashes on back or forward navigation; 0 console errors |

Evidence: `test-artifacts/edge-cases-result.json`, `test-artifacts/back-forward-final-state.png`, `screens/admin-settings/test-artifacts/throttled-reload-admin-settings.png`.

---

## 6. Console / network / server-log hygiene (§3.2 point 7)

- **Browser console errors across all sweeps (unauth ×2 passes, authed-demoted ×2 passes, user-detail sub-route ×2 passes, throttled reload, back/forward):** 0 uncaught errors, 0 page errors, in every single run.
- **Failed browser requests:** 0 across all runs.
- **Server-side `/var/log/aether/api.log`:** grepped for every `admin` line across the **entire log history** (2026-07-11 birth through end of session, 35,757 lines) for a 5xx status code → **zero matches**. Every `/admin/*` request in the log, at any point in history, resolved to 200/401/403/404/405/422 — never a 5xx or an unhandled exception on an admin path.
  - Note: the log **does** contain a block of historical 200 OK admin-mutation entries (spend-cap/suspend/unsuspend/settings, for one user id) that pre-date this session by a large margin (thousands of log lines earlier). This is consistent with — but is not fresh evidence for — the "temporary admin account" referenced in CLM-044's testimony from a prior phase. Per the epistemic-discipline rule ("prior-phase reports/logs are testimony, not evidence"), this observation is noted for context only and is **not** used to close or confirm any claim in this session; no live admin session existed or was reachable by this tester at any point.
  - The log also shows unrelated 503s on `POST /agents/tailor/run` during the session window — this is a different, concurrent MV tester's traffic on a different screen (agent-monitor / job-discovery), entirely outside the admin cluster's endpoint set, and does not affect any `/admin/*` finding.
- **`/var/log/aether/web.log`:** last modified 2026-07-17T13:27:04Z, well before this session's 15:36Z start; contains 0 `/admin` references. No fresh web-server-side errors attributable to this session.

---

## 7. Claim verdicts (cluster-wide; see also each screen's own report for the identical rows scoped to it)

| Claim | Screens | Verdict | Evidence |
|---|---|---|---|
| **CLM-047** — admin/admin123 shows `isAdmin:false`, unconditionally demoted every boot | login, admin-root | **PARTIALLY-TRUE.** `isAdmin:false` [VERIFIED-WITH-FRESH-EVIDENCE, `test-artifacts/login-response-redacted.json`, 2026-07-17T15:37Z and re-confirmed T15:41Z]. The "every boot" mechanism claim requires restarting `aether-api.service` to observe, which is prohibited for a screen-tester (no service restarts) — **UNVERIFIABLE-FROM-UI** for that half. | `test-artifacts/login-response-redacted.json` |
| **CLM-062** — Playwright sweep of 14 routes + `/pricing` + `/admin` as a *paid admin* showed 0 console/failed-request/page errors | dashboard, …, admin-root | **UNVERIFIABLE-FROM-UI** (my remit only). No admin credential exists to reproduce "as a paid admin"; only 1 of the 16 routes (`/admin`) is in my cluster. My own sweep of `/admin` (unauthenticated + demoted, not "paid admin") independently showed 0 console/failed-request errors in all 4 sub-runs — consistent with, but not proof of, the original claim, which specifically requires a session this tester could not obtain. | `test-artifacts/passA-sweep-unauth.json`, `test-artifacts/passA-sweep-authed.json` |
| **CLM-065** — `/admin` redirects cleanly (no crash) without an `isAdmin:true` session | admin-root | **CONFIRMED.** [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-17T15:36–15:51Z, both unauthenticated→`/login` and demoted-authenticated→`/dashboard`, 0 console errors, 0 crashes, reproduced twice each]. | §2, §3 tables above |
| **CLM-070** — credential rotation off admin/admin123 still pending; check if any other operator credential is now active | login, admin-root | **PARTIALLY-TRUE.** admin/admin123 still `isAdmin:false` — **CONFIRMED**. Whether any *other* operator credential is active — **UNVERIFIABLE-FROM-UI** (no candidate credential to test; per protocol I will not guess or brute-force). See §6 note re: historical (non-fresh) log entries, provided as context only. | `test-artifacts/login-response-redacted.json`, governance doc §0 |
| **CLM-089** — all 10 `/admin/*` routes gated server-side, 401 unauth / 403 non-admin, never client-side-only trust | all 6 screens | **CONFIRMED.** [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-17T15:36–15:51Z] 20/20 unauth calls → 401, 20/20 demoted calls → 403 across 10 endpoints × 2 passes; raw-HTML no-JS check confirms zero server-side data leak before any client guard runs. | §4 table, `test-artifacts/run1-api-transcript.txt`, `run2-api-transcript.txt`, `raw-html/*` |
| **CLM-044** — admin flows verified live via a temporary admin account; formal closure needs operator-rotated credential | admin-spend, admin-users, admin-settings, admin-audit-log | **PARTIALLY-TRUE.** "Formal closure blocked" half — **CONFIRMED** (operator credentials still absent, admin/admin123 still non-admin, live-reconfirmed). "Verified live via a temporary admin account" half describes prior testing this tester did not witness and has no credential to reproduce — **UNVERIFIABLE-FROM-UI**. | governance doc, `test-artifacts/login-response-redacted.json` |
| **CLM-088** — $0 spend cap blocks agent run before LLM dispatch (429, AgentRun count unchanged) | admin-spend | **UNVERIFIABLE-FROM-UI / HUMAN-GATED.** Requires setting a spend cap via `POST /admin/users/{id}/spend-cap`, which is admin-only and returned 403 for the only credential available to this tester. | §4 table row 4 |
| **CLM-100** — signup toggle exists; audit log entries cannot be edited or deleted | admin-settings, admin-audit-log | **PARTIALLY-TRUE.** Immutability half — **CONFIRMED** [VERIFIED-WITH-FRESH-EVIDENCE, live 405/404 on every mutate-shaped audit-log path, reproduced twice]. Signup-toggle functional-effect half (does it actually gate signup) requires admin access to flip it — **UNVERIFIABLE-FROM-UI / HUMAN-GATED**. | §4a table |
| **CLM-101** — admin panel provides a data export/delete capability for user data | admin-users, admin-settings | **UNSURE, leaning REFUTED.** Cannot rule out a dead UI button without the human-gated real admin UI, but **live-probed** (twice) and **source-reviewed** (full `admin.py`, full `main.py` router mounts): no export/delete-user backend endpoint exists anywhere (`GET .../export` → 404; `DELETE /admin/users/{id}` → 405). Any UI control for this would be non-functional even if present. Escalated as UNSURE rather than flat REFUTED because the actual rendered admin-panel UI could not be inspected. | `test-artifacts` audit/export probe files (both screens) |

---

## 8. UNSURE items requiring orchestrator escalation

1. **CLM-101 (data export/delete capability).** See verdict above — strong live+source evidence of absence at the API layer, but the actual admin-panel UI (which might show a now-dead button, or might genuinely have none) is HUMAN-GATED and could not be visually inspected. Recommend the orchestrator treat this as REFUTED-pending-operator-confirmation rather than close it outright from this evidence alone.
2. **MV-admin-settings-002 (422-before-401 body-parse ordering).** Confirmed live and reproducible, genuinely minor (no data disclosure) — flagging for orchestrator triage on whether this warrants a fix (stricter auth-first middleware ordering) or is accepted as standard framework behavior.

No other items were left genuinely ambiguous — every other check produced a clean, reproducible, unambiguous result.

---

## 9. NOT-TESTED (HUMAN-GATED only)

The following could **not** be tested in this session because no operator-admin credential exists in production (`AETHER_ADMIN_EMAIL` / `AETHER_ADMIN_PASSWORD_HASH` both absent — see governance doc). This is a hard credential gate, not a scoping choice:

- **admin-root:** the actual `/admin` overview page render (health-overview widget with live service/agent/cron data, the 4 nav link cards) as an authenticated operator-admin.
- **admin-health:** the `/admin/health` service/agent-success-rate/cron/provider status detail view, and any interactive element on it.
- **admin-users:** the `/admin/users` list (search `q`, `plan` filter, `suspended` filter, pagination via `limit`/`offset`), and the `/admin/users/[id]` detail page including the spend-cap input + save button and the suspend/unsuspend toggle button — all require a real admin session to render and click.
- **admin-settings:** the `/admin/settings` signup-enabled toggle and email-verification-enabled toggle, and their functional effect on actual signup behavior (CLM-100's second half).
- **admin-audit-log:** the `/admin/audit-log` table render, its pagination, and confirming that admin mutations performed by a real admin actually produce new rows with correct actor/action/target/detail/ip fields.
- **admin-spend:** the `/admin/spend` total + per-user USD spend table render, and CLM-088's full spend-cap-blocks-agent-run flow (set $0 cap as admin → run agent as that user → confirm 429 + AgentRun count unchanged).
- Any AI-agent integration testing (§3.2 point 5) scoped to the admin cluster: not applicable — `agents: []` in every admin-cluster BRIEF.json, confirmed by source inspection of `apps/web/src/app/admin/**` (no agent-invoking UI anywhere in the admin shell).

**Reason for all items above, uniformly:** HUMAN-GATED — no operator-admin credential is configured in production (verified live: `admin`/`admin123` → `isAdmin:false`; governance doc confirms both required env vars absent). Per the run brief, this is expected and out of this tester's authority to remediate (no credential creation, no service restarts, no self-authorization of admin access).

---

## 10. Screenshots index

All screenshots are full-page PNGs, Playwright `page.screenshot({fullPage:true})`, production URL.

| File | Screen | Phase |
|---|---|---|
| `test-artifacts/passA-unauth-admin-root-fullpage.png` / `passB-...` | admin-root | unauthenticated → `/login` |
| `test-artifacts/passA-authed-admin-root-fullpage.png` / `passB-...` | admin-root | demoted-authenticated → `/dashboard` |
| `screens/admin-health/test-artifacts/passA/B-unauth/authed-admin-health-fullpage.png` | admin-health | both phases |
| `screens/admin-users/test-artifacts/passA/B-unauth/authed-admin-users-fullpage.png` | admin-users | both phases |
| `screens/admin-users/test-artifacts/passB-unauth/authed-admin-users-detail-fullpage.png` | admin-users `[id]` | both phases (2nd pass, content identical to 1st per JSON) |
| `screens/admin-settings/test-artifacts/passA/B-unauth/authed-admin-settings-fullpage.png` | admin-settings | both phases |
| `screens/admin-settings/test-artifacts/throttled-reload-admin-settings.png` | admin-settings | throttled unauth reload |
| `screens/admin-audit-log/test-artifacts/passA/B-unauth/authed-admin-audit-log-fullpage.png` | admin-audit-log | both phases |
| `screens/admin-spend/test-artifacts/passA/B-unauth/authed-admin-spend-fullpage.png` | admin-spend | both phases |
| `test-artifacts/back-forward-final-state.png` | admin-root | back/forward edge case |

---

## 11. Sign-off

All checks in this report were executed against **production** (`https://5cb5f0620.abacusai.cloud`), never localhost, with no code changes, no service restarts, and no `git` writes. Every finding and claim verdict above was reproduced in a **fresh session a second time** before filing (§3.2 point 9) — no FLAKY items were encountered. No prohibited actions were taken (no self-closure, no fixture injection, no destructive admin mutations attempted against real data — the only mutation-shaped calls made were rejected with 401/403/404/405 before reaching any handler logic that would touch data).

**Tester:** screen-tester agent role, Claude Sonnet 5 (Claude Agent SDK), MANUAL-VERIFICATION Stage 1, admin cluster.
**Session:** 2026-07-17T15:36:55Z – 2026-07-17T15:51:13Z UTC.
