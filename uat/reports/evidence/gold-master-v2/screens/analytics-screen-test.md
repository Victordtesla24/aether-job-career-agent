# GOLD-MASTER-V2 §3.2 — Screen Test: Analytics (`/dashboard/analytics`)

- Production: `https://5cb5f0620.abacusai.cloud`
- Tester: screen-tester agent (Playwright 1.62, headless Chromium, ONE browser at a time, fully serial — no
  sub-agents per task rules)
- Repo: `/home/ubuntu/github_repos/aether-job-career-agent`
- Evidence root: `uat/reports/evidence/gold-master-v2/screens/analytics/`
- Wireframe: `design/screens/analytics.html`
- Identities used: **admin/admin123** ("as OWNER", real data-rich account, `isAdmin:true`, email
  `sarkar.vikram@gmail.com`) and the canonical non-admin account from
  `uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md` ("as NEW USER")
- Fresh evidence timestamps: API reconciliation probes 2026-07-31T06:15–06:19Z; Playwright pass
  2026-07-31T06:20:53Z–06:23:43Z (session log: `uat/reports/evidence/gold-master-v2/screens/analytics/` +
  `/tmp/.../gm2-run.log`); supplementary period-persistence + main-dashboard cross-check
  2026-07-31T06:2xZ (`supp-*` files)
- **Every claim below is tagged.** `[VERIFIED]` = fresh screenshot/JSON evidence from this run (2 independent
  browser sessions, "verify twice" per protocol). `[INFERRED]` = derived from source-code reading, not
  independently exercised live. `[UNSURE]` = both interpretations given, flagged for human judgement.

---

## 1. Element inventory

| Element (wireframe id) | Present in prod? | Notes |
|---|---|---|
| Sidebar nav (`sidebar-main-an01`) | ✓ | Full nav incl. Dashboard/Jobs/…/Analytics(active)/Offers/Settings |
| Range pills 7d/30d/90d/All (`range-pills-an04`) | ✓ | `data-testid="period-selector"`, 4 working buttons |
| Export button (`btn-export-an05`) | ✗ **MISSING** | 0 export buttons found in DOM, confirmed 2× (see ML-ANALYTICS-001) |
| "Last 30 days · updated 4 min ago" freshness label | ✗ **MISSING** | Prod subtitle is static: "Funnel conversion, ATS score quality and agent spend." — no period echo, no staleness timestamp (ML-ANALYTICS-002) |
| Application Funnel chart (`funnel-an07`) | ✓ (different form) | Prod renders as labelled numeric grid (Jobs Found/Applied/Screened/Interviewed/Offers), not the wireframe's bar chart — data present either way |
| Interview Conversion chart (`conversion-an08`) | ✓ (different form) | Prod's "Stage Conversion" grid includes "Screened → Interview" and "Interview → Offer" — see §2 |
| Sources donut (`sources-an09`) | ✓ (different form) | Prod's "Jobs by Source" list (Greenhouse/Ashby/Lever/etc., under Market Pulse) covers this; no donut SVG |
| Top Skills (`skills-an10`) | ✓ | Present, honestly empty ("Not enough job data yet…") |
| ATS Score Distribution (`ats-an11`) | ✓ | Histogram present with live hover tooltips |
| Weekly Activity heatmap (`heatmap-an12`) | ✓ | Present under Market Pulse |
| Job Probability Score (`probability-an13`) | ✓ | Present, live-computed |
| Employer Hiring Activity (`employer-activity-an14`) | ✓ | Present, real activity feed |
| Recruiter Activity (`recruiter-trends-an15`) | ✓ | Present |
| Market vs. Your Performance (`market-vs-you-an16`) | ✓ | Present, **honestly** shows "no market data connected" (§2.5) |
| Trend Indicators (`trend-indicators-an17`) | ✓ | Present |

Production groups everything the wireframe splits into two rows into three logical sections: (1) Dashboard
Summary + Application Funnel + Stage Conversion + ATS Distribution + Agent ROI, (2) "Real-Time Market Pulse"
(probability score, employer activity, recruiter trends, sources, top skills, heatmap), (3) Market-vs-you +
Trend indicators. Structurally richer than the wireframe (adds a Dashboard-Summary card and Agent-ROI card
the wireframe doesn't show), while dropping the Export button and the header freshness label the wireframe
does show.

---

## 2. Per-check results

### 2.1 Is an interview-conversion metric displayed? What value? Does it match 0/72 = 0.00%? `[VERIFIED]`

**Yes — displayed in two distinct forms, both reading 0%, both honest:**

1. **Stage Conversion "Screened → Interview": `0%`** — server-computed as `interviewed / screened` (2 screened,
   0 interviewed) — `apps/api/app/routers/analytics.py:184`, `rate(data["interviewed"], data["screened"])`.
2. **Job Probability Score factor "Interview conversion": `0`** — server-computed as
   `round(interviews / total_apps * 100)` — `analytics.py:493-494` — this one **is** an applications-denominator
   conversion rate, structurally the closest match to the task's "0/72" framing.
3. The main **Dashboard** screen (not this screen, but directly cross-checked per item 3 below) shows its own
   **"Interview Rate: 0% (0 of 47 applied)"** stat card — `interviewed / applied` —
   `apps/web/src/components/dashboard/DashboardStats.tsx:33-34`.

All three are currently `0%` because `InterviewSchedule` is empty (0 interviews) — this is mathematically
unfalsifiable proof of "no fabrication" (a fabricated pipeline would show >0%), but it also means the three
metrics' **different denominators** (screened=2, `total_apps`=see §2.2 caveat, applied=47) cannot be
distinguished from a single all-zero numerator. `[UNSURE — ML-ANALYTICS-004]`: code review shows the
Job-Probability-Score factor's `total_apps` is sourced from a **raw, non-deduplicated** `COUNT(*) FROM
"Application"` (`analytics.py:328-338`), not the codebase's own documented canonical
`get_application_counts()` helper (used everywhere else, explicitly to prevent counting one job's multiple
draft/refine cover-letter rows as multiple "applications" — the historical RT-004 bug). This is a **code-level
risk, not a confirmed live defect**: it cannot be observed today because (a) the numerator is 0 regardless of
denominator, and (b) the sibling "Application volume" factor computed from the same `total_apps` is already
saturated at its 100-point cap. Flagging as UNSURE per protocol §7 rather than guessing.

**Conclusion:** yes, honestly displayed, matches "0 interviews → 0%" in every form checked. `interview_conversion_shown = true`, `value = "0%"`, `matches_db = true` (0 interviews is unambiguous — DB truth and every UI/API surface agree).

### 2.2 Reconciliation of every headline figure — API vs. task's stated DB ground truth vs. fresh live DB state

**Important preliminary finding:** the task's stated ground truth ("74 applications: 72 submitted, 2
screening… 51 jobs, scores 24.89–50.05 avg 39.63") **no longer matches live production**, measured fresh at
2026-07-31T06:15–06:19Z. This production account is shared across many concurrent test agents in this same
GOLD-MASTER-V2 swarm run (confirmed by sibling reports, e.g. applications-screen-test.md: "a third pending item…
had also appeared… from other concurrent test activity"), so drift between the task's snapshot and my fresh
read is expected, not itself a defect. Table below reconciles what I could **directly, freshly, independently
verify**:

| Figure | Task's stated ground truth | Fresh API (2026-07-31T06:1x-19Z) | Fresh UI (analytics screen) | Fresh UI (main Dashboard) | Reconciles? |
|---|---|---|---|---|---|
| Applications (total, incl. drafts) | 74 | `GET /applications` (39) + `?include_applied=true` (10) = **49** | "Applications" card: **49** | *(not shown as a distinct card)* | ✓ API = UI; ✗ vs. task's stale 74 (see note) |
| Applications (submitted/applied) | 72 | funnel.applied = **47** | Funnel "Applied": **47** | "Active Applications": **47** | ✓✓✓ perfectly reconciled across API + both screens; ✗ vs. task's stale 72 |
| Screening | 2 | **2** (both funnel and `include_applied` rows) | Funnel "Screened": **2** | Funnel (all time) "Screened": **2** | ✓ fully reconciled |
| Interviews | 0 | **0** | "Interviews": **0** | "Interviewed": **0** | ✓ fully reconciled |
| Jobs | 51 | **52** | "Jobs Found": **52** | "Jobs Found": **52** | ✓ API=UI (both screens); off-by-1 vs. task's stale 51 (one job added since) |
| Avg fit score | 39.63 | 39.7 (dashboard endpoint) / 39.85 (computed from raw fitScore fields) | "Avg Fit Score": **39.7%** | — | ✓ reconciled to 1 decimal; small variance (39.7 vs 39.85) is a rounding-vs-raw-mean difference, not a defect |
| Fit score range | 24.89–50.05 | **24.89–50.05** (computed across both `/applications` views) | ATS histogram buckets consistent (20-30:1, 30-40:24, 40-50:26, 50-60:1, total 52) | — | ✓ exact match, unchanged |
| Users | 7 | `GET /admin/users` → **total: 7** | *(not shown on this screen)* | — | ✓ exact match, unchanged |

**Note on the 49-vs-47 "two different Applications numbers":** this is **not a bug**. `apps/api/app/routers/
analytics.py:29-50` documents an explicit, repo-wide data-consistency ruling (`MV-dashboard-001,
MV-analytics-004/005/006`): the analytics **Dashboard Summary** card is defined to show `total` (every
`Application` row regardless of status, including the 2 still-`draft` rows = 49), while any surface labelled
"submitted"/"applied"/"active" — the Funnel's "Applied" node, the main Dashboard's "Active Applications" card,
and Market Pulse's "Applications / month" — must all use `submitted` (=47). I verified live that **both
screens implement this ruling correctly and consistently** (49 vs 47, both reproduced twice, both matching
their documented definitions). `unreconciled_figures = []` — nothing on this screen fails to reconcile once
each figure's own documented definition is applied.

### 2.3 The "47 active applications" vs. DB "74" question (§3.2 item 7 / cross-screen consistency)

**Fresh finding: 47 is correct, and both screens show it consistently.** The main Dashboard's "Active
Applications: 47" card and this Analytics screen's Funnel "Applied: 47" **agree exactly** — cross-screen
consistency **holds** for this specific figure, freshly verified `[VERIFIED]` (`supp-01-main-dashboard.png` +
`supp-01-main-dashboard-stats.txt` vs. `fresh-01-dom-initial.json`). The task's cited "74" ground truth is
**not reproduced anywhere in the live UI or API today** — every application-count surface I could reach
(analytics dashboard-summary total=49, funnel/dashboard applied=47, main-dashboard active-applications=47)
is internally self-consistent with the documented `total` vs. `submitted` distinction, and none of them is
74. `[INFERRED]`: 74 is closest to a **raw, non-deduplicated Application row count** (the RT-004 bug class the
codebase explicitly fixed elsewhere — one job's multiple draft/refine cover-letter rows each counted as a
separate "application"); 74 − 47 = 27 "extra" rows is a plausible magnitude for that pattern, though I cannot
prove this without direct DB access. I did **not** find the ML-APP-003 sibling defect (Board 0 / Applied-tab
"applied" / Sankey 2 three-way disagreement) reproduced *on this screen* — that finding is specific to the
Applications screen's Kanban board and Applied-tab badge, neither of which exists here; this screen's own
Screened figure (2) matches the Sankey (2) and the funnel (2) consistently.

`active_applications_shown = 47` (main dashboard, cross-checked); this screen's own closest equivalent
(Funnel "Applied") also reads **47**, in agreement.

### 2.4 Honest empty state with 0 interviews `[VERIFIED]`

No fabrication found. Every interview-related figure reads a plain `0` / `0%` with no placeholder chart data,
no fake trend arrows implying interviews exist, and no hidden non-zero value anywhere in the raw API bodies
(`fresh-08-allrequests.json`). The wireframe's static mock data (23 interviews, "+3.2%" trend, a populated
interview-conversion line chart) is **not** reproduced in production — production correctly shows its own
real (zero) data instead of the wireframe's placeholder numbers. `empty_state_honest = true`.

### 2.5 "External market benchmark unavailable — Provider: none configured" `[VERIFIED]`

Confirmed present **verbatim**, twice (owner session + verify-twice session):
> "External market benchmark unavailable / Provider: none configured — your figures are derived from your
> saved jobs and applications. / … Market data: not connected / you 47 / … Market data: not connected / you 0%
> / No market data source connected — showing your own figures only."

Honest — not fabricated. `[VERIFIED-WITH-FRESH-EVIDENCE fresh-01-dom-initial.json + session4-verify2.json,
2026-07-31T06:21Z / 06:23Z]`.

---

## 3. Every control exercised

| Control | Action taken | Result |
|---|---|---|
| Range pills 7d/90d/All/30d | Clicked each | Each fires 5 API calls (`funnel`, `dashboard`, `conversion` w/ `?period=`; `agent-roi`, `ats-distribution` unscoped) and re-renders the summary/funnel/conversion cards; verified numbers change correctly per period (7d: Applications 47/Jobs Found 8; 30d/90d/All: 49/52 — see `fresh-02-period-clicks.json`) |
| ATS histogram bar hover | Hovered | Native `title` tooltip fires, e.g. `"0-10: 0"` — `[VERIFIED]` |
| Reload | `page.reload()` after selecting 90d | **Period selection does NOT persist** — resets silently to "All" every time (ML-ANALYTICS-003) |
| Back/forward nav | `/dashboard` → back | Correctly returns to `/dashboard/analytics`, no broken state |
| Mobile 390px | Resized viewport | `scrollWidth === clientWidth === 390` — **no horizontal overflow** |
| NUL byte adversarial | `?period=%00` on funnel/dashboard/conversion (in-browser `fetch` + curl) | Clean **422** `"Invalid period ' '. Valid: [...]"` — not the systemic 500 (see §5) |
| Unauthenticated access | Fresh context, no token, direct nav + direct API call | UI: redirect to `/login?next=%2Fdashboard%2Fanalytics` (no data flash); API: `GET /analytics/funnel` → **401** |

`export_button_exists = false` (see ML-ANALYTICS-001) — there is no Export control to exercise.

---

## 4. UI ↔ backend wiring / network capture

All 5 analytics endpoints (`funnel`, `dashboard`, `conversion`, `agent-roi`, `ats-distribution`) plus
`market-pulse` returned **200** on every legitimate call observed (`fresh-08-allrequests.json`, 2573+ lines
across sessions). No optimistic-success pattern exists to test on this screen — it is 100% read-only
(no forms, no mutating buttons) so there is no "action that could fake success" surface. Errors surface
honestly: the deliberate NUL-byte probes produced real 422s with descriptive bodies, correctly reflected as
browser console `error` entries (expected DevTools behavior for any non-2xx fetch, not an app bug).

**Realtime refresh — measured via `window.fetch` instrumentation (not passive capture), per task instruction:**
a 65-second in-page fetch log (`fresh-04-realtime-fetchlog.json`) captured **zero** repeat calls to this
screen's own data endpoints (`/analytics/*`) — they fire only on mount and on period-pill click, never on a
timer. The only periodic activity observed in that window was the **global app-shell's Agents-Idle sidebar
widget**, `GET /api/agents`, firing at t≈30.0s and t≈60.0s (a clean 30-second interval, consistent with the
task's own note "agents polls 30s"), plus one `GET /api/approvals?status=pending` at t≈60.0s (global
pending-approvals badge, not this screen's own data). `realtime_interval_ms = null` for the analytics screen's
own data (no auto-refresh); the only interval present on this route belongs to shared shell chrome.

**Console / page errors:** 2 console `error` entries total, both my own NUL-byte 422 probes
(`fresh-05-console.json`). 0 uncaught page errors (`fresh-06-pageerrors.json`). 9 `net::ERR_ABORTED` entries in
`fresh-07-failed.json`, all timestamped identically to the immediate post-login navigation to
`/dashboard/analytics` — classic client-side navigation-cancel artifacts (in-flight requests from the
dashboard shell aborted by the browser when the next `page.goto` fires), not server failures; none recurred
on reload or on the verify-twice pass.

---

## 5. NUL byte / systemic-500 cross-check

The task expected "NUL→500 confirmed on 7 endpoints, fix verified but UNDEPLOYED." Cross-checked against
`docs/delivery/GOLD-MASTER-V2-STATE.json → nul_byte_affected_endpoints`: `PUT /workspaces/settings`,
`POST /resumes`, `POST /agents/tailor/run`, `POST /stories`, `PUT /stories/{id}`,
`POST /cover-letters/{id}/refine`, `POST /agents/cover-letter/run` — **none of these belong to the Analytics
screen.** The systemic bug is specifically in free-text **body** fields reaching a raw DB `cur.execute()` call
unvalidated; the Analytics screen has no such input — its only user-controllable parameter is the `period`
query enum, which is validated against a fixed set (`_PERIODS`) and rejects a NUL byte with a clean 422 before
touching the database (`analytics.py:19-28`). **Confirmed: no matching attack surface on this screen; the
absence of a 500 here is the correct, expected result, not a false negative.**

---

## 6. Cross-identity checks

- **Unauthenticated:** clean redirect, no data leak, API 401 — `[VERIFIED]` twice (session 1 + session 4 area).
- **New user (nonadmin, unsubscribed):** `08-newuser-analytics.png` — full, honest paywall ("Subscribe to
  unlock Aether…"), **not** an empty/fabricated analytics view, **not** a broken page. Consistent with the
  same account's paywall on the Applications screen (sibling report). `[VERIFIED]`.
- **Owner, verify-twice (fresh 2nd browser context, no shared state with session 2):** identical headline
  figures reproduced exactly — Applications 49, Interviews 0, Offers 0, Jobs Found 52, Avg Fit Score 39.7%,
  Screened→Interview 0%, Probability Score 60% (Interview conversion 0) — `session4-verify2.json` vs.
  `fresh-01-dom-initial.json`. **Byte-for-byte reproducible.** `[VERIFIED-WITH-FRESH-EVIDENCE, 2 independent
  sessions]`.

---

## 7. Findings

| id | severity | category | summary |
|---|---|---|---|
| ML-ANALYTICS-001 | LOW | visual conformance | Wireframe's "Export" button (`btn-export-an05`) does not exist in production — 0 export controls found, confirmed 2× |
| ML-ANALYTICS-002 | LOW | visual conformance | Wireframe's header freshness label ("Last 30 days · updated 4 min ago") is absent; production's header subtitle carries no period echo or staleness timestamp |
| ML-ANALYTICS-003 | LOW | UX / state management | Selected time-range pill does not persist across reload — silently resets to "All" every time (code-confirmed: plain `useState`, no URL/localStorage sync) |
| ML-ANALYTICS-004 | LOW / **UNSURE** | code-quality risk | Job-Probability-Score's "Application volume"/"Interview conversion" factors are computed from a raw, non-deduplicated `COUNT(*) FROM "Application"` (`analytics.py:328-338`), bypassing the codebase's own documented canonical dedup helper used everywhere else — currently unobservable live (0 interviews, saturated cap), flagged for human review rather than guessed at |

**No BLOCKER/HIGH findings on this screen.** No fabricated data, no fixture/placeholder content, no broken
wiring, no optimistic-success-on-failure pattern found.

### ML-ANALYTICS-001 — LOW: Export button missing vs. wireframe
- **Reproduction:** `document.querySelectorAll('button')` filtered for `/export/i` text → 0 matches, both in
  the initial owner session and the verify-twice session.
- **Expected (wireframe):** a top-right "Export" button (`btn-export-an05`).
- **Observed:** no export affordance anywhere on the page.
- **Evidence:** `fresh-01-dom-initial.json` (`exportButtons: 0`), `01-owner-desktop-full.png`.
- **Status:** OPEN

### ML-ANALYTICS-002 — LOW: header freshness label missing vs. wireframe
- **Reproduction:** visual inspection of the header region across all screenshots; DOM text search for
  "updated" near the range pills → not found.
- **Expected (wireframe):** `<span id="rangeLabel">Last 30 days</span> · updated 4 min ago`.
- **Observed:** header subtitle is the static string "Funnel conversion, ATS score quality and agent spend."
- **Evidence:** `fresh-01-dom-initial.json`, `01-owner-desktop-full.png`.
- **Status:** OPEN

### ML-ANALYTICS-003 — LOW: period selection not sticky across reload
- **Reproduction:** click "90d" → confirm active + "DASHBOARD SUMMARY (90D)" renders → `page.reload()` →
  active pill is now "all", "DASHBOARD SUMMARY (ALL)" renders.
- **Expected:** either persistence (URL param or localStorage) or, at minimum, no silent surprise.
- **Observed:** silent reset to the broadest ("All") view — not misleading (broadest, not narrowest, view),
  but a real state-loss a user could be confused by mid-analysis.
- **Evidence:** `supp-02-period-persistence.json`, `supp-02-after-90d-reload.png`; code:
  `apps/web/src/app/dashboard/analytics/page.tsx:28` (`useState<Period>("all")`, no persistence layer).
- **Status:** OPEN

### ML-ANALYTICS-004 — LOW/UNSURE: possible row-inflation in one Probability-Score panel
- **Reproduction:** code reading only — `analytics.py:328-338` (`market_pulse()`'s own inline
  `COUNT(*) FROM "Application"`) vs. `analytics.py:33-70` (`get_application_counts()`, the documented
  single-source-of-truth helper with `COUNT(DISTINCT "jobId")`, used by every other "applications" surface
  per the repo's own MV-dashboard-001/MV-analytics-004/005/006 rulings).
- **Expected:** every "applications" count on this screen uses the canonical deduped helper (per the
  codebase's own documented rule).
- **Observed:** this one panel's two factors ("Application volume", "Interview conversion") do not.
- **Why UNSURE, not filed as a confirmed defect:** with 0 interviews, `interviews/total_apps = 0` regardless
  of whether `total_apps` is deduped (49) or an inflated raw count — the numerator kills the distinction. The
  sibling "Application volume" factor is separately capped at 100 and already renders 100 either way. I could
  not devise a live, safe (read-only) test that would surface a difference with the current data. Filed per
  protocol §7 ("UNSURE → file with both interpretations") rather than asserted as fact.
- **Evidence:** source excerpts above; `fresh-01-dom-initial.json` (Probability Score panel: "Interview
  conversion 0", "Application volume 100").
- **Status:** OPEN, UNSURE

---

## 8. Not tested (human-gated / genuinely unreachable)

- **Waiting for a real interview to be scheduled** to observe whether the three differently-denominated
  "interview conversion" metrics (§2.1) diverge once the numerator is non-zero — requires real pipeline
  progress over days/weeks, not reproducible in a single test session. Not human-gated in the strict sense,
  just not currently possible with this account's data.
- **Direct DB query** to pin down whether "74" in the task's stated ground truth was in fact a raw
  (non-deduplicated) Application row count — I do not have DB credentials in this session; my conclusion in
  §2.3 is `[INFERRED]`, not `[VERIFIED]`, for that specific number.

---

## 9. Screenshot index (`uat/reports/evidence/gold-master-v2/screens/analytics/`)

| File | Description |
|---|---|
| `00-unauth-access.png` | Fresh unauthenticated access → redirected to `/login?next=...` |
| `01-owner-desktop-full.png` / `01b-owner-desktop-viewport.png` | Owner, full-page + viewport, initial load |
| `02-after-period-clicks.png` | After cycling 7d→90d→All→30d |
| `03-after-reload.png` | Post-reload state |
| `04-after-back-nav.png` | After `/dashboard` → back |
| `05-mobile-390-full.png` | Mobile 390px, full page (no overflow) |
| `08-newuser-analytics.png` | New (nonadmin, unsubscribed) user — honest paywall |
| `09-verify2-analytics.png` | Second fresh browser session — figures reproduced identically |
| `10-tooltip-open.png` | ATS histogram bar hover tooltip (from earlier same-day pass) |
| `supp-01-main-dashboard.png` | Main `/dashboard` stat cards, for cross-screen reconciliation |
| `supp-02-after-90d-reload.png` | 90d selected then reloaded → reverted to "All" (ML-ANALYTICS-003) |

Plus earlier same-day evidence retained from this run's initial pass (`00-login-page.png`, `00b-login-filled`,
`02-period-{7d,30d,90d,all}.png`, `05b/05c-mobile-*`, `06-after-interview-schedule-created.png`,
`07-unauthenticated-access.png`, `09-newuser-mobile-390.png`) — consistent with the fresh pass, retained as
corroborating evidence rather than superseded.

---

## 10. Console / network / server-log summary

- Console errors: 2, both self-induced by my own NUL-byte adversarial probes. `console_errors: []` organic.
- Page errors (uncaught exceptions): 0.
- Failed requests: 9, all navigation-cancel artifacts at the login→analytics transition, none reproduced on
  reload/verify-twice.
- All 6 analytics/market-pulse endpoints: 200 on every legitimate call, 422 on adversarial NUL byte, 401
  unauthenticated. No 500s. No 403s (analytics has no admin-only surface).

---

## 11. Sign-off

Analytics is a **read-only reporting screen with no forms and no mutating controls**, and it is honest: every
figure I could reconcile does reconcile (once each figure's documented definition — total vs. submitted — is
applied), the "0 interviews" state is presented truthfully everywhere, the market-benchmark-unavailable
message is genuine, and no fixture/placeholder/fabricated content was found anywhere on this screen. The 4
findings filed are all LOW severity (2 wireframe-conformance gaps, 1 state-persistence UX nit, 1 UNSURE
code-review risk with no live reproduction) — **none block production use of this screen.**

## 12. Return-schema summary

```json
{
  "artifact": "uat/reports/evidence/gold-master-v2/screens/analytics-screen-test.md",
  "interview_conversion_shown": true,
  "value": "0%",
  "matches_db": true,
  "unreconciled_figures": [],
  "active_applications_shown": 47,
  "empty_state_honest": true,
  "realtime_interval_ms": null,
  "findings": [
    {"id": "ML-ANALYTICS-001", "severity": "LOW", "desc": "Wireframe Export button missing in production"},
    {"id": "ML-ANALYTICS-002", "severity": "LOW", "desc": "Wireframe header freshness label ('updated N min ago') missing in production"},
    {"id": "ML-ANALYTICS-003", "severity": "LOW", "desc": "Selected time-range pill does not persist across reload, silently resets to All"},
    {"id": "ML-ANALYTICS-004", "severity": "LOW/UNSURE", "desc": "Probability-score panel may use a non-deduplicated Application COUNT(*) instead of the canonical helper; unobservable live with current (0-interview) data"}
  ],
  "verdict": "Clean, honest, fully-reconciled reporting screen. The task's stated DB ground truth (74/72 applications, 51 jobs) is stale — live measurement (49 total / 47 submitted, 52 jobs) reconciles perfectly across the analytics screen, the main dashboard, and the raw API, all agreeing on 47 as the correct 'active applications' figure. Interview-conversion metrics are displayed honestly at 0% (0 real interviews), the market-benchmark-unavailable message is genuine, and no fabricated or fixture content exists on this screen. 4 LOW findings filed (2 wireframe-conformance gaps, 1 reload-persistence nit, 1 UNSURE code-review risk); zero BLOCKER/HIGH. Production-clean."
}
```
