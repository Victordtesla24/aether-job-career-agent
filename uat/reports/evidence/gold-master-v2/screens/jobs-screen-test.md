# GOLD-MASTER-V2 §3.2 — Screen Test Report: `/dashboard/jobs` (Job Discovery)

**Tester**: screen-tester agent (serial, single headless Chromium instance, Playwright/Python)
**Production target**: https://5cb5f0620.abacusai.cloud
**Test window**: 2026-07-30T23:47Z – 2026-07-31T00:08Z
**Identities used**: `admin`/`admin123` (OWNER/operator, isAdmin:true, real data — labelled **as OWNER/ADMIN**) and
`gm2-nonadmin-1785454990@example.com` (isAdmin:false, disposable, labelled **as NEW USER**) per
`uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md`.
Evidence dir: `uat/reports/evidence/gold-master-v2/screens/jobs/` (22 screenshots + 10 JSON evidence dumps, indexed below).

All claims below are tagged **[VERIFIED]** (fresh screenshot/network/console capture this run, timestamped) or
**[INFERRED]** (read from source, not exercised live). Every headline finding was reproduced in **two independent,
freshly-launched browser sessions** (see "Verify-twice" §).

---

## 1. Element inventory (live DOM, OWNER session)

| Element | data-testid / selector | Present |
|---|---|---|
| Header stats line | `jobs-stats` | ✅ dynamic: "20 matches across markets · 0 new today · 3 sources connected" |
| Sync Now button | `run-discovery-btn` | ✅ |
| Market tabs (AU/Intl/Saved) | `market-tab-au/intl/saved` | ✅ live counts 6/14/0 |
| Source integration bar | `source-bar` | ✅ 3 cards (Greenhouse 14, ashby 4, RemoteOK 2) — real per-source counts |
| Per-source sync-status chips | `source-status-chip` (×10) | ✅ adzuna/ashby/Greenhouse/Indeed AU/Lever/LinkedIn AU/RemoteOK/Remotive/wellfound/workable |
| Role filter (text) | `job-role-filter` | ✅ |
| Source filter (select) | `job-source-filter` | ✅ 8 options, 3 disabled |
| Location filter (text) | `job-location-filter` | ✅ |
| Salary filter (select) | `job-salary-filter` | ✅ 4 bands |
| Remote·Hybrid toggle | `remote-toggle` | ✅ |
| Sort select | (aria-label="Sort jobs") | ✅ fitScore / newest |
| Match-min slider | `match-min-slider` | ✅ 0–100 step 5 |
| Clear all | `clear-filters` | ✅ |
| Select-all checkbox | `select-all` | ✅ |
| Bulk "Apply (N)" | `bulk-apply` | ✅ disabled when 0 selected |
| Bulk "Skip" (deselect) | `bulk-skip` | ✅ |
| Job cards | `job-card` (×6 AU / ×14 Intl) | ✅ **no per-card Apply button** — see §5 |
| Per-card checkbox | `job-select` | ✅ |
| Per-card source link | `job-source-link` | ✅ real external URL, `target=_blank` |
| Detail panel | `job-detail-panel` | ✅ |
| Detail save/bookmark | `detail-save` | ✅ |
| Detail source link | `detail-source-link` | ✅ |
| CRM link | `crm-link` → `/dashboard/networking` | ✅ |
| AI Match Analysis | `match-analysis` | ✅ real per-job narrative |
| 10-Dim Fit Score + radar | `fit-score`, `fit-dimension` (×10) | ✅ |
| Risk Signals | `risk-signals`, `risk-flag` | ✅ real per-job flags |
| Role description | `role-description` | ✅ |
| Apply flow (idle/tailoring/tailored) | `apply-flow`, `tailor-resume`, `preview-link`, `view-posting-link`, `skip-job`, `tailoring-progress`, `apply-step2`, `review-apply`, `retailor` | ✅ all present, state-dependent |
| Submit gate modal | `submit-gate`, `submit-cancel`, `submit-confirm`, `gate-posting-link`, `submitted-state` | ✅ |
| Bulk-apply gate modal | `bulk-apply-gate`, `bulk-apply-cancel`, `bulk-apply-confirm`, `bulk-apply-gate-list`, `bulk-submitted-state` | ✅ |
| Saved view | `saved-view`, `saved-card`, `unsave`, `saved-apply-all`, `saved-jobs-empty-state` | ✅ |

---

## 2. Visual conformance vs `design/screens/job-discovery.html`

Screenshots: `02-admin-jobs-initial.png` (browse), `09-admin-saved-tab.png` (saved), `10-admin-submit-gate-open.png`,
`12-admin-bulk-apply-gate.png`.

No BLOCKER/HIGH visual divergence found. Structural layout (sidebar nav, market tabs, source bar, filter row,
560px-ish job list + wide detail panel, two-step apply flow, submit gate) matches the wireframe faithfully. All
observed departures are deliberate and, on inspection, **more honest than the mock**, not regressions:

1. **Global search** lives in the persistent dashboard topbar (shared across all screens) rather than embedded in
   the Jobs page header as the wireframe drew it — an architectural consolidation, not a missing feature.
2. **Source integration bar** shows only adapters with real discovered jobs (Greenhouse/ashby/RemoteOK in this
   data snapshot) instead of the wireframe's fixed Seek/LinkedIn/Workforce-AU/Jora/Indeed card set with
   "Connect via Browser"/"Connect via MyGov" buttons. The wireframe's fictional per-user OAuth-connect flow was
   never built; production instead runs a server-side Scout agent against real adapters (Greenhouse, Lever,
   Remotive, RemoteOK, ashby, adzuna, indeed, linkedin, wellfound, workable — Seek intentionally excluded per the
   binding risk-officer ruling). A separate **Sync Status** panel (`source-status-panel`) shows honest per-adapter
   ok/skipped/unavailable state instead. This is correct, not a defect (see task brief).
3. Live filter row adds a **Sort** dropdown (fit score / newest) not in the wireframe — additive.
4. Bulk action is labelled **"Apply (N)"**, not the wireframe's "Tailor & Apply (N)" — and the bulk-confirm modal
   explicitly says bulk submission uses the "current, untailored resume" and "does not run per-job tailoring."
   This is a more honest label than the wireframe implied (no promise of bulk AI tailoring that doesn't happen).
5. **Bulk-apply confirmation gate** (`bulk-apply-gate`) does not exist in the wireframe at all — clicking the
   mock's bulk button had no defined behaviour. Production adds a proper irreversible-action confirmation dialog.
   Positive addition.
6. Risk Signals / AI Match narrative / skill tags are **live per-job computed values** (e.g. "17 key skills not
   matched", "Low keyword coverage (42%)", "Domain overlap only 17%") rather than the wireframe's fixed
   illustrative text ("High applicant volume (500+)", "Role reposted 3 times") — confirms real backend
   computation, not fixture/placeholder content.
7. Submit-gate copy is more precise than the mock: live text reads "Complete the submission on Greenhouse — open
   the job posting" (honestly disclosing the app does **not** auto-submit to the real employer), vs. the
   wireframe's more ambiguous "will be submitted via Seek.com.au."
8. Saved-view empty-state copy is **byte-identical** to the wireframe ("No saved jobs yet" / "Tap the bookmark on
   any role to save it here and revisit it later.").

**[VERIFIED]** `21-verify2-admin-jobs.png`, `02-admin-jobs-initial.png`, `09-admin-saved-tab.png`.

---

## 3. Interactive-element / form testing (OWNER)

All results from `03-phase3-results.json`, `04-phase4-results.json`, screenshots `03`–`14`.

| Test | Input | Result |
|---|---|---|
| Role filter — XSS payload | `<script>alert(1)</script>` | **[VERIFIED]** Rendered as inert text in the input (React-escaped); list correctly shows `jobs-empty-state` ("No matching jobs / No roles match the current market and filters — try Clear all."). No execution, no raw error. `03-admin-role-filter-xss.png`. |
| Role filter — very long string | 2000× "A" | **[VERIFIED]** Accepted verbatim (`input_value()` returns full 2000 chars), no crash, no overflow break. |
| Role filter — unicode/emoji | `héllo wörld 日本語 🚀` | **[VERIFIED]** Round-trips exactly. |
| Location filter — SQLi-shaped string | `'; DROP TABLE jobs; --` | **[VERIFIED]** Stored/rendered as plain text; no error, no data loss (jobs list unaffected on clearing filter). |
| Salary filter | `$200k+` | **[VERIFIED]** 0/6 AU cards match (all real AU jobs are below $200k cap) → honest empty state, no crash. `04-admin-salary-200k-filter.png`. |
| Remote·Hybrid toggle | on/off | **[VERIFIED]** `aria-pressed` flips true/false; card count narrows to 2/6 when on. `05-admin-remote-filter.png`. |
| Match-min slider | 0 → 80% | **[VERIFIED]** Label updates live ("80%"); 0/6 cards match (max real score is 44) → honest empty state. `06-admin-match80-filter.png`. |
| Sort select | fitScore → newest → fitScore | **[VERIFIED]** Re-orders card list, no error. `07-admin-sort-newest.png`. |
| Clear all | — | **[VERIFIED]** Resets all filters to defaults. |
| Source filter — select disabled "Seek (unavailable)" | — | **[VERIFIED]** Playwright cannot select a disabled `<option>` (times out) — confirms the option is genuinely non-selectable in the DOM, not just visually greyed. |
| Source filter — Greenhouse | valid selection | **[VERIFIED]** Narrows to 5 AU cards. |
| Market tabs — International | click | **[VERIFIED]** 14 cards shown, matches tab badge. `08-admin-intl-tab.png`. |
| Market tabs — Saved | click | **[VERIFIED]** 0 saved cards + `saved-jobs-empty-state` shown, matches badge "0". `09-admin-saved-tab.png`. |

**Adversarial input verdict**: honest handling throughout — no raw stack trace, no silent swallow, every
adversarial input either renders inertly (text fields) or produces a correct, worded empty state (filters).

---

## 4. Apply flow (gate G-H)

### 4a. Per-card Apply button — **NOT present** (verified twice, matches wireframe)

**[VERIFIED]** (`04-phase4-results.json` + re-run `09-phase9-verify-results.json`, two independent browser
sessions): `page.eval_on_selector_all("[data-testid='job-card'] button", …)` returns, for every one of the 6 AU
cards, a single button whose text is the job title itself (the card's own keyboard-accessible selection control) —
**no "Apply" text appears on any card button in either run.** Apply is exposed exclusively via:
- the **detail panel**'s two-step flow (Tailor Resume → Review & Apply) for the currently-selected job, and
- the **bulk "Apply (N)"** button in the list header, gated by an explicit checkbox selection + confirmation modal.

This matches `design/screens/job-discovery.html` exactly — the wireframe never draws a per-card Apply button
either (jd12–jd15 cards have no Apply CTA; apply lives in the detail pane jd32–jd39, and bulk in jd10). So
`per_card_apply_button_present = false` is the **correct, wireframe-conformant** answer, not a regression.

### 4b. Submit-confirmation gate — content, Cancel path

**[VERIFIED]** `10-admin-submit-gate-open.png`. Clicking `review-apply` (job already at "tailored" step — this
job's `tailoredResumeId` was set by a prior agent run, confirmed by "✓ Resume already tailored for this role")
opens `submit-gate` with real, job-specific content:
> "Submit application to **Twilio**? Your application for **Staff Impartner Product Owner, PRM** will be recorded
> as **Applied** with your tailored resume attached. Complete the submission on **Greenhouse** — open the job
> posting ↗." + summary block (Role / Company / Match score **44**).

Clicking **Cancel**: network capture over the click shows **zero** `POST …/apply` requests fired
(`apply_post_fired_on_cancel: false`); the modal closes; job list/state unchanged. `11-admin-after-cancel.png`.
**Confirmed correctly does NOT apply.**

### 4c. Bulk-apply confirmation gate — content, Cancel path

**[VERIFIED]** `12-admin-bulk-apply-gate.png`. Select-all (6/6) → "Apply (6)" opens `bulk-apply-gate`:
> "Submit 6 applications without tailoring? These jobs will be recorded as Applied using your current, untailored
> resume — bulk submission does not run per-job tailoring. This action cannot be undone."
with a per-job list (title + company) matching the selected set exactly. Cancel: **zero** `POST …/apply` requests
fired (`bulk_apply_post_fired_on_cancel: false`), modal closes, selection cleared via subsequent "Skip".

### 4d. Confirm (real POST) — **deliberately not executed against OWNER data; scope note, not a gap**

The OWNER account (`admin`) holds real, irreplaceable production job-search history (51 jobs sourced, 47 real
applications). `POST /jobs/{id}/apply` does **not** call any external employer API (confirmed by reading
`apps/api` and by the gate's own honest copy — it only creates an internal `Application` row and flips the job to
`applied`; the user must still separately complete the submission on the source board). So this action would not
"transmit to a real third party" — but it **would** permanently add a live "Applied" record to the real product
owner's actual job-search tracker for a role (44% match, "17 key skills not matched") they may not want tracked as
applied, and there is no DELETE endpoint on `applications.py` to reverse it cleanly. Given the instruction to clean
up or precisely document any test data left behind, and no low-risk cleanup path existing for this screen's scope,
**I did not click Confirm on the OWNER account.** The disposable NEW-USER account (created for exactly this kind
of destructive test) is unconditionally paywalled out of this entire screen (§6), so it could not be substituted.
This is filed as a scope decision, not a guess — see Not-Tested §9.
What **was** verified live: honest 404 for a bad job id on both `/insights` and `/apply` (§6), the gate's exact
POST target/body shape (read from source, `POST /jobs/{id}/apply` with `Bearer` auth), and that Cancel never
fires it.

### 4e. Save / bookmark toggle — persistence

**[VERIFIED]** `04-phase4-results.json`. Initial `aria-pressed=false` → click → `POST /jobs/{id}/save` fires,
returns **200** (`04-phase4-console.json`, two occurrences logged) → `aria-pressed=true` → **page reload** →
`aria-pressed` still `true` (server-persisted, not optimistic-only). Clicked again to restore → reload →
`aria-pressed=false`, confirming full round-trip and **restoring the account to its original state (no residual
test data left)**. `13-admin-after-save-toggle.png`, `14-admin-after-reload-save-check.png`.

### 4f. "View on [source]" link

**[VERIFIED]** Present at three levels: card (`job-source-link`), detail panel (`detail-source-link`), and inside
the submit gate itself (`gate-posting-link`). All point to a real external URL:
`https://job-boards.greenhouse.io/twilio/jobs/8088442`, `target="_blank" rel="noopener noreferrer"`. Not a
placeholder/fixture URL.

---

## 5. Sources / filters (do not file Seek as a defect — per task brief)

**[VERIFIED]** (two independent sessions, `03-phase2` inventory + `09-phase9-verify-results.json`):
`GET /agents/scout/sources/availability` → source filter renders `Seek.com.au (unavailable)`,
`LinkedIn AU (unavailable)`, `Indeed AU (unavailable)` as **disabled** `<option>` elements (confirmed
non-selectable, §3). Enabled/selectable: All sources, Greenhouse, Lever, Remotive, RemoteOK. Source bar shows only
Greenhouse (14), ashby (4), RemoteOK (2) for the currently-active (unapplied) job set — consistent with 47/51 real
jobs already having moved to "applied" status, leaving 20 active across Greenhouse/ashby/RemoteOK. This matches
the task's ground truth (51 jobs across ashby/greenhouse/lever/remoteok/remotive, 0 from seek) — the UI's
per-source counts and disabled state are backend-truthful, not hardcoded. **No finding filed for Seek.**

---

## 6. ATS / fit scores (gates G-J / G-C)

**[VERIFIED]** twice (`02-admin-jobs-initial.png` inventory + `09-phase9-verify-results.json` re-run): AU card
scores = **44, 43, 38, 36, 34, 33** — every value below the 85 target, consistent with the task's DB baseline
(24.89–50.05 range, avg 39.63; this live subset skews slightly higher but the conclusion — nothing near 85 —
holds). Detail-panel match ring, AI Match Analysis narrative ("Your resume covers 16 of 33 keywords… 44% overall
ATS fit"), and the submit-gate's own "Match score 44" all display the **same** number for the same job — no
UI/API mismatch found. `GET /jobs/{id}/insights` returns 200 for every card; values are internally consistent.

---

## 7. Network capture — endpoint wiring

**[VERIFIED]** (`02-admin-console.json`, `03-phase3-console.json`, `04-phase4-console.json`,
`09-phase9-console.json`, `05c-realtime-v2-full.json`) — every user action fired its documented endpoint, all
200s except the deliberately-forced error probes (§8):

| Action | Endpoint | Status |
|---|---|---|
| Page load | `GET /jobs?sort=fitScore` | 200 |
| Card/selection prefetch | `GET /jobs/{id}/insights` (×6+) | 200 |
| Sort change | `GET /jobs?sort=...` | 200 |
| Source filter change | `GET /jobs?sort=...&source=...` | 200 |
| Save toggle | `POST /jobs/{id}/save` (×2, on+off) | 200, 200 |
| Cancel apply / bulk-cancel | *(none fired — correct)* | — |
| Scout source status | `GET /agents/scout/sources` | 200 |
| Source availability | `GET /agents/scout/sources/availability` | 200 |
| Last-sync source | `GET /agents` | 200 |

Zero non-2xx responses on any legitimate UI-driven action. No optimistic-success-on-failure observed (the only
failure paths exercised — bad job id — surfaced honest 404s, see §8).

---

## 8. Console capture + forced backend error

**[VERIFIED]** Across all 4 captured sessions (`02`, `03`, `04`, `09` console JSON dumps): **zero `pageerror`
events, zero uncaught exceptions** in any session. One benign `console.error` observed once
(`03-phase3-console.json`): *"Failed to fetch RSC payload for .../dashboard/networking. Falling back to browser
navigation. TypeError: Failed to fetch"* — a standard Next.js App-Router prefetch-cache-miss message; the app
gracefully fell back to a full navigation (self-healing, no user-facing break). Filed as LOW/informational only.

**Forced backend error** (`06-phase6-results.json`): direct fetch to `GET /api/jobs/NONEXISTENT-ID-XYZ/insights`
→ **404** `{"detail":"Job not found"}`; `POST /api/jobs/NONEXISTENT-ID-XYZ/apply` → **404**
`{"detail":"Job not found"}`. Clean JSON, no stack trace, no 500.

---

## 9. Reload-and-re-read (state persistence)

**[VERIFIED]**:
- Save/bookmark toggle persists across reload (§4e) — full round trip confirmed both directions.
- Client-only filter state (role/location/salary/remote/match/sort text) does **not** survive a full page reload
  or browser back-navigation (resets to defaults) — this is expected (never sent to a persistence endpoint; purely
  local React state) and matches the wireframe's implied ephemeral-filter model. Not filed as a defect.
- Market-tab selection does **not** survive `back()` navigation — landing back on `/dashboard/jobs` after
  visiting `/dashboard` always shows the default "Australia (Local)" tab even if "International" was last active.
  `17-after-back-nav.png`. Minor UX nit (ML-JOBS-006 below), not a data-integrity issue.

---

## 10. Realtime polling (gate G-I)

**[VERIFIED] — genuine 20-second auto-refresh confirmed, contrary to first-pass appearance.**

Initial `page.on('response')` listener runs (66–76s wait) showed only **one** `GET /jobs?sort=fitScore` call and
no repeats — but a `setInterval`-wrapping instrumentation script proved the 20s/30s/60s intervals (jobs/sidebar/
topbar) **do fire on schedule** (`05d-interval-probe.json`, `05e-interval-fire-probe.json`), and a `window.fetch`
-wrapping probe (`05f-fetch-probe.json`) then caught the actual network calls the `page.on('response')` listener
had missed:

```
t_rel=0.39s   GET /api/jobs?sort=fitScore
t_rel=20.39s  GET /api/jobs?sort=fitScore
t_rel=40.39s  GET /api/jobs?sort=fitScore
t_rel=60.39s  GET /api/jobs?sort=fitScore
```

Deltas: exactly **20.00s** each. This matches the code comment in `page.tsx` ("HOTFIX realtime-board-refresh…
Poll every 20s… pause while the tab is hidden"). **`realtime_interval_ms = 20000`**, confirmed live, not just
inferred from source. (Root-cause note for future testers: `page.on('response')` in headless Playwright appears to
silently stop receiving events for long-idle background polling in some runs — instrument `window.fetch`/
`window.setInterval` directly for reliable long-window network assertions, as done here.)

This is a **positive** finding — this route genuinely diverges from the "most routes are a single static fetch,
no periodic refresh" baseline the task brief describes, and does so correctly.

---

## 11. Error / edge states

| Check | Result |
|---|---|
| Unauthenticated access to `/dashboard/jobs` | **[VERIFIED]** Redirects to `/login?next=%2Fdashboard%2Fjobs`; clean sign-in form, **no job data or app chrome leaked** before redirect. `16-unauth-jobs-access.png`. |
| Back navigation | **[VERIFIED]** Returns to `/dashboard/jobs` correctly (URL + content), but resets to default AU tab (§9). `17-after-back-nav.png`. |
| Forward navigation | **[VERIFIED]** Returns to `/dashboard` correctly. |
| Forced backend error (bad job id) | **[VERIFIED]** Honest 404 JSON on both `/insights` and `/apply`, no stack trace (§8). |
| Throttled reload | Not separately exercised (network throttling API); reload-and-re-read (§9) covers the state-persistence intent of this check. |

---

## 12. Identity comparison — OWNER vs NEW USER (as required by the brief)

This is the single biggest behavioural difference found on this screen.

**As OWNER/ADMIN** (`admin`/`admin123`, subscribed — sidebar showed "Pro · 18/100 runs this period"): full Job
Discovery UI renders with real data (20 active matches, 6 AU / 14 Intl), all filters/tabs/apply flows functional
exactly as described above.

**As NEW USER** (`gm2-nonadmin-…`, on the **Free** plan, sidebar shows "Free · 0/5 runs this period"):
navigating to `/dashboard/jobs` renders **no Job Discovery UI at all** — the entire screen is replaced by a
full-page gate:

> "**Subscribe to unlock Aether** — Aether is in limited beta. An active subscription is required to run the AI
> agents that power your job search — discovery, tailoring, cover letters, and the inbox agent." + bullet list of
> features + **View plans & subscribe** button (→ `/pricing`, confirmed) + "You can still browse pricing and
> manage your account."

`18-nonadmin-jobs-initial.png`, `19-nonadmin-paywall-gate.png`, `20-nonadmin-pricing-page.png`. Verified twice
(`22-verify2-nonadmin-paywall.png`, fresh session).

**Backend-level probe** (`08-phase8-nonadmin-probe-results.json`, direct authenticated `fetch()` calls from the
NEW USER's own session, bypassing the client route gate):
- `GET /jobs?sort=fitScore` → **200**, `[]` — the read endpoint itself is **not** subscription-gated (correctly
  scoped to 0 jobs for this brand-new user; no cross-user data leak).
- `POST /agents/scout/run` → **402** `{"error":"subscription_required","message":"An active subscription is
  required to use Aether. Subscribe to unlock.","upgradeUrl":"/pricing"}` — the costly agent action **is**
  properly enforced server-side, not just hidden client-side. Good security backstop.
- `POST /jobs/FAKE-ID/apply` → **404** `{"detail":"Job not found"}` (job doesn't exist, so the subscription check
  either isn't reached or isn't applied to apply — inconclusive on its own, but apply is not agent-cost so this is
  low-risk either way).

**Finding filed**: ML-JOBS-003 (§13) — the **Free** plan is presented on `/pricing` as the "CURRENT PLAN" for
this account with explicit included features ("5 agent runs / month", "**Resume tailoring** + ATS scoring",
"Community support"), yet the actual product blocks **100% of agent functionality** (confirmed via the 402 on
Scout, and the full-screen gate on Jobs) for this same Free account. The paywall's own text ("active subscription
is required to run the AI agents") contradicts the pricing page's own claim that the $0 Free tier includes usable
agent runs. `20-nonadmin-pricing-page.png` (Free card, $0, "CURRENT PLAN", "5 tailored agent runs / month").

---

## 13. Findings table

| id | severity | description | reproduction | evidence | status |
|---|---|---|---|---|---|
| ML-JOBS-003 | **MEDIUM** | Pricing page advertises the $0 Free plan (shown as the NEW USER's "CURRENT PLAN") as including "5 agent runs/month" and "Resume tailoring + ATS scoring," but the product unconditionally blocks all AI-agent functionality for Free-tier accounts: `/dashboard/jobs` shows a full-screen "Subscribe to unlock Aether" gate and `POST /agents/scout/run` returns `402 subscription_required` for this same account (0/5 monthly runs used — not a quota exhaustion, an unconditional plan-tier block). Two interpretations: (a) intentional temporary "limited beta" override not reflected in the pricing copy, or (b) the Free tier's advertised entitlements are simply not wired up. Filed as UNSURE between these two — both are plausible and the evidence supports either; only Abacus/product can adjudicate intent. | 1. Log in as `gm2-nonadmin-1785454990@example.com`. 2. Visit `/dashboard/jobs` → full paywall gate renders instead of the Jobs UI. 3. Visit `/pricing` → Free card shows "CURRENT PLAN", "$0", "5 agent runs / month", "Resume tailoring + ATS scoring" as included. 4. From the browser console, `fetch('/api/agents/scout/run', {method:'POST', headers:{Authorization:'Bearer '+token}, ...})` → 402 `subscription_required`. | `18-nonadmin-jobs-initial.png`, `19-nonadmin-paywall-gate.png`, `20-nonadmin-pricing-page.png`, `08-phase8-nonadmin-probe-results.json` | OPEN |
| ML-JOBS-006 | LOW | Market-tab selection (Australia/International/Saved) does not persist across browser back-navigation — landing back on `/dashboard/jobs` always shows the default "Australia (Local)" tab regardless of which tab was active when the user navigated away. Purely client `useState`, never round-tripped. | 1. On `/dashboard/jobs`, click "International" tab. 2. Navigate to `/dashboard`. 3. Click browser Back. 4. Observe tab resets to "Australia (Local)". | `17-after-back-nav.png`, `06-phase6-results.json` (`after_back_active_tab`) | OPEN |
| ML-JOBS-007 | LOW / informational | One benign Next.js RSC-prefetch-fallback console error observed during rapid interaction ("Failed to fetch RSC payload for /dashboard/networking… Falling back to browser navigation"). App self-heals via full navigation; no user-facing break, no data loss. Noting for completeness only — recommend NOT filing as an actionable defect. | Rapid sequential interaction with the Jobs page (filters, tab switches) in one session; observed once, not reproduced on the 3 other captured sessions. | `03-phase3-console.json` | OPEN (informational) |
| ML-JOBS-008 | INFO — not a defect | Confirmed by design, not a gap: no individual per-card "Apply" button exists; Apply is exposed only via the detail panel (selected job) and bulk "Apply (N)". This exactly matches `design/screens/job-discovery.html` (no per-card CTA in the wireframe either). Recorded here only because the test brief's checklist explicitly asked whether every card exposes an individual Apply button — answer is **no**, verified twice, and this is correct/wireframe-conformant, not a defect. | See §4a. | `04-phase4-results.json`, `09-phase9-verify-results.json` | CLOSED (by design) |
| — | — | Live confirm-apply / bulk-confirm-apply POST **not executed** against real OWNER production data (permanent, un-reversible-via-API mutation to real job-search history); NEW USER account is fully paywalled out of this screen so could not substitute. Cancel-path, modal-content-accuracy, and 404-error-path all fully verified live instead. See §4d and §14 (Not Tested). | — | `10-admin-submit-gate-open.png`, `12-admin-bulk-apply-gate.png`, `11-admin-after-cancel.png` | N/A — scope decision, not a filed defect |

No BLOCKER or HIGH severity findings. No placeholder/fixture content found on any user-reachable path (all
scores, narratives, risk signals, and source links are real, per-job, backend-computed values). No security gap
found (unauthenticated access correctly gated; server-side 402 backstop on the costly agent action; no cross-user
data leak for the 0-job NEW USER).

---

## 14. Not-tested items (HUMAN-GATED / scope-limited only)

1. **Live `Confirm Submit` / `Confirm N Applications` execution** (creating a real `Application` row + job-status
   flip + success toast, then reload-verifying persistence) — not executed against the OWNER's real production
   data by deliberate safety choice (§4d); the disposable NEW USER account that exists specifically for this kind
   of destructive test is unconditionally paywalled off this entire screen (§12), and no third identity with an
   active paid subscription and disposable status was available to this tester. **Recommend**: a future pass
   provision one disposable *subscribed* test account (Starter tier, $19/mo, refundable/cancel-immediately) to
   close this specific gap with real evidence, OR accept the code-level read (`POST /jobs/{id}/apply`, updates
   `Job.status` + creates `Application`, per `apps/api` source — [INFERRED], not exercised live this run) plus the
   fully-verified Cancel-path/modal-content/404-path evidence already gathered as sufficient.
2. **Live "Tailor Resume" agent run** (idle → tailoring-in-progress → tailored, with a genuinely fresh/never-
   tailored job) — both AU cards inspected on the OWNER account were already at the "tailored" step from prior
   agent runs (their `tailoredResumeId` was already set), so the idle→tailoring transition animation/copy could
   not be exercised without either (a) triggering a real, billed LLM tailoring run against OWNER production data
   for a job that hadn't been through it, or (b) using the NEW USER account, which is paywalled off Sync/Tailor
   entirely. The idle-state UI (Tailor Resume / Preview / Skip buttons) IS confirmed present in source and was
   screenshotted in its "tailored" (post-run) state; the transition itself is [INFERRED] from source
   (`startTailoring()` → `POST /agents/tailor/run` → `resolveRun()` polling → `apply-step2`), not live-verified.
3. **Throttled-network reload** (explicit CDP network-throttle emulation) — not separately exercised; the
   reload-and-re-read persistence check (§9) covers the functional intent (state survives a reload) but not the
   specific "does the UI show an honest loading/degraded state under a slow connection" sub-question.

No cleanup required: no persistent test data was left on either account. The one stateful mutation performed
(OWNER save/bookmark toggle) was verified reverted to its original `false` state via a follow-up reload (§4e).

---

## 15. Screenshot index

| # | File | Content |
|---|---|---|
| 00 | `jobs/00-login-page.png` | Login page baseline |
| 01 | `jobs/01-admin-post-login.png` | OWNER dashboard post-login |
| 02 | `jobs/02-admin-jobs-initial.png` | Jobs screen, OWNER, initial load |
| 03 | `jobs/03-admin-role-filter-xss.png` | Role filter with XSS payload → honest empty state |
| 04 | `jobs/04-admin-salary-200k-filter.png` | Salary $200k+ filter → 0 results |
| 05 | `jobs/05-admin-remote-filter.png` | Remote·Hybrid toggle active |
| 06 | `jobs/06-admin-match80-filter.png` | Match ≥80% slider → 0 results |
| 07 | `jobs/07-admin-sort-newest.png` | Sort: newest |
| 08 | `jobs/08-admin-intl-tab.png` | International tab, 14 cards |
| 09 | `jobs/09-admin-saved-tab.png` | Saved tab, empty state |
| 10 | `jobs/10-admin-submit-gate-open.png` | Submit-application gate open |
| 11 | `jobs/11-admin-after-cancel.png` | After Cancel — no state change |
| 12 | `jobs/12-admin-bulk-apply-gate.png` | Bulk-apply gate (6 selected) |
| 13 | `jobs/13-admin-after-save-toggle.png` | After bookmark toggle |
| 14 | `jobs/14-admin-after-reload-save-check.png` | Reload confirms save persisted |
| 15 | `jobs/15-admin-card2-detail.png` | Second card detail (also pre-tailored) |
| 16 | `jobs/16-unauth-jobs-access.png` | Unauthenticated → redirected to /login |
| 17 | `jobs/17-after-back-nav.png` | After browser Back — tab reset to AU |
| 18 | `jobs/18-nonadmin-jobs-initial.png` | NEW USER — dashboard post-login |
| 19 | `jobs/19-nonadmin-paywall-gate.png` | NEW USER — Jobs screen paywall gate |
| 20 | `jobs/20-nonadmin-pricing-page.png` | NEW USER — /pricing (Free = current plan) |
| 21 | `jobs/21-verify2-admin-jobs.png` | Verify-twice, fresh session, OWNER |
| 22 | `jobs/22-verify2-nonadmin-paywall.png` | Verify-twice, fresh session, NEW USER |

**JSON evidence**: `02-admin-console.json`, `03-phase3-results.json`, `03-phase3-console.json`,
`04-phase4-results.json`, `04-phase4-console.json`, `05-phase5-results.json`, `05b-realtime-results.json`,
`05c-realtime-v2-full.json`, `05d-interval-probe.json`, `05e-interval-fire-probe.json`, `05f-fetch-probe.json`,
`06-phase6-results.json`, `07-phase7-nonadmin-results.json`, `07-phase7-nonadmin-console.json`,
`08-phase8-nonadmin-probe-results.json`, `09-phase9-verify-results.json`, `09-phase9-console.json` — all under
`uat/reports/evidence/gold-master-v2/screens/jobs/`.

---

## 16. Overall verdict

**No BLOCKER or HIGH findings.** The Job Discovery screen is solidly built: real per-job scores/narratives/risk
signals (no fixture content anywhere), honest empty/error states under adversarial input, correct auth gating,
correct Seek/LinkedIn/Indeed unavailability (backend-truthful), a genuinely-working 20s realtime poll, and correct
Cancel-never-applies behaviour on both the single and bulk apply gates.

**One MEDIUM finding** (ML-JOBS-003) around a pricing/entitlement inconsistency for Free-tier accounts is the most
actionable item — it's a business-facing honesty concern (advertised vs. enforced entitlements) rather than a UI
bug, and would benefit from explicit product adjudication rather than a code fix from this report alone.

**Two LOW items** (tab-state not preserved across back-nav; one benign console warning) are cosmetic.

**One scope-limited gap** (live confirm-apply execution) was deliberately not closed to avoid an unreversible
mutation of the real product owner's job-search history, given no safe disposable+subscribed identity was
available; Cancel-path, modal-accuracy, and error-path were fully verified as a substitute, and the specific
recipe to close the gap safely is documented in §14 for a follow-up pass.

**Verdict: PASS with one MEDIUM finding for product review (ML-JOBS-003) and one scope-limited item for follow-up
(§14.1).**
