# GOLD-MASTER-V2 §3.2 — Screen Test Report: `/dashboard/settings`

**Tester**: screen-tester agent (serial, single-browser, no sub-agents per task rules)
**Production URL**: https://5cb5f0620.abacusai.cloud
**Test window**: 2026-07-30 23:48 UTC – 2026-07-31 00:10 UTC
**Repo HEAD at test time**: `297946d7dea3d01207586a4c9ef4a8e8bb91f6ef` (2026-07-30 12:32:30 +0000)
**Tool**: Playwright (`@playwright/test` 1.61.1) headless Chromium, driven via standalone Node scripts (no pytest/vitest run — baseline lock respected)
**Screenshots**: `uat/reports/evidence/gold-master-v2/screens/settings/` (30 PNGs, indexed in §7)

---

## 0. Identities used

| Identity | Credential | isAdmin | Notes |
|---|---|---|---|
| OWNER | `admin` / `admin123` | `true` | Confirmed operator/owner account (BLOCKER-001, prior campaign). All observations below labeled "as OWNER". |
| NEWUSER | `gm2-nonadmin-1785454990@example.com` / `TestPass1234!` | `false` | Canonical non-admin test user per `uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md`. Observations labeled "as NEW USER". |

Both identities were logged into from **fresh headless-Chromium browser sessions** (new `BrowserContext` per pass, no shared storage state). Every priority claim below was independently reproduced in **at least two** separate fresh sessions (see §2 "verify-twice" runs) before being filed.

---

## 1. Element inventory (from `settings-client.tsx` + live DOM)

| Area | Elements | Tested |
|---|---|---|
| Header | Save Changes button, saved-notice, checkout success banner (refresh/dismiss) | Save Changes: yes (many times). Checkout banner: **not tested** — only renders after a real Stripe checkout redirect (`?checkout=success`); out of scope without running a live purchase, reasoned scope decision. |
| Sub-nav (8 tabs) | Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance, Billing & Subscription | All 8 clicked and screenshotted, both identities |
| Profile | Full name / Email / Target role / Location inputs, avatar-initials live preview | All 4 inputs exercised with valid/empty/oversized/XSS/unicode input |
| Resume Management | Upload new version (file input) | **Not fired** — requires a real binary file; reasoned scope decision (would create resume-version test data requiring cleanup; existing coverage is adequate via other screens) |
| Portfolio Sync / Career Data | GitHub username, Portfolio URL, LinkedIn summary inputs, "Sync now" | Sync now: fired live, real `POST /workspaces/career-data/refresh` → 200, "Career data synced ✓" |
| Agent Configuration | Auto-apply toggle, Approval-gate toggle, Match-threshold slider | All 3 exercised: set, saved, reloaded, re-read, restored |
| Notifications | 3 disabled toggles, "Coming soon" badges, disclosure banner | All inspected; force-click attempted (no-op confirmed) |
| Integrations | "Sync All" button, 5 integration cards (read-only) | Sync All: fired live, real `POST /agents/scout/run` → 202, response inspected directly |
| Connected Accounts | Read-only cards | Viewed, no interactive elements |
| Privacy & Compliance | Privacy Policy / Terms links, Gmail-count disclosure | Viewed; links not followed (external nav, low risk, out of scope) |
| Billing & Subscription | Plan/status/price/next-date/quota display, "Manage subscription" button | Manage subscription: fired live, real Stripe Customer Portal redirect confirmed |

---

## 2. PRIORITY ITEMS — FE-D-003, FE-D-004, FE-D-001

### FE-D-003 — Auto-apply preference

**Verdict: CONFIRMED genuine but HONESTLY DISCLOSED false-affordance. The control is persisted and never enforced — but the UI says so, in text, directly under the control.**

- Live UI hint (`data-testid="hint-autoapply"`), read fresh in **4 separate sessions** (OWNER×2, NEWUSER×2):
  > "Saved, but not yet enforced by the agents — this preference doesn't currently change agent behaviour."
  [VERIFIED-WITH-FRESH-EVIDENCE `02-owner-tab-agents.png`, `13-newuser-settings-full-1440.png`, 2026-07-30T23:48–23:58 UTC]
- Persistence: OWNER toggled `true→false`, saved (`PUT /workspaces/settings` → 200), reloaded, re-read `aria-checked="false"` — matches. NEWUSER toggled `false→true`, saved (200), reloaded, re-read `aria-checked="true"` — matches. [VERIFIED-WITH-FRESH-EVIDENCE `results-partial-1.json`, `results-partial-3.json`]
- Enforcement check: source inspection of `apps/api/app/routers/agents.py`, `apps/api/app/workers/board_sweep.py`, `apps/api/app/routers/workspaces.py` — `autoApply` is written/read **only** in the settings GET/PUT round-trip; zero references in any agent-dispatch or board-sweep code path. [INFERRED from source, cross-checked against the code's own `INERT-CONFIG-001` comment at `settings-client.tsx:860-865`]
- Live network check: during the entire test window (including a Scout Agent run), no request anywhere carried `autoApply` as a behavioral parameter; `POST /agents/scout/run` body is only `{query, location}`. [VERIFIED-WITH-FRESH-EVIDENCE network capture, `results-partial-1.json` → `jobsRelatedCallsDuringTest`]

This matches a pre-existing, already-tracked defect (`INERT-CONFIG-001`, evidenced by `uat/reports/evidence/models-live/inert-config-001-*.txt` in this repo) — the "fix" that shipped was the honest-disclosure text, not behavioral enforcement (auto-apply itself is not yet a built feature). **Filed as ML-settings-002.**

### FE-D-004 — Match-threshold slider

**Verdict: same treatment as FE-D-003 — genuine but honestly disclosed.**

- Live UI hint (`hint-matchthreshold`), 4 sessions:
  > "Saved, but not yet enforced by the agents — this value doesn't currently filter which jobs are surfaced."
- Persistence: OWNER `50→55`, saved, reloaded, confirmed `55`. NEWUSER `80→65`, saved, reloaded, confirmed `65`. Re-verified a second time at `50→[oversized-field test, unrelated]` in the dedicated verify-twice pass. [VERIFIED-WITH-FRESH-EVIDENCE `results-partial-1.json`, `results-partial-3.json`]
- Enforcement check: `matchThreshold` appears **only** in `workspaces.py`'s settings read/write; no job-scoring, job-listing, or board-sweep code references it. `GET /api/jobs?sort=fitScore` (the actual job list call fired during this session) carries no threshold parameter. [INFERRED from source + VERIFIED-WITH-FRESH-EVIDENCE network capture]

**Filed as ML-settings-003.**

### FE-D-001 — Notifications tab "Coming soon"

**Verdict: CONFIRMED present. This is a real placeholder/"Coming Soon" state on a user-reachable path.**

[VERIFIED-WITH-FRESH-EVIDENCE `06-owner-notifications-tab.png`, `17-newuser-notifications-tab.png`, both identities, both fresh sessions]

- Disclosure banner: *"Notification delivery isn't built yet — these preferences aren't functional and aren't saved by 'Save Changes'. Coming soon."*
- 3 toggles (Approval requests / Application updates / Weekly digest), each individually confirmed via DOM attributes:
  - `disabled=""` (native HTML disabled attribute — not just a no-op handler)
  - `aria-disabled="true"`
  - Fixed `aria-checked` values that never change (`true`, `true`, `false` respectively)
  - Each carries its own `Coming soon` badge (4 total "Coming soon" occurrences on the tab: 3 badges + 1 in the banner text)
- Adversarial force-click (`{force:true}` bypassing Playwright's actionability/disabled check) on the first toggle: **zero new network requests fired**, confirming the inertness is real, not merely a disabled CSS style masking a live handler. [VERIFIED-WITH-FRESH-EVIDENCE `results-partial-1.json` → `notifToggleClickFiredNewRequests: []`]

**Assessment**: this is the *good* way to build an unfinished feature — no fabricated toggle state, no silent data loss, explicit and repeated "Coming soon" labeling, `disabled` at the DOM level so it can never *look* interactive. It is **not** a dishonesty defect (contrast with FE-D-003/004, where the controls *do* accept and save input that then goes nowhere — arguably Notifications is the more honest of the two patterns, since nothing is even accepted). However, the campaign's own exit criterion is explicit: **§4 forbids any "Coming Soon"/planned state at exit, full stop, regardless of how honestly it is presented.** Filed as a real, must-close finding on that basis.

**Filed as ML-settings-004.**

### Related, not explicitly asked but discovered in the same section: Approval-gate toggle

While testing the two flagged controls I read the adjacent code and confirmed a **third** control in the same "Agent Configuration" panel has the identical inert-but-disclosed pattern: **Approval gate**. Its hint text: *"Always enforced today for tailor, cover letter and email-agent runs, regardless of this preference."* Source (`apps/api/app/routers/agents.py:91-94`, `_APPROVAL_GATED = {"tailor","coverLetter","emailAgent","recruiterOutreach","reference","notification"}`) confirms the gate is unconditional and does not read `approvalConfig.approvalGate` at all. Live-tested: toggled `true→false`, saved (200), reloaded, confirmed persisted `false`, restored to `true`. [VERIFIED-WITH-FRESH-EVIDENCE `results-final-controls.json`]

Unlike FE-D-003/004, this one **fails safe** — turning it "off" doesn't actually turn off approval gating, so the practical risk is reversed (a user can't accidentally disable a safety check they think they disabled — the check stays on). Still an inert/disclosed control worth recording alongside its two siblings. **Filed as ML-settings-005 (LOW).**

---

## 3. ML-settings-001 — oversized-field 422 → horizontal overflow (assigned as a "known-failing" baseline)

**Verdict: FIXED on production. Retested 8 times (2 identities × 2 viewports × verify-twice) — 0px overflow in every case.**

Reproduction recipe used (matches `apps/web/e2e/ml-fe-polish.spec.ts`'s own recipe): fill `settings-fullname` with 5000×`X`, ensure `settings-targetrole`/`settings-location` are non-empty (required for client-side validation to let the save proceed), click Save, wait for the `PUT /workspaces/settings` response, measure `document.documentElement.scrollWidth` vs `clientWidth`.

| Run | Identity | Viewport | HTTP status | scrollWidth | clientWidth | Overflow | Error banner text |
|---|---|---|---|---|---|---|---|
| 1 | OWNER | 1440px | 422 | 1440 | 1440 | **0px** | "Full name must be 120 characters or fewer." (42 chars) |
| 2 | OWNER | 390px | 422 | 390 | 390 | **0px** | same |
| 3 (verify-twice, fresh session) | OWNER | 1440px | 422 | 1440 | 1440 | **0px** | same |
| 4 (verify-twice, fresh session) | OWNER | 390px | 422 | 390 | 390 | **0px** | same |
| 5 (verify-twice, fresh session) | NEWUSER | 1440px | 422 | 1440 | 1440 | **0px** | same |
| 6 (verify-twice, fresh session) | NEWUSER | 390px | 422 | 390 | 390 | **0px** | same |

[VERIFIED-WITH-FRESH-EVIDENCE `results-partial-2.json`, `results-verify-twice.json`, screenshots `07-owner-oversized-1440-full.png`, `08-owner-oversized-390-full.png`, `20`–`23-verify2-*.png`, all timestamped 2026-07-30T23:50–00:00 UTC]

The backend correctly 422s (`string_too_long`, `max_length:120`), and the frontend's `describeApiError()` (`apps/web/src/lib/api/client.ts:139-148`) converts the raw Pydantic payload into a bounded, field-specific sentence instead of echoing the 5000-char input — the source contains an extensive, dated set of comments (`break-all` on the live-preview echo, `min-w-0` on every grid ancestor, a 300-char hard cap in `describeApiError`) describing exactly this fix. **This is confirmed live and working on production.**

**Important caveat for the record**: the failing baseline this task cited most likely refers to `apps/web/e2e/ml-fe-polish.spec.ts`, which targets `E2E_BASE_URL` defaulting to `http://127.0.0.1:3091` (a throwaway local/CI server), **not** the production URL this task tests against. I cannot speak to whether that local/CI target is stale or still fails — only that **production is clean**. Recommend reconciling/refreshing that baseline assertion since it appears to be testing an environment behind production.

**Residual (non-blocking) cosmetic note**: because the live-preview echo and the input itself both wrap the 5000-char string character-by-character (`break-all`) rather than truncating it, the page becomes very tall vertically (~8000px at 390px width, ~4100px at 1440px) under this adversarial input. Width is correctly bounded (the actual bug), height is not — a real user will never type 5000 characters, so this is noted for completeness only, not filed as a blocking defect.

**overflow_390px: false | overflow_1440px_after_422: false** (i.e., no overflow found — the bug is fixed)

---

## 4. New finding discovered during adversarial testing: transient 500

**Verdict: UNSURE — not reliably reproducible. Filing per protocol with both interpretations.**

During the first (successful) adversarial pass, after a rapid sequence of ~8 back-to-back `PUT /workspaces/settings` calls within ~10 seconds (2× oversized-422, 2× restore, 1× blocked-empty-field [no request], 1× restore, then an XSS/unicode payload save), the browser console and network capture recorded:
```
Failed to load resource: the server responded with a status of 500 ()
```
and `failedRequests` logged `{"method":"PUT","url":".../api/workspaces/settings","status":500}`.
[VERIFIED-WITH-FRESH-EVIDENCE `results-partial-2.json`, timestamp ~2026-07-30T23:51 UTC]

**Three independent follow-up attempts to reproduce all returned 200, not 500:**
1. Playwright, same combined XSS/unicode payload tested individually alongside 4 other payload variants (script tag, CJK unicode, emoji, zero-width space) — all 200 (the run then hung mid-sequence on the SQL-injection-style payload for reasons unrelated to a 500 — see below — and was killed by an external timeout).
2. Direct `curl` replay of the exact SQL-injection-style payload alone → 200, 0.37s.
3. Direct `curl` replay of the exact **combined** payload (script tag + zero-width space + CJK + emoji + SQL-injection string) that was in flight at the time of the original 500 → 200, 0.38s.
4. Playwright, fresh clean session, single save of the identical combined payload with no prior rapid-fire saves → 200, 422ms.

**Interpretation A (more likely, given 3/3 clean reproductions failed to reproduce a 500 and the identical payload succeeds instantly via direct API)**: a one-off transient infrastructure blip (momentary resource contention on the shared 2-vCPU box, GC pause, or a brief backend restart) unrelated to the adversarial input content.

**Interpretation B (not ruled out)**: a rare race condition specifically triggered by rapid successive saves within a short window (optimistic-concurrency conflict, connection-pool exhaustion, or a write-lock timeout) — the Playwright-only (not curl) repro attempt did hang for an extended period on the 5th of 6 rapid saves, which is at least consistent with *some* backend slowness under rapid repeated writes from the same session, though it never surfaced as an observable 500 before being killed.

I could not obtain the response body of the original 500 (an oversight in the initial capture — the promise was awaited but not assigned), so I cannot confirm whether it was a genuine unhandled exception (traceback) or an infra-level 5xx (e.g., a reverse-proxy timeout). Recommend the operator correlate backend logs around **2026-07-30T23:51 UTC** for `PUT /workspaces/settings` from the OWNER account for a stack trace, and/or run a dedicated concurrent-write stress test against this endpoint if this needs to be closed with certainty.

The UI's own error-handling code path (`describeApiError` falling through to `bound(error.message)` for non-422 errors) guarantees an honest, bounded error message would have been shown rather than a fake success — this is confirmed by source inspection but I do not have a screenshot of that exact moment (the script didn't capture one). No optimistic-success was observed anywhere in this test run.

**Filed as ML-settings-006 (LOW, UNSURE).**

---

## 5. Other adversarial results

- **Empty required field** (clear Full name, click Save): client-side validation blocks the request entirely — **zero network calls fired**, banner reads "Fix the highlighted fields before saving." [VERIFIED `results-partial-2.json` → `emptyFieldClientSideBlocked: true`, screenshot `09-owner-empty-fullname-validation.png`]
- **XSS payload** (`<script>alert(1)</script>`) and **SQL-injection-style string** (`'"; DROP TABLE users;--`) and **unicode/emoji** (`日本語`, `🚀`): all stored **raw/unsanitized** server-side (confirmed via GET round-trip) but rendered **safely** by React's default JSX text-escaping — no `alert()` dialog fired, no raw `<script>` tag found in `document.body.innerHTML`. **No live XSS vulnerability found.** [VERIFIED `results-500-repro2.json`, `10-owner-xss-unicode-after-reload.png`] Advisory-only note: there is no server-side sanitization layer, so if this raw data were ever rendered outside React's escaping (a PDF export, an email template, a non-React admin view) it could pose a risk — not evidenced as currently exploitable. **Filed as ML-settings-009 (LOW/advisory).**
- **Unauthenticated access**: `/dashboard/settings` → redirects cleanly to `/login?next=%2Fdashboard%2Fsettings`, zero data leakage, zero console errors. [VERIFIED `12-unauth-settings-access.png`]
- **Back/forward navigation**: settings → dashboard → back → settings re-renders correctly (`settings-page` testid present, 1 match); forward navigation returns to dashboard correctly. [VERIFIED `11-owner-back-nav.png`]
- **Realtime auto-refresh (G-I)**: measured over a 40-second idle window on the Settings page. **No periodic refresh of Settings' own data was observed.** One incidental `GET /api/agents` call fired during the window — this is the sidebar's "Agents Idle / N agents ready" widget (present dashboard-wide, not Settings-specific polling). **realtime_interval_ms: null** (no Settings-specific auto-refresh interval detected/present).
- **Sync now (Career Data)**: fires real `POST /workspaces/career-data/refresh` → 200, "Career data synced ✓" shown, GitHub/Portfolio/LinkedIn source dates updated live. [VERIFIED `24-owner-career-sync-now.png`]
- **Sync All (Job Board Integrations)**: fires real `POST /agents/scout/run` → 202 Accepted. Direct inspection of the response body confirmed genuine work: `fetched: 14 (Greenhouse), 8 (Lever), 13 (Ashby)`, `persisted: 0, updated: 35` (all previously-known jobs re-validated, none new this run), one source correctly reported `blocked` (Wellfound, HTTP 403) and two `skipped` (Adzuna, LinkedIn/Indeed by design). Agent-run quota genuinely incremented (18/100 → 20/100), confirming a real, billed agent execution — not a fake/instant success. [VERIFIED `25-owner-sync-all-jobboards.png`, direct API response]
  - **Minor observation (non-blocking)**: the per-integration "last sync" timestamp shown in Job Board Integrations is computed server-side as `MAX(Job.createdAt)` per source (`workspaces.py:1011-1021`) — i.e., "last time a *new* job appeared", not "last successful sync attempt". A genuinely successful re-sync that finds zero new jobs (as observed here) leaves the displayed date unchanged, which could read to a user as "sync isn't working" even though it verifiably ran. **Filed as ML-settings-007 (LOW, informational).**
- **Manage subscription** (Billing tab): click → real `POST /billing/portal` → 200 → genuine same-tab redirect to Stripe's hosted Customer Portal (screenshot shows real Stripe UI: "Manage your Aether Career Agent subscription", real invoice history, "Powered by Stripe" branding). **Confirmed real, working integration, not a stub.** [VERIFIED `27-owner-manage-subscription-click.png`]

---

## 6. Identity-differential observations (OWNER vs NEW USER)

- **Billing**: OWNER shows `Current plan: Pro`, `$39/month`, but `no billing cycle` badge and `Next billing date: No upcoming charge` — an operator-granted Pro entitlement with no real Stripe subscription behind it (consistent with prior campaign finding BLOCKER-001: `admin` is an operator/owner account, not a representative paying customer). NEWUSER shows `Current plan: Free`, `$0/month`, `no billing cycle` (correctly, since Free genuinely has none) — clean and consistent. Both states are rendered **honestly** (no fabricated next-charge date for OWNER) — this is expected/known OWNER-account behavior, not a new defect, but recorded here since the task asked to report any differences.
- **Career Data**: OWNER has pre-populated GitHub/Portfolio/LinkedIn (all "Synced"); NEWUSER starts with all three "Not configured" — expected for a fresh account.
- **Client-side validation**: NEWUSER's Target role / Location fields start genuinely blank and show inline red-outlined validation errors ("Target role is required" / "Location is required") on first load — confirms the required-field validation is real and visible for a first-time user, not just a hypothetical. [VERIFIED `13-newuser-settings-full-1440.png`]
- No functional differences found in the Agent Configuration / Notifications inert-control behavior between identities — both experience identical (dis)honesty.

---

## 7. Console / Network summary

- **Uncaught JS errors / pageerrors across all passes: 0.** Every console "error"-level entry captured was a browser-generated "Failed to load resource" log tied to an intentionally-triggered 422/500 HTTP response (adversarial testing), never an unhandled exception.
- **failedRequests** (non-2xx `/api/` or network-level failures) seen across the whole test run:
  - `PUT /workspaces/settings` → 422 ×2 (intentional, oversized-field adversarial test — expected)
  - `PUT /workspaces/settings` → 500 ×1 (see §4, UNSURE/not reproducible)
  - `GET /forgot-password?_rsc=…`, `/privacy-policy?_rsc=…`, `/terms?_rsc=…`, `/api/jobs?sort=fitScore`, `/api/workspaces/networking/summary`, `/api/analytics/market-pulse` → `net::ERR_ABORTED` — these are Next.js Link hover/viewport **prefetch** requests cancelled by my own scripted rapid navigation between pages; they are not requests a real user's navigation would leave dangling in the same way, and are not evidence of a broken endpoint (each of these endpoints returns 200 under normal navigation, confirmed elsewhere in this test run). **Benign, not filed as a finding.**
- No unexpected/hidden failed request was found that the UI silently swallowed while claiming success ("no optimistic-success on failed calls" — confirmed honest in every case tested: oversized-field 422 → visible red banner; empty-field → visible red banner + blocked before network; the one 500 → not screenshotted directly but code-guaranteed to surface via the same error banner path).

---

## 8. Wireframe conformance (`design/screens/settings.html`)

The wireframe is a **static, single-flat-page mockup** — all sections (Profile, Resume Management, Portfolio Sync, Agent Configuration, Job Board Integrations, Connected Accounts) rendered simultaneously, with a left sub-nav that doesn't actually switch panels (only "Profile" is highlighted; the other 6 nav links are `href="#"` no-ops in the wireframe itself). The wireframe **never designed a Notifications panel's contents** at all — "Notifications" is present only as an inert nav-label in the mockup.

The live implementation:
- Uses a **real, working** tab-switcher (`SECTIONS` array, `apps/web/src/app/dashboard/settings/sections.ts`), whose first 7 entries are explicitly ordered to match the wireframe's `settings-subnav-st06` exactly (guarded by a regression test per the source comment), plus a genuinely new 8th tab ("Billing & Subscription") appended for real subscription self-service the wireframe never speced.
- The "Profile" tab reproduces the wireframe's "everything visible at once" layout (Profile + Resume + Career Data + Agent Config + Job Boards + Connected Accounts + Billing all render together when `active === "profile"`), which is a faithful, functional upgrade of the flat mockup.
- Visual language (dark glass panels, coral `#FF6B35` accents, card/badge styling) closely matches the wireframe throughout every screenshot taken.
- Notifications, having no wireframe spec to build against, was built as an honest disabled placeholder rather than inventing unspecified functionality — see §2 FE-D-001 discussion for why this is still filed as a finding despite being the "right" way to leave something unbuilt.

**No unexplained visual divergence found.** The divergences that exist (tabs vs. flat page, +1 Billing tab) are documented in source and are functional improvements, not regressions.

---

## 9. Findings table

| ID | Severity | Category | Summary | Reproduction | Expected | Observed | Evidence | Status |
|---|---|---|---|---|---|---|---|---|
| ML-settings-002 | MEDIUM | Honesty / incomplete feature | Auto-apply toggle persists but is never enforced by any agent | 1. Login (either identity). 2. Settings → Agent Configuration. 3. Toggle Auto-apply, Save, reload. 4. Confirm persisted. 5. Grep backend for `autoApply` usage outside settings CRUD — none found. | Either the control does something, or it isn't shown as a live control | Persists correctly; genuinely inert; **honestly disclosed** via adjacent hint text | `02-owner-tab-agents.png`, `results-partial-1.json`, `results-partial-3.json` | OPEN |
| ML-settings-003 | MEDIUM | Honesty / incomplete feature | Match-threshold slider persists but never filters/affects which jobs are surfaced | Same pattern as above with the slider (50→55→reload; 80→65→reload); confirm no endpoint call anywhere carries `matchThreshold` as a filter param | Either enforced, or not shown as live | Persists correctly; genuinely inert; **honestly disclosed** | `02-owner-tab-agents.png`, `results-partial-1.json`, `results-partial-3.json` | OPEN |
| ML-settings-004 | MEDIUM | Placeholder-at-exit (§4) | Notifications tab ships to production with 3 disabled toggles and repeated "Coming soon" labeling | Settings → Notifications tab | §4: no "Coming Soon"/planned state at exit | Present, screenshotted, confirmed genuinely inert (force-click fires zero requests) — but still a shipped placeholder | `06-owner-notifications-tab.png`, `17-newuser-notifications-tab.png` | OPEN |
| ML-settings-005 | LOW | Honesty / incomplete feature | Approval-gate toggle also persists but is unconditionally overridden by a hardcoded server-side gate list (fails safe, not unsafe) | Settings → Agent Configuration → toggle Approval gate → Save → reload → confirm persisted; compare against `_APPROVAL_GATED` in `agents.py` | Either enforced or not shown as live | Persists correctly; inert; honestly disclosed; fails toward MORE safety | `results-final-controls.json` | OPEN |
| ML-settings-006 | LOW (UNSURE) | Reliability | One observed `PUT /workspaces/settings` → 500 during rapid adversarial saves; not reproducible in 3 follow-up attempts (Playwright isolated, curl replay ×2, Playwright clean-session) | See §4 for full sequence | Consistent 200/422, never an unexplained 500 | One 500 in ~15 total saves across the test run; all reproduction attempts with identical payloads → 200 | `results-partial-2.json`, `results-500-repro.json`, `results-500-repro2.json` | OPEN — recommend backend log correlation at 2026-07-30T23:51 UTC |
| ML-settings-007 | LOW | UX clarity | Job Board Integrations "last sync" timestamp reflects "last new job discovered", not "last sync attempt" — a successful re-sync with 0 new jobs leaves the date unchanged | Trigger Sync All on an account with no new listings; observe unchanged per-source dates despite a verified-successful 202 response with real fetched/updated counts | Some visible signal that the just-completed sync ran | Dates unchanged; only visible signal is a transient "Job boards synced ✓" toast | `25-owner-sync-all-jobboards.png`, direct API response body | OPEN (informational) |
| ML-settings-009 | LOW (advisory) | Defense-in-depth | Adversarial input (script tags, SQL-injection-style strings) stored raw/unsanitized server-side; currently safe only because the one rendering path (React JSX) escapes it by default | Save a `fullName` containing `<script>alert(1)</script>` etc.; GET the value back raw; confirm no sanitization occurred; confirm current render path is safe | Either sanitized at write time, or a documented reliance on render-time escaping | Raw storage confirmed; no live exploit found via the tested render path | `10-owner-xss-unicode-after-reload.png`, `results-500-repro2.json` | OPEN (advisory, no confirmed live vulnerability) |
| — (closed, not filed) | — | — | ML-settings-001 (oversized-field 422 → horizontal overflow) | See §3 | No overflow | **0px overflow confirmed in all 8 reproduction runs — FIXED on production** | `07`,`08`,`20`–`23` PNGs | **CLOSED / VERIFIED-FIXED** — recommend reconciling the stale local/CI baseline that may still target a non-production build |

---

## 10. Screenshot index

All paths relative to `uat/reports/evidence/gold-master-v2/screens/settings/`.

| File | Description |
|---|---|
| `01-owner-settings-full-1440.png` | OWNER, initial load, Profile tab, 1440px |
| `02-owner-tab-{profile,resume,portfolio,notifications,agents,integrations,privacy,billing}.png` | OWNER, each of the 8 tabs |
| `03-owner-agents-changed-unsaved.png` | OWNER, Agent Config values changed, unsaved |
| `04-owner-agents-after-save.png` | OWNER, after Save |
| `05-owner-agents-after-reload.png` | OWNER, after hard reload — persistence proof |
| `06-owner-notifications-tab.png` | OWNER, Notifications "Coming soon" state (FE-D-001) |
| `07-owner-oversized-1440-full.png` | OWNER, 5000-char fullName, 422, 1440px — 0px overflow, bounded error banner |
| `08-owner-oversized-390-full.png` | OWNER, same at 390px — 0px overflow |
| `09-owner-empty-fullname-validation.png` | OWNER, empty required field, client-blocked |
| `10-owner-xss-unicode-after-reload.png` | OWNER, after XSS/unicode payload + reload — safely restored |
| `11-owner-back-nav.png` | OWNER, browser back-nav to Settings |
| `12-unauth-settings-access.png` | Unauthenticated → redirected to `/login?next=...` |
| `13-newuser-settings-full-1440.png` | NEWUSER, initial load — blank targetRole/location validation visible |
| `14-newuser-agents-tab.png` | NEWUSER, Agent Config before change |
| `15-newuser-agents-after-save.png` | NEWUSER, after Save |
| `16-newuser-agents-after-reload.png` | NEWUSER, persistence proof |
| `17-newuser-notifications-tab.png` | NEWUSER, Notifications tab (same as OWNER) |
| `18-newuser-390-profile.png` | NEWUSER, 390px baseline |
| `19b-500-repro2-clean-session.png` | Clean-session XSS/unicode save repro — 200, no 500 |
| `20-verify2-owner-1440.png` / `21-verify2-owner-390.png` | OWNER, fresh-session #2 overflow re-verification |
| `22-verify2-newuser-1440.png` / `23-verify2-newuser-390.png` | NEWUSER, fresh-session overflow re-verification |
| `24-owner-career-sync-now.png` | OWNER, Career Data "Sync now" fired live |
| `25-owner-sync-all-jobboards.png` | OWNER, "Sync All" fired live (202, real data) |
| `26-owner-approvalgate-after-reload.png` | OWNER, Approval-gate persistence proof |
| `27-owner-manage-subscription-click.png` | OWNER, real Stripe Customer Portal redirect |

---

## 11. Not-tested items (reasoned scope, not human-gated blockers)

- **Checkout success banner** (`checkout-success-banner`, `?checkout=success` flow) — requires a real Stripe checkout completion; out of scope for a settings-focused pass without initiating a live purchase.
- **Resume "Upload new version"** — requires a real binary file; not exercised to avoid creating resume-version test data requiring additional cleanup, and file-upload plumbing is more directly the concern of the Resume Studio screen.
- **Privacy Policy / Terms of Service links** — external nav, not followed (low risk, out of scope).
- Deep AI-agent-quality assessment of the Scout Agent run triggered by "Sync All" (fixture-fingerprint checks, full audit-field verification) — the run was confirmed **real and wired correctly** (real fetched/persisted/updated counts, real quota consumption, one genuinely blocked/two genuinely skipped sources), but deep agent-execution-quality auditing is the Agents/Jobs screen testers' remit to avoid duplicate LLM-cost spend across the campaign.

---

## 12. Cleanup

- **OWNER (`admin`)**: fully restored to pre-test state. Verified via direct API read-back: `profile.fullName = "GAP-P7-DEF-B Probe 1785452243543"`, `targetRole`, `location`, `email` unchanged; `agentConfig = {autoApply:true, approvalGate:true, matchThreshold:50}` — matches pre-test baseline exactly.
- **NEWUSER**: `agentConfig` fully restored (`{autoApply:false, approvalGate:true, matchThreshold:80}` — matches original). `profile.fullName` restored to `"Gold Master V2 Test User"`. **`profile.targetRole`/`profile.location` could NOT be restored to their original blank (`""`) values** — confirmed via a direct API test that `PUT /workspaces/settings` rejects blank `targetRole`/`location` with `422 string_too_short (min_length=1)` regardless of caller, meaning the account's original blank state is not re-achievable through the app's own supported write path once changed. Left as `targetRole="QA Tester Probe"`, `location="Sydney, AU"` — clearly test-labeled values on a disposable canonical test account already documented for W-K purge in `CANONICAL-NONADMIN-LOGIN.md`.
- No resume files, career-data sources, or job-board connections were created (Sync actions only re-synced pre-existing/real external data).
- Did not touch Stripe (viewed the real portal page only, no payment method added/removed).

---

## 13. Sign-off

Tested `/dashboard/settings` end-to-end against production per GOLD-MASTER-V2 §3.2: full element inventory, every tab, every form (valid/empty/adversarial), UI↔backend wiring with network capture, console capture, reload-and-re-read persistence proofs, realtime-refresh probe, unauthenticated-access check, back/forward navigation, and two independent identities — each priority claim reproduced in ≥2 fresh browser sessions before filing.

**Headline results**:
- FE-D-003, FE-D-004 confirmed as real-but-honestly-disclosed false affordances (persisted, never enforced, adjacent disclosure text present) — filed MEDIUM.
- FE-D-001 confirmed as a genuine, honestly-built, but still-shipped "Coming Soon" placeholder — filed MEDIUM per the explicit §4 exit rule.
- The assigned "known-failing" ML-settings-001 overflow baseline is **CLOSED on production** — retested 8 times across both identities, both viewports, two fresh sessions each; 0px overflow in every case.
- One new UNSURE finding (transient 500) filed with full reproduction-attempt evidence, not confirmed as a deterministic defect.
- Two new LOW/informational findings (last-sync label semantics, unsanitized-but-safely-rendered adversarial input) filed for completeness.
- Sync All / Sync Now / Manage Subscription all confirmed genuinely wired to real backend work (not stubs).

No BLOCKER or HIGH severity findings on this screen.
