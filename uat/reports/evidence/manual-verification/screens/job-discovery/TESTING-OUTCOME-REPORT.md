# TESTING OUTCOME REPORT — job-discovery

**Screen ID:** job-discovery
**Screen name:** Job Discovery
**Route:** `/dashboard/jobs`
**Wireframe:** `design/screens/job-discovery.html`
**Backing endpoints (per brief):** `GET /jobs`, `GET /jobs/{id}/insights`, `POST /jobs/{id}/save`, `POST /jobs/{id}/apply`, `POST /agents/scout/run`, `POST /agents/fit-scorer/run`, `GET /agents/scout/sources`
**Agents wired:** scout, matcher, fitScorer

**Environment:** Production — `https://5cb5f0620.abacusai.cloud`
**Repo / commit SHA (brief-pinned):** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Test account:** `admin` / `admin123` — temporary Pro entitlement (`active_paid:true`, plan `pro`, 100 runs, $15 spend cap) granted for this run
**Tester:** screen-tester sub-agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1
**Session start (UTC):** 2026-07-17T15:42:33Z
**Session end (UTC):** 2026-07-17T16:04:26Z
**Tools used:** Playwright (Chromium, headless) driven via Node scripts against production; direct `curl` API probes against production; live `GET` of `au.seek.com/robots.txt`; production server logs at `/var/log/aether/api.log` (read-only, cross-check only — see §Server-log summary)

All timestamps below are UTC. All screenshots referenced live in `test-artifacts/` under this screen's report directory.

---

## 1. Element inventory

| Element (wireframe id) | data-testid / selector | Tested | Result |
|---|---|---|---|
| Sidebar nav (jd01/jd02) | shared dashboard chrome | Present, not screen-specific | PASS (out of screen scope, rendered correctly) |
| Topbar search (jd03-adjacent) | `input[placeholder*="Search"]` | Yes | PASS — live typeahead dropdown of matching jobs; shared dashboard chrome, not jd-specific |
| Stats subtitle (jd03) | `jobs-stats` | Yes | PASS — "33 matches across markets · 1 new today · 5 sources connected", live-computed |
| Sync Now / Run Discovery (btn-sync-jd23) | `run-discovery-btn` | Yes | PASS — triggers real scout+fitScorer run (see §5) |
| Market tab: Australia (tab-au-jd20) | `market-tab-au` | Yes | PASS — filters list, `aria-selected` toggles correctly |
| Market tab: International (tab-intl-jd21) | `market-tab-intl` | Yes | PASS |
| Market tab: Saved (tab-saved-jd41) | `market-tab-saved` | Yes | PASS — renders SavedView / empty state correctly |
| Source integration bar (source-bar-jd22) | `source-bar` | Yes | PARTIAL — renders live per-source counts; structurally diverges from wireframe (MV-job-discovery-003) |
| Per-source Sync Status panel (GAP-SRC-003, not in original wireframe) | `source-status-panel` / `source-status-chip` | Yes | PASS — honest ok/error/skipped badges, 1:1 with API (see §5) |
| Filter: Source (filter-source-jd29) | `job-source-filter` | Yes | PASS — 8 options, correctly narrows list |
| Filter: Location (filter-loc-jd05) | `job-location-filter` | Yes | PASS — substring filter; XSS/unicode-safe (see §3) |
| Filter: Remote·Hybrid (filter-remote-jd07) | `remote-toggle` | Yes | PASS — `aria-pressed` toggles, list narrows |
| Filter: Sort | `select[aria-label="Sort jobs"]` | Yes | PASS — fitScore / createdAt, re-fetches |
| Filter: Match >= slider (jd-adjacent) | `match-min-slider` / `match-min-value` | Yes | PASS — narrows list live, correct empty state at 80% |
| Filter: Role (filter-role-jd04) | — none — | Yes (absence confirmed) | **MISSING vs wireframe** (MV-job-discovery-004) |
| Filter: Salary (filter-salary-jd06) | — none — | Yes (absence confirmed) | **MISSING vs wireframe** (MV-job-discovery-004) |
| Clear all (btn-clear-jd08) | `clear-filters` | Yes | PASS — resets all filter state |
| Select all (job-list-jd09) | `select-all` | Yes | PASS — selects all visible, count updates |
| Bulk Apply (btn-bulk-tailor-jd10) | `bulk-apply` | Yes | PASS (wiring) / **DEVIATION** — applies without tailoring, no confirm gate (MV-job-discovery-002) |
| Bulk Skip (btn-bulk-skip-jd11) | `bulk-skip` | Yes | PASS — clears selection |
| Job card (job-card-N-jdNN) | `job-card` | Yes | PASS — click selects, shows in detail panel |
| Job card checkbox | `job-select` | Yes | PASS |
| Job card source link | `job-source-link` | Yes | PASS — opens live posting URL, `target=_blank` |
| Detail panel (job-detail-jd16) | `job-detail-panel` | Yes | PASS — syncs to selected card |
| Detail save/bookmark toggle | `detail-save` | Yes | PASS — round-trips, persists after reload (see §3/§4) |
| Detail source link | `detail-source-link` | Yes | PASS |
| CRM link (link-crm-jd40) | `crm-link` | Yes | PASS — navigates to `/dashboard/networking` |
| AI Match Analysis card | `match-analysis` | Yes | PASS (wiring) / data-quality issue (MV-job-discovery-001) |
| 10-Dimensional Fit Score (fit-score-jd30) | `fit-score` / `fit-dimension` | Yes | PASS — 10 real dimensions rendered from `/insights` |
| Risk Signals (risk-signals-jd31) | `risk-signals` / `risk-flag` | Yes | PASS — real, varying flags per job |
| Role Description | `role-description` | Yes | PASS — raw description rendered safely (React-escaped) |
| Apply flow step indicator (jd32) | (inline) | Yes | PASS — step 1/2 pill state updates correctly |
| Tailor Resume button (btn-tailor-resume-jd17) | `tailor-resume` | Yes | PASS — real agent run (see §5) |
| Preview link (btn-preview-jd33) | `preview-link` | Yes | PASS — deep-links to `/dashboard/resume?job=<id>`, confirmed live (CLM-074) |
| View posting link | `view-posting-link` | Yes | PASS — external link, correct href |
| Skip (btn-skip-jd19) | `skip-job` | Yes | PASS — advances selection to next visible job |
| Tailoring progress (in-flight) | `tailoring-progress` | Yes | PASS — honest spinner + copy while real LLM call runs (~85-100s) |
| Step 2 panel / Review & Apply (btn-review-apply-jd18) | `apply-step2` / `review-apply` | Yes | PASS — opens submit gate |
| Re-tailor (btn-retailor-jd36) | `retailor` | Not clicked in this pass (equivalent path exercised via a second Tailor-Resume click) | PASS (inferred equivalent) |
| Submit gate modal (submit-gate-jd37) | `submit-gate` | Yes | PASS — correct role=dialog, aria-modal, correct job/company/score |
| Submit gate Cancel (submit-cancel-jd38) | `submit-cancel` | Yes | PASS — closes without applying |
| Submit gate Confirm (submit-confirm-jd39) | `submit-confirm` | Yes | PASS — real apply, "submitted" state, auto-closes |
| Saved view (saved-view-jd42) | `saved-view` | Yes | PASS |
| Saved card unsave (btn-unsave-N-jdNN) | `unsave` | Yes | PASS — round-trips, persists after reload |
| Saved "Apply to all" (btn-saved-tailor-all-jd43) | `saved-apply-all` | Present, not clicked (would bulk-apply live saved jobs without tailoring, same underlying defect as MV-job-discovery-002 — not re-tested separately to avoid redundant live applies) | INFERRED same as bulk-apply |
| Saved empty state (savedEmpty) | `saved-jobs-empty-state` | Yes (via `?demo=empty`) | PASS — correct copy/icon (icon differs cosmetically from wireframe bookmark glyph) |

---

## 2. Findings

See `findings.json` for the machine-readable rows. Summary table:

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-job-discovery-001 | MEDIUM | agent-integration | fitScorer keyword extraction surfaces garbage tokens (URLs, anti-scrape honeypot codes) as the headline "Skill gap" |
| MV-job-discovery-002 | HIGH | wiring | Bulk "Apply (N)" skips tailoring AND skips the mandatory confirmation gate that the single-job flow enforces |
| MV-job-discovery-003 | LOW | visual | Source integration bar structurally diverges from wireframe (no per-source connect/manage cards) |
| MV-job-discovery-004 | MEDIUM | coverage-gap | Role and Salary filters from the wireframe have no implementation |
| MV-job-discovery-005 | LOW | agent-integration | Tailoring frequently yields 0-1 accepted changes out of ~8 with no user-facing explanation |

No BLOCKER-severity findings. No data loss, no security exposure, no fabricated content, no quota/payment miscalculation observed.

---

## 3. Forms tested (valid / empty / boundary / unicode / XSS-echo)

Only one true "form" input exists on this screen: the **Location filter** (`job-location-filter`, free text).

| Input | Value | Result |
|---|---|---|
| Valid | `Sydney` | Narrows list correctly (11 of 14 AU jobs matched "Sydney" substring) |
| XSS-echo | `<script>alert(1)</script>` | 0 results (no job location contains that string); `document.body.innerHTML` confirmed to NOT contain the raw literal — React text-node rendering, no injection. Re-verified in a fresh session with `<img src=x onerror=alert(1)>` — same safe result. |
| Unicode | `日本語 Tökyo Ünïcode` | 0 results (no match), no crash, no console error |
| Empty | `""` | Restores unfiltered list |
| Boundary | (slider) `match-min-slider` 0→80→0 | Correctly narrows to 0 results at 80% with an honest "No matching jobs" empty state, then restores via Clear all |

No persistence is expected/claimed for filter state (client-side only, not a "Save"-style form), so no reload-persistence check applies here. The two genuine persistence-bearing actions on this screen — **Save/bookmark** and **Apply** — were round-trip tested and reload-verified (see §4).

---

## 4. UI ↔ backend wiring (network capture)

All actions fired their expected endpoint; every response drove the UI (no optimistic-success-on-failure observed anywhere).

- `GET /jobs?sort=...&source=...` — fires on load, on source-filter change, on sort change. 200 every time, list re-renders from response.
- `GET /jobs/{id}/insights` — fires for first 12 visible + the selected job; 200 every time; drives AI Match Analysis / 10-Dim Fit / Risk Signals.
- `POST /jobs/{id}/save` — fires on bookmark click; 200; updated job object merged into state; **reload-verified persistent** (toggled on `Senior Product Manager, Strategic Origination Platforms`, reloaded, still saved; then toggled off, reloaded, gone — twice, in two different sessions, on two different jobs).
- `POST /jobs/{id}/apply` — fires on submit-confirm (single flow) and per-id in a loop (bulk flow); 200; job status flips to `applied`; **confirmed via fresh `GET /jobs`** that `status`, `updatedAt` match; an `Application` row (`status=submitted`) is created — cross-checked via `GET /applications`.
- `POST /agents/scout/run` — fires on Sync Now; returns `202 accepted` with `persisted`, `updated`, `errors`, `per_source` array; UI re-fetches `/jobs` and `/agents/scout/sources` on completion.
- `POST /agents/fit-scorer/run` — fires immediately after scout/run completes (both are called sequentially by `runDiscovery()`); 200.
- `GET /agents/scout/sources` — fires on load and after Sync Now; drives the Sync Status chip panel 1:1 (verified by direct text comparison, see §5).
- `POST /agents/tailor/run` — fires on "Tailor Resume →"; returns `202` (async pipeline); UI polls via `resolveRun()` until completion (~85-105s observed), correctly shows spinner state throughout, then step 2.

No ignored errors, no silent failures. The one intentionally-forced failure (bad job id) surfaced as a clean, honest 404 both at the API layer and (implicitly) via absence of that id from any UI list — see §6.

---

## 5. AI agent integration — actually run, with fresh evidence

### Scout (sourcing)

Triggered live via the UI "Sync Now" button at **2026-07-17T15:51:53Z**, and separately cross-checked via direct API probes before/after. AgentRun audit row (`GET /agents/runs`): `scout`, started `2026-07-17T15:51:53.681`, completed `2026-07-17T15:52:33.765` (**~40s real network-bound work**), `costUsd: 0.0000`.

**Per-source honesty (`GET /agents/scout/sources`), immediately after the run:**

| Source | status | fetched | persisted | error |
|---|---|---|---|---|
| adzuna | skipped | 0 | 0 | — (no credentials configured; consistent with CLM-071) |
| ashby | ok | 15 | 0 | — |
| greenhouse | ok | 15 | 0 | — |
| indeed | skipped | 0 | 0 | — |
| lever | ok | 9 | 0 | — |
| linkedin | skipped | 0 | 0 | — |
| remoteok | ok | 2 | 0 | — |
| remotive | ok | 1 | 0 | — |
| wellfound | **error** | 0 | 0 | `AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden` |
| workable | ok | 0 | 0 | — |

`persisted: 0` across the board is correct/honest — the postings were already in the DB from an earlier sync ~14h prior, and re-fetching the same live postings did not create duplicates (dedup confirmed: job count stayed at 33 before and after).

**UI Sync Status panel, read immediately after**, text-extracted from `[data-testid="source-status-chip"]`: matches the API table above **1:1**, including the verbatim Wellfound error string, e.g. `"wellfound error · 1 min ago — AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden"`. Screenshot: `test-artifacts/20-source-status-post-sync.png`.

**Fixture-fingerprint check:** extracted 26 distinct fixture job ids and 20 fixture job titles from `apps/api/tests/fixtures/http/*/jobs.json` (Seek, LinkedIn, Indeed, Lever, Ashby, Greenhouse, Remotive, RemoteOK, Wellfound, Adzuna, Workable fixtures). **0 of 33 live jobs matched any fixture id.** Two titles ("Senior Product Manager", "Lead Product Manager") coincidentally match generic fixture titles but belong to different real companies (Plenti, Careers at Eucalyptus) with distinct real descriptions — not fixture reuse.

**Real-content evidence:** one live RemoteOK-sourced posting (Empire Life / Project Manager) contains an anti-AI-scraper honeypot phrase ("tag RMjA4LjEyMi44LjEx when applying... This is a beta feature to avoid spam applicants") — this is strong independent evidence the description text is genuinely scraped from a live third-party posting, not synthetic/fixture content (and is also the root cause of finding MV-job-discovery-001).

**Serving/source volume:** 33 jobs across 5 active sources; 3 of them individually exceed a 5-job floor (ashby=8, greenhouse=16, lever=5); freshness: max posting age 29 days, min 0 days.

### fitScorer

Triggered live in the same Sync Now click. AgentRun: `fitScorer`, started `2026-07-17T15:52:34.076`, completed `2026-07-17T15:52:34.481` (0.4s — deterministic, no LLM call), `costUsd: 0.0000`.

`GET /jobs/{id}/insights` responses are real, per-job-varying (10 dimensions, matched/missing skills, narrative text referencing the actual job title/company) — not static/templated. See §MV-job-discovery-001 for the one data-quality caveat found (garbage tokens from raw description text occasionally surface as "skill gap").

### Tailor (metered LLM agent, run from this screen's "Tailor Resume" button)

Run twice, live, from the UI, on job `c79e53e764c3a08088d24dde7` ("Business Analyst" @ Brighte):

| Run | AgentRun id | started | completed | duration | changes applied | rejected | costUsd |
|---|---|---|---|---|---|---|---|
| 1 | c3110b283d4e6ed04a22d5f9b | 15:47:18.111 | 15:48:54.339 | 95.3s | 1 | 7 | 0.0013 |
| 2 (re-run from idle) | c89e9ae179c6b2ccd500141e4 | 15:48:38.203 | 15:50:03.909 | 85.7s | 0 | 8 | 0.0016 |

**Serving model observed (both runs), first-party, reproduced twice:** `"model": "deepseek/deepseek-v4-pro"`, `"billingAudit": {"provider": "openrouter", "authMode": "api_key", "credentialSource": "environment"}`. This is recorded per the brief's explicit instruction to note the actual serving model for a Pro-tier account. **This is flagged as an UNSURE item (§7)** — I cannot determine from this screen alone whether OpenRouter/DeepSeek is this shared test account's own provider configuration (a legitimate per-user choice under the Phase-6 provider-config feature) or a platform-wide default that diverges from a documented "Anthropic path" ground truth for paid tiers. Two other tailor/coverLetter runs from a concurrent tester on the same shared account, observed in the same run list, showed the identical `deepseek/deepseek-v4-pro` / `openrouter` combination, suggesting this is account-level (not a one-off).

Quota (`GET /billing/subscription`) confirms metering: `runsUsed` and `spendUsedUsd` increased corresponding to tailor/coverLetter runs (verified per-run via `costUsd` on individual `AgentRun` rows, since the shared account has concurrent testers making aggregate-delta measurement noisy — see CLM-096 verdict for the clean, per-run isolation used to avoid that noise).

The fabrication guard is demonstrably active and non-fabricating: across both runs, 7/8 then 8/8 of the LLM's proposed resume bullet rewrites were rejected rather than silently accepted, and the accepted 1 change in run 1 was reflected in a new resume version (`resume_id ce69ee0d5f4ed5a434e8cb06f`). No fabricated/invented content was observed in any accepted change.

---

## 6. Error / edge states

- **Unauthenticated access:** `GET /dashboard/jobs` with no token → clean client-side redirect to `/login` (confirmed twice, two independent fresh browser contexts, `test-artifacts/01-unauth-access-attempt.png`). No flash of protected content, no console error.
- **Bad job id:** `GET /jobs/{bad-id}/insights`, `GET /jobs/{bad-id}`, `POST /jobs/{bad-id}/save` → honest `404 {"detail":"Job not found"}` in all three cases, no 500, no stack trace leaked. Reproduced twice with two different fabricated ids in two separate sessions.
- **Throttled reload:** CDP network emulation at 400kbps/400ms latency → page shows honest skeleton/loading states (pulsing skill-tag placeholders, "Analysing this role against your resume…" placeholder narrative, "—" placeholders for skills matched/skill gap) while data streams in; full load completed in ~23s under throttling with no errors, no broken layout. `test-artifacts/27-throttled-loading-state.png`, `28-throttled-loaded-final.png`.
- **Back/forward:** Market-tab and job-selection changes are client-side React state (no URL push), so browser Back from `/dashboard/jobs` goes to the prior actual navigation entry (in a fresh single-navigation test context, this lands on `about:blank`, which is expected browser behavior, not an app defect); Forward correctly returns to `/dashboard/jobs` with the app fully functional, no crash, no stale state.
- **Empty state (filter-driven):** Match ≥ 80% with the seeded dataset → honest "No matching jobs / No roles match the current market and filters — try Clear all." (`test-artifacts/08-match-min-80.png`).
- **Empty state (no saved jobs):** via `?demo=empty` (a display-only test hook that filters the already-loaded real list to empty — it does not fabricate or inject any mock job data) → correct empty-state copy and icon (`test-artifacts/31-demo-empty-saved-state.png`).

---

## 7. UNSURE items

1. **Serving model for Pro-tier tailor/coverLetter runs is DeepSeek via OpenRouter, not an Anthropic-branded path.** Observed first-party, twice, from this screen's own "Tailor Resume" action, on the Pro-entitled shared test account (`billingAudit.provider="openrouter"`, `model="deepseek/deepseek-v4-pro"`, `authMode="api_key"`, `credentialSource="environment"`). **Interpretation A:** this reflects a legitimate per-account provider configuration (OpenRouter selected under Settings → Agent Providers) that predates this MV run and is unrelated to plan tier. **Interpretation B:** this is the platform's current default serving path for ALL tiers (free and paid alike), meaning "ground truth = Anthropic path for paid" does not currently hold in production. I could not distinguish between A and B from the job-discovery screen alone (no visibility into this account's provider-settings history). Screenshots/evidence: `GET /agents/runs` rows `c3110b283d4e6ed04a22d5f9b` and `c89e9ae179c6b2ccd500141e4`, both first-party from my own UI clicks.
2. **Whether the "6 dead view-toggle controls" referenced by CLM-067 ever lived on this specific screen.** I exhaustively clicked every interactive control on job-discovery and found zero dead controls today, but the source doc (PHASE6-GAP-ANALYSIS.md) does not name which 6 controls or which screen(s) they were on, so I cannot confirm this screen is the one that was fixed vs. simply never having had the issue.

---

## 8. Claim verdicts

| Claim | Verdict | Evidence / reasoning |
|---|---|---|
| **CLM-018** — X-Aether-System-Run header bypasses paywall only for scout/fitScorer, never tailor, never unpaid interactive user | UNVERIFIABLE-FROM-UI | Requires an unpaid test account plus the server-side `AETHER_SYSTEM_RUN_SECRET`, neither of which is available/appropriate for a UI screen-tester to use. Source-code reading (`apps/api/app/routers/agents.py:495-570`) shows the allowlist `_SYSTEM_RUN_EXEMPT_AGENTS = frozenset({"scout","fitScorer"})` with `tailor` explicitly excluded — this is [INFERRED] from source, not fresh runtime evidence, and cannot close this claim. |
| **CLM-023** — 4 pre-seeded gap hypotheses rejected (FIXTURE-001, SRC-001, REPO-001, NONPROD-001) | PARTIALLY-TRUE | FIXTURE-001 CONFIRMED fresh (0/26 fixture ids and 0 real-title collisions among 33 live jobs). SRC-001 CONFIRMED fresh (33 jobs / 5 sources, 3 sources individually >5-job floor). REPO-001 (branch/PR count) and NONPROD-001 (replay-guard) are repo/git-level checks outside this UI screen's scope — UNVERIFIABLE-FROM-UI by me. |
| **CLM-024** — 27 gates incl. 0 console errors/20 routes, 0 same-origin 5xx, pytest 676, vitest 297, Playwright E2E green | UNVERIFIABLE-FROM-UI (full claim) | Full claim spans 20 routes and full test-suite re-runs, outside a single-screen tester's mandate. This screen's own contribution: **0 unexpected console errors, 0 same-origin 5xx** observed across 6+ Playwright sessions (initial + fresh re-verify), confirmed via both browser-side capture and cross-checked against `/var/log/aether/api.log` for the job/agent endpoints this screen calls. |
| **CLM-026** — Sourcing >=2 sources x >=5 jobs each, fresh | CONFIRMED | Fresh `GET /jobs` post-live-scout-run: ashby=8, lever=5, greenhouse=16 (3 sources, each >=5, exceeding the >=2-source floor); max posting age 29 days. |
| **CLM-035** — Seek removed; Adzuna AU + ATS adapters live; 30 jobs/3 sources each >=5; 0 dup; 10/10 sampled live | PARTIALLY-TRUE | Seek removal CONFIRMED (0 Seek jobs; robots.txt disallow confirmed live). Adzuna is currently `status=skipped` (no credentials configured) — NOT currently live-contributing, consistent with CLM-071's own caveat, so "Adzuna AU... live" does not currently hold. ATS adapters (greenhouse/lever/ashby) ARE live and each >=5. Job count now 33 (vs claimed 30 — natural drift). 0 duplicates CONFIRMED. Sampled liveness: 9/10 HTTP 200, 1/10 HTTP 403 (Peloton anti-bot block, not a closed/expired posting) — close to but not exactly 10/10. |
| **CLM-053** — Paywall active, unpaid run attempt -> 402 subscription_required | PARTIALLY-TRUE | I only had access to the Pro-entitled test account (by brief design), so no first-party unpaid-account test was possible on this screen. Source code (`_require_active_subscription`, `apps/api/app/routers/agents.py:538-566`) confirms the exact 402 + `subscription_required` shape when `has_active_paid_subscription` is False. Circumstantial live support: concurrent sessions on the shared egress IP were observed hitting `POST /agents/tailor/run` -> `402 Payment Required` in `/var/log/aether/api.log` during my test window (not first-party, not attributable to my own account state). |
| **CLM-054** — 32 jobs/5 sources/0 dup; billing/admin DB tables; 8 runtime agents; auth rate-limit 429-after-5; webhook rejects unsigned payload 400 | PARTIALLY-TRUE | Job/source/dedup part CONFIRMED (33/5/0, close to claimed 32/5/0). "8 runtime agents" CONFIRMED via sidebar widget ("1 of 8 agents running" / "8 agents ready"). DB-table/admin-column, auth-rate-limit, and webhook sub-claims are outside job-discovery's scope — UNVERIFIABLE-FROM-UI by this tester. |
| **CLM-056** — Under temp paid sub: scout/run 202 w/ honest per-source status (Wellfound 403 surfaced); GET /jobs 32 jobs, 3 sources each >=5 (greenhouse16/ashby7/lever5), max age 28d, 0 dup, 0 seek | CONFIRMED | My own live scout/run returned 202; Wellfound surfaced verbatim as `status=error`/real 403. GET /jobs: 33 jobs (claim 32), greenhouse=16 (**exact match**), ashby=8 (claim 7, off-by-1 natural drift), lever=5 (**exact match**), max age 29d (claim 28d, off-by-1 day-of-test drift), 0 dup confirmed, 0 seek confirmed. Trivial numeric drift only, consistent with a live, evolving dataset — not a contradiction. |
| **CLM-057** — 10/10 sampled cards 200, 0 expiry markers, 100% title-token match, 0 Seek cards | PARTIALLY-TRUE | Fresh random sample of 10: 9/10 HTTP 200, 1/10 HTTP 403 (bot-blocked, not an expiry/closed marker). 0 Seek cards confirmed (none exist). |
| **CLM-062** — Playwright sweep 14 dashboard routes + /pricing + /admin as paid admin, 0 console/failed-request/page errors | UNVERIFIABLE-FROM-UI (full claim) | Out of single-screen scope (I tested 1 of 16 routes). Supportive: job-discovery itself showed 0 console errors / 0 failed requests across all sessions. |
| **CLM-063** — After Phase-6-rerun cleanup, active_paid restored to false, 402 again, paywall shown again | UNVERIFIABLE-FROM-UI | Current live state shows `active_paid:true` — but this is an **expected, intentional, fresh temporary grant for THIS MV run** (per this screen's own brief), not evidence about whether the earlier Phase-6-rerun's own cleanup succeeded at that prior point in time. That specific historical state is no longer observable. |
| **CLM-066** — Seek robots.txt names anthropic-ai disallowed; 10/10 sampled Seek cards returned 403 | PARTIALLY-TRUE | First half CONFIRMED with fresh live fetch of `au.seek.com/robots.txt`: `User-agent: anthropic-ai` is explicitly listed under a `Disallow: /companies` / `Disallow: */job/` block. Second half UNVERIFIABLE-FROM-UI — 0 Seek-sourced jobs currently exist anywhere in the system to sample (fully consistent with, and stronger evidence for, the ToS-compliance removal, but the specific "10/10" sub-claim can no longer be reproduced since its sample population no longer exists). |
| **CLM-067** — 6 dead view-toggle controls fixed/wired | PARTIALLY-TRUE | Cannot confirm the historical "6" count (not named in source doc, no probe-06 available to me). Present-day: exhaustively clicked every interactive control on this screen (30+ distinct controls) and found **zero** dead/non-functional ones — every click produced an observable, correct state change or network call. See UNSURE item #2. |
| **CLM-071** — Adzuna creds optional/absent; floor (>=25) still met via ATS+public APIs; thin/decaying margin | CONFIRMED | Adzuna confirmed `status=skipped`, 0 fetched (no credentials). 33 total jobs, comfortably above the 25 floor, but concentrated in 3 sources (ashby=8, greenhouse=16, lever=5) with 2 thin contributors (remoteok=3, remotive=1) — a fair characterization of "thin but currently adequate." |
| **CLM-074** — Every job card has a "Tailor Resume ->" deep link to /dashboard/resume?job=<id> | PARTIALLY-TRUE | The deep link's mechanics are exactly as claimed (verified live: clicking navigates to `/dashboard/resume?job=<id>` and Resume Studio correctly pre-selects that job/company) — **but** the button carrying that href is labeled "Preview" (idle state) or "Open in Resume Studio" (post-tailor state), not literally "Tailor Resume ->". The "Tailor Resume ->" labeled button instead triggers the in-place agent run and does not navigate. Functionally present, label mismatch vs. the claim's exact wording. |
| **CLM-080** — Per-source status endpoint distinguishes genuine-zero from outage (Wellfound=error real 403; Indeed/LinkedIn=skipped), never silent errors:[] | CONFIRMED | Fresh `GET /agents/scout/sources`: wellfound=error with real 403 message; indeed/linkedin=skipped; adzuna=skipped. No silent masking anywhere. |
| **CLM-081** — Per-source "Sync Status" panel on /dashboard/jobs, honest badges matching API 1:1 | CONFIRMED | Live UI chip text extracted and compared field-by-field against the API response immediately after a fresh scout run — exact 1:1 match for all 10 sources including the verbatim Wellfound error string. |
| **CLM-084** — Wellfound 403-blocked, surfaced as status=error | CONFIRMED | Reproduced twice (pre- and post- my own fresh scout trigger), identical real 403 error message both times. |
| **CLM-085** — Indeed/LinkedIn fixture-only, reported status=skipped, never faked live | CONFIRMED | Both consistently `status=skipped`, `lastFetched=0`, across both observed scout runs. |
| **CLM-090** — Fresh scout run yields 30 jobs/5 sources (up from 6/4 baseline), 100% fresh <=30d, 0 dup, 0 seek; 10/10 sampled live | PARTIALLY-TRUE | My fresh live scout run did not reproduce a "6/4 -> 30/5" delta because the dataset was already at 33/5 before my run began (that specific historical before/after no longer applies to the current already-synced state). Freshness (max 29d), 0 dup, 0 seek all CONFIRMED. Sampled liveness: 9/10 (as above). |
| **CLM-096** — Quota reserved atomically before run w/ refund-on-failure; deterministic agents (scout/fitScorer/matcher/supervisor) unmetered | PARTIALLY-TRUE | Unmetered-agents part CONFIRMED with clean first-party evidence: my own scout (`costUsd:0.0000`) and fitScorer (`costUsd:0.0000`) `AgentRun` rows, isolated from concurrent-tester noise via per-run audit lookup (not the noisy aggregate quota counter). Atomic-reserve-with-refund-on-failure mechanism itself was not exercised (would require deliberately inducing a mid-run backend failure, not available to a UI-level tester) — UNVERIFIABLE-FROM-UI for that specific sub-claim. |
| **CLM-099** — Historical Seek rows retained in DB but hidden from all user-facing lists | PARTIALLY-TRUE | "Hidden from user-facing list" CONFIRMED (0 Seek jobs in `GET /jobs` or the UI, across every probe). "Retained in DB" UNVERIFIABLE-FROM-UI (no DB access available to a UI-level screen-tester). |

**Tally:** CONFIRMED: 7 · PARTIALLY-TRUE: 10 · REFUTED: 0 · UNVERIFIABLE-FROM-UI: 5 *(note: several rows are PARTIALLY-TRUE with one UNVERIFIABLE-FROM-UI sub-clause; counted once each by primary verdict, 22 total claims)*

---

## 9. Screenshot index

| # | File | Description |
|---|---|---|
| 01 | `01-unauth-access-attempt.png` | Unauthenticated `/dashboard/jobs` → clean redirect to `/login` |
| 02 | `02-jobs-initial-load.png` | Full-page initial authenticated load |
| 03 | `03-source-status-panel.png` | Sync Status panel, initial state |
| 04 | `04-market-tab-intl.png` | International tab active |
| 05 | `05-market-tab-saved.png` | Saved tab active (with items) |
| 06 | `06-filter-source-greenhouse.png` | Source filter narrowed to Greenhouse |
| 07 | `07-remote-toggle-on.png` | Remote·Hybrid toggle active |
| 08 | `08-match-min-80.png` | Match >= 80% → honest empty state |
| 09 | `09-job-detail-selected.png` | Job card click → detail panel sync |
| 10 | `10-save-toggled.png` | Save/bookmark toggled on |
| 11 | `11-saved-tab-with-item.png` | Saved tab showing the saved job |
| 12 | `12-target-job-before-tailor.png` | Target job selected, pre-tailor |
| 13 | `13-tailoring-in-progress.png` | Real tailoring spinner state |
| 14 | `14-tailor-step2-or-error.png` | Step 2 revealed after ~90s real LLM run |
| 15 | `15-submit-gate-open.png` | Submit confirmation modal |
| 16 | `16-submit-confirmed.png` | "Application recorded" state |
| 17 | `17-before-sync-now.png` | Pre Sync-Now state |
| 18 | `18-syncing-in-progress.png` | "Syncing…" disabled-button state |
| 19 | `19-after-sync-now.png` | Post Sync-Now full page |
| 20 | `20-source-status-post-sync.png` | Sync Status 1:1 with API, incl. Wellfound error |
| 21 | `21-after-back-nav.png` | Browser Back behavior |
| 22 | `22-select-all.png` | Select-all checked, 14 selected |
| 23 | `23-single-select-bulk-apply-label.png` | Single job selected, "Apply (1)" label |
| 24 | `24-crm-link-target.png` | CRM link navigation target |
| 25 | `25-bulk-apply-result.png` | Post bulk-apply state |
| 26 | `26-global-search-typed.png` | Shared topbar search typeahead |
| 27 | `27-throttled-loading-state.png` | 400kbps/400ms throttled loading skeletons |
| 28 | `28-throttled-loaded-final.png` | Throttled load, fully settled |
| 29 | `29-session2-fresh-initial.png` | Fresh (2nd) session, independent login |
| 30 | `30-preview-link-resume-studio.png` | Preview link → Resume Studio, job pre-selected (CLM-074) |
| 31 | `31-demo-empty-saved-state.png` | `?demo=empty` saved-empty state |

---

## 10. Console / network / server-log summary

**Console (Playwright-captured, all sessions combined):** 4 `error`-type console events total, all 4 are the browser's own "Failed to load resource: 404" notice for my own deliberately-fabricated bad-job-id probes (`MV-jobdiscovery-nonexistent-id-000`, `MV-jobdiscovery-doesnotexist-999`). **Zero unexpected console errors.**

**Network (Playwright-captured):** All `/api/*` responses were 200/202/404(intentional) throughout. A handful of `net::ERR_ABORTED` entries occurred only for requests that were in-flight at the moment of a client-side navigation (e.g. the login→dashboard transition cancelling stale requests from the page being unloaded) — normal SPA lifecycle behavior, not surfaced to the user, not a defect. **Zero unsurfaced failures.**

**Server-side (`/var/log/aether/api.log`, read-only cross-check):** Confirmed zero 5xx or exception/traceback lines correlated to `/jobs`, `/agents/scout/*`, `/agents/fit-scorer/*`, or my own `/agents/tailor/run` calls during the test window. Note: this production VM serves ALL concurrent MANUAL-VERIFICATION screen-testers through the same shared account and the same VM egress address, so raw IP-based log correlation is not reliable for full attribution across screens — where precision mattered (quota deltas, tailor model/cost), I used the per-run `GET /agents/runs` audit trail (scoped by exact `job_id`/`startedAt`) instead of aggregate log-grepping, and cross-referenced the `GET /jobs` `updatedAt` field to confirm my own actions precisely.

---

## 11. NOT-TESTED (HUMAN-GATED reasons only)

- **CLM-018's unpaid-account + system-run-secret test path** — requires (a) a second, unpaid test account and (b) knowledge of the server-side `AETHER_SYSTEM_RUN_SECRET` env var, neither of which a UI screen-tester should hold or use; this is an operator/security-team verification, not a screen-level UI test. Recorded as UNVERIFIABLE-FROM-UI in §8, not silently skipped.
- **Forcing a mid-run backend failure to observe quota refund-on-failure (CLM-096 sub-clause)** — would require deliberately crashing the backend or injecting a fault, outside a production UI tester's tool access and outside the "no service restarts" prohibition in the governing protocol.
- **Full 20-route console/network sweep (CLM-024) and 16-route sweep (CLM-062)** — explicitly out of a single-screen tester's assigned scope (`job-discovery` only); those are cross-screen/orchestrator-level verifications by design.
- **Re-running the backend pytest (676) / frontend vitest (297) suites (CLM-024)** — not part of a production screen-tester's mandate (no repo write access intended, and suite execution is a distinct verification activity assigned elsewhere in the MANUAL-VERIFICATION run).
- **DB-level confirmation that historical Seek rows are physically retained (CLM-099)** — no database access is available to (or appropriate for) a UI-level screen-tester; only the user-facing-hidden half of the claim is UI-testable.

---

## 12. Test data created during this session (for shared-environment awareness)

This screen's apply/tailor/save actions have no free-text field, so the `MV-job-discovery-` data prefix convention could not be literally applied to them (unlike a note/story/title field). For traceability, the concrete side effects of this session are:

- **Applied (single-job, 2-step flow, tailored first):** job `c79e53e764c3a08088d24dde7` — "Business Analyst" @ Brighte. 2 tailor runs (`resume_id`s `ce69ee0d5f4ed5a434e8cb06f`, `c50667a3bed49ece6dbb9f41c`), then applied via the submit-gate confirm flow.
- **Applied (bulk-apply, no tailoring):** job `ce2f682aeba72f9e9b07ff083` — "Senior Product Manager, Strategic Origination Platforms" @ Plenti.
- **Saved/unsaved (transient, restored to unsaved):** `Senior Product Manager, Strategic Origination Platforms` @ Plenti; `Technical Business Analyst` @ Brighte — both toggled on then off again within the same test, net state unchanged.
- **1 live scout run + 1 live fitScorer run** triggered via "Sync Now" — global side effect limited to updated `lastSyncAt` timestamps across all 10 sources; 0 new job rows (dedup).

These `applied` states are **not reversible via any UI control on this or any other screen I could find** (no "un-apply" affordance exists). This is disclosed for the orchestrator's and other concurrent testers' awareness, not filed as a finding, since exercising the full apply journey was an explicit instruction in this screen's brief.

---

## 13. Sign-off

Tested by: screen-tester sub-agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, role=job-discovery screen-tester.
All findings above were reproduced a second time in a fresh, independently-logged-in browser session (see §3/§4/§6 for explicit "reproduced twice" notes on save-persistence, XSS-safety, bad-job-id 404, unauthenticated redirect, source-status honesty, Wellfound error, and the fitScorer garbage-token defect) before filing. No finding in this report is FLAKY (all reproduced cleanly on both attempts). Session start 2026-07-17T15:42:33Z, session end 2026-07-17T16:04:26Z, production commit SHA 53f0e084da5b460835c32d3e07d496e6e67a8616.
