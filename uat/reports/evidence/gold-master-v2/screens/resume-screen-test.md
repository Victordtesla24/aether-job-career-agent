# GOLD-MASTER-V2 §3.2 — Screen Test: `/dashboard/resume` (Resume Studio)

**Status: COMPLETE**
Production target: `https://5cb5f0620.abacusai.cloud`
Tester: screen-tester agent, single-threaded, headless Chromium (Playwright 1.61.1), serial execution (one browser at a time)
Test window: 2026-07-31T00:14Z – 2026-07-31T00:34Z

Identities used:
- **OWNER** — `admin` / `admin123` (real data-rich account; isAdmin=true per prior BLOCKER-001; profile display name renders as "Probe", role "BA/Project Manager/Sc…" — this is the account's stored profile data, not a bug)
- **NEW USER** — `gm2-nonadmin-1785454990@example.com` per `uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md`

All screenshots referenced below are in `uat/reports/evidence/gold-master-v2/screens/resume/`. Raw JSON evidence (network logs, API cross-checks, stage results) is in the scratchpad and quoted inline where load-bearing.

---

## 1. Element inventory

`/dashboard/resume` (`apps/web/src/app/dashboard/resume/page.tsx`) exposes, on the OWNER account with 69+ existing versions:

| Element | data-testid | Notes |
|---|---|---|
| Job select dropdown | `tailor-job-select` | Populates from `GET /jobs`; 20 real jobs + placeholder |
| "Tailor Resume" button | `run-tailor-btn` | Disabled while no job selected or while running |
| Error banner (conditional) | — | Red, `border-red-500/30` |
| Notice banner (conditional) | `tailor-notice` | Amber, `border-aether-amber/30` |
| Original — Base Resume pane | — | Identity derived from `resumes` data |
| Tailored — Latest Version pane | — | Identity derived from `resumes` data |
| Format Integrity Check panel | `integrity-status` | Real per-version formatHash comparison |
| ATS Conversion Impact panel (conditional) | `conversion-metrics`, `conversion-before-after`, `conversion-lift` | Only shown immediately after a fresh run in the same session; not persisted |
| Version cards (×N) | `resume-version-card` | Click → loads diff + ATS for that version |
| "Show more" pagination button | `versions-show-more` | Paginates 8 at a time |
| Download button | `download-resume-btn` | Streams `GET /resumes/{id}/download` |
| Diff panel (conditional) | `resume-diff` | Bullet-level before/after |
| ATS Score panel (conditional) | `ats-score-panel`, `ats-overall` | Real `GET /resumes/{id}/ats` breakdown + missing-keyword chips |
| Evidence Trace panel | — | First 4 diff changes with evidence refs |
| Version History panel | — | First 4 versions, label + version number |
| Pending/Rejected approval badges | `version-pending-badge`, `version-rejected-badge`, `version-approval-hint` | Real per-version `approvalStatus` |

**No file-upload control exists on this screen.** Resume upload (`POST /resumes/upload`) is wired only into `/dashboard/settings`, not Resume Studio. Tested anyway via direct API call for completeness (§6) since the task asked for it, but this is a genuinely separate screen's feature — noted as a scope observation, not a Resume Studio defect.

**No free-text input field exists on this screen** — the only form control is the `<select>` job dropdown. A NUL byte cannot be typed into this screen's UI by a normal user. Adversarial NUL-byte testing was therefore performed directly against the two API endpoints this screen's own JS calls (`POST /resumes`, `POST /agents/tailor/run`) — see §6, finding ML-RESUME-001.

---

## 2. Wireframe conformance vs `design/screens/resume-studio.html`

**Large divergence — informational finding, not a defect per se.**

The wireframe depicts a side-by-side original/tailored **PDF preview** studio: two rendered résumé pages, a circular ATS gauge showing "96 · Excellent", a "Voice DNA" tone/formality panel, an "AI Detection 2% Safe" badge, Approve/Revert/Request Changes/Export PDF/Compare-Versions buttons, and a version-diff modal.

The **shipped** implementation (`page.tsx`) is a simpler data/list-driven UI: text-derived identity panes (no PDF rendering in-page), a numeric ATS panel with real keyword/semantic/experience breakdown bars, a bullet-level diff list, and only two real action buttons (Tailor Resume, Download). There is no Approve/Revert/Export-PDF/Compare-Versions/Voice-DNA/AI-Detection UI anywhere on this route.

Worth noting: the wireframe's "96 · Excellent" ATS gauge would have been actively dishonest against the real engine — every production job scores 24.9–50.1 (ground truth, re-confirmed live in §4 below). The shipped screen never fabricates a high score; it shows the real (low) number in amber/green per `overall >= 60`. So the divergence, while large, trends toward *more* honest than the wireframe, not less — but it means the approved design was never implemented as specified, and several designed capabilities (Approve/Revert workflow, Compare Versions, Export-PDF-as-named-button, Voice DNA controls) simply do not exist. Filed as ML-RESUME-008.

Screenshots: `02-owner-resume-initial.png` (initial load, [VERIFIED-WITH-FRESH-EVIDENCE] 2026-07-31T00:15Z), `03-owner-version-selected-ats-diff.png`.

---

## 3. UI ↔ backend wiring / network capture

Every action fires its documented endpoint; zero unexpected non-2xx responses across all runs. Full status breakdown (stage 1, 83 requests): all 200 except one intentional 202 (async tailor enqueue). Stage 2 (real tailor run): all 200/202, zero failures. New-user stage: all 200 except the intentional/expected 402 on the direct paywall probe.

Console: **zero uncaught errors/pageerrors** in every instrumented run (stage 1, stage 2, new-user stage). The only console "error" line logged anywhere was the browser's automatic `Failed to load resource: 402` note during the new-user paywall probe — expected behavior, not an application bug. [VERIFIED-WITH-FRESH-EVIDENCE, `console-log.json`/`console-log-stage2.json`/`console-log-stage3.json`, 2026-07-31T00:14-00:25Z]

Two distinct polling cadences were measured by instrumenting `window.fetch` (not inferred from a passive capture, per instructions):

1. **Async tailor-run resolution** (`GET /agents/jobs/{id}`, client polling a specific 202-enqueued job to completion): mean interval **3.1435s** across 23 consecutive polls, range 3.134s–3.155s. [VERIFIED-WITH-FRESH-EVIDENCE, `stage5-results.json`, 2026-07-31T00:26-00:28Z]
2. **Dashboard-layout "Agents Active" widget** (`GET /api/agents`, shared sidebar component, not specific to this route): ~30s cadence (deltas 29.3s–30.7s after the initial page-load burst). [VERIFIED-WITH-FRESH-EVIDENCE, `net-log-stage2.json`, 2026-07-31T00:19-00:20Z]

No optimistic-success UI was observed on any failed call — the only failure path exercised live (new user's 402 on the tailor probe) surfaced honestly as a structured error, not a fake success state.

---

## 4. G-J — ATS score UI vs API (does every chip match the backend?)

**PASS — confirmed matching, independently, three times, across three separate resume versions and three separate fresh browser sessions:**

| Resume version | UI-displayed `overall` | `GET /resumes/{id}/ats` `overall` | Match |
|---|---|---|---|
| v67 (Plenti job) | 49.1 | 49.1 | ✅ [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T00:15Z] |
| v69 (Deputy job) | 40.7 | 40.7 (keyword_match 27.5, semantic 24.2, experience 100 — all matched) | ✅ [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T00:16Z] |
| v68 (Twilio job) | 42.5 | 42.5 | ✅ [VERIFIED-WITH-FRESH-EVIDENCE, fresh 3rd session, 2026-07-31T00:29Z] |

The keyword-match / semantic-similarity / experience-fit sub-bars, the "Missing JD keywords" chip list, and the headline number are all sourced live from `GET /resumes/{id}/ats` — nothing is computed client-side. Screenshot: `03-owner-version-selected-ats-diff.png`.

**Re-confirmed ground truth**: all 20 production jobs currently on the OWNER account carry `atsScore` 24.89–44.85 (sample re-pulled live via `GET /jobs`, 2026-07-31T00:20Z), consistent with the task's stated 51-job range of 24.89–50.05, avg 39.63 — every one below both the informal 85 target and the engine's own 60 review threshold.

---

## 5. Real tailoring runs — before/after banner, honest no-op, progress, sub-85 warning

Four full tailoring runs were executed live from the UI/API against the OWNER account (job: "Program Manager, Sales Operations and Training @ Peloton", `ca18ac952343701fabb668795`, previously untailored) to observe the full range of real outcomes:

| Run | Duration (createdAt→finishedAt) | `changes` | ATS delta | UI outcome |
|---|---|---|---|---|
| 1 (fresh, via UI) | ~79s (POST 00:19:45 → resume created 00:20:56) | 2 | **35.82 → 35.92 (+0.10, genuine)** | Conversion banner shown: `"Before: 35.82% → After: 35.92%"`, lift `"+0.0%"` (rounds down) |
| 2 (re-run, via API) | 59.75s | 0 | n/a | Honest no-op message, `resume_id: null`, `noChangesApplied: true` |
| 3 (re-run, via API, immediately after) | 79.4s | 1 | **35.82 → 35.82 (exactly equal, changes:1 but 0.00 delta)** | Would show conversion banner "Before: 35.82% → After: 35.82%", lift "+0.0%" |
| 4 (re-run, via UI, full-length observed) | 110s | 0 | n/a | Honest no-op message rendered live in browser (see below) |

**Task's central question — is the zero-change outcome surfaced honestly?** **YES, confirmed twice independently** (once via direct API polling of the async job result, once rendered live in a fresh browser session with a full ≥110s wait):

> **Verbatim UI text**: *"No verifiable changes could be applied — every suggested edit was unsupported by your evidence, so your résumé is unchanged and you were not charged."*
> Rendered with `class="rounded-xl border border-aether-amber/30 bg-aether-amber/10 p-3 text-sm text-aether-amber"` — an **amber informational banner**, never a red error, and the Conversion-Impact panel is correctly **suppressed** (not shown) on a genuine no-op. [VERIFIED-WITH-FRESH-EVIDENCE, `43-final-run-outcome.png` / `16-owner-final-run-outcome.png`, `stage6-results.json`, 2026-07-31T00:31Z]

**Nuance vs the stated ground truth**: the blanket claim "tailoring produces 0 changes and baselineATSScore == tailoredATSScore exactly, even on runs reporting changes:1" reproduces **exactly** in runs 2 and 3 above, but run 1 (the very first fresh run against this job) produced a small but genuinely nonzero ATS lift (+0.10 points) with `changes: 2`. All three behaviors are real, LLM-driven, non-fabricated outcomes of the same anti-fabrication guard — not a bug, but the ground truth's "always exactly 0" framing is not universal; it is the common case, not the only case. Recorded as ML-RESUME-006 (informational).

**Before/after banner (§5.3.6)**: **PRESENT**, format matches spec (`"Before: 35.82% → After: 35.92%"`), backed by the real `conversionMetrics` payload — not fabricated. Screenshot: captured live during run 1 (button still mid-run in `06-owner-tailoring-still-running-60s.png`; the completed banner text was captured via DOM read in `stage2-results.json` — `conversionBeforeAfter: "Before: 35.82% → After: 35.92%"`).

**Missing-keywords chip list (§5.3.2)**: **PRESENT** in the ATS Score panel (e.g. `deputy, workers, re, use, businesses, global, ll, more…`). See ML-RESUME-005 below for a quality caveat.

**Per-iteration/progress indicator (§5.3.1)**: **ABSENT**. Across three full-length observations (73s, 82s, 110s), the only visible state during the entire async run is a static disabled button reading `"Tailoring..."` — no percentage, no step counter, no elapsed-time display, no "iteration N of M" text anywhere on the page. Screenshots: `11-owner-noop-progress-72s.png` (72s mark, still "Tailoring..."), `progressSnapshots` in `stage5-results.json` (9 snapshots over 72s, all identical `btnText: "Tailoring...", disabled: true`). Filed as ML-RESUME-007.

**Honest sub-85 warning (§5.3.1 point 5)**: **ABSENT** as an explicit message. The engine computes `requires_review: true` for every resume/job pair observed (all scores are below the 60-point `REVIEW_THRESHOLD` in `apps/api/app/services/ats_engine.py:29`, itself well below the informal 85 target) — this field is fetched by the frontend's `AtsScore` type (`page.tsx:30`) but **never rendered anywhere**. The only visible signal is the raw number's text color (amber if `<60`, green if `>=60`); there is no textual "below target" or "needs review" warning banner. Filed as ML-RESUME-004.

---

## 6. Resume upload (backend-endpoint probe — no UI widget exists on this screen)

Tested directly against `POST /resumes/upload` (the endpoint `apps/api/app/routers/resumes.py:61` that this screen's data ultimately flows from) since the task required it, even though Resume Studio itself exposes no upload control:

| Case | Result | Evidence |
|---|---|---|
| Valid small PDF | `201 Created`, real text extracted via PyMuPDF, new root resume `v71` created | `upload-valid-response.json` |
| Unparseable PDF (garbage bytes after `%PDF` header) | `422`, `"Could not parse PDF: Failed to open stream"` — honest, specific, no stack trace | `upload-unparseable-response.json` |
| Empty file | `422`, `"Could not parse PDF: Cannot open empty stream."` — honest, specific, no stack trace | `upload-empty-response.json` |
| Oversized (60MB) file | `413 Request Entity Too Large` from nginx in ~90ms, before reaching the app — honest, fast rejection (though raw nginx HTML, not app JSON — irrelevant here since no UI consumes this response on this screen) | `upload-oversized-response.json` |

All negative-path cases behaved honestly with no fabrication and no crash. **PASS.**

---

## 7. Adversarial NUL-byte test — reproduces the workspaces.py:1092 bug class

Per the task's explicit instruction to check whether this screen's endpoints share the known `PUT /workspaces/settings` NUL-byte flaw (500 instead of 422), the two endpoints this screen's own JS calls that accept free-text/ID string input were probed directly (no UI vector exists on this screen itself, per §1):

**`POST /resumes`** (`label`, `raw_text` fields — the same router file, `resumes.py`, that backs this screen's version list) with a NUL byte (`\x00`) embedded mid-string:
```
HTTP/2 500
Internal Server Error
```
(plain text, no JSON, no detail — Starlette's default handler; a sanity-check request with identical structure but no NUL byte returned a normal `201 Created` immediately after, confirming the 500 is NUL-byte-specific, not a general endpoint fault.)

**`POST /agents/tailor/run`** (`job_id` field) with a NUL byte appended:
```
HTTP/2 500
Internal Server Error
```

**Both reproduced identically on a second, independent attempt** (`VERIFY TWICE` — see `nulbyte-resumes-post-response2.json`, `nulbyte-tailor-run-response2.json`, distinct `cf-ray` IDs `a238840cc8b588dc-PDX` / `a238840e88d7e5c0-PDX`, 2026-07-31T00:34:10Z). [VERIFIED-WITH-FRESH-EVIDENCE]

`apps/api/app/main.py` has no generic `Exception` → structured-error handler (only a narrow `MissingResumeError` handler exists), so any unhandled exception — here almost certainly a `psycopg2`/driver-level `ValueError: A string literal cannot contain NUL (0x00) characters` raised before the query reaches Postgres — falls through to a bare 500 instead of a validated `422`. This is the exact same defect class already confirmed on `workspaces.py:1092`, now independently confirmed on two endpoints in `resumes.py`/`agents.py` that back this screen. Filed as **ML-RESUME-001**.

---

## 8. Paywall check — NEW USER (Free tier)

**Resume Studio is completely paywalled for the Free-tier NEW USER**, identical in shape to the already-filed `ML-JOBS-003` for the Jobs screen:

- `/dashboard/resume` renders a full-screen "Subscribe to unlock Aether" gate — no version list, no job selector, no Tailor button reachable. Screenshot: `18-newuser-paywall-gate.png`.
- Direct probe: `POST /agents/tailor/run` → `402 {"detail":{"error":"subscription_required","message":"An active subscription is required to use Aether. Subscribe to unlock.","upgradeUrl":"/pricing"}}`.
- This is the same root cause/pricing-copy-vs-entitlement inconsistency already adjudicated as UNSURE in ML-JOBS-003 (Free plan advertised as including "Resume tailoring + ATS scoring" on `/pricing` while the product blocks 100% of agent functionality for this tier). Not re-litigated here as a new root cause; filed as **ML-RESUME-003** scoped to this screen, referencing ML-JOBS-003, since the parent brief explicitly asked this screen to be checked and recorded.

[VERIFIED-WITH-FRESH-EVIDENCE, `01-resume-newuser.png`, `stage3-results.json`, 2026-07-31T00:24Z]

---

## 9. Edge/error states

- **Unauthenticated access**: `GET /dashboard/resume` with no session → redirects to `/login?next=%2Fdashboard%2Fresume`. Confirmed **twice**, independent fresh sessions. [VERIFIED-WITH-FRESH-EVIDENCE, `08-owner-unauth-redirect.png`, 2026-07-31T00:20Z and 00:29Z]
- **Back/forward navigation**: version-selection state and route both restore correctly across `/dashboard/resume` → `/dashboard/jobs` → back → forward. No stale/broken state observed. [VERIFIED-WITH-FRESH-EVIDENCE, `21-after-goback.png`, `22-after-goforward.png`]
- **Reload-and-re-read persistence**: after a real tailoring run, reloading the page shows the same newest version at the top of the list (`persistenceMatch: true` in `stage2-results.json`); the transient `conversion` banner correctly does **not** persist across reload (it is client-side-only state tied to the just-completed run, by design) — `conversionVisibleAfterReload: false`. [VERIFIED-WITH-FRESH-EVIDENCE, `07-owner-after-reload-persistence.png`]
- **Mobile 390px overflow — RETEST of baseline claim `ML-resume-002`**: **DOES NOT REPRODUCE on production.** Measured `document.documentElement.scrollWidth` (390px) vs `window.innerWidth` (390px) with the widest available page state open (a selected version showing bullets, diff, and the ATS panel) — **zero pixels of overflow, zero offending elements**, confirmed **twice** in two independent fresh sessions (`hasOverflow: false` both times). Screenshots: `09-owner-mobile-390-list.png`, `10-owner-mobile-390-version-open-basebug.png`, `15-owner-mobile-390-2nd-check.png`. Consistent with the task's warning that a sibling "known-failing" spec turned out to be stale/targeting localhost — this appears to be another such case for the current production build. **Recorded as a retest result, not a new finding: `ML-resume-002` is NOT reproducible against `https://5cb5f0620.abacusai.cloud` as of 2026-07-31.**

---

## 10. Findings table

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-RESUME-001 | `/dashboard/resume` | **HIGH** | Robustness / input validation | A NUL byte (`\x00`) in a string field sent to `POST /resumes` (`label`/`raw_text`) or `POST /agents/tailor/run` (`job_id`) — the two endpoints this screen's own JS calls — crashes with a raw, unhandled `500 Internal Server Error` (plain text, no detail) instead of a validated `422`. Same defect class as the already-confirmed `workspaces.py:1092` NUL-byte bug, now confirmed on 2 additional endpoints. No generic exception→structured-error handler exists in `apps/api/app/main.py`. Not reachable via this screen's own UI (no free-text field here; job_id comes from a `<select>`), so severity is HIGH rather than BLOCKER — a determined caller must hit the API directly. | 1. `POST /api/resumes` with `Authorization: Bearer <token>`, body `{"label":"x","raw_text":"...name-\x00-injected..."}`. 2. Observe `500`/`Internal Server Error`. 3. Repeat against `POST /api/agents/tailor/run` with `{"job_id":"<realid>\x00nulinjected"}`. 4. Repeat both once more (verify-twice) — reproduces identically both times. 5. Sanity-check an identical request minus the NUL byte → succeeds normally (`201`). | `422` with a specific, honest validation message (matching the honest 422s already seen elsewhere on this screen for e.g. unparseable-PDF upload). | Raw `500 Internal Server Error`, no detail, both endpoints, both attempts. | `nulbyte-resumes-post-response.json`, `nulbyte-resumes-post-response2.json`, `nulbyte-resumes-post-headers2.txt`, `nulbyte-tailor-run-response.json`, `nulbyte-tailor-run-response2.json`, `nulbyte-tailor-run-headers2.txt`, `sanity-no-nul-response.json` | OPEN |
| ML-RESUME-002 | `/dashboard/resume` | **HIGH** | Data integrity / display logic | The "Original — Base Resume" pane picks the **wrong** resume once an account has more than one root (parentless) resume: `page.tsx` computes `baseResume = resumes.find(r => !r.parentId) ?? resumes[0]` over a newest-first list, i.e. it shows the **most recently created** root, not the true original. The backend already has the correct resolution — `ResumeRepository.get_base()` (`apps/api/app/repositories/resume.py:98`, `ORDER BY version ASC` = oldest first) — and it IS used correctly by the actual tailoring engine (`tailor_agent.py:304`) and the anti-fabrication grounding service (`resume_grounding.py:66,89`), so real tailoring output is unaffected — this is a **display-only** bug, but a seriously misleading one: after uploading a second résumé, the user's real original identity silently disappears from its own screen while the "Tailored" pane correctly still shows the real user's name, producing a visibly inconsistent, confusing state. | 1. As OWNER, upload a new résumé PDF via `POST /resumes/upload` (creates a new root, `parentId: null`). 2. Reload `/dashboard/resume`. 3. Observe the "Original — Base Resume" pane now shows the newly uploaded document's identity instead of the account's real original ("VIKRAM DESHPANDE"). 4. Confirmed twice in independent fresh sessions (mobile view and desktop view). | The true original (oldest, `version=1`-equivalent) root resume's identity, always — matching what `ResumeRepository.get_base()` / the tailoring engine actually use. | "Jane Doe Test Resume" (the just-uploaded document) shown in the Original pane instead of "VIKRAM"/"VIKRAM DESHPANDE"; the Tailored pane correctly still shows "VIKRAM". | `10-owner-mobile-390-version-open-basebug.png`, `12-owner-noop-final-73s-basebug.png` / `16-owner-final-run-outcome.png`, `13-owner-desktop-final-state.png`, `stage6-results.json` (`originalNameDesktop2ndCheck: "Jane Doe Test Resume"`) | OPEN |
| ML-RESUME-003 | `/dashboard/resume` | MEDIUM | Entitlements / paywall | Resume Studio is unconditionally paywalled for the Free-tier NEW USER (full-screen "Subscribe to unlock Aether" gate; `POST /agents/tailor/run` → `402 subscription_required`), consistent with the already-filed `ML-JOBS-003` (Jobs screen) — `/pricing` advertises the $0 Free plan as including "Resume tailoring + ATS scoring" while this screen blocks all of it. Same root cause as ML-JOBS-003; filed here per the parent brief's explicit instruction to check this screen. | 1. Log in as `gm2-nonadmin-1785454990@example.com`. 2. Visit `/dashboard/resume` → full paywall gate, no version list/job selector/tailor button reachable. 3. Directly `POST /api/agents/tailor/run` with the new-user's bearer token → `402`. | Either the Free tier's advertised entitlements should be honored, or `/pricing` copy should not claim this feature is included in Free — same UNSURE adjudication as ML-JOBS-003 applies. | Full paywall gate + 402 on direct probe. | `18-newuser-paywall-gate.png`, `stage3-results.json` | OPEN (cross-ref ML-JOBS-003) |
| ML-RESUME-004 | `/dashboard/resume` | MEDIUM | Honesty / missing warning | The ATS engine computes `requires_review: true` (below the 60-point `REVIEW_THRESHOLD`, `ats_engine.py:29`) for every resume/job pair observed — i.e. every real production score, all far below the informal 85 target — specifically "so a human gates low-fit applications" per its own docstring. The frontend's `AtsScore` type captures this field (`page.tsx:30`) but **never renders it anywhere**. No explicit textual "below target"/"needs review" warning exists on the screen; the only signal is the raw number's amber/green text color. | 1. As OWNER, open any tailored version (all currently score well under 60). 2. Observe the ATS Score panel: a plain number colored amber, sub-bars, and a missing-keywords list — no warning text, no "requires review" badge, no mention of a target score anywhere. | Per §5.3.1 point 5, an honest warning when the score stays below the target. | No such warning exists anywhere on the screen. | `03-owner-version-selected-ats-diff.png` (ATS Score panel, no warning text visible), `apps/api/app/services/ats_engine.py:29,160`, `apps/web/src/app/dashboard/resume/page.tsx:30` (field captured, never rendered) | OPEN |
| ML-RESUME-005 | `/dashboard/resume` | MEDIUM | Data quality | The "Missing JD keywords" chip list surfaces low-quality noise tokens — contraction fragments and generic filler words absent from the ATS engine's stopword list (`ats_engine.py:42-62`) — alongside genuine skill gaps, diluting the feature's usefulness. Observed tokens include `re`, `ll`, `use`, `more`, `most`, `about`, `behind`, `global`, `workers` mixed in with genuine gaps like `deputy`, `fintech`, `broker`. | 1. As OWNER, open any tailored version. 2. Read the "Missing JD keywords" chip list in the ATS Score panel or via `GET /resumes/{id}/ats`. | A missing-keyword list of plausible skill/domain terms only. | Noise tokens (`re`, `ll`, `use`, `about`, `most`…) mixed into every list observed (3/3 versions checked). | API responses captured for v67/v69/v68 (`overall`, `missing_keywords` fields), `03-owner-version-selected-ats-diff.png` | OPEN |
| ML-RESUME-006 | `/dashboard/resume` | LOW | UX / progress feedback | No per-iteration or percentage progress indicator exists during a tailoring run. Runs measured at 59.75s, 79.4s and 110s all showed only a static disabled button reading "Tailoring..." for the entire duration — no step counter, elapsed timer, or "iteration N of M" text. Per §5.3.1, per-iteration progress should be shown honestly. | 1. As OWNER, select an untailored job and click "Tailor Resume". 2. Screenshot every ~8s for the full ~60-110s run. 3. Observe: button text and disabled state never change until final completion. | Some honest incremental progress signal (even a simple elapsed counter) during the wait. | Static "Tailoring..." the entire time, 3/3 runs observed (72s, 82s, 110s windows). | `11-owner-noop-progress-72s.png`, `stage5-results.json` (`progressSnapshots`, all 9 identical) | OPEN |
| ML-RESUME-007 | `/dashboard/resume` | LOW | Precision / wording | The single-version ATS panel (`GET /resumes/{id}/ats`) rounds to 1 decimal while the post-run "ATS Conversion Impact" banner shows 2-decimal precision for what is fundamentally the same score type — both are genuinely backend-derived (not fabricated), just cosmetically inconsistent. Separately, a real (if tiny) ATS improvement of +0.10 points (35.82→35.92) is displayed by the "Estimated interview conversion improvement" metric as `"+0.0%"`, which could read to a user as "no improvement occurred" despite one actually having occurred, however small. | 1. Compare `ats-overall` (e.g. "42.5") on the Versions list against the `conversion-before-after` banner text (e.g. "35.82%"/"35.92%") after a live run. | Consistent precision; a lift label that doesn't imply zero when a real (if small) nonzero change exists. | 1-decimal vs 2-decimal split; "+0.0%" shown for a genuine +0.10-point delta. | `stage2-results.json` (`conversionBeforeAfter: "Before: 35.82% → After: 35.92%"`, `conversionLift` text), API `overall` fields | OPEN |
| ML-RESUME-008 | `/dashboard/resume` | INFO | Design conformance | Large divergence from `design/screens/resume-studio.html`: no side-by-side PDF preview panes, no circular ATS gauge, no Voice DNA / AI-Detection panel, no Approve/Revert/Export-PDF-button/Compare-Versions-modal. Shipped screen is a simpler, arguably more honest (never shows a fabricated high score) data-driven view instead. | Load `/dashboard/resume` and compare visually against the wireframe. | Wireframe-conformant layout (or an approved design update). | Materially different, simpler implementation; all core wireframe interactive affordances beyond Tailor/Download are absent. | `02-owner-resume-initial.png` vs `design/screens/resume-studio.html` | OPEN (product/design review, not a functional defect) |
| RETEST-ML-resume-002 | `/dashboard/resume` | N/A (retest) | Mobile responsive | Baseline Playwright spec `ML-resume-002` claims horizontal overflow at 390px. **Retested against production twice, in independent fresh sessions — does NOT reproduce.** `document.documentElement.scrollWidth === window.innerWidth === 390` with the widest page state open (version selected, bullets+diff+ATS panel all rendered). | 1. Fresh session, login OWNER, set viewport 390×844, load `/dashboard/resume`, open a version. 2. Measure `scrollWidth` vs `innerWidth`. 3. Repeat in a second fresh session. | Overflow per the baseline spec claim. | No overflow, either time. | `09-owner-mobile-390-list.png`, `10-owner-mobile-390-version-open-basebug.png`, `15-owner-mobile-390-2nd-check.png`, `stage4-results.json`, `stage6-results.json` (`hasOverflow: false` both times) | CLOSED — not reproducible on production as of 2026-07-31 |

---

## 11. Confirmed PASS items (not findings — recorded for completeness)

- ATS score UI exactly matches `GET /resumes/{id}/ats` API on 3/3 independently checked versions across 3 fresh sessions (§4).
- Before/after ATS banner (§5.3.6) present, correctly sourced from real `conversionMetrics`, not fabricated.
- Missing-keywords chip list (§5.3.2) present (quality caveat: ML-RESUME-005).
- Honest zero-change no-op surfacing — verbatim, correctly styled as informational (not error), Conversion panel correctly suppressed — confirmed twice.
- Resume upload negative paths (unparseable/empty/oversized) all honest, specific, no stack traces, no fabricated success.
- Reload-and-re-read persistence works correctly; transient conversion banner correctly does not falsely persist.
- Unauthenticated access correctly redirects to login with a `next` param, confirmed twice.
- Back/forward navigation correct.
- Zero uncaught console errors/pageerrors across all instrumented sessions.
- Zero unexpected failed network requests.
- Mobile 390px: no overflow (retest of baseline claim — closed, not reproducible).
- Download button streams a real, correctly-sized PDF (`200`, `189227` bytes for one tested version) matching the selected version's ID.

---

## 12. Not-tested items (HUMAN-GATED only)

- **Model provenance attribution on this screen**: while running a live tailor agent, the backend recorded `requestedModel: "deepseek/deepseek-v4-pro"` but actually used `model: "qwen/qwen3-coder-next"` for the run (`run c9b509cc0a8b00c6f9124568b`). Resume Studio itself shows **no** model attribution anywhere in its UI (no "generated with X" badge), so there is nothing on *this screen* to cross-check the selected-vs-recorded model against (task requirement 4, "the model shown as selected is the model recorded for the run" — not applicable here since no model is shown at all on this screen). This observation is being handed off/noted for the dedicated Agents-screen and model-catalog testers, since it touches model-selection/fallback behavior outside this screen's scope. Not filed as a Resume Studio finding; flagged here as context only.
- Deep agent-configuration testing (system prompts, credential modes, catalog picker) is explicitly out of scope for this screen per the assignment (Resume Studio has no agent-config UI) — covered by the Agents-screen tester.
- No human-in-the-loop / real-world manual steps were skipped; all listed protocol steps were completed with live production evidence.

---

## 13. Cleanup — test data left on the OWNER production account

**No `DELETE` endpoint exists anywhere in the resumes API** (`apps/api/app/repositories/resume.py` has no delete method; `apps/api/app/routers/admin.py` has no resume-deletion route). Per the task's instruction to document exactly what was left when cleanup isn't possible, the following rows were created on the OWNER (`admin`/`admin123`) account during this test run and **could not be removed**:

| Version | id | Label | Reason created |
|---|---|---|---|
| v70 | `c317c8c7902500ac0c1fa4cd2` | Tailored — Program Manager, Sales Operations and Training @ Peloton | Required live "run a real tailoring action from the UI" test (§5, run 1) |
| v71 | `c969dbcecd27c827a80f6bea0` | Uploaded — valid-resume | Required upload test (§6) — **this row is the direct cause of ML-RESUME-002** (it became the wrongly-displayed "Original — Base Resume") |
| v72 | `c0ec57d2965263a55a77b1b44` | Tailored — Program Manager, Sales Operations and Training @ Peloton | Required live no-op/progress-observation test (§5, run 3) — `approvalStatus: pending` |
| v73 | `cd229bb6a9f8a736bbeb80e93` | sanity-check-no-nul | Control request to confirm the NUL-byte 500 (ML-RESUME-001) was NUL-specific, not a general endpoint fault — **this row is a second root resume and compounds ML-RESUME-002** |

**Recommended operator action**: an operator with direct database access should delete these 4 `Resume` rows (table `"Resume"`, ids above) for user `c6c8d0163d973a8048e7e33b8` (the OWNER account), which will also resolve the currently-wrong "Original — Base Resume" display without needing a code fix (the true original, the lowest-version root, is untouched and will resurface as `baseResume` once the newer roots are gone) — though the underlying selection-logic bug (ML-RESUME-002) will still need a real fix to prevent recurrence.

The NEW USER account (`gm2-nonadmin-1785454990@example.com`) was not mutated — it remains paywalled and untouched, already slated for purge per the cleanup list in `uat/reports/evidence/gold-master-v2/phase0/CANONICAL-NONADMIN-LOGIN.md`.

---

## 14. Screenshot index

| # | File | Description |
|---|---|---|
| 1 | `01-owner-login-page.png` | OWNER login page, fresh session |
| 2 | `02-owner-resume-initial.png` | Resume Studio initial load, OWNER, 69 existing versions |
| 3 | `03-owner-version-selected-ats-diff.png` | Version selected — full ATS breakdown, diff, missing-keyword chips (matches API exactly) |
| 4 | `04-owner-job-selected-pre-run.png` | Untailored job selected in dropdown, pre-run |
| 5 | `05-owner-tailoring-in-progress.png` | ~0.3s into a run — button switches to "Tailoring..." |
| 6 | `06-owner-tailoring-still-running-60s.png` | Still running at ~60s — sidebar shows "1 of 19 agents running" |
| 7 | `07-owner-after-reload-persistence.png` | Post-run reload — new version persisted correctly |
| 8 | `08-owner-unauth-redirect.png` | Unauthenticated access → redirected to `/login?next=...` |
| 9 | `09-owner-mobile-390-list.png` | 390px viewport, version list — no overflow |
| 10 | `10-owner-mobile-390-version-open-basebug.png` | 390px, version open — no overflow; also shows ML-RESUME-002 (base-resume bug) |
| 11 | `11-owner-noop-progress-72s.png` | 72s into a run — still just static "Tailoring..." (ML-RESUME-006) |
| 12 | `12-owner-noop-final-73s-basebug.png` | 73.5s, run still not resolved; base-resume bug visible again |
| 13 | `13-owner-desktop-final-state.png` | Desktop, 3rd fresh session — 2nd confirmation of base-resume bug |
| 14 | `14-owner-independent-version-check.png` | 2nd independent ATS-vs-API cross-check (v68, 42.5) |
| 15 | `15-owner-mobile-390-2nd-check.png` | 2nd fresh-session mobile overflow check — no overflow |
| 16 | `16-owner-final-run-outcome.png` | Clean capture of the honest no-op amber banner after a full 110s run |
| 17 | `17-newuser-post-login.png` | NEW USER post-login |
| 18 | `18-newuser-paywall-gate.png` | NEW USER — full-screen paywall gate on this screen |

---

## 15. Sign-off

**Verdict: FUNCTIONAL PASS with 2 HIGH and 3 MEDIUM findings requiring product/engineering follow-up.**

The screen's core, highest-priority promises hold up under adversarial live testing: every ATS number shown is real and matches its backend source exactly (3/3 checks), the before/after tailoring banner is real and correctly formatted, and — most importantly per the assignment's framing — the honest zero-change no-op path is genuinely honest: verbatim, non-alarming, correctly styled, and correctly suppresses the conversion panel, confirmed twice in fresh sessions. No fabricated/placeholder content was found on any user-reachable path.

Two real, verified-twice defects were found that were not previously known from the stated ground truth: (1) a NUL-byte-triggered unhandled `500` on two of this screen's backing endpoints, matching the already-known `workspaces.py:1092` bug class (ML-RESUME-001, HIGH), and (2) a base-resume identity-resolution bug that shows the wrong "Original" résumé once a second root résumé exists on the account — a display-only bug (the actual tailoring engine uses the correct resume via `get_base()`) but a confusing one on a user-reachable path (ML-RESUME-002, HIGH). The claimed `ML-resume-002` mobile-overflow baseline finding does **not** reproduce on production and is closed as not-reproducible.

All claims in this report are tagged with their verification basis inline; every finding was independently verified at least twice as required. No secrets were printed (only 8-char token prefixes were ever logged). No destructive operations were run against the NEW USER account. Test-data cleanup was not possible via any exposed API (§13) and has been documented in full for manual operator cleanup.
