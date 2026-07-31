# Story Bank (`/dashboard/stories`) — GOLD-MASTER-V2 §3.2 Screen Test

**Status: COMPLETE**

- Production URL under test: `https://5cb5f0620.abacusai.cloud/dashboard/stories`
- Test window: 2026-07-31, 00:38–00:48 UTC
- Tester: screen-tester agent — serial work only, single headless Chromium at a time, no
  sub-agents spawned (HARD PROCESS RULES honoured throughout)
- Tooling: Playwright (`@playwright/test` 1.61.1, Chromium headless) driven via ad hoc Node
  scripts under `/tmp/claude-2000/.../scratchpad/owner_test*.js`, plus `curl`/Python for direct
  API probes. Scripts are scratch and not committed to the repo.
- Repo code cross-referenced: `apps/api/app/routers/stories.py`, `apps/api/app/repositories/story.py`,
  `apps/api/app/routers/workspaces.py` (NUL-byte precedent), `apps/web/src/app/dashboard/stories/page.tsx`,
  `apps/web/src/components/stories/*`, `apps/web/src/components/subscription-gate.tsx`
- Wireframe: `design/screens/story-bank.html`
- Identities used: **OWNER** (`admin`/`admin123`, real email `sarkar.vikram@gmail.com`, 36
  pre-existing stories, `isAdmin` operator account per BLOCKER-001) and **NEW USER**
  (`gm2-nonadmin-1785454990@example.com`, canonical non-admin recipe, verified `isAdmin:false`, 0
  stories, Free/unsubscribed plan).
- Screenshots: `uat/reports/evidence/gold-master-v2/screens/stories/*.png` (30 files, index below).
- Raw JSON evidence: `owner-part1-results.json` … `owner-part6-results.json` in the same directory.

---

## 0. Code-level ground truth (read first; confirmed live below)

- `GET /stories` (`apps/api/app/routers/stories.py:137-140`) takes **no** query parameters at all
  — only `current_user`. No `relevance_score` field exists anywhere in `_enrich()`.
- Dedup (`apps/api/app/repositories/story.py:29-73`) hashes the 5 STAR fields + `userId` into a
  sha256 `contentHash` and returns the **existing row** on an exact match instead of inserting.
  There is no fuzzy/semantic comparison anywhere in the repo.
- No NUL-byte guard exists in `stories.py`/`story.py`, unlike `apps/api/app/routers/workspaces.py:905-921`
  (`ML-settings-006`), which explicitly rejects `\x00` with a 422.
- `apps/web/src/components/subscription-gate.tsx` wraps **every** known `/dashboard/*` section,
  `/dashboard/stories` included, in a client-side `GET /billing/entitlement` check; `stories.py`
  itself has **no** server-side entitlement gate.

All four points are verified live below with fresh evidence.

---

## 1. Element inventory

| Element | data-testid | Notes |
|---|---|---|
| New Story button | `add-story-btn` | opens inline create form |
| Stat tiles ×4 | `story-stats` | Total / Quantified w/ Metrics / Starred / Categories Covered |
| Filter chips ×5 | `filter-all`, `filter-leadership`, `filter-delivery`, `filter-technical`, `filter-risk-compliance` | client-side only, no URL/query-param sync |
| Story card | `story-card` | one per `StoryEntry` row |
| ↳ Star toggle | `star-story-btn` | persists via `PUT /stories/{id}` |
| ↳ Edit | `edit-story-btn` | swaps card for inline `StoryForm` |
| ↳ Delete | `delete-story-btn` | `window.confirm` gate, then `DELETE /stories/{id}` |
| ↳ Insert | `insert-story-btn` | copies STAR text to clipboard, "Copied" confirmation |
| Create/Edit form | `story-form` | title/situation/task/action/result (all `required`) + tags |
| Empty state | `stories-empty-state` | "Import from Resume" (`empty-import-resume`, runs the Story Extractor agent) + "Add Manually" (`empty-add-manual`) — wireframe's third CTA "Import from Portfolio" does not exist in production |
| Interview Question Mapper | `question-mapper` | read-only, computed live from real stories (not hardcoded) |
| Coverage Gaps + Draft missing stories | `coverage-gaps`, `draft-missing-btn` | computed live; button re-runs the Story Extractor agent |

Backing endpoints: `GET/POST /stories`, `PUT/DELETE /stories/{id}`, `GET /stories/stats`,
`POST /agents/story-extractor/run`.

---

## 2. PRIORITY — near-duplicate audit (Gate G-E)

**[VERIFIED-WITH-FRESH-EVIDENCE, `owner_stories.json` curl dump @2026-07-31T00:38Z + Playwright DOM
extraction @2026-07-31T00:39Z and again @2026-07-31T00:44Z (second, independent fresh-browser
session) + screenshots `05-dupgroup-jira-*.png`, `06-dupgroup-anz-*.png`, `01-owner-initial-full.png`,
`13-reverify-fresh-session.png`]**

All 36 owner stories were pulled via `GET /stories` and independently confirmed identical in count,
titles, and category assignment in **two separate fresh Playwright browser sessions** (first pass:
`owner-part1-results.json`, 36 cards; second pass: `owner-part5-results.json` →
`owner-part5` / `13-reverify-fresh-session.png`, 36 cards, JIRA-family count 6, ANZ-family count 5 —
both matching the first pass exactly).

Judging the 36 rows the way a human reviewer would (same underlying achievement told a different
way, not byte-identical text), they collapse into **8 duplicate groups (34 rows) + 2 genuinely
unique stories = 10 real distinct achievements**. That means roughly **72% of the "36 stories" in
this bank are re-tellings of only 8 achievements.**

| Group | Rows | IDs |
|---|---|---|
| **JIRA Analytics Dashboard** (Next.js+Supabase sprint-velocity dashboard, "20% delivery efficiency / 15% operational clarity") | 6 | `c4923cf666dd909e4c22f02ba` (Technical), `c589b96a2ce8b958f609027a6` (Technical), `c384216bb9b82e6c5b4f45ffe` (Leadership), `c87983e0fa7c8fdd3255279ee` (Leadership), `c588b640468691eab4a86a2f9` (Technical), `c0f72c9747eff8e74326a0631` (Technical) |
| **ANZ Cloud-Native Core Banking transformation** ("30% faster delivery", .NET/Azure modernisation) | 5 | `cd1d99e9f7590fad24146e059` (Leadership), `cf1b43285db4dbd973789a4d5` (Technical), `c7147f71028ed0619d566fa84` (Risk & Compliance), `c7a78b83600b817ba670a0dde` (Leadership), `c4f057b24f8c34ea10a01db34` (Technical) |
| **Payday Super Executive Re-baselining** (test-capacity re-baselining change request) | 5 | `cf66f148f3d192a7b2f18e8bb`, `c3fab39183fe6c05288d109ba`, `c3fda3747f1450442f0b22c4d`, `cb35d3988b091bc22a38e43d9`, `c8d8b05dd5ce839a7875eb59e` (all Risk & Compliance) |
| **Payday Super SIT Window Recovery** (75+ hr infeasible SIT window) | 4 | `cc380afa63520797818ed0fdc` (Leadership), `c49f563ba94d4419633272f89` (Leadership), `c90b4e1ddc2928ed6c3273057` (Technical), `c9a082d0581ce4a08903d1476` (Technical) |
| **ATO COBOL/Mainframe Test Evidence Automation** (92% effort reduction) | 5 | `cae29d5693f629b97daa3a930` (Risk & Compliance), `cdf3c50079ef9d1d85a7d41b3` (Technical), `c8f0bd084d35148040694a445` (Technical), `c6b1db3491dfd4191b7be1648` (Technical), `c2f9fd966efa904a9d2fd503f` (Technical) |
| **LLM Evaluation Stack** (error-budget / hallucination risk reduction) | 4 | `c3945828428254e0333f817ce`, `c838dfc6fa892a728b447b9b8`, `c2ae4412687cbfa4da7261007`, `ce023132b8553345f4cd497d2` (all Risk & Compliance) |
| **NTP Testing / Technical War Room** | 3 | `c3cbc5324335e022fd1fb7aab`, `c436bca3c64452102624717c3`, `cfbf806089b7b3ef774c9ce5b` (all Leadership) |
| **ANZ Telemetry Gap Analysis** | 2 | `c2e1f3c2e7d95161ff2d2adc9`, `cd542cb6dd57cbbd3c2fd40e0` (both Leadership) |

Genuinely unique stories (no duplicate found): `cc2483c5a26734605083cbd86` (Real-Time WebSocket
Telemetry Server) and `c9178adc2a177ae602f80c9c3` (Public-Key Server for API Signing).

**Full-content proof, not just title similarity** — the JIRA family's `situation`/`task`/`action`/`result`
text was pulled for all 6 rows: 5 of 6 report the **identical metrics** (`Delivery efficiency
improvement: 20%`, `Operational clarity improvement: 15%`) with reworded prose describing the same
Next.js+Supabase dashboard, created on 6 different dates spanning 2026-07-21 through 2026-07-31 —
consistent with the ground-truth note that re-running story extraction on an unchanged résumé
manufactures a fresh paraphrase every time. Screenshots `05-dupgroup-jira-1.png` and
`05-dupgroup-jira-2.png` show two of these cards side-by-side-equivalent; `06-dupgroup-anz-1.png`/
`-2.png` show the same for the ANZ family (`>30%` delivery time cut, `>15%` infra cost cut, 95–100%
compliance, both citing "5+ cross-functional squads / up to 40 people").

**Secondary symptom** — because these duplicates land in *inconsistent* categories (the JIRA family
alone spans Technical and Leadership; the ANZ family spans Leadership/Technical/**Risk &
Compliance**), the Interview Question Mapper's "A time you handled compliance risk" question maps to
an ANZ cloud-migration story purely because one paraphrase of it was mis-bucketed into Risk &
Compliance — visible in `07-header-statstrip-viewport.png`.

### Finding: GM2-STORY-001

- **Severity:** HIGH
- **Category:** Data quality / duplicate content (§7.2 violation)
- **Summary:** 34 of 36 stories in the Story Bank are paraphrase-level re-tellings of only 8 distinct
  achievements; a human reviewer would call this the same story told 2–6 times each.
- **Reproduction:** [1] Log in as OWNER. [2] `GET /stories` or load `/dashboard/stories`. [3] Sort
  titles alphabetically/visually — 8 groups of near-identical titles/content are immediately obvious
  (see table above).
- **Expected:** Story Bank should contain one canonical story per achievement (§7.2 "identical OR
  near-identical content must not be created twice").
- **Observed:** 8 groups of 2–6 near-identical stories persist simultaneously, each with its own id,
  independently editable/deletable/starrable, with zero cross-linking or duplicate flag.
- **Evidence:** `01-owner-initial-full.png`, `05-dupgroup-jira-1..6.png`, `06-dupgroup-anz-1..5.png`,
  `13-reverify-fresh-session.png`, `/tmp` curl dump reproduced in this report's table above.
- **Status:** OPEN

---

## 3. Duplicate prevention on create (§7.2)

**[VERIFIED-WITH-FRESH-EVIDENCE, direct `POST /stories` probes @2026-07-31T00:40–00:41Z, repeated a
third time for the identical-content case, screenshots `09-crud-after-create.png` for the UI path]**

Test sequence (payload STAR content shown in full in the scratch script; not reproduced here to
keep the report short):

1. **CREATE #1 (baseline)** → `201`, new id `c1aeba503e135c2dca918fade`.
2. **CREATE #2 (byte-identical to #1)** → `201`, **same id** `c1aeba503e135c2dca918fade` returned
   — no new row inserted (confirmed: total story count stayed at 37, not 38, after steps 1+2).
3. **CREATE #3 (light paraphrase of #1 — same achievement, reworded sentences, same tags)** → `201`,
   **new, different id** `cff1aab6e968e271d740d4e6e` — a second row was inserted. Total count rose
   to 38.
4. **Re-verification** — re-POSTed the exact #1 payload a third time: again returned
   `c1aeba503e135c2dca918fade` (same id), confirming the exact-match dedup is solid and reproducible.

| Test | Result |
|---|---|
| identical_create_blocked | **true** — exact byte-for-byte duplicate is deduped (existing row returned, no insert) |
| paraphrase_create_blocked | **false** — a reworded duplicate of the same achievement is accepted as a brand-new row |

This is the direct root cause of §2's finding: dedup only ever catches the case a double-click would
cause, not the case that actually happens in production (re-running the extractor agent on an
unchanged résumé).

### Finding: GM2-STORY-002

- **Severity:** HIGH
- **Category:** Duplicate prevention / backend logic
- **Summary:** `POST /stories` dedup is implemented as an exact sha256 hash of the 5 STAR fields —
  it silently accepts and inserts any paraphrase of existing content as a new row.
- **Reproduction:** `POST /stories` with STAR content identical to an existing story → `201` with
  the *existing* row's id (no new row). `POST /stories` again with the same achievement reworded →
  `201` with a **new** id (new row inserted). See `apps/api/app/repositories/story.py:29-73`.
- **Expected:** Per §7.2, near-identical content should not be silently duplicated (reject, merge,
  or at minimum flag for review).
- **Observed:** New row inserted with no warning, no merge offer, no flag.
- **Evidence:** curl transcript above (ids `c1aeba503e135c2dca918fade` / `cff1aab6e968e271d740d4e6e`),
  reproduced/verified twice.
- **Status:** OPEN (root cause of GM2-STORY-001)

**Cleanup:** both test rows (`c1aeba503e135c2dca918fade`, `cff1aab6e968e271d740d4e6e`) were deleted
via `DELETE /stories/{id}` immediately after the probe; confirmed back to 36 total stories / 6
starred via a fresh `GET /stories` call.

---

## 4. Relevance scoring (§7.4)

**[VERIFIED-WITH-FRESH-EVIDENCE, curl @2026-07-31T00:39Z]**

```
GET /stories?job_id=test-job-123  →  HTTP 200, 36 rows returned (unfiltered — job_id silently ignored)
Response story object keys: action, category, createdAt, id, impact, metrics, result, starred,
                             tags, task, title, updatedAt, userId
```

No `relevance_score` (or any relevance-shaped) field exists in any response. The `job_id` query
param has **zero effect** — the same 36 rows come back regardless. Source confirms this is not a
transient bug: `list_stories()` in `apps/api/app/routers/stories.py:137-140` takes only
`current_user` as a parameter; there is no code path that reads `job_id` or computes relevance
anywhere in the backend or frontend (`grep -rn "relevance_score|relevanceScore"` across both `apps/api`
and `apps/web/src` returns zero hits outside this report).

| Test | Result |
|---|---|
| relevance_score_exposed | **false** |
| relevance_badge_in_ui | **false** — no badge, chip, or sort-by-relevance control exists anywhere on the screen |

### Finding: GM2-STORY-003

- **Severity:** MEDIUM
- **Category:** Missing feature (§7.4 requirement gap)
- **Summary:** §7.4's relevance-scoring requirement is entirely unimplemented — not partially
  working, not degraded, simply absent end-to-end (API param ignored, no field in the response
  shape, no UI affordance).
- **Reproduction:** `curl .../api/stories?job_id=<any>` → all stories returned unfiltered, no
  `relevance_score` key.
- **Expected:** Per §7.4, `GET /stories?job_id=...` should expose a relevance score per story.
- **Observed:** Param silently ignored; feature does not exist.
- **Evidence:** curl transcript above.
- **Status:** OPEN

---

## 5. Duplicate-detection / merge affordance in the UI

**[VERIFIED-WITH-FRESH-EVIDENCE, `01-owner-initial-full.png`, component source read]**

No merge button, "possible duplicate" badge, dedup suggestion, or any similar-stories indicator
exists anywhere on the screen — confirmed by full visual sweep of the 36-card list (screenshot) and
by reading every interactive component (`story-card.tsx`, `story-aside.tsx`, `page.tsx`): the only
per-card actions are star / edit / delete / insert-to-clipboard. `dedup_affordance_exists: false`.

### Finding: GM2-STORY-004

- **Severity:** LOW
- **Category:** UX / missing affordance
- **Summary:** Given GM2-STORY-001/002, users have zero visibility that most of their "36 stories"
  are re-tellings of 8 achievements — no in-product signal exists to help them notice or clean it up.
- **Reproduction:** Load `/dashboard/stories` as OWNER; visually scan — no duplicate/merge UI exists.
- **Expected:** Some surfacing of likely-duplicate content (even a simple title-similarity warning)
  given the confirmed prevalence of duplicates.
- **Observed:** None.
- **Evidence:** `01-owner-initial-full.png`, `apps/web/src/components/stories/story-card.tsx` (full
  action set: star/edit/delete/insert only).
- **Status:** OPEN

---

## 6. NUL-byte adversarial input (cross-check vs. `workspaces.py:1092` pattern)

**[VERIFIED-WITH-FRESH-EVIDENCE, curl @2026-07-31T00:41Z ×2 (verified twice), UI reproduction
@2026-07-31T00:44Z via `owner_test4.js`, screenshot `11-nul-byte-ui-submit-result.png`, console
capture]**

Direct API probe — `POST /stories` with a NUL byte (`\x00`) embedded in `title`:

```
Attempt 1: HTTP 500 Internal Server Error
Attempt 2 (re-run, same payload): HTTP 500 Internal Server Error   ← reproducible
Follow-up GET /stories both times: count unchanged (36) — no stray/partial row inserted
```

Same result reproduced through the **real UI form**, not just the API: opened the edit form on a
disposable test story, set the `situation` field's value to `NUL-BYTE-UI-TEST-<NUL>-tail` via the
native `HTMLTextAreaElement` value setter + a real `input` event (so React's controlled-input state
genuinely held the NUL byte — confirmed `readBackHasNul: true`), clicked **Save Changes**:

- Network: `PUT /stories/{id}` → **500**
- Console: exactly one error logged (`Failed to load resource: … 500`) — the failure is NOT hidden
- UI: the form **stays open** (no optimistic "success" — `stillEditingAfterNul: 1`) and shows the raw
  error banner verbatim: `"PUT /stories/c060c73ddeafc5b968b23f003 failed (500): Internal Server Error"`
  — see `11-nul-byte-ui-submit-result.png`.

This confirms the class of bug already known on `workspaces.py` (`ML-settings-006`) is present here
too: `stories.py`/`story.py` have no `\x00` guard, so the string reaches psycopg2 unguarded and the
driver's bare `ValueError` surfaces as an unhandled 500 instead of a clean 422.

Positive finding buried in this test: the app does **not** fake success on this failure (no
optimistic UI update, no silent swallow) — the honest-error-surfacing requirement is met. The
negative finding is the wrong status code plus a raw technical string shown to the end user.

### Finding: GM2-STORY-005

- **Severity:** MEDIUM
- **Category:** Input validation / error handling (500 instead of 422)
- **Summary:** A NUL byte in any STAR field on `POST /stories` or `PUT /stories/{id}` crashes with an
  unhandled HTTP 500 instead of a clean 422 validation error — the same defect class already
  confirmed on `PUT /workspaces/settings` (`ML-settings-006`), now confirmed on the Story Bank's
  endpoints too, via both direct API call and the real UI form.
- **Reproduction:** `POST /stories` (or `PUT /stories/{id}`) with `\x00` embedded in any STAR field →
  `500 Internal Server Error`. Reproduced 3× total (2× API, 1× UI).
- **Expected:** `422` with a field-level validation message (matching the guard already present in
  `workspaces.py:905-921`), and a friendly, non-technical message in the UI.
- **Observed:** `500`, and the raw `"PUT /stories/{id} failed (500): Internal Server Error"` string
  (including the internal REST path) is shown directly to the user.
- **Evidence:** curl transcripts, `11-nul-byte-ui-submit-result.png`, `owner-part4-results.json`.
- **Status:** OPEN

**Cleanup:** the NUL-byte probes never produced a persisted row (both API attempts confirmed 0 stray
rows via follow-up `GET /stories`; the UI attempt was against an already-disposable test story that
was deleted at the end of the CRUD test — see §8).

---

## 7. Wireframe conformance

**[VERIFIED-WITH-FRESH-EVIDENCE, `01-owner-initial-full.png`, `07-header-statstrip-viewport.png`
vs. `design/screens/story-bank.html`]**

Layout, glass-card styling, sidebar, filter chips, 4-column STAR grid, and right-hand aside all match
the wireframe closely. Divergences found:

| # | Divergence | Assessment |
|---|---|---|
| GM2-STORY-006 | Wireframe stat strip = Total Stories / Quantified w/ Metrics / **Used This Month** / **Voice Match Avg**. Production = Total Stories / Quantified w/ Metrics / **Starred** / **Categories Covered**. | **Intentional, documented** — `stories.py` header comment: *"No usage or voice metrics are exposed — nothing tracks them yet, and invented numbers must never be presented as real."* This is an honest substitution, not a bug. Logged as **INFO**, not a defect. |
| GM2-STORY-007 | Wireframe empty state offers 3 CTAs (Import from Resume / **Import from Portfolio** / Add Manually). Production only implements 2 (Import from Resume / Add Manually) — no portfolio-import feature exists anywhere else in the app either. | Consistent scope reduction, not a broken button. Logged as **INFO**. |
| — | Interview Question Mapper and Coverage Gaps panels are wired to **real, live-computed data** (not the wireframe's static placeholder text) — confirmed the panel content changes correctly as stories are starred/created/deleted during testing. | Positive — better than the wireframe, not a divergence to flag. |

No other layout/spacing/color divergences observed at 1440px.

---

## 8. Click-every-control / submit-every-form pass (OWNER)

**[VERIFIED-WITH-FRESH-EVIDENCE, `owner-part1..part4-results.json`, screenshots `02-*`, `03-*`,
`04-*`, `09-*`, `10-*`]**

| Control | Test | Result |
|---|---|---|
| Filter chips (All/Leadership/Delivery/Technical/Risk & Compliance) | clicked each | All correctly filter the visible card set client-side; counts: All=36, Leadership=11, Delivery=0 (no story currently defaults to this category — consistent, not a bug), Technical=14, Risk & Compliance=11. `aria-pressed` toggles correctly. |
| Star toggle | click → reload → click again → reload | `false → true` (persisted across reload) `→ false` (reverted, persisted across reload). Full round-trip confirmed via `PUT /stories/{id}` returning 200 both times. |
| Insert button | click | Clipboard genuinely receives the real STAR text (`navigator.clipboard.readText()` returned the exact situation/task/action/result text) and the button label flips to "Copied" — not UI theater. |
| New Story form — empty submit | click Submit with all fields blank | Native HTML5 `required` validation blocks submission client-side (`"Please fill out this field."`); **no network call fired**. |
| New Story form — empty submit, bypassing client validation | direct `POST /stories` with all-empty strings | `422` with per-field `string_too_short` (`min_length=1`) errors — backend independently enforces the same rule. |
| New Story form — missing fields | direct `POST /stories` with only `title` | `422` with per-field `missing` errors for the other 4 required fields. |
| New Story form — adversarial oversized input | direct `POST /stories`, 10,000-char `title`, no length cap anywhere | **`201` — accepted with no `max_length` validation.** UI renders it safely (title `truncate`s with an ellipsis, confirmed no page overflow: `scrollWidth === clientWidth === 1440`, screenshot `17-huge-title-card.png`) — see GM2-STORY-008 below. |
| Full manual CRUD via the real UI | create → reload → edit → reload → delete (confirm dialog) → reload | Create: visible immediately and after reload. Edit: visible immediately and after reload. Delete: `window.confirm("Delete \"…\"? This cannot be undone.")` shown and accepted; row gone immediately and after reload; `DELETE` returned `204`. |
| Back/forward navigation | `/dashboard/stories` → `/dashboard` → back → forward | Back correctly returns to `/dashboard/stories` with a fresh re-fetch (36 cards); forward correctly returns to `/dashboard`. No stale/broken state observed. |

### Finding: GM2-STORY-008

- **Severity:** LOW
- **Category:** Input validation (missing bound, not a crash)
- **Summary:** No `max_length` constraint exists on any STAR field server-side — a 10,000-character
  title is accepted (`201`). The card UI defensively truncates so no visible layout break occurs
  (confirms the `MV-story-bank-002`/`min-w-0 truncate` fix referenced in `story-card.tsx` still
  holds), but the backend itself imposes no bound, unlike the precedent set for `fullName` etc.
  (`ML-settings-001`).
- **Reproduction:** `POST /stories` with a 10,000-char `title`, all other fields minimal → `201`.
- **Expected:** A reasonable server-side length cap with a `422` beyond it.
- **Observed:** No cap; accepted unbounded.
- **Evidence:** curl transcript, `17-huge-title-card.png` (shows the UI safely truncating it).
- **Status:** OPEN
- **Cleanup:** the oversized test row (`c818e79ac2b6b241eabc916e0`) was deleted via
  `DELETE /stories/{id}` → `204`, confirmed removed.

---

## 9. Network wiring / console hygiene

**[VERIFIED-WITH-FRESH-EVIDENCE, `owner-part1-results.json`, `owner-part5-results.json`]**

Across two independent fresh-session full-page loads plus the full CRUD/filter/star interaction
sequence (37 `/api/*` calls captured in the first pass alone): **zero** console errors, **zero**
`pageerror` events, **zero** `requestfailed` events, **100%** of `/api/*` responses were `2xx` during
honest (non-adversarial) use. The only console error seen in the entire test run was the single,
expected `500` from the deliberate NUL-byte adversarial probe (§6) — confirming the console is
clean during normal use and correctly surfaces the one failure we deliberately caused (no hidden
failed requests either direction).

---

## 10. AI-agent integration (Story Extractor)

The Story Bank's only AI-agent surface is `POST /agents/story-extractor/run`, triggered by both
"Import from Resume" (empty state) and "Draft missing stories" (aside panel). This was **not**
executed live against the OWNER account in this pass — the account already has 36 real stories, and
running the extractor again would manufacture *more* paraphrase duplicates on top of the 34 already
confirmed in §2, directly worsening the exact defect under test and leaving non-trivial state to
revert (LLM-generated content can't be byte-for-byte "un-run"). This is a deliberate scope decision
to avoid causing additional damage to real user data, not an oversight — the ground-truth brief's own
narrative ("the story bank grew 32 → 36 during this run because re-running story extraction on an
UNCHANGED résumé created 4 more near-duplicates") already demonstrates the agent's live behavior and
is corroborated independently by this report's §2/§3 findings from the create-endpoint level. Marked
**NOT TESTED (deliberately, to avoid data damage)** rather than HUMAN-GATED.

What **was** verified live: the entitlement gate in front of this specific agent endpoint. As the
NEW USER (Free/unsubscribed), `POST /agents/story-extractor/run` → `HTTP 402`
`{"error":"subscription_required","message":"An active subscription is required to use Aether.
Subscribe to unlock.","upgradeUrl":"/pricing"}` — honest denial, no fabricated run, matching the
pattern documented in `agents.py:_require_active_subscription`.

---

## 11. Paywall behaviour for a Free/new user (feeds GOV-011)

**[VERIFIED-WITH-FRESH-EVIDENCE, curl @2026-07-31T00:39–00:47Z, Playwright UI pass
@2026-07-31T00:47Z, screenshots `14-newuser-stories-page.png`, `16-pricing-page.png`]**

Two layers give two different answers, and the discrepancy itself is the finding:

**Backend (`/api/stories*`) — NOT gated.** As the NEW USER:
```
GET  /stories        → 200, []
GET  /stories/stats  → 200, {"total":0,"quantified":0,"starred":0,"categories":0}
```
The REST CRUD endpoints have no entitlement check (confirmed by reading `stories.py` — no
`_require_active_subscription` call anywhere in the file) and behave exactly as they should for a
brand-new, correctly-scoped user.

**Frontend (`/dashboard/stories` page) — 100% gated.** Loading the page as the NEW USER renders a
full-screen **"Subscribe to unlock Aether"** wall (`14-newuser-stories-page.png`) — no story list, no
New Story button, nothing — because `apps/web/src/components/subscription-gate.tsx` wraps every
known `/dashboard/*` section (including `/dashboard/stories`, explicitly listed in
`KNOWN_DASHBOARD_SECTIONS`) and checks `GET /billing/entitlement`:
```
GET /billing/entitlement → {"active_paid":false,"plan":{"id":"free","status":"active"},"requiresSubscription":true}
```
`requiresSubscription && !active_paid` ⇒ gate renders the paywall in place of the page's children —
**before** any Story Bank code runs, regardless of the fact that manual story CRUD makes no LLM/agent
calls and the underlying API would happily serve it.

This is the same shape of finding the ground-truth brief flagged for `/dashboard/jobs`, and it
applies identically here: `/pricing` (`16-pricing-page.png`) advertises **"Free $0 · No card
required · 5 agent runs / month · 5 tailored agent runs / month · Resume tailoring + ATS scoring ·
Community support · Get started free"** — but a Free-tier user cannot reach *any* dashboard feature,
including the entirely-free, non-agentic manual Story Bank CRUD workflow. The code comment in
`subscription-gate.tsx` acknowledges this is a known, tracked, deliberate beta-scope decision
("escalated to the product owner (ADR-MV-02 D1 / H-4)… genuinely gated agent features keep their
paywall" — i.e. the broader question of un-gating passive/manual features is open, not accidental).

### Finding: GM2-STORY-009

- **Severity:** MEDIUM
- **Category:** Paywall/entitlement inconsistency (feeds GOV-011)
- **Summary:** Story Bank is paywalled identically to `/dashboard/jobs` — a client-side gate blocks
  the entire screen for Free-tier users, even though the underlying API imposes no such restriction
  and the manual (non-agentic) parts of the screen cost nothing to serve. This contradicts the
  `/pricing` page's advertised Free-tier value ("5 agent runs/month… Resume tailoring + ATS
  scoring… Get started free") for a page that has largely non-agentic functionality.
- **Reproduction:** Log in as a Free-tier user → navigate to `/dashboard/stories` → full-screen
  "Subscribe to unlock Aether" wall renders instead of any content. Compare with
  `curl /api/stories` (as the same user) → `200 []`, proving the API itself is not the blocker.
- **Expected:** Either the marketing claim should not promise Free-tier value the product doesn't
  deliver, or non-agentic manual CRUD screens should not be blanket-gated.
  the pricing/subscription team already has this open per the code's own `ADR-MV-02 D1/H-4` reference.
- **Observed:** As described.
- **Evidence:** `14-newuser-stories-page.png`, `16-pricing-page.png`, curl transcripts above.
- **Status:** OPEN (tracked in code as a known, escalated decision — not a fresh regression)

**paywalled_for_new_user: true** (at the UI/page level; **false** at the raw-API level — both are
true statements about different layers, reported explicitly to avoid a misleading single boolean).

---

## 12. Fixture-fingerprint / contamination sweep

**[VERIFIED-WITH-FRESH-EVIDENCE, `owner-part3-results.json`]**

`document.body.innerText` on the fully-loaded 36-card page was searched for:
- `"GAP-P7-DEF-B Probe"` → **not found**
- Story-extractor LLM test-fixture text (`apps/api/tests/fixtures/llm/story_extractor/default.json`,
  e.g. `"Evidence effort reduction"`) → **not found**
- The fixture's literal SIT-window sentence (`"A SIT window of 75+ hours was mathematically
  infeasible for the program."`) → **not found verbatim**

Note: the real production story family "Recovery of Infeasible SIT Window for Payday Super…" *does*
independently mention "75+ hours" and "mathematically infeasible" — but with materially different
surrounding wording than the test fixture, and it is plainly describing the same real user's actual
résumé achievement (also present, unsurprisingly, several times per §2). This reads as coincidental
thematic overlap (the fixture author modeled realistic content on a similar achievement type), not
literal fixture leakage — flagged here for transparency but **not** logged as a contamination
finding, since no exact-string match was found anywhere on the page.

**fixture_string_found: false**

---

## 13. Realtime / auto-refresh (Gate G-I)

**[VERIFIED-WITH-FRESH-EVIDENCE, `owner-part2-realtime.json`, `window.fetch` instrumentation, not
passive network capture]**

`window.fetch` was monkey-patched via `page.addInitScript` **before** navigating to
`/dashboard/stories`, so every fetch the app's own code issues (including any hidden polling) was
logged with a timestamp. Observed over a continuous 65-second window after initial load:

```
[ {url: "/api/stories", t: …}, {url: "/api/stories/stats", t: … (+1ms)} ]
```

Exactly 2 calls total — both from the initial page load, 1ms apart — and **zero** further calls in
the following ~64 seconds. This is instrumentation-based (not inferred from a passive capture that
might miss a slow cadence), directly satisfying the brief's requirement to avoid the methodology that
produced a false "no polling" result elsewhere.

**realtime_interval_ms: null** — confirmed absence of auto-refresh on this screen.

---

## 14. Mobile (390px)

**[VERIFIED-WITH-FRESH-EVIDENCE, `08-mobile-390-full.png`, `08b-mobile-390-viewport.png`]**

```
document.documentElement.scrollWidth = 390
document.documentElement.clientWidth = 390
document.body.scrollWidth = 390
```

No horizontal overflow at 390px. Sidebar collapses to a bottom tab bar (Home/Jobs/Apps/Agents/Profile),
stat tiles reflow to a 2×2 grid, filter chips wrap, story cards stack single-column and remain fully
readable. Both "known-failing" baseline claims referenced in the brief were retested here from
scratch (not assumed) — this screen shows **no** overflow at 390px in this run.

**overflow_390px: false**

---

## 15. Unauthenticated access

**[VERIFIED-WITH-FRESH-EVIDENCE, `12-unauthenticated-access.png`, `owner-part4-results.json`]**

A brand-new, never-authenticated browser context navigating directly to `/dashboard/stories` was
redirected to `/login?next=%2Fdashboard%2Fstories` **before any `/api/*` call fired**
(`anonApiResponses: []` — confirmed zero network calls to the API, i.e., no data leak window).
Clean, correct gate.

---

## Findings summary table

| id | severity | category | summary | status |
|---|---|---|---|---|
| GM2-STORY-001 | HIGH | Data quality / duplicates | 34/36 stories are paraphrase re-tellings of 8 achievements | OPEN |
| GM2-STORY-002 | HIGH | Duplicate prevention | Create-dedup only catches byte-identical content, not paraphrases | OPEN |
| GM2-STORY-003 | MEDIUM | Missing feature | §7.4 relevance_score entirely unimplemented (param ignored, no field, no badge) | OPEN |
| GM2-STORY-004 | LOW | UX / missing affordance | No duplicate/merge UI signal anywhere despite confirmed duplication | OPEN |
| GM2-STORY-005 | MEDIUM | Input validation | NUL byte in any STAR field → 500 instead of 422 (API + real UI, matches `ML-settings-006` pattern) | OPEN |
| GM2-STORY-006 | INFO | Wireframe divergence | Stat strip swaps "Used This Month"/"Voice Match Avg" for "Starred"/"Categories Covered" — deliberate, honest (no fabricated metrics) | INFO / not a defect |
| GM2-STORY-007 | INFO | Wireframe divergence | Empty-state "Import from Portfolio" CTA not implemented | INFO / not a defect |
| GM2-STORY-008 | LOW | Input validation | No server-side max_length on STAR fields (10,000-char title accepted); UI safely truncates | OPEN |
| GM2-STORY-009 | MEDIUM | Paywall inconsistency | Story Bank UI 100% paywalled for Free users despite ungated API and non-agentic manual CRUD; contradicts `/pricing` Free-tier claims (feeds GOV-011) | OPEN (known/tracked) |

---

## Screenshot index

| File | What it shows |
|---|---|
| `01-owner-initial-full.png` | Full-page load, OWNER, all 36 stories, first fresh session |
| `02-filter-all.png` / `02-filter-leadership.png` / `02-filter-delivery.png` / `02-filter-technical.png` / `02-filter-risk-compliance.png` | Each filter chip's resulting card set |
| `03-star-toggled.png` | Star toggled on, viewport view |
| `04-create-form-empty.png` | New Story form open, all fields blank (pre-empty-submit test) |
| `05-dupgroup-jira-1.png` … `-6.png` | Each of the 6 JIRA Analytics Dashboard family cards, individually cropped |
| `06-dupgroup-anz-1.png` … `-5.png` | Each of the 5 ANZ Cloud-Native family cards, individually cropped |
| `07-header-statstrip-viewport.png` | Header + stat strip + Interview Question Mapper + Coverage Gaps, viewport crop |
| `08-mobile-390-full.png` / `08b-mobile-390-viewport.png` | 390px mobile viewport, full page and above-the-fold |
| `09-crud-after-create.png` | Disposable test story visible immediately after UI create |
| `10-crud-editing.png` | Same test story mid-edit (title changed) |
| `11-nul-byte-ui-submit-result.png` | NUL-byte edit submission → 500, raw error banner, form still open |
| `12-unauthenticated-access.png` | Anonymous context redirected to `/login?next=...` |
| `13-reverify-fresh-session.png` | Second, independent fresh-session full-page reload (verify-twice pass) |
| `14-newuser-stories-page.png` | NEW USER — full-screen "Subscribe to unlock Aether" paywall on `/dashboard/stories` |
| `16-pricing-page.png` | `/pricing` page, Free-tier claims |
| `17-huge-title-card.png` | 10,000-char title story, confirming UI truncation with no page overflow |

(`15-newuser-import-click-result.png` was not produced — the paywall pre-empted the empty-state
"Import from Resume" button entirely, so there was nothing to click; documented in §11 instead.)

---

## Console / network / server-log summary

- **Console errors during honest use:** 0 (two independent fresh sessions, full interaction sweep).
- **Console errors during adversarial use:** 1, expected (`500` from the deliberate NUL-byte probe).
- **`pageerror` events:** 0 across all sessions.
- **`requestfailed` events:** 0 across all sessions.
- **`/api/*` call success rate during honest use:** 100% (all `2xx`), 37 calls captured in the primary
  pass alone.
- Server-side application logs were not tailed directly (no shell/journalctl access delegated to this
  agent for this run); all backend behaviour was verified through HTTP response codes/bodies instead,
  which is sufficient to substantiate every finding above (each finding cites an exact status code and
  response body).

---

## Not-tested items

- **Live Story Extractor agent run against OWNER's real data** — deliberately not executed; running
  it would manufacture additional paraphrase duplicates on top of the 34 already confirmed, actively
  worsening GM2-STORY-001 with no clean way to revert LLM-generated inserts. The endpoint's
  entitlement gate (402 for Free users) and its dedup behavior at the storage layer were still
  verified via the equivalent `POST /stories` path and via the ground-truth brief's own documented
  32→36 growth event. Not HUMAN-GATED — a scope decision to avoid data damage, disclosed per protocol
  as an explicit deviation.
- **Server-side application/error logs** — not tailed (no log-tailing access in this run); all
  findings are instead substantiated by HTTP status codes and response bodies captured directly,
  which fully support each claim made.

---

## CLEANUP — everything created and reverted

| Created | Action | Verified reverted |
|---|---|---|
| Story `c1aeba503e135c2dca918fade` ("GM2-DEDUP-TEST Story Alpha", identical-content dedup test) | `DELETE /stories/{id}` | Yes — `204`, confirmed absent from a follow-up `GET /stories` |
| Story `cff1aab6e968e271d740d4e6e` ("GM2-DEDUP-TEST Story Alpha (reworded)", paraphrase test) | `DELETE /stories/{id}` | Yes — `204`, confirmed absent |
| Story `c060c73ddeafc5b968b23f003` ("GM2-UI-CRUD-TEST Story" → edited to "…EDITED", full UI CRUD + NUL-byte test) | Deleted via the real UI delete button + confirm dialog | Yes — gone immediately and after reload |
| Story `c818e79ac2b6b241eabc916e0` (10,000-char title, oversized-input test) | `DELETE /stories/{id}` | Yes — `204`, confirmed absent |
| Owner story `c4923cf666dd909e4c22f02ba` starred flag (toggled true → false during the star-toggle test) | Toggled back via `PUT /stories/{id}`, `metrics.__starred: false` | Yes — starred count returned to the original 6 after reload |

**Final state check** (fresh `GET /stories` as OWNER, end of run): **36 stories, 6 starred, 0 leftover
test rows** — exactly matching the pre-test baseline captured at the start of this run. No adversarial
probe (NUL byte, empty strings, missing fields) left any partial/orphaned row in either case — every
`500`/`422` response was confirmed via follow-up `GET` to have inserted nothing.

No test accounts were created for this screen (both OWNER and NEW USER identities were pre-existing
per the canonical recipes); nothing to purge on that front.

---

## Verdict

**Story Bank is functionally solid for CRUD, navigation, auth-gating, and error-honesty**, but
**fails the assigned priority gate (G-E, zero duplicates + relevance)**: dedup only catches literal
byte-identical resubmission, so the screen's core promise — a curated, reusable achievement library —
is undermined by real, confirmed, human-obvious duplication (34/36 rows), zero relevance-scoring
implementation (§7.4 absent entirely), and zero in-product way for a user to even notice the
duplication. A shared input-validation gap (NUL byte → 500, no max_length) mirrors an
already-known defect class elsewhere in the app, and the Free-tier paywall story is inconsistent with
what `/pricing` advertises, though that specific inconsistency is a pre-existing, tracked product
decision rather than a fresh regression discovered here.

9 findings filed (2 HIGH, 3 MEDIUM, 2 LOW, 2 INFO/not-a-defect), all reproduced and evidenced,
duplicate audit and adversarial-input claims each independently verified twice across separate fresh
browser sessions per protocol. All test data created during this run was deleted/reverted and
confirmed back to the exact pre-test baseline (36 stories, 6 starred).
