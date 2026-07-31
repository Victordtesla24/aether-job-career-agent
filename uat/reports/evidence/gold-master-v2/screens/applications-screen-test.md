# GOLD-MASTER-V2 §3.2 — Screen Test: Application Tracker (`/dashboard/applications`)

- Production: `https://5cb5f0620.abacusai.cloud`
- Tester: screen-tester agent (Playwright, headless Chromium 1.61.1, one browser at a time)
- Test window: 2026-07-31T00:15Z – 2026-07-31T00:45Z (all timestamps below are UTC unless noted)
- Identities used: **Owner** (`admin`/`admin123` → `sarkar.vikram@gmail.com`, `isAdmin:true`) and **New user**
  (`gm2-nonadmin-1785454990@example.com`, id `c56667cb7661a0cfef18ada20`, `isAdmin:false`, verified via fresh
  `/api/auth/me` call at test time)
- Evidence root: `uat/reports/evidence/gold-master-v2/screens/applications/` (32 screenshots, indexed §8)
- Scripts used to drive Playwright (kept for repro, not part of the product): `/tmp/.../scratchpad/gm2-apps/test*.js`
  (scratchpad, not committed)

Every check below was run to completion at least once, and every finding was **re-verified in a second, fresh
session** (new `chromium.launch()` / new curl process with a freshly-issued token) before being filed — see the
"re-verify" line under each finding.

---

## 1. Element inventory (Board view, owner account)

| Element | data-testid / selector | Exists | Notes |
|---|---|---|---|
| View tabs (Board/Sankey/Timeline/Applied) | `view-board`, `view-sankey`, `view-timeline`, `view-applied` | ✓ | all 4 clicked |
| Filter menu (All / Match≥85 / Match<85 / Needs approval) | `filter-btn` + `role=menuitemradio` | ✓ | all 4 options clicked |
| Sort menu (Latest / Match score / Company A–Z) | `sort-btn` + `role=menuitemradio` | ✓ | all 3 options clicked |
| Clear Pipeline button + confirm gate | `clear-pipeline-btn`, `clear-pipeline-gate`, `-cancel`, `-confirm` | ✓ | opened + **canceled** (destructive; see §6) |
| Auto-apply banner | `auto-apply-banner` | ✓ | static, reflects live `agentConfig` |
| Pending-approvals banner (link) | `pending-approvals-banner` | ✓ | clicked through to `/dashboard/approvals` |
| 8 kanban columns | `kanban-column-{discovered,evaluating,tailoring,ready,submitted,in-review,interview,offer}` | ✓ | all present |
| Application card | `application-card` | ✓ | 41 cards total (owner) |
| Card → detail panel | click on card / inner `<button>` | ✓ | opens `application-detail-panel`, closes via `×` |
| Per-card "Move to…" menu | `move-menu-btn`, `move-option-{stage}` | ✓ | **keyboard-operated end to end**, see §3 |
| Per-card native HTML5 drag | `draggable="true"` on `<article>` | ✓ (attr present) | mouse-driven drag **did not** fire the handler in 2 methods, see §3 |
| "Mark as submitted" (detail panel, draft only) | `mark-submitted-btn` | code-present | **not reachable** — no draft-stage card currently on board (§6) |
| "Request approval" (Ready column card) | `request-approval-button` | code-present | **not reachable** — Ready column has 0 cards currently (§6) |
| Closed strip | `closed-strip` | code-present | **not reachable** — 0 rejected/withdrawn applications exist (§6) |
| Sankey Flow view | `sankey-view` | ✓ | loads `/applications/funnel/sankey` |
| Timeline view | `timeline-view` | ✓ | 38 items, sorted by `updatedAt` |
| Applied view | `applied-view` | ✓ | 9 articles, all badge `applied` (see Finding ML-APP-003) |

---

## 2. Visual conformance vs `design/screens/application-tracker.html`

[VERIFIED-WITH-FRESH-EVIDENCE `03-owner-applications-board.png`, `03b-viewport-only.png`, 2026-07-31T00:16Z]

Layout, typography, glass-card styling, per-stage dot colours/icons, and the auto-apply banner all match the
wireframe closely. Expected, intentional divergences (confirmed against source, not bugs):

- Subtitle reads "**N pipeline items across 8 stages**" instead of the wireframe's literal "37 active
  applications across 8 stages" — deliberate per code comment (`MV-adv-A-001` in `page.tsx`) to avoid overloading
  "applications" with two different numbers app-wide.
- "Clear Pipeline" button and per-card "Move to…" control do not exist in the static wireframe — both are later
  additions (FEAT-CLEAR, FEAT-B2) beyond the original mock, functioning correctly.
- Auto-apply threshold shown is **50%** (this account's configured `matchThreshold`), not the wireframe's
  hardcoded 85% — correct, account-driven behaviour.
- Avatar initials reflect the logged-in account, not the wireframe's "VD".

One real layout divergence found — see **Finding ML-APP-004**.

---

## 3. Gate G-F — stage-move (priority)

### 3.1 Can a user move a card? — YES, via an accessible per-card menu

[VERIFIED-WITH-FRESH-EVIDENCE `14-move-menu-open-keyboard.png` … `20-after-reload-restored.png`, network capture
`step3-movenetwork.json`, 2026-07-31T00:17:42Z–00:17:50Z; **re-verified** a second time via `test4-dragdrop.js`'s
cleanup pass at 00:2xZ using the same keyboard path]

Keyboard-only reproduction (mouse never used):
1. `locator('[data-testid="move-menu-btn"]').focus()` → `document.activeElement.dataset.testid === 'move-menu-btn'` ✓
2. `Enter` → `aria-expanded="true"` on the button, menu (`role="menu"`) visible ✓
3. `Tab` → focus lands on `move-option-ready` (first legal target); `Tab` again → `move-option-in-review`, etc.
   (menu items are plain `<button>`s in natural DOM tab order — no roving-tabindex trap, no keyboard dead-end)
4. `Enter` on `move-option-in-review` → fires `POST /applications/{id}/move {"to_stage":"in-review"}` → **200**,
   response body `status:"screening"`
5. Board updates immediately: Submitted 38→37, In Review 0→1 (no reload needed)
6. **Reload** → counts persist (37 / 1), card renders under "In Review" with correct title/company (persistence
   confirmed, not just an optimistic client update)
7. Same keyboard path used to move the card **back** to Submitted → 200, Submitted 38 / In Review 0 restored,
   reload-confirmed

This satisfies §8.1: the affordance is **not** drag-only. `menu_move_exists = true`, `keyboard_operable = true`.

### 3.2 Drag-and-drop — UNSURE (see Finding ML-APP-005)

Two independent mouse-driven attempts against the same card, both **failed to trigger any network call**:
- Playwright `locator.dragTo(column, {force:true})` (uses CDP native-drag dispatch) — 0 `/move` calls,
  counts unchanged [`21-after-dragto-attempt.png`, `step4-results.json`]
- Manual `page.mouse.down()` → 12-step granular `mouse.move()` with 60ms pauses → `mouse.up()` — 0 `/move` calls,
  counts unchanged [`24-after-manual-mouse-drag-retry.png`, `step4b-results.json`]
- Control: a raw DOM-level dispatch of `dragstart`/`dragover`/`drop` `DragEvent`s with a real `DataTransfer`
  (bypassing mouse-gesture initiation entirely) **did** fire the move correctly — 200, counts updated, persisted
  on reload [`22-after-manual-dispatch-dnd.png`, `step4-results.json`]

Interpretation A (bug): real mouse users cannot drag cards in production — some overlay/event-order issue
prevents native HTML5 drag initiation. Interpretation B (tooling limitation): Chromium headless's native-drag
simulation is unreliable even via CDP, and a real user with physical mouse hardware would succeed where
Playwright's synthetic gesture did not. I could not distinguish these with the tools available. Filed as
**UNSURE (ML-APP-005)** with both interpretations. Not a blocker regardless, because the keyboard "Move to…" path
(§3.1) is a fully independent, fully functional affordance — the feature is not drag-only.

`drag_move_works = false` (both rigorous attempts failed; reported as verified-false for the mouse path
specifically, with the UNSURE caveat above).

### 3.3 One-click quick action ("Mark as In Review" / "Complete")?

**No.** Code review (`apps/web/src/app/dashboard/applications/page.tsx`) confirms no single-click stage-advance
button exists on a card. The only card-level actions are the "Move to…" menu (2 interactions: open, then pick)
and, for Ready-stage drafts only, a "Request approval" re-request button (a different action, not a stage move).
`quick_action_exists = false`.

### 3.4 Illegal transitions — server-side enforced, honest 422s

[VERIFIED-WITH-FRESH-EVIDENCE, curl, 2026-07-31T00:2xZ; **re-verified in a fresh session with a freshly-issued
token** at 00:4xZ — identical results]

Legal matrix (from `apps/api/app/routers/applications.py:209-230`, confirmed live): application cards move freely
forward/backward among `ready↔submitted↔in-review↔interview↔offer` (any direction, same-stage is a no-op); job
cards move freely among `discovered↔evaluating↔tailoring`. Crossing the split, or targeting an unknown stage, is
rejected:

| Attempt | Result | Body |
|---|---|---|
| app card → `discovered` (job-fed) | **422** | `"Stage 'discovered' is Job-status-fed — a application card cannot move there..."` |
| app card → `tailoring` (job-fed) | **422** | same shape |
| app card → `evaluating` (job-fed, re-verify pass) | **422** | same shape |
| app card → `bogus-stage` (unknown) | **422** | `"Unknown stage 'bogus-stage'..."` |
| empty body `{}` | **422** | Pydantic `"Field required"` on `to_stage` |
| unknown application id | **404** | `"Application not found"` |

After every illegal attempt, `GET /applications/{id}` was re-fetched and confirmed **unchanged** (`status:
"submitted"` throughout) — no partial/silent writes. The UI never offers an illegal target in the first place
(`moveTargetsFor()` filters client-side to the legal set, confirmed by inspecting every rendered menu — no
Discovered/Evaluating/Tailoring option ever appeared on an application card's menu), so this path is only
reachable by calling the API directly, exactly as intended (defence in depth, not a UI bug).

`illegal_move_server_rejected = true`.

**Not tested (data unavailable):** moving a **closed** (rejected/withdrawn) application. The owner account
currently has **zero** rejected/withdrawn applications (`GET /applications?include_applied=true` returns none),
so the `_CLOSED_STATUSES` 422 guard (`applications.py:351-356`) could not be exercised live. [INFERRED FROM CODE
ONLY] — not a finding, just a coverage gap caused by the current data set.

### 3.5 Counts vs Sankey/funnel reconciliation — **FALSE**, see Finding ML-APP-003

My own live move (3.1) reconciled correctly in real time (Submitted/In-Review counts and the underlying data
moved together). However the **pre-existing** data has a standing, reproducible mismatch between the Board's "In
Review" column (shows **0**) and the Sankey's "Screened" node (shows **2**) for two genuinely `screening`-status
applications. Full detail in Finding ML-APP-003. `counts_reconcile = false`.

### 3.6 Audit log

[VERIFIED-WITH-FRESH-EVIDENCE `GET /api/admin/audit-log`, 2026-07-31T00:17:50Z]

Every move produced an audit row with actor, target, and a `{from, to, to_stage}` detail, e.g.:
```json
{
  "actorUserId": "c6c8d0163d973a8048e7e33b8",
  "action": "application.stage_move",
  "targetType": "application",
  "targetId": "c4865aeb927b498aedafabc50",
  "detail": {"to": "submitted", "from": "screening", "to_stage": "submitted"},
  "createdAt": "2026-07-31T00:17:50.747648+00:00"
}
```
Both the forward move (submitted→screening) and the reverse (screening→submitted) each produced their own row,
correctly ordered and timestamped. `audit_row_created = true`.

---

## 4. Findings

| id | severity | category | summary |
|---|---|---|---|
| ML-APP-001 | **BLOCKER** | data hygiene / fixture leak | Test-suite fixture text (`GAP-P7-DEF-B Probe 1785452243543`) is the signature on a **real, live, pending** cover-letter approval for Grafana Labs, reachable from this screen's pending-approvals banner |
| ML-APP-002 | HIGH | data integrity / UX | RT-004 per-job dedup silently hides superseded `draft` Application rows that still have a live pending approval — the "Needs approval" filter can never surface them even though the pending-approvals banner correctly counts them |
| ML-APP-003 | HIGH | data integrity / UX | 2 real `screening`-status applications are invisible on the Board's "In Review" column (shows 0), miscounted as generic "applied" in the Applied tab, yet correctly counted (2) in the Sankey — 3 self-contradictory numbers on one screen |
| ML-APP-004 | MEDIUM | visual/layout | Kanban columns use default flexbox stretch — every column is forced to the height of the tallest (4382px, measured), producing ~4700px of near-empty scroll on both desktop and mobile |
| ML-APP-005 | LOW / UNSURE | interaction | Mouse-driven native HTML5 drag-and-drop did not fire in 2 rigorous automated attempts; low-level DOM event dispatch proves the handlers are wired correctly, so this may be a Playwright/headless-Chromium limitation rather than a real bug — not a blocker since the keyboard Move-menu is a full, working alternative |
| ML-APP-006 | LOW / INFO | data / config | "Match ≥ 85" filter can never return results for this account (all live scores are 24.89–45.54 in the default view); separately the account's own auto-apply threshold (50%) differs from this hardcoded UI filter cutoff (85) — not a bug, just a note |

### ML-APP-001 — BLOCKER: fixture/probe content in a live pending approval

- **Reproduction:**
  1. As owner, `GET /api/approvals?status=pending` → entry `id=cd8c0a3e0382fae35a68be0d3`, `company: "Grafana
     Labs"`, `payload.preview` ends `"...I am available for a call at your convenience.\n\nSincerely,\nGAP-P7-DEF-B
     Probe 1785452243543\n"`.
  2. In the UI: Applications Tracker → pending-approvals banner ("N items need your review → open the Approvals
     queue") → `/dashboard/approvals` → "Review" on the Grafana Labs card → modal renders the full letter; DOM
     text content contains `GAP-P7-DEF-B` (confirmed via `page.evaluate` on rendered `document.body`).
  3. `GAP-P7-DEF-B` is a known test-suite fixture identifier: `apps/web/e2e/gap_p7_def_b.spec.ts`,
     `apps/api/tests/test_gap_p7_def_b_persist.py`, `apps/api/tests/test_gap_p7_def_b_email_validation.py`,
     `docs/delivery/archive/PHASE7-GAP-ANALYSIS.md`.
- **Expected:** no test/fixture content ever reachable on a user-facing production path.
- **Observed:** a real user reviewing their pending approvals (one click from this screen) sees a cover letter
  signed with a QA-probe identifier instead of their name, on an approval that is otherwise indistinguishable
  from genuine AI-agent output (84% confidence, real reasoning checks, real job posting).
- **Evidence:** `31-approvals-queue-fixture-evidence.png`, `32-approvals-review-expanded-fixture.png`, API
  payload capture (`step2/step7` curl output).
- **Re-verify (fresh session):** re-queried `/api/approvals?status=pending` with a freshly-issued token — entry
  still present, `GAP-P7-DEF-B` still in the preview, at 2026-07-31T00:4xZ (a *third* pending item, unrelated,
  had also appeared by then from other concurrent test activity on this shared production account — does not
  affect this finding).
- **Note on scope:** the review modal itself lives on `/dashboard/approvals`, a different screen in the SCREEN
  MATRIX. It is reported here because the *only* discovery path tested was this screen's own pending-approvals
  banner, and the underlying data (the pending `ApprovalRequest` + its `Application` row) is inseparable from
  Finding ML-APP-002 below, which **is** squarely this screen's defect.
- **Status:** OPEN

### ML-APP-002 — HIGH: superseded draft applications are invisible and unfilterable

- **Reproduction:**
  1. `GET /applications/c15369eafaad7210d65151a6d` (owner) → `status:"draft"`, `jobId:
     c0642f2dc8cbc53209d95421d` (Grafana Labs) — the same fixture-content application from ML-APP-001.
  2. `GET /applications` (default board query) does **not** include this id — the board's own
     `DISTINCT ON (jobId) ... ORDER BY status-rank DESC` (`applications.py:144-161`) collapses it because a
     newer, higher-ranked `submitted` Application already exists for the same `jobId` ("Grafana Labs" appears
     once in the Submitted column, confirmed via the company-sort screenshot).
  3. On the Board, `filter=needs-approval` → 0 cards, even though the pending-approvals banner reads "N items
     need your review." Root cause: `pendingApprovalIds` contains the **hidden** draft's id
     (`c15369eafaad7210d65151a6d`), but the only card actually rendered for that job carries the **different**,
     visible Application's id — so `cardMatchesFilter()`'s `pendingApprovalIds.has(card.app.id)` can never be
     true for this item (`tracker-lib.ts:294`).
- **Expected:** either the Ready-to-Apply column surfaces every application genuinely awaiting the user's
  approval, or the "Needs approval" filter/banner pair stay consistent with what's actually visible on the board.
- **Observed:** the banner and the filter disagree — a real, resolvable action item is unreachable from the
  Board view's own filter tool, and only escapable via the cross-screen banner link.
- **Evidence:** `06-filter-needs-approval.png` (0 cards) vs `step1-results.json` (`"pendingApprovalsBanner": "1
  item needs your review..."`), API captures above.
- **Re-verify (fresh session):** repeated the filter click + API cross-reference in `test7-banner-link-evidence.js`
  (separate browser instance) — same result.
- **Status:** OPEN

### ML-APP-003 — HIGH: In-Review column, Applied tab, and Sankey disagree about the same data

- **Reproduction:**
  1. `GET /applications?include_applied=true` (owner) → 2 rows with `status:"screening"` (Deputy, Plenti — job
     ids `cf7936fe7ce5d24cc16dc184a`, `c40090ef033bb2408e524bcdb`), both with `fitScore` 42.0 and 50.05.
  2. Board view: `kanban-column-in-review` count = **0**, 0 cards.
  3. Applied tab: both jobs appear as articles, but the status chip is a **hardcoded literal "applied"**
     (`page.tsx:1090-1093`, no conditional on real `status`) — confirmed both `appliedBadgeTexts` entries read
     `"applied"` and `appliedViewMentionsScreening === false` even though `appliedViewMentionsDeputy` /
     `...Plenti === true`.
  4. Sankey Flow: "Screened" node = **2** (`funnel_sankey()` counts `status IN (screening,interview,offer)`
     regardless of `Job.status`, unlike the board's default listing which excludes `Job.status='applied'`).
- **Root cause:** `submit_application` advances `Job.status` to `'applied'` on submission; a later stage-move to
  `screening` only touches `Application.status`, so the job becomes permanently excluded from the default board
  query (`applications.py:126-131`) while still being live progress a user would want to see.
- **Expected:** a user's real interview-pipeline progress (2 applications now at "In Review") should be visible
  somewhere on the board with its real label, and the same number should read consistently across this screen's
  own 3 views.
- **Observed:** 0 (Board) vs "applied" (Applied tab, wrong status) vs 2 (Sankey) — three different answers to "how
  many of my applications are in screening?" on one screen.
- **Evidence:** `01`-series network JSON (`step1-results.json` column counts), `11-applied-view.png`,
  `09-sankey-view.png` (Screened: 2), curl captures above.
- **Re-verify (fresh session):** re-ran `GET /applications/funnel/sankey` with a fresh token — still
  `screened: 2` — while the board column count (fresh page load, separate context) was still 0.
- **Status:** OPEN

### ML-APP-004 — MEDIUM: kanban columns force-stretch to the tallest column's height

- **Reproduction:** `page.evaluate(() => [...document.querySelectorAll('[data-testid^="kanban-column-"]')].map(c
  => c.getBoundingClientRect().height))` on the owner's board → **all 8 columns measured exactly 4382px**,
  `document.body.scrollHeight = 4715px`, even though 6 of the 8 columns render only an "Empty" placeholder or 3
  short cards.
- **Cause:** the columns' parent (`<div class="flex w-max gap-4">` in `page.tsx`) uses the flexbox default
  `align-items: stretch` with no `items-start` override, so every `<section>` column is stretched to match
  Submitted (the tallest, with 25 rendered cards).
- **Expected:** each column's height should reflect its own content (wireframe intent: compact, independently-
  sized columns).
- **Observed:** ~4700px of page height, most of it blank space inside near-empty columns, on both desktop
  (`03-owner-applications-board.png`) and mobile 390px (`25-mobile-390-applications.png`, 6473px tall) — a
  distracting, unnecessary scroll for real production data volumes.
- **Evidence:** `03-owner-applications-board.png`, `03b-viewport-only.png` (visible even within one viewport —
  "Empty" boxes already oversized), DOM height measurement above.
- **Re-verify:** re-measured in a second, independent script run — identical 4382px across all 8 columns.
- **Status:** OPEN

### ML-APP-005 — LOW / UNSURE: mouse-driven drag-and-drop did not trigger in automated testing

See §3.2 for full detail and both interpretations. Evidence: `21-after-dragto-attempt.png`,
`24-after-manual-mouse-drag-retry.png` (both 0 network calls, unchanged counts) vs `22-after-manual-dispatch-
dnd.png` (raw DOM DragEvent dispatch succeeded, 200, counts updated, reload-persisted). **Not filed as a
blocker** because §8.1's drag-only-affordance condition does not apply here (a fully keyboard-operable
alternative exists and works). **Status: OPEN, tagged UNSURE** — recommend a human confirm with a physical mouse
before treating this as a real defect.

### ML-APP-006 — LOW / INFO: "Match ≥ 85" filter structurally empty for this account; threshold mismatch

Not a code defect — scores are real and match the API exactly (see §5) — but worth recording: every one of the
owner's 38 default-view scores falls in 24.89–45.54 (avg 38.65), so the wireframe-inherited 85-point "high-fit"
filter cutoff can never match anything for this account, while the account's own configured auto-apply threshold
(shown in the banner directly above the filter) is 50%. Two different "high fit" numbers, neither reachable via
the filter. **Status: OPEN (informational)**.

---

## 5. ATS/fit score verification (gates G-J / G-C)

[VERIFIED-WITH-FRESH-EVIDENCE `step5-results.json`, 2026-07-31T00:2xZ]

- `GET /applications` (owner): 38/38 rows have a non-null `fitScore`; **min 24.89, max 45.54, avg 38.65**
  (task's stated ground truth: 24.89–50.05, avg 39.63 — the 50.05 max belongs to the Plenti application, which is
  `screening`-status and therefore excluded from this default listing per Finding ML-APP-003; restricting to the
  same default-view population the board itself renders, the observed range/avg is consistent).
  Non-default view (`include_applied=true`) recovers the Plenti row and its 50.05 score exactly.
- Card-rendered scores (`Math.round(fitScore)`) cross-checked against 25 rendered Submitted-column cards — 1:1
  match, e.g. Peloton `fitScore:35.82` → card renders "36" (`Math.round(35.82) = 36`, correct); Samsara
  `fitScore≈34.x` → "34"; etc. No mismatches found. `score_shown = true`.

---

## 6. Deliberately not exercised (data-unavailable or destructive-action scope decisions, not human-gated)

These are disclosed for completeness; none are "human-gated" in the strict §5-schema sense, but all represent
real coverage limits and are reported honestly per protocol:

1. **Closed-application illegal-move 422** — no rejected/withdrawn application currently exists in the owner
   account to exercise `_CLOSED_STATUSES` (server code reviewed, not live-tested). [INFERRED FROM CODE]
2. **"Clear Pipeline" final confirm** — the gate was opened, its copy/labels verified, and **canceled**
   deliberately rather than confirmed, because confirming would irreversibly archive the 3 real live
   Tailoring-stage jobs currently in this production account. The affordance up to (but not including) the
   irreversible POST was fully tested.
3. **"Mark as submitted" button** and **"Request approval" re-request button** — both are code-present
   (`page.tsx:821-831`, `:287-299`) but currently unreachable: the Ready-to-Apply column has 0 visible cards
   (the one real draft is the same superseded row hidden by Finding ML-APP-002).
4. **Closed strip rendering** — 0 rejected/withdrawn applications exist, so the strip never renders; its code
   path (`page.tsx:985-1003`) was reviewed but not visually exercised.
5. **Real pending-approval Approve/Reject** — never clicked, per the "do not transmit to a real third party /
   don't destroy real data" rule; only "Review" (read-only expand) was used.

---

## 7. Console / network / other checks

- **Console errors/warnings:** **0** across all sessions — owner board load, owner interaction pass (filter/sort/
  views/move/drag), new-user paywall load, and two unauthenticated-access loads. `console_errors: []`.
- **Page errors (uncaught exceptions):** 0.
- **Network — no optimistic-success on failure:** every illegal/adversarial move (§3.4) returned its real HTTP
  status (422/404) and the board never showed a false-positive state change; the one client-side rollback path
  in `moveCard()` (revert `apps`/`jobs` state on a caught error) was not exercised live because the UI never
  offers an illegal target — confirmed dead-code-but-safe by inspection.
- **Realtime refresh (gate G-I):** confirmed **20-second poll**, paused implicitly whenever
  `document.visibilityState !== 'visible'` (code) — live-observed repeat `GET /applications`, `/jobs`,
  `/approvals?status=pending`, `/workspaces/settings` firing at **t≈20.876s** after page mount in a 35s watch
  window (`step5b-allcalls.json`). `realtime_interval_ms = 20000`.
- **Mobile 390px overflow:** **none** on `/dashboard/applications` (`scrollWidth === clientWidth === 390`) despite
  the column-height issue (ML-APP-004) making the page very tall — no *horizontal* overflow. `overflow_390px =
  false`.
- **`/dashboard/approvals` at 390px (rg-mob-appr baseline claim check):** loaded in **1261ms**, no timeout, no
  horizontal overflow (`26-mobile-390-approvals.png`). The stated Playwright baseline failure ("approvals page
  times out at mobile viewport") **did not reproduce** — either already fixed, flaky, or environment-specific;
  reported as a contradiction of the cited baseline, not a new finding.
- **Unauthenticated access:** `/dashboard/applications` while logged out → HTTP 200 on the shell, immediate
  client redirect to `/login?next=%2Fdashboard%2Fapplications` (clean login page, no data leakage); confirmed in
  2 independent fresh sessions (`00-unauth-access.png`, `29-unauth-fresh-session-2.png`). Direct API call with no
  token → `GET /api/applications` → **401**.
- **New user (non-admin) empty/first-run state:** the account is genuinely unsubscribed
  (`GET /api/billing/entitlement` → `active_paid:false, requiresSubscription:true`), so this screen shows a full
  **paywall** ("Subscribe to unlock Aether", feature list, "View plans & subscribe" CTA, "browse pricing"/"manage
  account" links) instead of an empty Kanban board — `27-newuser-applications-paywall.png`. Judged honestly: the
  paywall copy is clear and not deceptive, and correctly explains *why* the board isn't shown; however it means
  **100% of genuine first-time free users see a paywall on this screen, never the empty-board state** the
  wireframe implies exists. 0 console/page errors on this path either.

---

## 8. Screenshot index (`uat/reports/evidence/gold-master-v2/screens/applications/`)

| File | Description |
|---|---|
| 00-unauth-access.png | Unauthenticated redirect to `/login?next=...` |
| 01/02-login-*.png | Login page, filled |
| 03-owner-applications-board.png | Full-page board, owner, initial load |
| 03b-viewport-only.png | Same, viewport-only crop (shows column-stretch bug within 900px) |
| 04–08 | Filter menu, high-fit filter (0 results), needs-approval filter (0 results), sort menu, company sort |
| 09-sankey-view.png | Sankey Flow (Screened: 2) |
| 10-timeline-view.png | Timeline view |
| 11-applied-view.png | Applied tab (generic "applied" badges) |
| 12-clear-pipeline-gate.png | Clear Pipeline confirmation modal (canceled, not confirmed) |
| 13-detail-panel.png | Application detail panel |
| 14–20 | Keyboard-driven Move-menu: open → focus item → after move → after reload → move back → after reload (restored) |
| 21–24 | Drag-and-drop attempts: Playwright dragTo (failed), manual DOM dispatch (worked), cleanup restore, manual granular mouse drag (failed) |
| 25/26 | Mobile 390px: `/dashboard/applications`, `/dashboard/approvals` |
| 27-newuser-applications-*.png | New user: paywall state |
| 30/31/32 | Pending-approvals banner → Approvals queue → expanded fixture-content evidence (ML-APP-001) |

---

## 9. Return-schema summary

```json
{
  "artifact": "uat/reports/evidence/gold-master-v2/screens/applications-screen-test.md",
  "drag_move_works": false,
  "menu_move_exists": true,
  "keyboard_operable": true,
  "quick_action_exists": false,
  "illegal_move_server_rejected": true,
  "counts_reconcile": false,
  "persists_after_reload": true,
  "audit_row_created": true,
  "score_shown": true,
  "console_errors": [],
  "realtime_interval_ms": 20000,
  "overflow_390px": false,
  "findings": [
    {"id": "ML-APP-001", "severity": "BLOCKER", "desc": "Test-fixture signature (GAP-P7-DEF-B) in a live pending cover-letter approval reachable from this screen"},
    {"id": "ML-APP-002", "severity": "HIGH", "desc": "Superseded draft applications with a live pending approval are hidden by per-job dedup and unreachable via the Needs-approval filter"},
    {"id": "ML-APP-003", "severity": "HIGH", "desc": "Board In-Review column (0), Applied tab badge (\"applied\"), and Sankey Screened count (2) disagree about the same 2 real applications"},
    {"id": "ML-APP-004", "severity": "MEDIUM", "desc": "Kanban columns flex-stretch to the tallest column (measured 4382px on all 8), producing ~4700px of near-empty scroll"},
    {"id": "ML-APP-005", "severity": "LOW", "desc": "UNSURE: mouse-driven native drag-and-drop did not fire in 2 automated attempts; keyboard Move-menu works fully so not a blocker"},
    {"id": "ML-APP-006", "severity": "LOW", "desc": "INFO: Match>=85 filter structurally empty for this account's real score range; differs from account's own 50% auto-apply threshold"}
  ],
  "verdict": "Core FEAT-B2 stage-move capability is genuinely solid: a fully keyboard-operable per-card Move-to menu works end-to-end with correct server enforcement (honest 422s for illegal/unknown targets), real persistence, and complete audit logging (BLOCKER-tier concerns from the brief are NOT present for the move mechanism itself). However this screen has one automatic-BLOCKER data-hygiene issue (test-fixture content on a live user-reachable approval) plus two HIGH-severity self-consistency defects where the Board, Applied tab, and Sankey/funnel disagree about the same underlying data (both traceable to the Job.status='applied' exclusion filter and per-job application dedup). A MEDIUM layout bug makes the board unpleasantly tall with real data. New users hit a paywall, not an empty board, before ever seeing this screen's board state. Zero console/network wiring defects found. NOT production-clean until ML-APP-001..003 are addressed."
}
```
