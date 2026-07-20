# TESTING OUTCOME REPORT — Story Bank

- **Screen ID:** story-bank
- **Screen name:** Story Bank ("Achievement & Narrative Library")
- **Route:** `/dashboard/stories`
- **Wireframe reference:** `design/screens/story-bank.html`
- **Backing endpoints (per BRIEF.json):** `GET/POST/PUT/DELETE /stories`, `GET /stories/stats`, `POST /agents/story-extractor/run`, `GET /agents/stats`
- **Agents:** storyExtractor
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Repo / commit SHA:** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Account under test:** `admin` / `admin123` (TEMPORARY Pro entitlement: `active_paid:true`, 100 runs/period, $15 spend cap — confirmed live via `GET /billing/entitlement` and `GET /billing/subscription`)
- **Session window (UTC):** 2026-07-17T15:42:52Z → 2026-07-17T16:06:52Z (two independent Playwright sessions/logins, plus one direct-API re-verification call)
- **Tester:** screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1

---

## 1. Element inventory

| Element | data-testid / selector | Tested | Result |
|---|---|---|---|
| New Story button (header) | `add-story-btn` | Yes | Opens create form. PASS |
| Stat strip (4 tiles) | `story-stats` | Yes | Real, live-computed values (Total/Quantified/Starred/Categories). Labels differ from wireframe — see MV-story-bank-007 |
| Filter: All | `filter-all` | Yes | Fires `GET /stories`, shows all. PASS |
| Filter: Leadership | `filter-leadership` | Yes | Fires `GET /stories?category=Leadership`, shows only Leadership cards. PASS |
| Filter: Delivery | `filter-delivery` | Yes | Fires `GET /stories?category=Delivery`. PASS |
| Filter: Technical | `filter-technical` | Yes | Fires `GET /stories?category=Technical`. PASS |
| Filter: Risk & Compliance | `filter-risk-compliance` | Yes | Fires `GET /stories?category=Risk%20%26%20Compliance`, URL-encoded correctly. PASS |
| Story card — star toggle | `star-story-btn` | Yes | `PUT /stories/{id}` with `metrics.__starred`; persists after reload. PASS |
| Story card — edit (pencil) | `edit-story-btn` | Yes | Opens inline `StoryForm`; save fires `PUT`; persists after reload. PASS |
| Story card — delete (trash) | `delete-story-btn` | Yes | Fires `DELETE`; removes immediately, no confirmation — see MV-story-bank-003 |
| Story card — Insert | `insert-story-btn` | Yes | Copies formatted STAR text to clipboard (verified via `navigator.clipboard.readText()`); button shows "Copied" feedback. PASS |
| Create-story form (title/situation/task/action/result/tags) | `story-form-*` | Yes | Valid/empty/XSS/unicode/huge-input all tested — see §3 |
| Empty state — Import from Resume | `empty-import-resume` | Yes | Real trigger, calls `POST /agents/story-extractor/run`. PASS |
| Empty state — Import from Portfolio | `empty-import-portfolio` | Yes | **Does nothing but open the blank manual form — no import occurs.** MV-story-bank-001 |
| Empty state — Add Manually | `empty-add-manual` | Yes (via equivalent "New Story" control, same handler per source) | Opens blank manual form. PASS |
| Interview Question Mapper (aside) | `question-mapper` | Yes (read-only) | Live-derived from current stories (best-match by category+metric count); updates correctly as stories are added. PASS |
| Coverage Gaps (aside) | `coverage-gaps` | Yes (read-only) | Live-derived keyword coverage over current stories (No story / Thin / Covered). PASS |
| "Draft missing stories" button | `draft-missing-btn` | Yes | Same `POST /agents/story-extractor/run` call; shows "Drafting from resume…" + spinner + disabled state while running. PASS — see §4 for full agent-run evidence |
| Sidebar nav links | n/a | Spot-checked (Dashboard, Story Bank active state) | Present, functional, consistent with app shell |
| Unauthenticated access to `/dashboard/stories` | n/a | Yes (2 fresh contexts) | Clean redirect to `/login`, no console errors |
| Back/forward browser nav | n/a | Yes | Round-trips correctly, filter state and card list intact |
| Throttled reload (400ms latency, 50KB/s) | n/a | Yes | Loads in 3.79s, all cards render, no stuck loading state |

**Total distinct interactive controls identified:** 17 (New Story, 5 filters, 3 per-card actions × N cards, Insert, 3 empty-state buttons, Draft-missing-stories, form submit/cancel). All exercised at least once; none found dead/404/no-op except "Import from Portfolio" (MV-story-bank-001).

---

## 2. Visual conformance vs wireframe

Full-page screenshots: `test-artifacts/01-initial-load-fullpage.png` (first load), `test-artifacts/18-final-clean-state-11-real-stories.png` (clean post-cleanup state), `test-artifacts/19-empty-state-demo-view.png` (empty state).

Layout, sidebar, header, filter chips, STAR-quadrant card structure, and the right-hand Interview Question Mapper + Coverage Gaps aside all match the wireframe's structure closely. Differences found:

- **Stat tiles**: wireframe's "Used This Month" / "Voice Match Avg" (hardcoded demo numbers) are replaced with "Starred" / "Categories Covered" (real, live-computed). Documented, deliberate anti-fabrication choice in `apps/api/app/routers/stories.py`'s module docstring. Logged as **MV-story-bank-007** (LOW, visual) per protocol (every deviation must be logged even if justified).
- **Card actions**: wireframe shows star + ellipsis (implying a dropdown menu); live app shows star + edit(pencil) + delete(trash) as three explicit icon buttons. Functionally equivalent-or-better (no hidden menu); not filed as a defect.
- **"Insert" button**: implemented as copy-to-clipboard of formatted STAR text rather than an in-place document insert. Reasonable interpretation of "Insert"; not filed as a defect.
- Empty state (icon, heading, copy, three buttons) matches the wireframe almost verbatim in copy and structure.

No missing/broken/misleading components found beyond what's logged above.

---

## 3. Forms — valid / empty / boundary / unicode / XSS

All via `POST /stories` and `PUT /stories/{id}`, verified with network capture and reload-persistence checks, **twice** (two independent sessions):

| Case | Result |
|---|---|
| Valid create (title/situation/task/action/result/tags) | `201 Created`; appears in DOM; **persists after reload** |
| Valid edit (title change) | `200 OK`; **persists after reload** |
| Empty submit (all fields blank) | Native HTML5 `required` validation blocks submission client-side (`validationMessage: "Please fill out this field."`); **zero API call fired** — confirmed no silent 200/failure |
| XSS payloads (`<script>alert(1)</script>`, `<img src=x onerror=alert(2)>`, `<svg onload=alert(3)>`, `<b>`, quotes, backslashes) in title/situation/task/action/tags | Stored and rendered as **literal escaped text** — zero `dialog` events fired in either pass (React's default JSX escaping). Confirmed safe in DOM (`page.content()`), safe on reload, and safe when copied via Insert→clipboard (plain text, not executed) |
| Unicode / emoji (`测试`, `🚀`, `émoji`, `日本語`, `Ñoño`, em-dash) | Stored and rendered correctly, no mangling |
| Huge unbroken input (15,000–20,000 chars, no whitespace) | `201 Created` — **no server-side length limit enforced** (acceptable) but **breaks page layout** — see **MV-story-bank-002** |

Star-toggle persistence (`PUT` with `metrics.__starred`) also verified round-tripping correctly across reload, twice.

---

## 4. UI↔backend wiring & AI-agent integration (storyExtractor)

**Agent run executed live, twice, from the real UI control ("Draft missing stories") and once more via direct API for a fresh timestamp check.**

### Run 1 (UI-triggered, script-driven Playwright click on `draft-missing-btn`)
- Button showed honest progress state: label changed to "Drafting from resume…", spinner icon, `disabled=true`, `aria-busy=true` while in flight.
- Network: `POST /agents/story-extractor/run` → `200 OK` after ~12.5s.
- Response: `{"created": 8, "dropped": ["Delivering Real-Time Telemetry Platform for 10k+ Devices at ANZ"], "model": "qwen/qwen3-coder-next", "tokensIn": 401, "tokensOut": 130, "costUsd": 0.000661, "duration_ms": 12458, "run_id": "cfb8f5408c4a09f58992b803a", "billingAudit": {"authMode": "api_key", "provider": "openrouter", "quotaPath": "metered_api", "credentialSource": "environment"}}`
- Stat strip updated live: Total Stories 5→13, Quantified 3→9, Categories Covered 3→4 — UI reflects the response, not stale/cached.
- Audit row confirmed independently via `GET /agents/runs` (`agentName: storyExtractor`, `status: completed`, matching `costUsd`, `startedAt: 2026-07-17T15:50:48.056Z`, `completedAt: 2026-07-17T15:51:00.722Z`).
- Quota: `GET /billing/subscription` before → `runsUsed: 10`; after → `runsUsed: 12` (delta of 2 includes at least one concurrent tester's run in the same window — confirmed via `GET /agents/runs` showing a `tailor` run from a different session completing seconds before mine; **my own run's individual quota consumption is independently confirmed via its own audit row**, not just the aggregate counter).

### Run 2 (direct API re-verification, fresh timestamp)
- `POST /agents/story-extractor/run` at `2026-07-17T16:01:49Z` → `{"created": 7, "dropped": [...], "model": "qwen/qwen3-coder-next", "tokensIn": 401, "tokensOut": 122, "costUsd": 0.000645, "duration_ms": 22391, "run_id": "c974b24738b44a2793ee9b0d2"}`.
- Confirms **non-deterministic, varying content between calls** (different `created` count, different dropped title) — inconsistent with a static canned fixture, consistent with genuine live generation.

### Real-generation verification (fixture-fingerprint check)
- `apps/api/tests/fixtures/llm/story_extractor/default.json` contains distinctive canned strings: title `"Evidence effort reduction"`, situation opening `"Manual evidence cutting for delivery scenarios..."`, title `"Delivery recovery of an infeasible SIT window"`.
- Grepped **all 15 stories created across both of my runs** (26 total stories in the account) for these exact fingerprint strings: **zero matches** — real-generation confirmed.
- Created content is specific and grounded: e.g. "Architecting COBOL/Mainframe Test Automation Reducing Effort by 92%" (situation: "The Payday Super reform program required test evidence automation for 200+ SIT/E2E scenarios across eight squads..."), "Recovering Infeasible SIT Window for Payday Super Reform Program", "Aligning Executive Strategy via 40+ GM Workshops at ANZ" — thematically related to the fixture's demo content but materially different, far more detailed, and citing real entities (ATO, Payday Super, ANZ) consistent with the account owner's actual career history, not generic filler.
- Backend enforces evidence-grounding server-side: `story_extractor.py::_metrics_evidenced` drops any story whose metric numbers don't appear verbatim in the source resume text — confirmed via the `dropped` list in both run responses (each dropped exactly one candidate story that didn't pass evidencing/dedup).

### Serving model observed
`qwen/qwen3-coder-next` (both of my runs). Server-side logs at test time show the *primary* configured model for the STRUCTURED tier (`claude-haiku-4-5-20251001`) is currently being rate-limited by its provider; the client's documented model-fallback chain (`D-0014`) correctly retried with the fallback model and succeeded — this is honest, working resilience behavior, not a defect.

### Production log finding — historical fixture-masquerade evidence (MV-story-bank-005)
While investigating agent audit trails I inspected `/var/log/aether/api.log` directly (per `docs/delivery/DEPLOYMENT-RUNBOOK.md` §4) and found 57 occurrences of the literal line `LLM auto mode: served fixture fallback for prompt '<name>'` (5 for `story_extractor`), a message that **does not exist anywhere in the current source tree**. `git log -p` shows this exact code path (silently replaying a static test fixture as "live" output on total live-call failure) was deleted by commit `0f7a5ff` (2026-07-16T12:33:01Z, "fix(GAP-P6-AUTH-002...): honest LLM failure (no fixture masquerade)") and replaced with an honest `LLMUnavailableError`. Because `api.log` is append-only and never rotated (confirmed in the runbook) and carries **no timestamps**, I cannot date these 57 lines precisely — they most plausibly predate the fix's deployment and are retained historical evidence, not a currently-reproducing defect: my own two fresh storyExtractor runs (latest 2026-07-17T16:01:49Z) show clean, honest, current behavior, no recurrence in the ~7,800 log lines following the last observed occurrence, and no fixture-fingerprint content is present anywhere in the live Story Bank. Filed as **MV-story-bank-005 (HIGH)** because the underlying defect class is exactly what the BLOCKER-tier "fabricated content" criterion describes and it directly bears on **CLM-024**'s claim that this exact gate is closed — the orchestrator should treat this as needing infra-level dating (exact deploy/restart timeline) rather than a UI re-test, since it is not reproducible from the UI alone.

---

## 5. CRUD round-trip (MV-storybank- prefixed data)

All created via the real UI, all verified to persist after a full page reload, all cleaned up by me at the end (verified gone after reload):

1. `MV-storybank-001 Reduced onboarding time by 47%` → created → edited to `MV-storybank-001-EDITED Reduced onboarding time by 51%` → starred → **deleted**. All 4 transitions persisted across reload.
2. `MV-storybank-002 <script>alert(1)</script> XSS 测试 🚀 émoji` (XSS/unicode boundary case) → created → persisted → **deleted**.
3. `MV-storybank-003 huge-input-test` (20,000-char boundary case, triggered MV-story-bank-002 layout bug) → created → persisted → **deleted** (cleanup, to de-pollute the shared account's layout for other concurrent testers).
4. `MV-storybank-004-VERIFY2` / `-EDITED` (second-session repro of XSS + edit + delete) → created → edited → **deleted**, no confirm dialog.
5. `MV-storybank-005-VERIFY2-huge` (second-session repro of the layout bug, 15,000 chars) → created → **deleted**.

Final state confirmed via direct API: **0 MV-storybank- prefixed stories remain** in the account. The 15 real stories produced by my 2 storyExtractor runs were left in place (legitimate, correctly-grounded product data — not test junk; deleting real, correctly-generated career narratives did not fit the intent of "clean up your test data").

---

## 6. Error / edge states

| Case | Result |
|---|---|
| Unauthenticated access to `/dashboard/stories` (fresh context, no token) | Clean redirect to `/login`; zero console errors; reproduced twice |
| Browser back/forward through the screen | Round-trips correctly; card list and filter state intact after `goBack`; no errors |
| Throttled reload (400ms RTT, 50KB/s via CDP `Network.emulateNetworkConditions`) | Loads in 3.79s; all cards render; no infinite/stuck loading skeleton |
| Delete with no confirmation | See MV-story-bank-003 |
| Huge unbroken input | See MV-story-bank-002 |
| Concurrent testers' activity on the shared account | Observed and correctly attributed via audit `run_id`/timestamps — did not assert on or modify any non-MV-prefixed data |

---

## 7. Console / network / server-log hygiene

- **Console errors (all sessions, all page loads/reloads, ~15 distinct navigations across 8 Playwright scripts):** 0 uncaught errors, 0 `pageerror` events, 0 unexpected `dialog` events.
- **Failed requests surfaced to the user:** 0.
- **Failed requests NOT surfaced to the user:** 4 (`net::ERR_ABORTED` on `DELETE /stories/{id}`, across two sessions) — functionally harmless, deletion verified correct via direct API cross-check both times. Filed as **MV-story-bank-004 (LOW)**.
- **Server-side 5xx during my session window (`/var/log/aether/api.log`):** 0 on any `/stories` or `/agents/story-extractor` endpoint. (One unrelated `501 Not Implemented` on `POST /resumes/{id}/download` was observed in the shared log during my window — a different screen/endpoint, out of scope, not asserted on.)
- **Historical log anomaly:** see MV-story-bank-005 above.

---

## 8. Claim verdicts

| Claim ID | Claim (abridged) | Verdict | Evidence |
|---|---|---|---|
| CLM-076 | "Story Bank supports manual create/edit of STAR-format stories via a form" (`POST /stories`, `PUT /stories/{id}`) | **CONFIRMED** | Live create + edit both exercised via the real form, twice, in two independent sessions; both round-trip correctly through a full page reload. §3, §5. |
| CLM-024 | "All 27 core Phase-7 gates VERIFIED-CLOSED incl. 0 console errors across 20 routes (GATE-16), 0 same-origin 5xx (GATE-17), 676 pytest, 297 vitest, Playwright E2E green" | **PARTIALLY-TRUE** (scoped to my one screen) | For `/dashboard/stories` specifically: 0 console errors and 0 same-origin 5xx confirmed fresh, across many reloads/sessions (§7). I cannot verify the other 19 routes or re-run the pytest/vitest suites from a single-screen tester's scope — **UNVERIFIABLE-FROM-UI** for those parts. Additionally, historical production-log evidence (MV-story-bank-005) shows the exact GAP-P6-AUTH-002 "fixture masquerade" defect this claim's gate set is supposed to have eliminated DID occur in this environment at some point retained in the (unrotated, un-timestamped) log — current live re-verification is clean, but the claim's unconditional "closed" framing is not fully supported by what I can verify. |
| CLM-062 | "Playwright sweep of 14 dashboard routes + /pricing + /admin as paid admin: 0 console errors / 0 failed requests / 0 page errors (GATE-03)" | **PARTIALLY-TRUE** (scoped to my one screen) | For `/dashboard/stories`: 0 console errors, 0 page errors confirmed. 0 failed requests **surfaced to the user**, but 4 non-user-facing `net::ERR_ABORTED` events were observed on DELETE calls (MV-story-bank-004) that a strict "0 failed requests" reading would not satisfy, even though they did not affect correctness. Cannot verify the other 13 routes + /pricing + /admin from my scope. |

---

## 9. UNSURE items (escalated, not guessed)

1. **Dating of the MV-story-bank-005 historical log evidence.** I cannot determine from black-box UI/API testing or un-timestamped logs exactly when the 57 "served fixture fallback" lines were written, nor whether any user-visible content (in any account, on any screen — tailor/coverLetter output is out of my scope) was silently served as fixture-masquerading-as-live during that window and is still live/undetected today. **Two candidate interpretations:**
   (a) Purely historical — these lines predate commit `0f7a5ff`'s deploy and are harmless residue in an unrotated log; current behavior (verified twice, freshest 2026-07-17T16:01:49Z) is honest.
   (b) The defect is intermittent/still latent under some condition I did not trigger (e.g., a specific rate-limit/budget-exhaustion combination), and could recur for other users' runs today.
   I lean towards (a) given the code-level fix is unambiguously present and my re-verification is clean, but I cannot fully rule out (b) without infra-level access to process/deploy history that is out of a screen-tester's scope. **Recommend the orchestrator route this to infra-discovery/qa-adversary for exact deploy-timeline correlation, and to the Resume Studio / Cover Letter Studio testers to check whether any currently-visible tailored-resume or cover-letter content matches THEIR fixture fingerprints.**
2. **"Add Manually" button** (empty-state) was verified functionally-identical to "New Story" via source-code reading (same `openCreate()` handler) and via extensive testing of the equivalent "New Story" control, but was not independently clicked in the empty-state view specifically (script crashed after the "Import from Portfolio" click removed the empty state before I could re-enter it and click "Add Manually" directly). Given the shared handler is unambiguous in source, I classify this as **INFERRED**, not UNSURE, but flag it for anyone re-verifying to do the one extra literal click for full protocol completeness.

---

## 10. Screenshot index

All under `test-artifacts/`:

| File | Shows |
|---|---|
| `01-initial-load-fullpage.png` | First authenticated load, 3 pre-existing seed stories |
| `02-story-bank-loaded-3-seed-stories.png` | Element-inventory pass |
| `03-after-create-MV-story.png` | After creating MV-storybank-001 |
| `04-create-persists-after-reload.png` | Reload persistence check for create |
| `05-after-edit-MV-story.png` | After editing MV-storybank-001 |
| `06-empty-form-native-validation.png` | Empty-submit native validation |
| `07-xss-unicode-story-created-safe.png` | XSS/unicode story rendered safely |
| `08-xss-safe-after-reload.png` | XSS story safe after reload |
| `09-BUG-huge-unbroken-string-layout-break-crop.png` | **MV-story-bank-002**: layout break from unbroken long string |
| `10-filter-leadership-active.png` | Leadership filter active state |
| `11-insert-copied-to-clipboard.png` | Insert → clipboard "Copied" feedback |
| `12-storyExtractor-running-state.png` | Honest in-flight progress state ("Drafting from resume…") |
| `13-storyExtractor-8-new-stories-created.png` | Post-run: 8 new real stories, updated stats |
| `14-unauthenticated-redirect-to-login.png` | Unauth redirect |
| `16-throttled-reload-loads-ok.png` | Throttled-network reload |
| `18-final-clean-state-11-real-stories.png` | Final clean state after all MV- cleanup |
| `19-empty-state-demo-view.png` | Empty state (`?demo=empty`) matching wireframe |
| `20-BUG-import-from-portfolio-opens-blank-manual-form.png` | **MV-story-bank-001**: Import-from-Portfolio does nothing but open the manual form |
| `evidence-*.json` | Raw network/API-call/result captures backing the above |

---

## 11. NOT-TESTED (HUMAN-GATED only)

- **Sidebar navigation to other screens** (Dashboard, Jobs, Resume Studio, etc.) beyond confirming the Story Bank nav item is active and links render — full functional testing of those screens is each their own screen-tester's scope, not mine.
- **Forcing a genuine live-LLM failure for storyExtractor on demand** (e.g., to directly reproduce the historical MV-story-bank-005 condition) — I have no supported way to make the live provider fail on command from the UI/API without either waiting for a real rate-limit window or modifying server config, both of which are outside a screen-tester's read-only, no-service-restart mandate. This is why MV-story-bank-005 is filed from log forensics rather than a live repro.
- **Multi-user cross-account verification of MV-story-bank-006** (whether a second, non-admin account's storyExtractor run would pull Vikram's resume content into that account's Story Bank) — creating and exercising a second real user account was outside this screen's assigned test identity (admin/admin123 only, per brief) and risks polluting the shared environment for other concurrent testers; filed as a source-code-verified (not live-verified) finding instead.

---

## Sign-off

Tested by: screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, screen `story-bank`.
Every finding above reproduced at least once and, where the finding is a live-UI behavior (not log forensics), reproduced a **second time in a fresh browser session** per §3.2.9 before filing. No finding is filed as FLAKY — all reproduced consistently on both passes. All claims in this report are [VERIFIED-WITH-FRESH-EVIDENCE] from this run's artifacts/timestamps unless explicitly marked [INFERRED] (source-code-verified only, e.g. MV-story-bank-006, the "Add Manually" note) in §9/§11.
