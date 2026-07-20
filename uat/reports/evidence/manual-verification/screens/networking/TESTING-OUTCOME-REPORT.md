# TESTING-OUTCOME-REPORT — Networking (Recruiter & Referral CRM)

- **Screen id:** `networking`
- **Route:** `/dashboard/networking`
- **Wireframe:** `design/screens/networking.html`
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Repo / commit SHA:** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Tester:** screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1
- **Session window (UTC):** 2026-07-17T16:14:42Z → 2026-07-17T16:23:49Z (four separate browser sessions/scripts; see Sessions below)
- **Login used:** canonical login snippet, `admin` / `admin123` (temp Pro entitlement per brief), verbatim per `uat/reports/evidence/manual-verification/canonical-login.md`

## My own expectation of this screen (formed before looking at the build)

From the wireframe (`networking.html`) and product sense, this screen should be a lightweight recruiter/referral CRM: a 5-stage pipeline (New → Warm → Active → Scheduled → Placed) of real contacts, an "Add Contact" action that actually creates a persisted contact, some way to open a contact and update its stage / add notes / set a follow-up reminder, an outreach queue showing drafted/queued messages tied to real `OutreachTask` rows, a communication log of past sends, and (per the brief) possibly an emailAgent-drafted-outreach flow gated behind Gmail OAuth. An empty state should offer a real LinkedIn import or a manual add.

## Sessions

| Session | Purpose | Script |
|---|---|---|
| A | Full first-pass protocol run: unauth redirect, login, load, element inventory, Add Contact (empty/valid/XSS/unicode), reload persistence, direct-API CRUD, empty-state, XSS render check, boundary/invalid, 404, back/forward, emailAgent presence check | `test-artifacts/scripts/nw-session-a.cjs` |
| B | Fresh browser, second verification pass: unauth re-verify, populated-state seed via real API, contact-card click, Review-all-drafts click, Add-Contact re-verify (client-only), throttled reload, wireframe-badge check, cleanup | `test-artifacts/scripts/nw-session-b.cjs` |
| C | Targeted evidence capture for the Outreach Queue / Communication Log field-mapping defect | `test-artifacts/scripts/nw-session-c-wiring-proof.cjs` |
| D | React duplicate-key console-warning check for Communication Log | `test-artifacts/scripts/nw-session-d-keycheck.cjs` |
| E (×2) | Modal close-control testing (X / Cancel / Escape), run twice fresh for VERIFY-TWICE | `test-artifacts/scripts/nw-session-e-modal-controls.cjs` |

All test data was prefixed `MV-networking-`; all of it was created and deleted by this tester only, confirmed empty (`GET /networking/contacts` → `[]`, `GET /networking/outreach` → `[]`) at the end of the run.

---

## Element inventory

| Element | Wireframe id | Tested | Result |
|---|---|---|---|
| Sidebar nav (Dashboard, Jobs, …) | nav-primary-nw02 | Out of scope | Shared dashboard shell, owned by other screens' testers |
| Top search / notification bell / avatar | (shell) | Out of scope | Shared dashboard shell |
| "+ Add Contact" header button | add-contact-nw05 | Yes | Opens modal correctly, but underlying Save is fake — see MV-networking-001 |
| Empty state: "Import from LinkedIn" button | empty-import-li-nw19 | Yes | Opens manual Add-Contact modal, no LinkedIn flow — MV-networking-003 |
| Empty state: "Add Contact Manually" button | empty-add-manual-nw20 | N/A | Does not exist in shipped build (merged into the mislabeled LinkedIn button) — MV-networking-003 |
| Add Contact modal — Name input | (new) | Yes | Client validation ("Name is required") works |
| Add Contact modal — Role input | (new) | Yes | Accepts XSS/unicode input safely (escaped on render) |
| Add Contact modal — Company input | (new) | Yes | Accepts XSS/unicode input safely |
| Add Contact modal — Save Contact button | (new) | Yes | "Succeeds" visually but never calls the backend — MV-networking-001 |
| Add Contact modal — Cancel button | (new) | Yes | Closes modal, discards from pipeline, but leaves stale text in form state — MV-networking-009 |
| Add Contact modal — X close button | (new) | Yes | Works correctly |
| Add Contact modal — Escape key | (new) | Yes | Does NOT close modal despite source handler — MV-networking-010 |
| Stat tiles (Contacts / Active conversations / Referrals in flight / Response rate) | crm-stats-nw06 | Yes | Real DB-backed values, verified via direct-API create+reload |
| Contact Pipeline — 5 columns | pipeline-nw07 | Yes | Real DB read-path correct; empty-column placeholders honest ("No contacts yet") |
| Contact card (per pipeline item) | contact-nw08…12 | Yes | Not clickable/interactive — no detail view exists — MV-networking-005 |
| Contact card — stage badges (Call Thu / Referred) | contact-nw11/12 | Yes | Missing vs wireframe — MV-networking-006 |
| Outreach Queue card | outreach-nw14 | Yes | Real data, but field-mapping mismatch leaves most fields blank — MV-networking-002 |
| "Review all drafts" button | review-outreach-nw15 | Yes | Dead button, no handler — MV-networking-004 |
| Communication Log card | commlog-nw16 | Yes | Real data, essentially illegible due to same field-mapping mismatch — MV-networking-002 |
| "Preview empty state" toggle (wireframe-only, no live equivalent) | toggle-empty-nw17 | N/A | Wireframe-only mock control; live build uses `?demo=empty` query param instead — functionally equivalent, verified working |

---

## Findings

See `findings.json` for the machine-readable rows (schema per §4.1). Summary table:

| id | severity | category | summary |
|---|---|---|---|
| MV-networking-001 | BLOCKER | defect | "Add Contact" is 100% client-side fake; never calls POST /networking/contacts; lost on reload |
| MV-networking-002 | HIGH | wiring | Outreach Queue / Communication Log field-name mismatch → real data renders blank/illegible |
| MV-networking-003 | HIGH | defect | "Import from LinkedIn" opens the manual Add-Contact modal; no real LinkedIn integration |
| MV-networking-004 | MEDIUM | defect | "Review all drafts" button has no click handler — dead end |
| MV-networking-005 | HIGH | coverage-gap | No contact-detail view; can't edit stage/notes/reminders from any UI control |
| MV-networking-006 | LOW | visual | Missing wireframe stage badges (Call Thu / Referred) |
| MV-networking-007 | MEDIUM | defect | OutreachTask FK/cascade not enforced — orphan rows possible |
| MV-networking-008 | LOW | coverage-gap | emailAgent not wired/reachable anywhere on this screen |
| MV-networking-009 | LOW | defect | Cancel doesn't reset Add-Contact form state |
| MV-networking-010 | LOW | defect | Escape key doesn't close Add-Contact modal |

---

## CRUD round-trip result: **FAILED for Create (via UI), PASSED for Read/Update/Delete (via direct API only)**

- **Create via UI:** FAILS — MV-networking-001. The only reachable "create" control never reaches the backend.
- **Create via direct API (POST /networking/contacts):** works, 201, persists.
- **Read (UI pipeline ← GET /workspaces/networking/summary ← real `Contact` rows):** works correctly — a contact created via direct API appears in the correct pipeline column after reload.
- **Update (PATCH /networking/contacts/{id}):** works via direct API; UI correctly reflects the change (stage move, title text) after reload. No UI control exists to trigger an update (MV-networking-005).
- **Delete (DELETE /networking/contacts/{id}):** works via direct API; UI correctly reflects removal after reload. No UI control exists to trigger a delete.

Because the screen's only reachable create path is fake, and edit/delete have zero UI entry points at all, I assess **CRUD round-trip as failed overall from a real user's perspective** — a paying user cannot actually manage a contact's lifecycle through this screen, only view what a database script/support engineer put there.

## Email/outreach-agent gate

No Gmail-OAuth gate, no "Connect Gmail" affordance, and no emailAgent trigger exist anywhere on this screen (MV-networking-008). This is not a paywall-402 or a broken OAuth handshake — it's simply absent. There is therefore no human gate to describe for this screen: the entire outreach-drafting-by-AI concept shown in the wireframe ("Agent drafted a warm follow-up referencing Canva scaling") does not exist in the shipped product. The Outreach Queue/Communication Log that *do* exist are plain CRUD views over `OutreachTask` rows with no AI involvement, and even those are rendered illegibly (MV-networking-002).

---

## Claim verdicts

| Claim id | Claim (abridged) | Verdict | Reasoning |
|---|---|---|---|
| CLM-024 | All 27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors/20 routes, 0 same-origin 5xx, 676 pytest, 297 vitest, Playwright E2E green | **PARTIALLY-TRUE** | For my one route (`/dashboard/networking`), I confirm 0 spontaneous console errors and 0 same-origin 5xx during normal navigation/interaction across two fresh sessions (the only console "errors" observed were the 3 I deliberately triggered via boundary/invalid-payload API tests, which are expected 4xx/422 validation responses, not defects). I did not and could not run the full pytest (676) / vitest (297) suites or test the other 19 routes from this single-screen role — that portion is UNVERIFIABLE-FROM-UI within my scope. |
| CLM-062 | Playwright sweep of 14 dashboard routes + /pricing + /admin as paid admin: 0 console errors / 0 failed requests / 0 page errors (GATE-03) | **PARTIALLY-TRUE** | Same reasoning: my route's slice of this multi-route claim holds (0 console errors, 0 unexpected failed requests during normal use, confirmed twice), but I can only speak to 1 of the ~16 routes covered by the claim. |

---

## UNSURE items

None. Every behavior tested resolved to a clear, reproduced (×2) verdict — either working-as-expected or a filed finding. No ambiguous cases required escalation.

---

## Screenshot index

All under `test-artifacts/`:

| # | File | Shows |
|---|---|---|
| 1 | `01-unauth-redirect.png` | Unauthenticated access → redirected to /login |
| 2 | `02-networking-loaded.png` | Initial load — account had 0 real contacts, correctly showed empty state |
| 3 | `03-after-review-drafts-click.png` | (empty-state pass) Review-drafts button absent as expected |
| 4 | `04-add-contact-modal-open.png` | Add Contact modal open |
| 5 | `05-add-contact-empty-submit.png` | Empty-name validation message shown |
| 6 | `06-add-contact-after-valid-submit.png` | Fake "success" — contact shown, no network call fired |
| 7 | `07-after-reload.png` | Contact gone after reload — proves non-persistence |
| 8 | `08-after-direct-api-create-reload.png` | Direct-API-created contact correctly appears (Read path works) |
| 9 | `09-after-patch-reload.png` | Direct-API PATCH correctly reflected (Update path works) |
| 10 | `10-empty-state-demo.png` | `?demo=empty` empty state |
| 11 | `11-linkedin-import-click-result.png` | "Import from LinkedIn" opens generic Add-Contact modal |
| 12 | `12-xss-contact-rendered.png` | XSS payload safely escaped, no dialog fired |
| 13 | `13-after-back-forward.png` | Browser back/forward navigation, no errors |
| 20 | `20-reverify-unauth.png` | Session B re-verify: unauth redirect |
| 21 | `21-populated-state.png` | Populated CRM with real seeded data — visible field-mapping defect in Outreach Queue |
| 22 | `22-after-contact-card-click.png` | Contact card click → no reaction |
| 23 | `23-review-drafts-populated-click.png` | Review-drafts click with real data present → no reaction |
| 24 | `24-throttled-reload.png` | Reload under 50kbps/400ms-latency throttle — renders correctly, no hang, no unsurfaced error |
| 25 | `25-final-cleanup-state.png` | Confirmed empty state after Session B cleanup |
| 26 | `26-wiring-mismatch-proof.png` | Full-page proof of Outreach Queue field-mapping defect |
| 27 | `27-outreach-queue-closeup.png` | Close-up: "tone:" with no value, missing recipient/preview |
| 28 | `28-communication-log-closeup.png` | Close-up: Communication Log entry renders essentially blank |
| 29 | `29-modal-reopen-after-cancel.png` | Cancel doesn't reset form — stale text on reopen |

Raw API probe transcripts (field-mapping proof, FK-integrity proof, validation sanity checks): `test-artifacts/raw-api-probes.md`.

---

## Console / network / server-log summary

- **Console (both sessions, all 4 scripts):** Zero uncaught errors or unexpected warnings during any normal navigation, click, or form interaction. The only `console.error`-level "Failed to load resource" entries recorded (3 total, Session A) correspond exactly to the 3 deliberate boundary/invalid-payload/404 probes I issued directly via `fetch()` (422 × 2, 404 × 1) — expected validation responses, not spontaneous defects.
- **Network (both sessions):** Every `/api/*` response captured is enumerated in `session-a-network-events.json` / `session-b-network-events.json`. Zero 5xx observed anywhere in either session. All 2xx/4xx codes are accounted for and match expected behavior (201 creates, 200 reads/updates, 204 deletes, 404 for a genuinely nonexistent contact id, 422 for boundary/invalid payloads).
- **Throttled reload:** Under emulated 50kbps down / 20kbps up / 400ms latency, the page reload completed in ~3.1s with correct content rendered, no hung skeleton, no unsurfaced error banner.
- **Server-side logs:** Not directly accessible to this screen-tester role (no SSH/journalctl access granted to this agent); this report's server-error claims are based solely on client-observed HTTP status codes (zero 5xx seen). Correlating with actual server-side journalctl output is deferred to the log-tailer role per the swarm's division of labor.

---

## NOT-TESTED (HUMAN-GATED only)

- **emailAgent / Gmail-OAuth outreach-drafting flow:** Not tested because it is not reachable from this screen's UI at all in the current build (see MV-networking-008) — there is no Gmail-connect affordance or agent-run trigger to click. This is a coverage-gap finding, not a skipped-because-inconvenient test; if/when such a control ships, it should be re-tested against the "no Gmail connected in prod" human-gated constraint noted in the brief.
- **Backend pytest (676 tests) / frontend vitest (297 tests) full-suite execution:** Out of scope for a single-screen manual UI tester; the claim ledger rows referencing these counts are marked PARTIALLY-TRUE / UNVERIFIABLE-FROM-UI for the suite-count portion specifically, not silently assumed true.
- **Server-side log correlation (journalctl / systemd):** No infra/SSH access provisioned to this tester role; client-observed network status codes stand in as the available evidence.
- **Shared dashboard-shell elements** (sidebar nav links to other screens, top search bar, notification bell, avatar menu): out of scope per "test EXACTLY ONE screen" — owned by their respective screens' testers.

---

## Sign-off

Tested by: screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, against production (`https://5cb5f0620.abacusai.cloud`), commit `53f0e084da5b460835c32d3e07d496e6e67a8616`. All findings reproduced twice in independent fresh browser sessions before filing (VERIFY TWICE, §3.2.9). All test data (prefix `MV-networking-`) created and deleted by this tester only; final state confirmed empty for both `Contact` and `OutreachTask` tables belonging to the admin test account. No code changes, no service restarts, no destructive actions taken against data not created by this tester.
