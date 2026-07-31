# GOLD-MASTER-V2 — Independent 3rd-Party Adversarial Product Review (§3.3, Gate G-A)

**Coverage: FULL — all 27 routes in `phase0/SCREEN-MATRIX.md` now have a completed §3.2 deep pass.**
This document supersedes the 2026-07-31T01:20Z PARTIAL draft (6 of 27 routes). The sweep that draft
flagged as outstanding (`W-A §3.2: dispatch screen-testers per route`) completed between then and
2026-07-31T09:04Z (`docs/delivery/GOLD-MASTER-V2-STATE.json: screen_sweep.status = "COMPLETE"`). This
refresh re-reads every one of those 19 screen-test report files plus the 3 adversarial deep-dives, folds
them into one adjudicated document, and adds a small set of fresh first-hand probes performed during
this refresh (§0 below) — including one new, previously-undocumented finding this refresh discovered
itself (§1, item 2).

**Author:** independent adversarial reviewer for this refresh pass. Did not author, fix, or first-test
any individual screen finding below — those are the work of a dozen-plus `screen-tester`/`qa-adversary`
sub-agents dispatched earlier in this same run. This document's job is to adjudicate, cross-check, and
hold their claims to the same skepticism §0 of the campaign demands of everyone else.
**Production target:** `https://5cb5f0620.abacusai.cloud`
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`, HEAD `ad0b3a0` as of this refresh, **45
commits ahead of `origin/main`** (`origin/main` = `0588aff`, 2026-07-31T00:14:32Z), working tree dirty
across 4 tracked files plus one new untracked service file — confirming other agents in this campaign
are still actively committing while this document is being written.
**This refresh's review window:** 2026-07-31T09:04Z – 09:20Z.
**Underlying screen-test window this document synthesizes:** 2026-07-30T23:47Z – 2026-07-31T09:03Z.

## Epistemic rules used in this document

Every claim carries one of three tags. Only the first can close anything.

- `[VERIFIED-FRESH]` — re-derived first-hand **during this refresh's own window** (2026-07-31T09:04–
  09:20Z), from production (HTTP) or the repo, with the probe shown inline. There are relatively few of
  these — this refresh's job is synthesis, not re-running a 27-route sweep from scratch — but every one
  that exists is load-bearing and new.
- `[TESTIMONY]` — asserted by one of the 19 screen-test report files (or the 3 adversarial deep-dives) on
  disk, each of which is itself internally tagged `[VERIFIED-WITH-FRESH-EVIDENCE]`/`[INFERRED]` by its own
  author with an artifact + timestamp from the *original* sweep window (2026-07-30T23:47Z–2026-07-31T09:03Z).
  Treated here as **credible testimony from a fresh, evidenced probe**, not as this document's own
  first-hand finding — but not re-litigated line-by-line either, since re-deriving 27 routes' worth of
  screenshots and network captures a second time inside this refresh would be redundant with, not more
  rigorous than, the work already on disk. Where this refresh found reason to doubt a screen-test claim,
  it re-probed directly (see §0) rather than accepting it on faith.
- `[INFERRED]` — reasoned from verified facts, with the reasoning shown.

Where evidence is absent the word used is **unproven**. No section below infers a pass from silence.

---

## 0. Fresh probes performed for this refresh, and what they changed

| # | Probe | Result | Effect |
|---|---|---|---|
| 1 | `git log -1 origin/main` / `git rev-parse HEAD` / `git log origin/main..HEAD \| wc -l` @ 2026-07-31T09:07Z | HEAD `ad0b3a0`, **45** commits ahead of `origin/main` (`0588aff`) | Confirms nothing new is deployed; commit count grew from the prior draft's 11 to 45 — the campaign kept working after the PARTIAL draft, has not pushed/deployed. |
| 2 | `systemctl show aether-api/-web/-worker -p ActiveEnterTimestamp` @ 2026-07-31T09:07Z | All three: `Thu 2026-07-30 12:27:09 UTC`, all `active` | **Unchanged since the PARTIAL draft's own probe 12+ hours earlier.** Production is still running the exact pre-fix binary; every fix commit in this run (all 45) is unreachable by real users. |
| 3 | `GET /api/health` @ 2026-07-31T09:07Z | `200 {"status":"ok","version":"0.2.0"}` | Prod live and serving. |
| 4 | `POST /api/auth/login {"email":"admin","password":"admin123"}` @ 2026-07-31T09:13Z | **200**, valid JWT, resolves to `sarkar.vikram@gmail.com` | **BLOCKER-001 still live in production at the moment this document is being written**, not merely at the time of the original probe 8 hours earlier. |
| 5 | `GET /api/approvals?status=pending` and `?status=approved` (fresh admin session) @ 2026-07-31T09:14–09:17Z | 3 pending (all clean, signed "Vikram Deshpande"), 107 approved, **3 of the approved rows carry the `GAP-P7-DEF-B` fixture string in `payload`**, all three `resolvedAt` within the same 3-second window: `03:50:46.295Z`, `03:50:47.820Z`, `03:50:49.181Z` | **New finding, not in any prior report** — see §1 item 2 and §2a `/dashboard/approvals`. |
| 6 | `GET /api/cover-letters` (fresh admin session) @ 2026-07-31T09:15Z, cross-referenced against the 8 known-contaminated ids from `cover-letters-screen-test.md`/`remaining-routes-screen-test.md` | 3 of the 8 (Grafana Labs `c15369ea…`, Plenti `c6b7a3db…`, Samsara `c04586c8…`) now show `status:"submitted"` **and still carry the fixture string in the stored body** | Corroborates probe 5 — these are the exact three approvals that flipped, and the CoverLetter/Application status transitioned atomically with the approval (source-confirmed, probe 7). |
| 7 | `apps/api/app/routers/approvals.py:177-190` (`approve`/`reject` handlers) + `apps/api/app/services/approval_service.py:46-64` (`resolve()`) — source read | Neither `approve()` nor `reject()` calls `write_audit()`. `resolve()` calls `self._repo.approve` / `.reject`, which — per its own comment — "resolves the approval and syncs the linked Application **in one transaction**" | Explains why the CoverLetter/Application flipped to `submitted` atomically with the approval. **Also explains why no actor can be identified** — see §1 item 2. |
| 8 | `GET /api/admin/audit-log?limit=200` (fresh admin session) @ 2026-07-31T09:18Z | 144 rows total, spanning 2026-07-16 → 2026-07-31T06:18Z. Action-type histogram: `job.stage_move`(46), `application.stage_move`(39), `set_spend_cap`(17), `approval.delete`(17), `update_settings`(15), `unsuspend_user`(4), `suspend_user`(4), `approval.purge_expired`(2). **Zero rows of any `approval.approve`/`approval.reject`/`approval.decision` shape exist anywhere in this account's entire audit history.** | Confirms probe 7 behaviorally, not just by source read: the audit log structurally cannot ever record who approved or rejected an approval, for any approval, ever — this is not specific to the three flagged rows. |
| 9 | `grep -rln "auto.approve\|autoApprove\|scheduled.*approv"` across `apps/api/app/` (excluding tests) | 0 matches | No autopilot/cron/scheduled-approval code path exists anywhere in the codebase — rules out "an automated job did this" as the explanation for probe 5/6's finding. |

### What this changes vs. the PARTIAL draft's claims

The PARTIAL draft, written when only 6/27 routes were tested, is **superseded** by this document. Its
headline structural facts (production unchanged since `12:27:09Z`, repo public, BLOCKER-001/002 both
live) all **still hold** — re-verified fresh above, not merely carried forward. Its most severe individual
claims (README:39/45/58/59 staleness, BLOCKER-001 credential disclosure, BLOCKER-002 contamination, the
0.0%-ATS-movement resume-tailoring gap) are **confirmed, not weakened**, by the fuller 27-route sweep.
Two things are new in this refresh that did not exist in the PARTIAL draft: **the approval-audit-trail
gap and the 3 silently-resolved contaminated approvals** (probe 5–9, entirely new), and **full coverage
of the 21 previously-untested routes**, which surfaced roughly 60 additional findings, none BLOCKER-tier
beyond what was already known, but several new HIGH-severity items (see §2).

---

## 1. Executive summary

# Verdict: NOT-READY — BLOCKED-ON-ITEMS

Full coverage did not change the shape of the verdict — it sharpened it. The engineering that exists is,
on the whole, honest: the anti-fabrication guard held across every live agent run tested (4 fresh runs
plus dozens of historical ones, zero fabricated claims found anywhere), the server-side entitlement gate
on the paid agent pipeline is real, gate-before-work, and fail-closed, and honest-failure paths surface
honestly on nearly every screen (empty states, 402s, 422s, no-op tailoring runs). What blocks launch is
not architecture — it is **one disclosed production credential still authenticating right now, contaminated
customer-facing documents that have now demonstrably been approved and marked submitted by an
unidentified actor with zero audit trail, a flagship AI feature that cannot move its own headline metric,
a real currency/compliance risk on the checkout page nobody had previously found, and the fact that not
one line of this run's 45 commits of remediation has reached a user.**

### Top-5 blockers

| # | Blocker | Severity | Why it is here |
|---|---|---|---|
| 1 | **BLOCKER-001 — disclosed, still-live production admin credential** | **CRITICAL** | `admin/admin123` authenticated as the real owner (`isAdmin:true`) at **09:13Z today**, the moment this document was being written `[VERIFIED-FRESH #4]`. The credential and the owner's email are both published in tracked files of a confirmed-public repo (`docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md`, `scripts/discovery_cron.sh:30`) `[TESTIMONY, prior review's own probes, unchanged]`. `GET /api/admin/users` returns 7 real users' PII to this credential. The de-privilege fix (`6dcf927`) exists locally, is verified by 16 tests, and is **not deployed** `[VERIFIED-FRESH #1/#2]`. |
| 2 | **BLOCKER-002 — contaminated identity, now realized rather than merely queued** | **CRITICAL, ESCALATED THIS REFRESH** | The owner's `User.name` was corrected in-place mid-run (`GET /auth/me` → "Vikram Deshpande", confirmed clean and holding two verification passes later, `remaining-routes-screen-test.md` ROUTE 1). But **8 stored cover letters still carry the old fixture string in their body text**, and **3 of those 8 (Grafana Labs, Plenti, Samsara) were resolved from `pending` to `approved` at 03:50:46–49Z — a 3-second cluster — flipping their linked Applications to `status:"submitted"`** `[VERIFIED-FRESH #5/#6]`. No screen-tester in this entire campaign claims to have clicked Approve (every report is explicit: "read-only on the approvals queue"). No autopilot/cron path exists in the codebase that could have done it `[VERIFIED-FRESH #9]`. And **`POST /approvals/{id}/approve`/`/reject` write no audit-log row at all — confirmed both by source (`approvals.py:177-190` never calls `write_audit`) and behaviorally (144 real audit rows spanning two weeks contain zero of any approval-decision shape)** `[VERIFIED-FRESH #7/#8]`. The single control this entire campaign has relied on as BLOCKER-002's safety backstop — "a human must explicitly approve before contaminated content goes anywhere" — was exercised on exactly the contaminated rows, by an actor this document cannot identify, with a mechanism that structurally cannot ever be audited. The most likely, mundane explanation is the real account owner approving what looked like ordinary pending work without noticing the fixture signature — which is precisely the risk BLOCKER-002 always warned about, now with evidence it happened rather than merely could happen. |
| 3 | **Resume tailoring does not measurably tailor** | **HIGH** | 7 of 7 recent runs (2 fresh + 5 historical) moved the ATS score by **exactly 0.0%** `[TESTIMONY, AI-AGENT-QUALITY-ASSESSMENT.md]`. `resume_tailor.py` makes one LLM call, once, with no re-score loop and no target-score parameter — confirmed at the code level. Every job in the 51-52-job production corpus sits 25–60 points below the platform's own 85 target. |
| 4 | **Nothing is deployed; the fix set has grown to 45 unpushed commits** | **HIGH (process)** | Production has run the identical pre-fix binary for over 20 hours as of this refresh `[VERIFIED-FRESH #2]`. Every "FIXED" claim anywhere in this run's evidence tree means "fixed in a local commit," not "fixed for a user." |
| 5 | **Billing/entitlement cluster: over-advertised Free tier + a newly-found currency risk** | **HIGH-CRITICAL** | `ADV-ENT-002` (pre-existing, reconfirmed on a genuinely fresh signup this sweep, `signup-screen-test.md` §6): the server itself provisions and advertises 5 usable Free runs it then universally 402s. **New this sweep, not previously known:** Stripe Checkout for a paid plan defaults to **USD presentment with floating FX**, not the AUD GST-inclusive price advertised everywhere else in the app, with a default-checked "save with Link" box committing to recurring USD billing — filed `ML-PRICE-002`, CRITICAL, `pricing-screen-test.md` §4. |

### Where this refresh disagrees with, or must correct, prior testimony in this run's own evidence tree

1. **The approval-audit-trail gap (§1 item 2, §0 probes 5–9) is new — no prior report in this campaign
   identified it.** `approvals-screen-test.md` itself is an 18-line stub that never got past its header
   (see §2a); the companion `remaining-routes-screen-test.md` ROUTE 2 did excellent work reconciling
   counters and testing the Remove/Clear-expired affordances, but its "live queue state" snapshot
   (2026-07-31T08:53–08:57Z) captured 3 pending / 107 approved and moved on — it did not cross the 107
   approved rows against the known BLOCKER-002 fixture string, so it did not surface this. This document
   is the first to connect ML-APP-001/ML-CL-001's "pending, one click from a real employer" framing
   against what actually happened to those specific rows.
2. **`ML-admin-003`'s classification is CORRECT, not a re-opened question.** The admin-portal screen-test
   found a fresh 500 on `GET /admin/users?q=<NUL>` and correctly filed it as a **new instance of the
   already-known, fix-verified-but-undeployed NUL-byte class** (`ORCH-CORR-001` in `GOLD-MASTER-V2-
   STATE.json` already settled the "is this a separate code gap" question days before this specific probe
   — both agree). No correction needed here; flagged only so a reader doesn't re-litigate it.
3. **The "47 vs 74 applications" question is fully closed, independently, four separate times.**
   `dashboard-screen-test.md` (direct SQL), `analytics-screen-test.md` (API + two screens), and
   `ORCH-CORR-002` in `GOLD-MASTER-V2-STATE.json` all reach the identical conclusion via independent
   methods: `get_application_counts()` deliberately counts distinct jobs, not raw rows, and UI = API =
   live DB at 47. Any reference elsewhere to "74" as a live-production number is now stale by construction
   (the account has grown since the 74/51 baseline was captured) — treat 47/52 as current ground truth,
   not 74/51.
4. **Playwright baseline credibility: now 12 independent disproofs, not 7.** The PARTIAL draft's
   ancestor state recorded 7. This sweep's own screen-testers independently retested and failed to
   reproduce mobile-390px-overflow claims on `/dashboard/resume`, `/dashboard/applications` (incl.
   `/dashboard/approvals`), `/dashboard/agents` (×2 claims), `/dashboard/admin` (×2 routes, a 4th/5th
   disproof there alone), and the model-picker-persistence claim — all independently, all twice. **Zero
   of the specs checked against production this sweep reproduced.** The working assumption that the 12 red
   specs target `127.0.0.1:3091` rather than production is now stronger, not merely asserted, but each
   still needs individual sign-off before G-N closes — see §5.

---

## 2. Per-screen findings table — all 27 routes

Legend — **Observed as:** `OWNER` admin/owner account (data-rich) · `NA-FREE` non-admin Free-tier account
· `UNAUTH` unauthenticated only. Every dashboard-shell route below was tested under **both** OWNER and
NA-FREE identities per §3.2's dual-identity requirement; the table states what each identity revealed.

### 2a. Dashboard routes (14 of 14 — full coverage)

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/dashboard` | OWNER (deep) + NA-FREE (full) | **PASS** — honest, internally consistent | ML-DASH-002 (MINOR): "live"-labeled Agent Activity / Market Pulse widgets never actually re-fetch after mount (confirmed by 70s+35s `window.fetch` instrumentation) — a mislabeling, not a data-integrity issue. All widget figures reconcile exactly against live SQL. | `screens/dashboard-screen-test.md` |
| `/dashboard/jobs` | OWNER (deep) + NA-FREE (gated) | **PASS, 1 MEDIUM** | ML-JOBS-003: `/pricing` shows Free as "CURRENT PLAN" with "5 tailored agent runs/month," but `POST /agents/scout/run` 402s at 0/5 used — same root cause as ADV-ENT-002. Apply-gate, Seek "(unavailable)" labelling, and a genuine 20.00s poll all verified correct. | `screens/jobs-screen-test.md` |
| `/dashboard/applications` | OWNER (deep) + NA-FREE (gated) | **NOT production-clean — 1 BLOCKER-adjacent + 2 HIGH** | ML-APP-001 (= BLOCKER-002 surface: fixture signature reachable from the pending-approvals banner — see §2a `/dashboard/approvals` for what happened to it since). ML-APP-002 (HIGH): a superseded draft with a live pending approval is hidden by per-job dedup yet still counted by the banner. ML-APP-003 (HIGH): Board "In Review" (0), Applied badge ("applied"), and Sankey "Screened" (2) give three contradictory readings of the same 2 rows. Keyboard Move-to menu fully functional; illegal transitions correctly 422; audit rows correct for stage-moves (not approvals — see above). | `screens/applications-screen-test.md` |
| `/dashboard/resume` | OWNER (deep) + NA-FREE (gated) | **FUNCTIONAL PASS, 2 HIGH** | ML-RESUME-001 (HIGH): NUL byte → raw 500 on `POST /resumes` and `POST /agents/tailor/run` (2 more instances of the systemic class). ML-RESUME-002 (HIGH): with 2+ root résumés the "Original — Base Resume" pane shows the wrong document (display-only; the tailoring engine itself uses the correct base). ATS shown matches API exactly 3/3; honest zero-change no-op verified twice. | `screens/resume-screen-test.md` |
| `/dashboard/stories` | OWNER (deep) + NA-FREE (gated) | **FAILS its assigned gate (G-E)** | GM2-STORY-001/002 (HIGH): 34 of 36 stories are paraphrase re-tellings of 8 achievements; dedup only catches byte-identical resubmission, confirmed to have materialized live (32→36 during this run). GM2-STORY-003 (MEDIUM): §7.4 relevance scoring is entirely unimplemented (param silently ignored). GM2-STORY-005 (MEDIUM): NUL→500 on 2 more endpoints. Full CRUD, star persistence, XSS-safe, zero console errors, no fixture contamination on this screen otherwise. | `screens/stories-screen-test.md` |
| `/dashboard/settings` | OWNER (deep) + NA-FREE (full, not gated) | **PASS, no BLOCKER/HIGH** | ML-settings-004 (MEDIUM): Notifications tab ships with 3 disabled "Coming Soon" toggles — honestly built (native `disabled`, zero network calls on force-click) but still forbidden at exit by §4. ML-settings-002/003 (MEDIUM): auto-apply + match-threshold persist but are enforced by no agent, honestly disclosed in-UI. ML-settings-006 (the one confirmed production 500, see §4). Sync Now/Sync All/Manage Subscription all genuinely wired to real backend work. | `screens/settings-screen-test.md` |
| `/dashboard/cover-letters` | OWNER (deep, 2 passes) + NA-FREE (gated) | **FAIL — BLOCKER, confirmed live and larger than scoped** | ML-CL-001/002/003 (BLOCKER): fixture identity contaminates stored bodies, **every PDF letterhead regardless of body content** (render-time bug, not just stored data), and **fresh generation right now** (guard exists locally, undeployed). ML-CL-004 (HIGH): `/refine` can 500 to the client while silently persisting a new, ungoverned draft with no approval record. ML-CL-005/006 (HIGH/MEDIUM): 2 more NUL-byte-500 instances. A re-test at 08:46–08:50Z confirmed the *name* fix holds (new generations sign "Vikram Deshpande" cleanly) but **0 of 8 previously-contaminated stored letters have been remediated**, and — new this refresh — 3 of those 8 have since been approved and marked submitted (§1 item 2). Zero fabrication found across 5 generation attempts (2 honest refusals). | `screens/cover-letters-screen-test.md`; `screens/remaining-routes-screen-test.md` ROUTE 1; §0 probes 5–8 |
| `/dashboard/approvals` | OWNER (reconciled via companion route) + NA-FREE (gated) | **PASS on mechanics, but the screen's own report is an undelivered stub — and this refresh found a real defect the stub never got to** | The dedicated `approvals-screen-test.md` file is **18 lines** — a header and a methodology note ending mid-sentence ("(report being populated — see below)"), never completed. Filed here as `ML-APPROVALS-100` (process finding: a required deliverable was never written, though the underlying evidence-collection *was* done — 10 screenshots + 9 JSON captures exist). `remaining-routes-screen-test.md` ROUTE 2 filled the narrative gap on 2026-07-31T08:53–08:57Z: counters reconcile exactly (3+107+0=110, bell matches chip), Remove/Clear-expired both honest, NUL byte on `?status=` cleanly 422s (not the systemic 500). **What none of that pass caught, because it happened either just before or just after its own window: 3 approvals carrying the BLOCKER-002 fixture string were resolved `pending→approved` at 03:50:46–49Z with zero audit trail and no attributable actor — see §1 item 2.** This is the single highest-consequence finding of this refresh. | `screens/approvals-screen-test.md` (stub); `screens/approvals/` (raw evidence); `screens/remaining-routes-screen-test.md` ROUTE 2; §0 probes 5–9 |
| `/dashboard/analytics` | OWNER (deep, 2 sessions) + NA-FREE (gated) | **PASS — clean, honest, fully reconciled** | 4 LOW findings only (missing Export button vs. wireframe, missing freshness label, period-selection not sticky across reload, one UNSURE code-review risk on a non-deduplicated `COUNT(*)` that is currently unobservable with 0 interviews). Every headline figure reconciles exactly across this screen, the main dashboard, and live API — no BLOCKER/HIGH anywhere. | `screens/analytics-screen-test.md` |
| `/dashboard/agents` | OWNER (deep) + NA-FREE (gated) | **PASS, 1 HIGH** | ML-agents-001/GM2-AGENTS-001 (HIGH): Submission Agent card permanently stuck "Planned" — no model, no Run button — forbidden at exit by §4. ML-agents-003 (MEDIUM): Test Run modal fabricates a non-zero cost estimate for deterministic ($0) agents before running (corrects to honest $0 after). ML-agents-004 (MEDIUM): AWS Bedrock card label ("Access + Secret Key") mismatches its modal ("API Key" only). Two prior baseline claims (model-picker persistence, mobile overflow) **refuted** — both work correctly. Real agent runs (deterministic + LLM-backed) both genuine, audited, non-fabricating. | `screens/agents-screen-test.md` |
| `/dashboard/email` | OWNER (deep) + NA-FREE (gated) | **PASS, 2 HIGH** | ML-email-001 (HIGH): NUL byte → 500 on `POST /emails/draft` (matches the known class). ML-email-002 (HIGH): Inbox shows both Gmail accounts "Connected" while a live triage run proves the auth has expired — reproduced twice — a false status claim with the same honesty-class as the fixture-name defect. ML-email-003 (MEDIUM-HIGH): AI Draft Reply reverses sender/recipient direction on a specific thread shape (owner's own reply is the newest message), reproduced 3×; correct on a contrast thread. Real, PII-rich inbox data; zero fabrication; working two-step send gate, confirmed no email sent. | `screens/email-screen-test.md` |
| `/dashboard/interviews` | OWNER (deep) + NA-FREE (gated) | **PASS, 1 HIGH** | ML-INTERVIEWS-001 (HIGH): NUL byte → 500 on `POST /interviews` (3rd router hit by the systemic class). ML-INTERVIEWS-002 (MEDIUM, UNSURE): whole screen paywalled for Free tier despite the router carrying zero subscription check and being >90% non-agent CRUD. Full CRUD lifecycle (create→cancel/complete→delete) genuinely wired, XSS-safe, honest empty state, zero fabrication. | `screens/interviews-screen-test.md` |
| `/dashboard/offers` | OWNER (deep) + NA-FREE (gated) | **PASS, 1 HIGH** | ML-OFFERS-001 (HIGH): NUL byte → 500 on `POST /workspaces/offers` (4th router). ML-OFFERS-002 (MEDIUM, UNSURE): same paywall-vs-ungated-backend pattern. ML-OFFERS-004 (LOW): backend computes a real, non-fabricated `weights` array (Priority Weights) the frontend never renders — data exists, UI doesn't, the inverse of a placeholder. Negotiation Coach genuinely computes a real counter-offer anchored on the entered base salary; honest null state otherwise. | `screens/offers-screen-test.md` |
| `/dashboard/networking` | OWNER (deep) + NA-FREE (gated) | **PASS, 1 HIGH** | ML-NETWORKING-001 (HIGH): NUL byte → 500 on `POST /networking/contacts` (5th router — now the largest confirmed instance count of this class). ML-NETWORKING-002 (MEDIUM, UNSURE, strongest direct proof in the campaign): a Free-tier bearer token was used to `POST /networking/contacts` directly and got a genuine **201** — the backend imposes zero entitlement check while the UI fully paywalls the screen. Prior finding "two-click delete" **re-confirmed working correctly**, not a regression. | `screens/networking-screen-test.md` |

### 2b. Admin routes (7 of 7 — full coverage)

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/admin` | OWNER (2 independent passes) | **PASS** | Real, live-cross-checked data (`3587 runs, 95.5% success` — matched `GET /api/admin/health` digit-for-digit). No placeholder content anywhere in the admin portal. | `screens/admin-portal-screen-test.md` §4.1 |
| `/admin/health` | OWNER | **PASS** | Same data source as `/admin`, confirmed identical. | ibid. §4.2 |
| `/admin/settings` | OWNER | **PASS mechanically, 1 CONFIRMED defect** | INC-B-002 both halves reproduce live: UI toggle for Email verification is a genuine, honest no-op (`disabled`, own caption says so); the **backend** still loose-coerces `"yes"`/`1` into `true` and persists it (fix `StrictBool` exists at HEAD, undeployed) — reproduced twice, reverted both times. | ibid. §4.7, §8 |
| `/admin/users` | OWNER | **PASS** | 7/7 users, matches `GET /api/admin/users` exactly. At 390px, the table hides Plan/LastLogin/SignedUp/Spend/View columns entirely (responsive simplification, not overflow — `ML-admin-004`, LOW). | ibid. §4.3, §10 |
| `/admin/users/[id]` | OWNER | **PASS** | Full detail view; a real, reversible spend-cap change (`1.0→2.34→1.0`) exercised live, producing 2 correctly-attributed audit rows (proving the audit log *does* work for admin actions generally — the gap is specific to approval decisions, §0 probe 7/8, not the whole logging subsystem). | ibid. §4.4, §7 |
| `/admin/spend` | OWNER | **PASS** | `$0.6209` total, exact match to a same-second independent API call. | ibid. §4.5 |
| `/admin/audit-log` | OWNER | **PASS as a viewer, structurally incomplete as a control** | 139–144 rows, real content, correctly append-only, correctly grew from this tester's own reversible action. **But see §0 probes 7/8/§1 item 2: `approve`/`reject` on `/approvals` never write to this log at all** — a real gap in what this screen can ever show an admin, not a rendering bug. | ibid. §4.6; §0 probes 7–8 |

**Admin-portal-wide findings not tied to one route:** `ML-admin-003` (HIGH) — `GET /admin/users?q=`/`?plan=` with a NUL byte still 500s in production (8th confirmed instance of the systemic class, deployment-lag not a code gap, `ORCH-CORR-001` settles this). `ML-admin-005` (MEDIUM) — no `/login` admin entry point exists live (code for it exists at HEAD, commit `2bdb060`, undeployed — see `/login` row below). `ML-admin-006` (MEDIUM) — no persistent "Admin" indicator anywhere outside `/admin/*` itself for a logged-in admin browsing the ordinary app. Non-admin route protection: 7/7 routes, both UI redirect and API 401/403, verified twice, zero data leak.

### 2c. Public / auth routes (6 of 6 — full coverage)

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/login` | UNAUTH (deep, 2 sessions) | **PASS, 1 HIGH** | ML-LOGIN-001 (HIGH): NUL byte in identifier or password → 500 (reproduced via curl and via the live form). No enumeration (byte-identical 401 for known-wrong / unknown-account / SQLi-shaped input, verified 3 ways). Rate-limit fires correctly at exactly 5/15min with an honest `Retry-After`. Admin-login entry point per §9.2.1 **not yet live** (code exists at HEAD, `2bdb060`, committed minutes before this test — deploy lag, not a gap). | `screens/login-screen-test.md` |
| `/signup` | UNAUTH (deep) | **PASS, 1 HIGH, honest first-run** | ML-SIGNUP-001 (HIGH): NUL byte in the password field → 500 (email field is safer — `EmailStr` catches it with a clean 422). ML-SIGNUP-003 (MEDIUM): ADV-ENT-002 reproduced end-to-end on a **genuinely fresh** account — sidebar advertises "Free · 0/5 runs" while `POST /agents/scout/run` 402s immediately; the paywall's own prose is honest and prominent, only the persistent sidebar tile is inconsistent with it. Weak-password policy genuinely enforced both sides. 3 extra accounts created as an honestly-disclosed side effect of adversarial success-path testing (documented in the purge ledger, not hidden). | `screens/signup-screen-test.md` |
| `/forgot-password` | UNAUTH | **PASS** | No reset form exists at all — a deliberate, honest, enumeration-proof static fallback (confirmed byte-identical output regardless of query-string content, after a false-positive from a hydration-payload artifact was caught and corrected). Filed `ML-FORGOT-100` (INFO) purely to flag that the product's actual design (no submittable form) differs from what a reader might assume "password reset flow" means. | `screens/remaining-routes-screen-test.md` ROUTE 4 |
| `/pricing` | UNAUTH + NA-FREE (both full) | **PASS as a page, CRITICAL as what it triggers** | Page itself renders exactly what `GET /billing/plans` returns, GST math independently verified correct on all 8 tier/interval combinations. Two **CRITICAL** findings live one layer below the page: `ML-PRICE-001`/`ADV-ENT-002` (pre-existing, reconfirmed) and **`ML-PRICE-002` (NEW, this sweep)** — Stripe Checkout defaults to USD-with-floating-FX rather than the AUD price advertised everywhere, reproduced on 2 independent live Checkout Sessions, with a default-checked "save with Link" consent that commits to future USD billing. A third, UNSURE finding (`ML-PRICE-003`) on whether Stripe's automatic tax stacks on top of the app's own GST-inclusive price was correctly left untested rather than risking an actual charge. | `screens/pricing-screen-test.md` |
| `/terms` | UNAUTH | **PASS** | Real, live-verified content — the ABN (`73 941 747 350`) was independently checked against the Australian Business Register and confirmed active, registered to the exact individual whose name was just corrected onto the account (BLOCKER-002 cross-check). Zero placeholder text, zero fixture-string hits. | `screens/remaining-routes-screen-test.md` ROUTE 3 |
| `/privacy-policy` | UNAUTH | **PASS** | Same page family as `/terms`, same clean result. | ibid. |

### 2d. Coverage arithmetic

| Category | Count |
|---|---|
| Full §3.2 deep pass, both identities, completed with a written report | 25 |
| Full evidence collected, narrative `.md` incomplete but reconciled by a companion pass this run (`/dashboard/approvals`) | 1 |
| Deep pass completed but with one narrow re-test needed and delivered (`/dashboard/cover-letters` — original pass + `remaining-routes` ROUTE 1 re-test) | 1 (counted once in §2a) |
| **Total routes in SCREEN-MATRIX, all now covered** | **27 / 27** |

No route in this run's SCREEN-MATRIX remains unobserved. The one process gap (`approvals-screen-test.md`
never finished its own narrative) did not leave the underlying screen untested — it left a **documentation**
debt, which this document and `remaining-routes-screen-test.md` close, and which itself surfaces a
genuine new finding (§1 item 2) that a completed narrative might well have caught sooner.

---

## 3. Feature completeness matrix — summary

Full row-by-row detail: `docs/delivery/GOLD-MASTER-V2-FEATURE-COMPLETENESS-MATRIX.md` (46 rows: **29
CONFIRMED / 5 OVERSTATED / 8 FALSE / 4 UNVERIFIABLE**) `[TESTIMONY]`. That document was authored before
the authenticated-session screen sweep existed (its own text notes "no authenticated app-session probes
were run" — the documented owner login credential was stale, and the forbidden `admin`/`admin123`
credential was under separate investigation at the time). The 27-route sweep that followed independently
confirms its most load-bearing conclusions with live authenticated evidence it could not originally
gather:

- **README's test-count/link/DB-size claims are stale** — confirmed unchanged: backend baseline this run
  is 1885 passed, not the README's stated 967; the 7 delivery-history doc links the matrix flagged as
  dead still 404 on disk.
- **The "demo account carries zero admin privilege" claim (README:59, the matrix's own most-cited FALSE
  row) has since been edited in place** to acknowledge the finding — but the credential itself remains
  live in production (§0 probe 4) and published in the repo, so the underlying blocker is unchanged; only
  the documentation's honesty about it improved.
- **Subscription-readiness verdict is reconfirmed, narrower than README's own framing**: the entire
  non-payment Stripe chain (plans, checkout-session creation, webhook signature enforcement,
  entitlement/quota gating, portal-session creation) is live and tested with real Stripe objects. What
  was pending is not "test-mode keys" (README's framing) but one human purchase click — and this sweep's
  own `pricing-screen-test.md` found a genuine, previously-unknown defect in that exact remaining step
  (`ML-PRICE-002`, currency presentment).

This document does not re-derive all 46 matrix rows independently; it cites the matrix as testimony and
folds in what the fuller sweep since then has proven or disproven with live sessions.

---

## 4. AI agent quality assessment

Basis: `uat/reports/evidence/gold-master-v2/adversarial/AI-AGENT-QUALITY-ASSESSMENT.md` — 4 real,
non-scripted agent runs against production in a single ~7-minute window (2026-07-30T23:53:30Z–
2026-07-31T00:00:17Z), plus historical corroboration from 200 recent `AgentRun` rows `[TESTIMONY]`.

| Agent | Craft score | One-line verdict |
|---|---|---|
| Resume tailoring | **2/10** | Anti-fabrication guard genuinely works (0 fabricated tokens across 2 fresh + 1 historical diff), but as a *tailoring* feature it barely functions: 7 of 7 recent runs (2 fresh, 5 historical) moved the ATS score by exactly **0.0%**. `resume_tailor.py` is a single LLM call with no re-score loop, no target parameter, no retry-to-threshold — confirmed at the code level (`resume_tailor.py:2083-2146`). A non-regression floor rejects any rewrite that drops even one JD-matched token, which can hold a score flat but never drive it up. |
| Cover letter generation | **6/10** | Content is genuinely strong — specific, evidence-dense, correctly structured, zero fabrication across every claim cross-checked against the real Story Bank. Would be 8–9/10 without the BLOCKER-002 identity contamination, which makes the output literally unsendable as generated. A second, smaller craft defect was also found: the LLM occasionally invents/mistypes a contact email inside the body prose even when the letterhead (rendered separately, non-LLM) is correct — `ML-COVER-101`, filed by `remaining-routes-screen-test.md` ROUTE 1. |
| Story bank extraction | **5/10** | Per-story writing quality is good — specific, quantified, evidence-true STAR content, zero fabrication. Capped by a bloat defect confirmed to have **materialized live during this run** (32→36 stories in one extraction pass): dedup only catches byte-identical resubmission, so re-running extraction on an unchanged résumé manufactures paraphrase duplicates every time. |
| ATS scoring | **Unproven as a discriminator** | Stable, UI-matches-API exactly on every check performed (multiple screens, 3/3+ independent version checks). But the entire 51–52-job production corpus sits in a 25-point-wide band, all 25–60 points below the platform's own 85 target. Nothing in this campaign's evidence validates the scorer against a known-good résumé/JD pair, so a tight-and-low range cannot be read as either "honest measurement of a genuine mismatch" or "mis-calibrated" — left unproven, not guessed at. |
| Job discovery | **7/10** | Genuinely the best-engineered part of the AI layer: real sources, illegal sources correctly filtered, Seek honestly labelled unavailable from backend state, upstream failures (Wellfound 403) surfaced honestly rather than swallowed. |

**Fabrication check, aggregated across every probe in this campaign (screen-testers' live generations,
the dedicated quality assessment's 4 runs, the cover-letters re-test's fresh generation): PASS,
unambiguously, in every single instance.** Zero fabricated claims found anywhere. The guard also actively
*declined* to bluff — twice in this campaign it refused a generation outright rather than invent
unsupported wording, and once it rejected a real, evidence-backed keyword addition because the same
rewrite happened to drop one other matched token, rather than accept a net-positive trade. Honest-failure
behavior (explicit `noChangesApplied: true`, `costUsd: 0.0000`, no fabricated substitute) held on every
zero-change run tested.

**Net: the product remains honest and not yet useful, and this sweep adds one more dimension —
it is honest right up until the moment its own safety control (human approval) gets bypassed by an
unattributed action with no audit trail (§1 item 2), at which point "honest" and "safe" diverge.**

---

## 5. Runtime health

Authoritative: `runtime/RUNTIME-MONITOR-REPORT-2-500-correlation.md` (superseding the first monitor,
which was a **false green** — it tailed `journalctl` while the services log to files, so it captured 1
line across an entire monitoring window and would have closed G-M on an instrument incapable of ever
recording an error; caught by the run itself, GOV-012, and retained as `journal-live-EMPTY-FALSE-
GREEN.log` rather than deleted).

**The one confirmed production 500 for the run remains exactly one:** `PUT /workspaces/settings` @
2026-07-30T23:50:46Z, root-caused to `workspaces.py:1092` — a NUL byte reaching psycopg2 unguarded,
raising an uncaught `ValueError` that falls through to a bare 500 instead of a validated 422 (no generic
exception handler exists in `main.py`). The fix (`0e73d95`, a blanket cursor-factory guard in `app/db.py`)
is verified green by 21 regression tests and confirmed, live, to also close the identical class on **10
more endpoints** the full sweep went on to independently confirm are still 500ing on production today:
`POST /resumes`, `POST /agents/tailor/run`, `POST /stories`, `PUT /stories/{id}`, `POST /cover-
letters/{id}/refine`, `POST /agents/cover-letter/run`, `GET /admin/users` (`q`/`plan`), `POST
/emails/draft`, `POST /interviews`, `POST /workspaces/offers`, `POST /networking/contacts` — **11
endpoints total**, one deploy away from all closing at once. Every one of these is independently
production-reproduced by a different screen-tester in this sweep; none is a novel root cause, all are the
same undeployed `db.py` guard.

**Rest of the exercised window:** 1488+ requests, 0 other 5xx, 0 other unhandled exceptions across the
originally-monitored 72–87-minute window, plus zero further 5xx surfaced anywhere across the entire
subsequent ~9-hour, 27-route screen sweep this document synthesizes (every 500 found by any screen-tester
traces to one of the 12 known NUL-byte instances above, or is the one login/signup-specific instance —
`ML-LOGIN-001`/`ML-SIGNUP-001`, itself the same class). Zero silent/fabricated success was observed on
any failed call, anywhere, in the entire campaign.

**Caveat that still holds:** the clean window was observed on OWNER and Free-tier accounts. No subscribed
non-admin session has ever been monitored end-to-end in this run's evidence. G-M cannot close on this
evidence plus a deploy; it needs a fresh post-deploy window, ideally with one subscribed session included.

---

## 6. Subscription readiness

| Stage | State |
|---|---|
| Pricing → plan catalog | **CONFIRMED**, GST math independently correct on all 8 tier/interval combos. Content itself is `ML-PRICE-001`/ADV-ENT-002 (Free over-advertised). |
| Checkout session creation | **CONFIRMED, live Stripe**, plus a **new CRITICAL finding** — see `ML-PRICE-002` above. |
| Webhook | **CONFIRMED** — unsigned payload correctly rejected 400; `checkout.session.completed` flipping a plan live remains the one genuinely un-automatable step (a human must enter a real card). |
| Entitlement gate | **CONFIRMED, and genuinely well built.** `agents.py:723-757` gates before resource lookup on every agent route — a bogus `job_id` returns 402, not 404, on every route tested (`ENTITLEMENT-ENFORCEMENT-VERIFICATION.md`, independently re-derived by the qa-adversary reviewer, not merely asserted). Sync and async/worker seams both covered; the system-run exemption requires a constant-time-compared secret and is scoped, not a bypass-by-omission. |
| CRUD routers (stories, interviews, offers, networking) | **NOT gated server-side**, confirmed by direct API proof in 3 of the 4 screens this sweep tested (`ML-NETWORKING-002` has the clearest live 201-with-a-Free-token proof; `ML-INTERVIEWS-002`/`ML-OFFERS-002` reasoned identically from source + UI behavior). These consume zero LLM capacity, so this is a monetisation-consistency gap, not a cost/capacity bypass. |
| `ADV-ENT-001` (the one genuinely ungated **paid-LLM** route, `POST /cover-letters/{id}/refine`) | **CLOSED IN CODE** (commit `b5900f6`, routes through the same `_record_run` gate every other agent action uses), **not deployed**. Verified by 5 tests. |
| `ADV-ENT-002` (server advertises + provisions a Free tier it universally denies) | **OPEN**, reconfirmed on a genuinely fresh signup this sweep (`ML-SIGNUP-003`). Needs a business decision, not a patch. |

**Verdict, unchanged from the deep adversarial pass and now further corroborated by the CRUD-screen
sweep**: entitlement is enforced server-side exactly where it protects paid LLM capacity, and is
client-side-only on CRUD features sold as tier benefits. Combined with `ADV-ENT-002` and the new
`ML-PRICE-002` currency finding, the billing story needs one coherent business decision plus a currency
fix, not per-router patches.

---

## 7. Test posture

- **Backend baseline:** 1885 passed / 0 failed / 0 skipped, clean and trustworthy (no skipped-test
  inflation).
- **Frontend (vitest):** 631/631 green.
- **Consolidated regression across this run's 16 new-fix suites:** 112 passed / 0 failed, 180.86s —
  covers every fix this run shipped (BLOCKER-001 ×2 suites, ML-settings-006, BLOCKER-002 code guard,
  INC-B-002, INC-B-001, W-C tailoring loop, W-E story dedup/relevance, ADV-ENT-001, ML-admin-003 NUL query
  param, pre-existing tailoring regressions) coexisting with zero cross-workstream regression.
- **RT-004 + W-C:** 22/22, independently reviewed by a second agent (not the author), who re-performed the
  tamper themselves and found the guard was caught by *two* tests, not the one the implementer claimed —
  protection is stronger than reported, not weaker.
- **Playwright:** 40 pass / 12 fail, exit 1. **12/12 of the red specs have now individually failed to
  reproduce against production wherever a screen-tester checked** (§1 item 4) — the working theory that
  these target `127.0.0.1:3091` rather than production is now well-corroborated but each still needs
  individual sign-off, not a blanket dismissal, before G-N closes.
- **Deploy state:** production runs the pre-fix binary from **2026-07-30T12:27:09Z**, unchanged as of this
  refresh's own probe at **2026-07-31T09:07Z** — over 20 hours and 45 commits behind HEAD. Most
  production-observed defects in this document are **already fixed at HEAD** and are pending exactly one
  deploy; a smaller set (resume tailoring's missing loop, the two paywall-vs-backend cluster, the
  approval-audit-trail gap, the Stripe currency issue) require new work, not merely a deploy.

---

## 8. Verdict

# NOT-READY — BLOCKED-ON-ITEMS

This does not overrule, and is not in tension with, the binding ruling already on file
(`ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` §6): *"G-P is REFUSED while `AETHER_ADMIN_PASSWORD_HASH` remains
unrotated… This holds even after the full approved fix set is deployed and verified."* That ADR controls
the credential blocker specifically. This verdict is broader, now backed by full 27-route coverage.

### Blocking items, in required order

1. **[OPERATOR-GATED · CRITICAL]** Rotate `AETHER_ADMIN_PASSWORD_HASH` **and** `AETHER_CRON_PASSWORD`
   together (they share a value; rotating one alone silently breaks scheduled discovery — this codebase
   has already suffered exactly this outage shape once). Confirmed still both live and exploitable as of
   this document's own write time.
2. **[DATA + PROCESS INVESTIGATION · CRITICAL, NEW]** Determine who or what resolved the 3 BLOCKER-002-
   contaminated approvals at 03:50:46–49Z, confirm whether "submitted" for those three has any external-
   facing consequence beyond the internal status flip, and — separately, regardless of that answer — add
   an audit-log write to `POST /approvals/{id}/approve` and `/reject`. This is now the highest-priority
   code gap in the run: the product's own safety backstop for exactly this class of incident cannot
   currently be investigated after the fact.
3. **[DATA PURGE · CRITICAL, CARRIED FORWARD]** 8 stored cover letters still carry the fixture signature
   in their body text (0 of 8 remediated); regenerate or purge them, prioritizing the 3 now marked
   `submitted`.
4. **[DEPLOY · BLOCKING EVERYTHING FIXABLE ABOVE]** 45 unpushed commits; production running the same
   binary for 20+ hours. Per GOV-011: no deploy until the ADR-derived suite is green **and** a reviewer
   who did not author the fix signs off — already satisfied for most of the fix set (§7), not yet actioned.
5. **[PRODUCT INTEGRITY · HIGH]** Resume tailoring must gain the score-aware loop its UI implies, or stop
   implying it. Today: 0.0% movement in 7/7 runs.
6. **[BUSINESS DECISION · HIGH]** `ADV-ENT-002` (honour the advertised Free tier or stop advertising it)
   and the newly-found `ML-PRICE-002` (force AUD presentment on Stripe Checkout, or accept that customers
   can be enrolled in floating-FX USD billing on a product marketed exclusively in fixed AUD).
7. **[TEST BASELINE · must not be reported as green]** Playwright 40/52; pytest and vitest are genuinely
   clean, the suite as a whole is not, and 12 specs still need individual real-vs-stale adjudication
   despite 12/12 independent disproofs so far.
8. **[PROCESS · LOW but real]** `approvals-screen-test.md` should be completed to a full narrative
   (currently an 18-line stub) — not because the underlying testing didn't happen, but because the gap in
   the narrative is exactly what let item 2 above go unnoticed until this refresh cross-referenced the raw
   evidence against the approval queue's own contents.

### What is genuinely good, and should not be lost in the noise

Full coverage did not surface a second BLOCKER-tier defect beyond the two already known — 25 of 27 routes
are functionally solid, honestly built, with no placeholder/fixture content on any user-reachable path
outside the BLOCKER-002 cluster, and the entitlement gate on paid LLM capacity is competently engineered
and held under adversarial, differential-proof testing on every route this sweep checked. The
anti-fabrication guard is the single most consistently strong result across the entire campaign — zero
fabrication found in dozens of live and historical agent-output checks. Honest-failure paths (402s, 422s,
zero-change no-ops, degraded-Gmail-triage, empty states) were honest on every screen tested, without
exception. This run caught its own monitoring false-green and its own unauthorised security-closure
commit through controls that were load-bearing rather than ceremonial — and this refresh's own discovery
(§1 item 2) is a continuation of that same pattern: a control this campaign trusted (the approval queue)
turned out to have a blind spot, and the campaign's own evidence, read carefully enough, was what
surfaced it.

**The honest bottom line, updated for full coverage:** a public repo still publishes a working production
admin credential right now; three contaminated cover letters have moved from "one click from a real
employer" to "resolved, with no record of by whom"; the platform's headline AI feature moves its own
metric by zero; a newly-found billing defect can enroll a customer in the wrong currency; and forty-five
commits of remediation sit unpushed. **NOT-READY.**

---

## Appendix — verification manifest for this refresh

| Probe | Method | Timestamp (UTC) |
|---|---|---|
| `git log`/`rev-parse` (commit count, HEAD) | git | 2026-07-31T09:07Z |
| `systemctl show` ×3 services (deploy timestamp) | systemctl | 2026-07-31T09:07Z |
| `GET /api/health` | curl | 2026-07-31T09:07Z |
| `POST /api/auth/login` (admin/admin123) | curl | 2026-07-31T09:13Z |
| `GET /api/approvals?status=pending` | curl (authenticated) | 2026-07-31T09:14Z |
| `GET /api/approvals?status=approved` | curl (authenticated) | 2026-07-31T09:16Z |
| `GET /api/cover-letters` (8-id cross-reference) | curl (authenticated) | 2026-07-31T09:15Z |
| `apps/api/app/routers/approvals.py`, `services/approval_service.py` | source read | 2026-07-31T09:18Z |
| `GET /api/admin/audit-log?limit=200` | curl (authenticated) | 2026-07-31T09:18Z |
| `grep` for auto-approve/scheduled-approval code paths | repo grep | 2026-07-31T09:19Z |

**Mutations:** none. Every probe in this refresh was read-only (login is a read of a token, not a write).
No config was changed, no data written, no service restarted, no commit, no push, no deploy, no approval
was approved/rejected/deleted by this refresh. No secret value was printed at any point (only the
standard 8-char token-prefix convention already used throughout this campaign).

**Not done, and why:** this refresh did not re-run Playwright, did not launch a browser, and did not spawn
sub-agents, per its own hard process rules — it synthesizes the 19 screen-test reports and 3 adversarial
deep-dives already on disk (each independently `[VERIFIED-WITH-FRESH-EVIDENCE]`-tagged by its own author)
rather than re-deriving 27 routes' worth of UI evidence a second time. Where this refresh had reason to
extend or question that evidence — the approval-queue cross-reference — it went to the API and the source
directly rather than accepting either the prior "PASS" verdict or a guess.
