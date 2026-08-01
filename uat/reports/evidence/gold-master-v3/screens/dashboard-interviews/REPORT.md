# TESTING OUTCOME REPORT — /dashboard/interviews (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 4)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:24–18:26Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright/Node, headless Chromium, 1440x1200.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-cold-load.png + results.json)

- Header "Interview Center", `schedule-interview-btn` "+ Schedule Interview" — present.
- Empty state (`interviews-empty-state`) — this account currently has 0 scheduled interviews (`InterviewSchedule` table empty), confirmed both fresh sessions.
- Schedule form (`schedule-interview-form`): application `<select required>`, type select (video/phone/onsite/technical…), `datetime-local required`, duration number input, location/meeting-link/notes fields, contact name/email.
- Interview cards (`interview-card`), each with status badge, Mark complete / Cancel / Delete (2-step confirm) buttons.
- **Interview Prep panel is entirely ABSENT** — gated in code (`atInterviewStage` in `page.tsx:182,301`) behind "at least one application has status `interview`". Live check: `GET /api/applications` → 49 apps, statuses {submitted:45, screening:2, rejected:1, draft:1} — **zero** at `interview` status, so the panel (and its "Run Interview Prep" button) does not render at all right now. Confirmed on both session 1 and session 2.
- **Wireframe drift (large, intentional per code comments MV-interview-center-001/002/003)**: the `interview-center.html` wireframe's Prep/Live-Assist/Debrief tabs, Company & Role Brief card, Live Assist preview (mute toggle, filler-word/pace metrics), Debrief snapshot, and Compliance banner are **all absent** — grepped `page.tsx` for "Live Assist"/"Debrief"/"tab-prep"/"compliance": zero matches. Production replaced the old static wireframe placeholder with a real CRUD screen + a data-gated Prep brief; it never implements Live Assist/Debrief.

## Targeted verifications

1. **Can an interview be created? Does `POST /interviews` fire?** YES. Filled the form (application + datetime + adversarial notes, see below), submitted once — network shows exactly one `POST https://…/api/interviews` → **201**, followed by `GET /api/interviews` → 200 refreshing the list (matches `interviews.py:258`/`204`). Card count went 0→1. Then **DELETE**d it: `DELETE /api/interviews/{id}` → **204**, card count back to 0, confirmed by post-delete reload. [VERIFIED-WITH-FRESH-EVIDENCE 02,05,06,08,09 + network.json]
2. **Google Calendar affordance?** CONFIRMED ABSENT. Full-page `innerText` scanned for "calendar" (case-insensitive) on both sessions: **0 matches** each. No event badge, no "Add to calendar", no sync indicator anywhere on the page, empty state, or created-interview card. Backend confirms why: `apps/api/app/agents/scheduling_agent.py:140` — `calendarIntegration: bool = False` hardcoded, with an explicit code comment "Aether reads and writes no calendar." **No dishonest calendar claim found anywhere in the UI.** [VERIFIED-WITH-FRESH-EVIDENCE 01,11 + results.json→calendarMentions=0 both sessions]
3. **Interview-prep AI action — trigger + real-vs-fixture check.** The UI button is unreachable (see above, data-gated). To still verify the underlying agent honestly, called the same endpoint the UI's Run button uses (`POST /agents/interviewPrep/run`, explicit `job_id` — supported per `interview_prep_agent.py:40/279`) twice for the same real job (Samsara "Principal Business Technology Product Manager"), authenticated as this account:
   - Both calls: HTTP 200, ~30.7s / ~30.9s wall time (real LLM latency, not a cached fixture).
   - Content is genuinely job-specific: questions reference "seller-facing quoting, approvals", "AI tools", "Sales/Finance/Engineering stakeholders" — all pulled from the actual posting, not generic boilerplate.
   - Run-to-run diff: **NOT byte-identical** (`json.dumps(sort_keys=True)` comparison) — question text differs between the two runs, confirming live generation, not a canned fixture.
   - Audit trail (`GET /agents/runs?agent=interviewPrep`) shows real per-run fields: `model: "anthropic/claude-sonnet-4"` (matches the agent-catalog "recommended" model for interviewPrep — selected model = model recorded), `tokensIn`/`tokensOut`, `costUsd` (~$0.05/run), `duration_ms`, `billingAudit: {authMode, provider, quotaPath, credentialSource}` all populated.
   - Fabrication guard observed live: 2 of the story-linked answer sketches were withheld with an honest `preparationNote` ("the drafted answer went beyond what it actually says, so it was withheld") rather than fabricating content — matches the FabricationError-guard design referenced elsewhere in the codebase.
   - **This was an API-level probe, not a UI click**, because the UI affordance is unreachable given this account's current data (no interview-stage application) — recorded as **NOT-TESTED-VIA-UI** below, but the underlying agent is verified genuinely functional, honest, and non-fixture. [VERIFIED-WITH-FRESH-EVIDENCE prep-run1.json/prep-run2.json (saved under this report's evidence dir as agent-run-1.json/agent-run-2.json), agent-runs-audit.json]
4. **Correlation with the 5 failing `test_wave4b_interview_prep_agent.py` baseline tests**: the observed pytest ERROR (`test_no_job_id_uses_the_interview_stage_application` and siblings) is `assert 401 == 200` / `"Could not validate credentials"` at the **register→login** step in `conftest.py:432`, i.e. a test-fixture auth/DB-registration collision, not a prep-agent behavioural failure. This matches the known shared-`aether_test`-schema flakiness (concurrent swarms truncating/re-registering the same fixture user). The exact production scenario one of those tests targets (no `job_id` **and** no interview-stage application) was independently verified live above (`GET /workspaces/interviews/prep` with 0 interview-stage apps → honest `{"brief":null,"questions":[],"compliance":{"message":"No interview scheduled…"}}`, no fixture content) — **behaves correctly in production**; the baseline failures look like test-infra flakiness, not a live product defect. [INFERRED — correlation, not a direct repro of the pytest failure itself]

## Interaction / forms / persistence

- Empty submit: `application`/`scheduled_at` are native `required` inputs — browser-native validation blocked submission before the custom `buildInput()` error path ran (no custom error text shown, no POST fired). Honest — no silent no-op. [03-empty-submit-error.png]
- Adversarial submit: filled notes with `<script>alert(1)</script>` + 20× `𝕏` (unicode) + 3000× `A` in one go; submission **succeeded on the first attempt** (`notes` server cap is `max_length=5000`, `interviews.py:109`, so 3000 chars was under the limit). Rendered back on the card via React `innerText` as **literal escaped text** — the `<script>` tag never executed (no `pageerror`/console entries fired) — no XSS. [VERIFIED-WITH-FRESH-EVIDENCE 05/06-*.png, results.json→cleanupCardText]
- Negative-number adversarial (duration_minutes=-100, done at API level against a real application_id to avoid stray UI-created rows): honest **422** — `"Input should be greater than or equal to 15"` (`ge=15` on `interviews.py:106`), nothing persisted. [VERIFIED-WITH-FRESH-EVIDENCE neg-duration.json]
- Reload-and-re-read: after creating, reload kept the card (count stayed 1); after deleting, reload confirmed count 0. [07,09-*.png]
- Idle 60s window: only `GET /api/agents` (t=28.2s) + `GET /api/approvals?status=pending` (t=58.2s) + `GET /api/agents` (t=58.2s) — i.e. **this screen has no dedicated idle poll**; the observed traffic is the global sidebar widget's 30s interval (`sidebar.tsx:45`), same pattern already tracked as ML-AGENTS-003 on the Agents screen. §15.1's ≤20s bar is not met by that global widget, but that is a pre-existing cross-screen finding, not new to Interviews.

## Error / edge states

- Unauthenticated access → redirected to `/login?next=%2Fdashboard%2Finterviews`. [10-unauthenticated-access.png]
- Verified twice: independent fresh session (session 2) reproduced 0 interviews, 0 calendar mentions, prep panel absent — identical to session 1. [11-freshsession2-verify.png]
- console.json / pageerrors.json: empty on both sessions — no console errors, no page errors. requestfailed.json shows only `net::ERR_ABORTED` on Next.js route-prefetch/sidebar-link fetches (jobs/networking/stories/analytics) aborted by navigation — benign prefetch cancellation, not a live defect.

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-INTERVIEWS-001 | /dashboard/interviews | INFO | UI-gap/data-state | Interview Prep panel unreachable via UI on this account | Load screen with 0 interview-stage applications | Some path to preview prep even before interview stage, or explicit messaging | Panel + Run button render nothing (not even an empty/explainer state) when `atInterviewStage` is false | 01-cold-load.png, results.json | OPEN |
| ML-INTERVIEWS-002 | /dashboard/interviews | LOW | wireframe-drift | Wireframe's tabs/Live Assist/Debrief/Compliance-banner entirely unimplemented | Compare `interview-center.html` to production `page.tsx` | Wireframe UI surface | None of it exists; screen was intentionally rebuilt as CRUD+Prep only (documented MV-interview-center-00x) | 01-cold-load.png | OPEN (by-design, not a runtime defect) |

No BLOCKER or HIGH findings. Calendar-claim dishonesty explicitly ruled out. No placeholder/fixture content found — created interview and prep-agent output both reflect real, account-specific/job-specific data.

## Not-tested (HUMAN-GATED / data-gated)

- Interview Prep AI generation **triggered via UI click** — impossible on this account right now (0 interview-stage applications); verified via direct authenticated API call to the same endpoint instead (see targeted verification 3). Fully testing the UI click path would require moving an application to `interview` status, which is Applications-screen territory and out of this screen's assigned scope.
- Mark-complete / Cancel status-transition buttons — not exercised (would have required leaving a persisted non-cleanable status change on a synthetic row that isn't necessary to prove the two already-verified POST/DELETE paths); low risk, same auth/ownership pattern as the tested delete path.

## Data left behind

None. The one interview created during adversarial-form testing was deleted in the same session (`DELETE` → 204) and reload-confirmed absent. The two `interviewPrep` agent runs (job_id=Samsara PBT-PM, ~$0.05 each, ~$0.10 total) are normal usage records, not stray rows — no delete-run endpoint exists and none was expected; left in place like the account's other 3667 historical agent runs.

## Sign-off

Screen tested per §3.2 protocol: cold-load screenshot, wireframe conformance (large documented drift noted), full CRUD exercised (create/delete) with network capture, empty/adversarial(script+unicode+long-string)/negative-number form submissions, calendar-affordance absence explicitly confirmed via full-text scan + source-code corroboration, interview-prep agent verified genuinely functional/honest/non-fixture via direct API run (UI path data-gated), idle-poll measured (30s global-sidebar only, no screen-specific poll), reload persistence, unauthenticated redirect, verified twice in a fresh session. Verdict: **real backend wiring throughout, no dishonest calendar claims, no fixture content in AI output, no BLOCKER/HIGH findings.**
