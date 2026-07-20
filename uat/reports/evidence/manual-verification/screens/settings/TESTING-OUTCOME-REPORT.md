# TESTING OUTCOME REPORT — Settings & Profile

**Screen id:** `settings`
**Screen name:** Settings & Profile
**Route:** `/dashboard/settings`
**Wireframe:** `design/screens/settings.html`
**Environment:** Production — `https://5cb5f0620.abacusai.cloud`
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Account under test:** `admin` / `admin123` (`admin@aether.local`) — TEMP Pro entitlement active for this MANUAL-VERIFICATION run
**Session window (UTC):** 2026-07-17T16:12:38Z → 2026-07-17T16:31:39Z (Pass 1, Pass 2, Pass 3, and a fresh-session VERIFY-TWICE pass)
**Tester:** screen-tester agent role, model claude-sonnet-5

---

## 1. Summary

The Settings screen's structural conformance to the wireframe is strong (all 7 sub-nav labels match exactly: Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance), and the Profile/Career-Data/Agent-Configuration forms are genuinely wired to the backend with correct validation, honest error handling, and confirmed persistence across reload (including a fresh, independent re-verification of the Phase-7 email-persistence regression, which is now fixed).

However, two of the screen's interactive affordances are **silent, fully non-functional decorations**, confirmed at both source-code and live-runtime level, in two independent sessions:

- The three **Notifications toggles** never change state under any click method (`MV-settings-001`, HIGH).
- The **Job Board "Sync"/"Sync All" buttons** fire zero network requests and never actually sync anything (`MV-settings-002`, HIGH).

Additionally, the screen's own backing-endpoint matrix includes 4 `/billing/*` endpoints, but 3 of them (`GET /billing/subscription`, `POST /billing/checkout`, `POST /billing/portal`) are never called by the page, and the one that is called (`GET /billing/entitlement`) has its real, live Pro-plan response silently discarded — there is no plan/quota/manage-subscription UI anywhere on Settings (`MV-settings-003`, HIGH; corroborates `MV-pricing-003`).

The **Privacy & Compliance** tab was found to be a genuine, honestly-written panel (not missing, not fake) that explicitly discloses: *"there is no self-service 'export all data' or 'delete all data' button yet; contact us to request a full data export or deletion and we will process it manually."* This confirms `data_export_control: absent` and corroborates `MV-privacy-policy-003` / `MV-terms-003` — the disclosure is honest, but no actual contact channel exists to act on it.

Zero uncaught console errors, zero page errors, and zero failed/unsurfaced requests were observed across the entire session (4 independent passes).

---

## 2. Element Inventory

| # | Element | Location/tab | Tested | Result |
|---|---|---|---|---|
| 1 | Full name input | Profile | ✅ | Text input, wired to `PUT /workspaces/settings.profile.fullName`, persists |
| 2 | Email input | Profile | ✅ | Wired, allowlist-validated (`aether.local` exact match only), persists — Phase-7 silent-discard bug re-verified FIXED |
| 3 | Target role input | Profile | ✅ | Wired, persists, accepts unicode/emoji/XSS-echo strings safely |
| 4 | Location input | Profile | ✅ | Wired, persists |
| 5 | "Change avatar" button | Profile (wireframe only) | ✅ | **Absent in production** — static initials circle only, no upload affordance (finding MV-settings-005) |
| 6 | "Save Changes" button | Global header | ✅ | Fires `PUT /workspaces/settings`, shows "Settings saved ✓", also fires on no-op saves without error |
| 7 | Sub-nav: Profile | Sub-nav | ✅ | Renders overview panel (Profile + Resume + Career Data + Agent Config + Integrations + Accounts) |
| 8 | Sub-nav: Resume Management | Sub-nav | ✅ | Renders Resume Management + Career Data panel |
| 9 | Sub-nav: Portfolio Sync | Sub-nav | ✅ | Renders same panel as #8, but heading still reads "Resume Management" (finding MV-settings-004) |
| 10 | Sub-nav: Notifications | Sub-nav | ✅ | Renders Notifications panel (all 3 toggles non-functional, finding MV-settings-001) |
| 11 | Sub-nav: Agent Configuration | Sub-nav | ✅ | Renders Agent Configuration panel (functional) |
| 12 | Sub-nav: Integrations | Sub-nav | ✅ | Renders Job Board Integrations (non-functional sync, MV-settings-002) + Connected Accounts (read-only, honest) |
| 13 | Sub-nav: Privacy & Compliance | Sub-nav | ✅ | Renders Profile fields + honest no-self-service-export/delete disclosure |
| 14 | "Upload new version" (resume) | Resume Management | ✅ | Opens native OS file chooser (real `<input type=file>`); actual upload submission NOT performed (see §9 Not Tested) |
| 15 | GitHub username input | Career Data | ✅ | Wired to `POST /workspaces/career-data/refresh`, validated (max 100 chars), persists, empty clears |
| 16 | Portfolio URL input | Career Data | ✅ | Wired, invalid URL handled with honest per-source error (no crash), persists |
| 17 | LinkedIn summary textarea | Career Data | ✅ | Wired, accepts XSS-echo payload safely (stored raw, never rendered via `dangerouslySetInnerHTML` anywhere in the frontend — confirmed by source grep), persists |
| 18 | "Sync now" (Career Data) | Career Data | ✅ | **Genuinely wired** — fires real `POST /workspaces/career-data/refresh`, live GitHub API + portfolio-scrape data returned (verified NOT a fixture — see §7) |
| 19 | Auto-apply toggle | Agent Configuration | ✅ | Functional — `aria-checked` flips correctly, persists across reload, restored |
| 20 | Approval gate toggle | Agent Configuration | ✅ | Functional — same as above |
| 21 | Match threshold slider (50–100%) | Agent Configuration | ✅ | Functional — value change persists across reload (tested 80%→55%→80% restore) |
| 22 | Approval requests toggle | Notifications | ✅ | **Non-functional** — `onChange={() => undefined}`, hardcoded `value={true}` (MV-settings-001) |
| 23 | Application updates toggle | Notifications | ✅ | **Non-functional** — same root cause (MV-settings-001) |
| 24 | Weekly digest toggle | Notifications | ✅ | **Non-functional** — same root cause (MV-settings-001) |
| 25 | "Sync All" button | Integrations | ✅ | **Non-functional** — client-only `setTimeout`, zero network calls (MV-settings-002) |
| 26 | Sync button ×5 (Greenhouse/Ashby/Lever/Remoteok/Remotive) | Integrations | ✅ | **Non-functional** — same root cause (MV-settings-002) |
| 27 | Connected Accounts list (OpenRouter/Abacus fallback/Google Gmail) | Integrations | ✅ | Read-only, honest — statuses cross-checked against real `.env` credential presence (OPENROUTER_API_KEY, ABACUS_API_KEY both genuinely set) |
| 28 | Unauthenticated access to `/dashboard/settings` | N/A | ✅ | Clean redirect to `/login` (both in main pass and fresh VERIFY-TWICE session) |
| 29 | Browser back/forward through the flow | N/A | ✅ | Works correctly, no stale-state artifacts |
| 30 | Throttled (slow-3G-equivalent) reload | N/A | ✅ | Loads successfully in ~0.5s even under emulated 500kbps/400ms-latency network, no errors |

---

## 3. Findings

| id | severity | category | summary |
|---|---|---|---|
| MV-settings-001 | HIGH | defect | Notifications toggles (all 3) are decorative no-ops; clicking never changes state; Save still reports success |
| MV-settings-002 | HIGH | defect | Job Board Integrations Sync/Sync All buttons are decorative `setTimeout` theater; zero backend calls ever fire |
| MV-settings-003 | HIGH | coverage-gap | 3 of 4 assigned `/billing/*` endpoints never called; Pro-plan/quota data fetched but never rendered; no manage-subscription UI (corroborates MV-pricing-003) |
| MV-settings-004 | LOW | visual | "Portfolio Sync" tab renders a panel mislabeled "Resume Management" |
| MV-settings-005 | LOW | visual | Several wireframe-vs-production content deviations (avatar upload absent, different job-board set, different connected-accounts set) |

Full JSON rows: `findings.json` (schema per §4.1).

---

## 4. Claim Verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-005** — dual-format Anthropic credential auto-detection (Console API key vs Claude Code OAuth token) via `PUT /agents/providers/anthropic/credential` / `PUT /agents/user/providers/anthropic/credential` | **UNVERIFIABLE-FROM-UI** (out of screen scope) | No such credential-entry control exists anywhere on `/dashboard/settings` (confirmed via full element inventory across all 7 tabs, and via source: the credential UI lives in `apps/web/src/components/agents/ProviderConfigModal.tsx`, rendered only from `apps/web/src/app/dashboard/agents/page.tsx`, a different screen). Deliberately did not exercise the write endpoint directly from this screen-tester role: `UserProviderCredential` DB inspection showed the endpoint is stateful/shared (one existing row for a different user, provider="anthropic"), and mutating it risks changing the *active* provider precedence relied upon by concurrent testers on the shared admin account. Recommend the `agents`/`agent-monitor` screen reports (which list this same claim) as the authoritative verdict. |
| **CLM-011** — interactive "Connect with Anthropic" OAuth-consent flow remains removed; only paste-token entry exists | **CONFIRMED** | `GET https://5cb5f0620.abacusai.cloud/api/agents/auth/anthropic/start` → HTTP 404 `{"detail":"Not Found"}`; `POST` to the same path → HTTP 404 `{"detail":"Not Found"}` (curl transcripts this session). No "Connect with Anthropic"/OAuth-consent button exists anywhere in the Settings element inventory (30 elements enumerated across 7 tabs, zero matches). |
| **CLM-012** — `AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS` (`aether.local`) is an exact-domain allowlist; `evil.local`/`sub.aether.local` rejected with 422 | **CONFIRMED** (verified twice, independent sessions) | `PUT /workspaces/settings` with `mv-settings-persisttest@aether.local` → 200, persisted (confirmed via subsequent GET). Same payload with `@evil.local` → 422 `"The part after the @-sign is a special-use or reserved name..."`. Same with `@sub.aether.local` → 422, identical message (exact-match logic, not suffix match). Fresh-session re-run (`VERIFY-TWICE-report.json`) reproduced `evil.local` → 422 and `aether.local` → 200+persisted identically. |
| **CLM-013** — `PUT /workspaces/settings` persists email changes (Phase-7 silent-discard bug fixed); confirmed via direct production-DB read | **CONFIRMED** | Changed email to `mv-settings-persisttest@aether.local` via `PUT /workspaces/settings` → 200; `GET /workspaces/settings` immediately after → email field shows the new value (not silently reverted). **Direct DB read** (`aether."User"` table, admin's row) after final restore shows `email = 'admin@aether.local'`, `updatedAt = 2026-07-17 16:18:46.567` matching the test window precisely. Source-level confirmation: `apps/api/app/routers/workspaces.py:874-893` — the `UPDATE "User" SET ... email = %s ...` statement includes `email` in its `SET` list (the Phase-7 bug was its prior omission). |
| **CLM-024** — 27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors/20 routes (GATE-16), 0 same-origin 5xx (GATE-17), 676 pytest, 297 vitest, Playwright E2E green | **PARTIALLY-TRUE** (scoped to this screen only) | For `/dashboard/settings` specifically: 0 console errors, 0 page errors, 0 failed requests, 0 same-origin 5xx across 4 independent test passes (consistent with GATE-16/17 for this one route). Did **not** re-run the full backend pytest (676) / frontend vitest (297) suites — that is outside a single-screen tester's scope and should be independently re-run by QA/orchestrator tooling. This screen's evidence corroborates but cannot alone confirm the full 27-gate claim. |
| **CLM-025** — reserved-TLD-but-non-allowlisted email (`sub.aether.local`) returns 422; allowlisted (`aether.local`) returns 200 and persists (GATE-09) | **CONFIRMED** | Identical evidence to CLM-012 above — `sub.aether.local` → 422, `aether.local` → 200 + persisted (verified twice). |
| **CLM-049** — all users backfilled to Free plan with a quota row (GATE-34) | **CONFIRMED** | Direct DB read: all 5 rows in `aether."User"` have exactly one `aether."Subscription"` row (4× `free`/`active`, 1× `pro`/`active` — the admin account's TEMP grant for this test run) and exactly one `aether."UsageQuota"` row each (0 users missing either). |
| **CLM-062** — Playwright sweep of 14 dashboard routes + /pricing + /admin as paid admin shows 0 console errors/failed requests/page errors (GATE-03) | **UNVERIFIABLE-FROM-UI** (scoped to this screen only) | Only `/dashboard/settings` was in this tester's scope; that one route showed 0 console errors / 0 failed requests / 0 page errors across all passes, consistent with but not a full reproduction of the 16-route claim. Defer to the per-route screen testers' own console/network sections for full coverage. |
| **CLM-068** — Stripe billing round-trip BLOCKED-ON-HUMAN pending operator Stripe keys/webhook secret/Price IDs/ABN-Tax enrollment | **CONFIRMED** | `POST /billing/checkout` (plan=starter, interval=month) → HTTP 400 `"This plan is not yet available for purchase (no Stripe price configured)"`. `POST /billing/portal` → HTTP 409 `"No billing account yet — subscribe first"` (even for this account's active TEMP-Pro entitlement, since it bypassed real Stripe checkout). Both are honest, clean degraded-state errors — no 500s, no fake success — confirming the block is real and correctly surfaced at the API layer (though, per MV-settings-003, never surfaced in any UI at all). |
| **CLM-094** — 4 tiers: Free $0 / Starter $19 / Pro $39 / Power $69 monthly; $179/359/649 annual; GST = round(total/11,2) | **CONFIRMED** | Live `GET /billing/plans`: Free monthly $0; Starter $19/$179 (gst $1.73/$16.27); Pro $39/$359 (gst $3.55/$32.64); Power $69/$649 (gst $6.27/$59.00). All 6 GST figures match `round(total/11, 2)` exactly (e.g. 39/11=3.545…→3.55 ✓; 649/11=59.0 exactly ✓). |

**Cross-reference note (not a duplicate finding):** Per the assignment brief, `MV-pricing-003` ("no subscription-management/downgrade/Stripe-portal UI exists anywhere") is **CORROBORATED** from the Settings screen — see `MV-settings-003` above, which documents this specifically from Settings' own endpoint-wiring perspective. `MV-privacy-policy-003` / `MV-terms-003` (no real data-export/delete-account contact channel) are also **CORROBORATED**: the Settings → Privacy & Compliance tab explicitly states *"there is no self-service 'export all data' or 'delete all data' button yet; contact us to request a full data export or deletion and we will process it manually"* — an honest disclosure, but with no actual email/form/link provided anywhere on the page or in the dashboard shell.

---

## 5. UNSURE Items

None. All ambiguous behaviors encountered (e.g., the "Portfolio Sync"/"Resume Management" tab overlap, the absent Anthropic row in Connected Accounts) were resolved with source-level or DB-level evidence rather than left as guesses — see findings/claims above for each.

---

## 6. Screenshot Index

All paths relative to `test-artifacts/`.

| File | Description |
|---|---|
| `00-unauth-access.png` | Unauthenticated `/dashboard/settings` → redirected to `/login` |
| `01-settings-load-fullpage.png` | Full-page authenticated load (primary visual-conformance reference) |
| `03-subnav-*.png` (7 files) | Each of the 7 sub-nav tabs clicked and captured |
| `04`–`10*.png` | Agent Configuration toggle/slider interaction + persistence-after-reload sequence |
| `11`–`14*.png` | Initial (imprecise-coordinate) Notifications toggle attempt — superseded by `20`–`27` below |
| `15-upload-resume-clicked.png` | Resume "Upload new version" — file chooser opened |
| `16-career-data-sync-now-clicked.png` | Career Data "Sync now" — real backend call confirmed |
| `17-jobboard-sync-clicked.png` | (mis-navigated frame, superseded by `28`-`30`) |
| `20`–`27*.png` | Precise `data-testid`-targeted Notifications-toggle and Agent-Configuration-toggle debugging — definitive non-functional-vs-functional proof |
| `28`–`30*.png` | Job Board Sync button before/during/after click — proves fake "Syncing…" animation with no backend effect |
| `31`–`34*.png` | Back/forward navigation and throttled-reload edge states |
| `VERIFY2-01/02/03*.png` | Fresh-session (VERIFY TWICE) reproduction of load, notification-toggle, and job-board-sync findings |

---

## 7. Network / Wiring Summary

Confirmed real, correctly-wired backend calls: `GET/PUT /workspaces/settings`, `GET/POST /workspaces/career-data(/refresh)`, `GET /billing/entitlement` (fetched but response unused — see MV-settings-003).

Confirmed **fake**/unwired affordances: Job Board "Sync"/"Sync All" (zero network calls — `jobboard-sync-evidence.json`), Notifications toggles (no backend field exists for them at all).

Career Data "Sync now" was verified to return **genuine, non-fixture** live data: the returned GitHub summary ("38 public repos, 20 total stars", repos `aether-job-career-agent`, `forgotten-mistory`, `abentertainment`, `3-tier-multi-agent-architecture`, `Error-Management-System`) does not match any string in `apps/api/tests/fixtures/github_fixture.py` (whose fixture data uses `"Sample User"`, repos named `aether-core`/`ml-pipelines`/`infra-templates`, `public_repos: 3`) — confirming this is a live GitHub API call, not fixture-fingerprinted filler.

`Connected Accounts & API Keys` statuses were cross-checked against the real production `.env`: `OPENROUTER_API_KEY` and `ABACUS_API_KEY` are both genuinely set (matching their "Connected" display); `ANTHROPIC_API_KEY`/`AETHER_LLM_API_KEY` are both genuinely unset, so the honest absence of an "Anthropic" row in this list is correct per its own (env-var-based, legacy) status logic — not a fabricated "connected" claim, and not itself a defect (a separate, DB-backed per-user credential vault exists for Anthropic but is a different, out-of-scope mechanism — see CLM-005 verdict).

---

## 8. Console / Server-Log Summary

Zero uncaught console errors, zero `pageerror` events, zero failed/unsurfaced requests, and zero same-origin 5xx responses across all 4 test passes (initial load/inventory, interaction pass, edge-state pass, and the fresh-session VERIFY-TWICE pass). Raw logs: `pass1-console.json`, `pass2-console.json`, `pass3-console.json` (all empty arrays), `pass1-pageerrors.json`/`pass2-pageerrors.json`/`pass3-pageerrors.json` (all empty), `pass1-failedrequests.json`/`pass3-failedreqs.json` (all empty).

All form-validation error responses (empty required fields, over-length strings, out-of-range numbers, malformed/non-allowlisted emails, invalid portfolio URLs) returned clean, descriptive 4xx JSON — never a raw stack trace or 500.

---

## 9. NOT-TESTED (HUMAN-GATED reasons only)

- **Actual resume-file upload submission.** The "Upload new version" button was confirmed to open a real native OS file chooser (correct wiring, real `<input type="file">`), but no file was actually submitted. The account's resume history already shows 43 versions with no visible delete/rollback control anywhere in the product; submitting a test file would very likely create a 44th, non-revertible version on the shared admin account. HUMAN-GATED: requires operator confirmation that a test resume upload (and its cleanup path, if any) is acceptable on the shared account before a tester submits one.
- **`PUT /agents/providers/anthropic/credential` / `PUT /agents/user/providers/anthropic/credential` write-path testing (CLM-005).** No UI control for this exists on `/dashboard/settings` at all (confirmed absent — see CLM-005 verdict). Exercising the write endpoints directly would mutate shared, stateful DB rows (`ProviderCredential`/`UserProviderCredential`) that determine the *active* LLM provider for the whole shared admin account, on which other concurrent MANUAL-VERIFICATION testers depend for their own agent-generation tests. HUMAN-GATED: this belongs to the `agents`/`agent-monitor` screen testers' scope, who can coordinate provider-state changes without cross-tester interference.
- **Full backend pytest (676) / frontend vitest (297) suite re-runs (part of CLM-024/CLM-062).** Outside a single-screen manual tester's tooling/scope; requires whole-repo CI execution, which is an orchestrator/QA-role responsibility.

---

## 10. Sign-off

Tested by: **screen-tester** agent role (model: `claude-sonnet-5`), MANUAL-VERIFICATION Stage 1, screen `settings`.
All findings reproduced at least twice (fresh, isolated browser sessions) before filing, per §3.2 point 9. No findings are FLAKY.
Report + `findings.json` + `test-artifacts/` written to `uat/reports/evidence/manual-verification/screens/settings/`.
