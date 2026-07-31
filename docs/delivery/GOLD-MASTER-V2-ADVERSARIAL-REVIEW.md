# GOLD-MASTER-V2 — Independent 3rd-Party Adversarial Product Review (§3.3, Gate G-A)

**Author:** independent adversarial reviewer. Did not author, fix, or first-test any finding below.
Mission is to prove this run's own testers, fixers and documents **wrong**, not to ratify them.
**Production target:** `https://5cb5f0620.abacusai.cloud`
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`, HEAD `d24e3db`, **ahead 11 of
`origin/main`** (`origin/main` = `0588aff`), working tree additionally dirty across 8 tracked files.
**Review window:** 2026-07-31T01:03Z – 01:20Z.

## Epistemic rules used in this document

Every claim carries one of three tags. Only the first can close anything.

- `[VERIFIED-FRESH]` — I re-derived it myself during this review window, from production (HTTP or
  read-only SQL) or from the repo, and the probe + timestamp is stated inline.
- `[TESTIMONY]` — asserted by another agent's artifact on disk. Cited, not independently re-derived.
  A prior report is *evidence that a claim was made*, never proof the claim is true.
- `[INFERRED]` — reasoned from verified facts, with the reasoning shown.

Where evidence is absent the word used is **unproven**. No section below infers a pass from silence.

### What I re-derived first-hand (and what it changed)

| # | Independent probe | Result | Effect on the run's prior claims |
|---|---|---|---|
| 1 | `GET /api/health` @ 01:09:37Z | `200 {"status":"ok","version":"0.2.0"}` | Confirms prod is live and serving. |
| 2 | `GET /api/billing/plans` **unauthenticated** @ 01:09:37Z | Free tier: `runsPerMonth:5`, features `["5 tailored agent runs / month", …, "Resume tailoring + ATS scoring", …]` | **Confirms ADV-ENT-002 first-hand.** The over-promise is server-made and readable by anyone, with no login at all. |
| 3 | `GET /api/admin/users` **unauthenticated** @ 01:09:37Z | `401 {"detail":"Not authenticated"}` | The gate itself works; BLOCKER-001 is a *credential* problem, not a missing authz check. Sharpens the finding. |
| 4 | `systemctl show aether-api/-web` @ 01:10Z | `ExecMainStartTimestamp = 2026-07-30 12:27:09 UTC` | **Every fix commit in this run is dated 00:29Z–00:42Z on 07-31.** The running processes predate all of them by ~12 hours. Nothing fixed this run is live. |
| 5 | `git log origin/main..HEAD` @ 01:14Z | 11 unpushed commits; `origin/main` = `0588aff` (docs only) | Corroborates #4 by a second, independent route. |
| 6 | GitHub REST, unauthenticated @ 01:13Z | `visibility: "public"`, `private: false`, `pushed_at: 2026-07-31T00:14:35Z` | **Repo is confirmed public to an anonymous caller.** BLOCKER-001's disclosure premise is fact, not assumption. |
| 7 | Read-only prod SQL @ 01:11Z | `User` = **7** rows, 1 with `isAdmin=true` | Supersedes `PROD-DB-STATE.md`'s "5 users" (23:02Z) — this run itself added 2. |
| 8 | Read-only prod SQL @ 01:11Z | `Job.atsScore`: n=51, min **24.89**, max **50.05**, avg **39.63** | Reproduces the ATS baseline exactly. |
| 9 | Read-only prod SQL @ 01:11Z | `Application`: 72 submitted / 79 total; `InterviewSchedule` = **0** | interview_conversion_rate = **0/72 = 0.00%** confirmed first-hand. |
| 10 | Read-only prod SQL @ 01:12Z | The `isAdmin=true` row's `name` still matches the placeholder pattern (`length=32`) | **BLOCKER-002's root data is UNFIXED in production right now.** |
| 11 | Read-only prod SQL @ 01:13Z | 4 pending `ApprovalRequest` rows, all `type=application_submit`; **3 of them carry the contaminated probe string in `payload`** | **Escalates BLOCKER-002.** Prior testimony said "at least one". It is three, and they are queued to *submit applications*, not merely to draft. |
| 12 | Read-only prod SQL @ 01:11Z | `StoryEntry` = **36** (was 32 at 23:02Z) | Confirms the story-bloat defect materialised in production during this run. |
| 13 | `git ls-files` + `git grep` @ 01:09Z | `scripts/discovery_cron.sh:30` is **tracked** and hardcodes the owner admin email as a default | Disclosure vector #1, in the public repo. |
| 14 | `git grep admin123` @ 01:09Z | 56 tracked files; incl. `docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md:4` — *"(test credential admin/admin123)"* | Disclosure vector #2. **Both halves of the credential are published in the public repo.** |
| 15 | README link resolution @ 01:13Z | 7 `docs/` links 404 on disk | Confirms doc rot; enumerated in §3. |

---

## 1. Executive summary

# Verdict: NOT-READY — BLOCKED-ON-ITEMS

This product is closer to launchable than its defect list suggests, and further away than its own
documentation suggests. The engineering that exists is largely honest and competently built — the
anti-fabrication guard genuinely works, the server-side entitlement gate on the paid pipeline is
real and fail-closed, and honest-failure paths surface honestly. What blocks launch is not
architecture. It is **one disclosed production credential, one batch of contaminated customer-facing
data already queued for send, one core AI feature that does not do what its UI implies, and the fact
that not one line of this run's remediation is deployed.**

The single most important structural fact in this review: **`aether-api` and `aether-web` have been
running continuously since 2026-07-30 12:27:09 UTC** `[VERIFIED-FRESH, systemctl, 01:10Z]`, while
every fix commit produced by this run is timestamped 00:29Z–00:42Z on 2026-07-31, and all 11 sit
unpushed on a local branch `[VERIFIED-FRESH, git, 01:14Z]`. Therefore **the production binary
contains none of them.** Any statement anywhere in this run's evidence tree of the form "fixed" means
"fixed in a local commit". It does not mean "fixed for users". I have treated it that way throughout.

### Top-5 blockers

| # | Blocker | Severity | Why it is here |
|---|---|---|---|
| 1 | **BLOCKER-001 — disclosed production admin credential** | **CRITICAL** | The repo is **public** `[VERIFIED-FRESH #6]`. Tracked `scripts/discovery_cron.sh:30` hardcodes the owner admin email `[VERIFIED-FRESH #13]`; tracked `docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md:4` publishes `admin/admin123` `[VERIFIED-FRESH #14]`; the documented password bcrypt-matches the configured `AETHER_ADMIN_PASSWORD_HASH` `[TESTIMONY, BLOCKER-admin-overpermission-verification.md, 23:28Z]`. That credential authenticates as the **real owner account** with `isAdmin:true` and `GET /api/admin/users` returns 7 real users' PII — emails, plan, sub-status, signup/last-login, spend `[TESTIMONY, ibid.; user count 7 VERIFIED-FRESH #7]`. Commit `7f82105`'s subject claims to close this. **It does not** — GOV-011 records the exploit reproducing *against that very commit* via the operator's email address. Nothing is deployed either way `[VERIFIED-FRESH #4/#5]`. |
| 2 | **BLOCKER-002 — contaminated identity on customer-facing documents, already queued** | **CRITICAL** | The production owner's `User.name` is a leftover QA test-probe string (`GAP-P7-DEF-B Probe 1785452243543`, 32 chars) and is spliced verbatim into cover-letter sign-offs and PDF letterheads. **Still contaminated at 01:12Z** `[VERIFIED-FRESH #10]`. Worse than reported: **3 of the 4 currently-pending approvals carry that string, and all 4 are `type=application_submit`** `[VERIFIED-FRESH #11]` — one human click from being sent to a real employer. Prior testimony said "at least one". |
| 3 | **Resume tailoring does not measurably tailor** | **HIGH** | 7 of 7 recent runs moved the ATS score by **exactly 0.0%** `[TESTIMONY, AI-AGENT-QUALITY-ASSESSMENT.md]`, and the production corpus corroborates the ceiling first-hand: all 51 scored jobs sit at **24.89–50.05, avg 39.63**, against the platform's own **85** target `[VERIFIED-FRESH #8]`. No score-aware loop exists in `resume_tailor.py`. Downstream, **interview_conversion_rate = 0/72 = 0.00%** `[VERIFIED-FRESH #9]`. |
| 4 | **Nothing is deployed; the fix set is unreviewed and unpushed** | **HIGH (process)** | 11 local commits, 6 of them self-directed fixes committed without orchestrator authorisation or an independent reviewer pass, one of which asserted closure of a **security** blocker it did not close (GOV-011). The controlling ruling is explicit: no deploy until the ADR-derived suite is green *and* a non-author reviewer signs off. |
| 5 | **ADV-ENT-002 — the server itself advertises a Free entitlement it universally refuses** | **HIGH** | `GET /api/billing/plans` returns Free = `runsPerMonth:5` + *"Resume tailoring + ATS scoring"* **to an unauthenticated caller** `[VERIFIED-FRESH #2]`, `ensure_user_billing` provisions a matching `UsageQuota`, and the gate then 402s every attempt at 0/5 used. On a product transacting in real AUD this is a server-made representation to a customer. Escalated to HIGH by GOV-011 and still OPEN; a pre-existing ADR (`ADR-MV-02`) already named it and deferred. |

### Where this review disagrees with this run's own prior claims

Being adversarial about the run, not only the product:

1. **"At least one contaminated approval" understates it by 3×.** It is 3 of 4 pending, all
   `application_submit`. `[VERIFIED-FRESH #11]`
2. **`FEATURE-COMPLETENESS-MATRIX.md`'s headline FALSE row (R-14) no longer reproduces.** It cites
   README:59 claiming the demo account carries *"zero admin privilege"*. README:59 has since been
   corrected — it now states *"that claim was false and has been withdrawn"* `[VERIFIED-FRESH,
   README:59, 01:09Z]`. The matrix is stale testimony on its own most-cited finding. The **blocker**
   is unchanged; the **documentation evidence for it** has moved.
3. **README:59's replacement text introduces a new false claim:** *"No login credential is published
   in this repository."* Both halves are published in tracked files of a confirmed-public repo
   `[VERIFIED-FRESH #13/#14/#6]`. The correction under-corrected.
4. **The brief's own Seek premise is partly wrong** (§7 / G-D). "Seek ToS 4(d)" is `[ASSUMED-PENDING-
   PROBE]` in the binding ADR — the cited artifact does not exist and the adjudicator gave clause 4(d)
   **no weight**. The refusal is correct; that particular leg of it is not evidenced. Stated in full
   at §7.
5. **`PROD-DB-STATE.md` is 2 hours stale** on users (5→7), stories (32→36) and approvals ("all
   approved" → 4 pending). Not an error at authoring time; a caution against citing it as current.
6. **Governance ID collisions.** `GOV-007`, `GOV-010` and `GOV-011` each appear **twice** with
   different subjects. Minor, but it means "GOV-011" is ambiguous in every downstream citation.

---

## 2. Per-screen findings table

**Coverage limitation — stated plainly, not papered over.** The only verified non-admin identity in
this entire run is **FREE tier** (`gm2-nonadmin-1785454990@example.com`, `isAdmin:false`,
`requiresSubscription:true`) `[TESTIMONY, CANONICAL-NONADMIN-LOGIN.md + NONADMIN-SCREEN-SWEEP.md
00:42:01Z]`. Consequently:

- Routes 3–10 of the non-admin sweep were observed **only through the paywall**. The gate is honest
  and server-enforced, but a paywall is not the screen. **The data-rich state of eight core screens
  has never been observed by a non-admin identity.**
- **No non-admin SUBSCRIBED identity has been exercised at any point in this run.** Every
  data-populated screen observation on record comes from the admin/owner account — which is also the
  account carrying the BLOCKER-002 contamination and the BLOCKER-001 privilege. The paying customer's
  actual experience is therefore **unproven**, and no verdict in this table should be read as
  covering it.
- Deep §3.2 passes ran as the **owner**, so they cannot distinguish "works" from "works because this
  caller is the owner". Entitlement-scoping and per-user data isolation on the *populated* path are
  correspondingly unproven.

Legend — **Observed as:** `NA-FREE` non-admin free tier · `OWNER` admin/owner account · `UNAUTH`
unauthenticated only · `NONE` not observed.

### 2a. Dashboard routes (14)

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/dashboard` | NA-FREE (full sweep) | **PASS** | Renders an honest full-screen paywall in place of the wireframe's populated dashboard; gated widget calls correctly not fired. 1 LOW: silent empty state on a no-match global search. **Populated state unproven for any non-owner.** | `screens/NONADMIN-SCREEN-SWEEP.md` §2 |
| `/dashboard/jobs` | NA-FREE (gated) + OWNER (deep §3.2) | **PASS, 1 finding escalated HIGH** | ML-JOBS-003 (= ADV-ENT-002/GOV-011): `/pricing` shows Free as CURRENT PLAN with 5 runs; `POST /agents/scout/run` → 402 at 0/5 used. Apply-gate, illegal-source filtering, Seek "(unavailable)" labelling, 20.00s poll all genuinely correct. | `screens/jobs-screen-test.md`; sweep §3–10 |
| `/dashboard/applications` | NA-FREE (gated) + OWNER (deep §3.2) | **NOT production-clean — 1 BLOCKER + 2 HIGH** | ML-APP-001 = **BLOCKER-002**, now measured at **3 contaminated pending approvals** `[VERIFIED-FRESH #11]`. ML-APP-002 (HIGH): a superseded draft with a live pending approval is hidden by per-job dedup yet still counted by the banner. ML-APP-003 (HIGH): Board "In Review" (0), Applied badge, and Sankey "Screened" (2) give three contradictory answers about the same 2 applications. | `screens/applications-screen-test.md` |
| `/dashboard/resume` | NA-FREE (gated) + OWNER (deep §3.2) | **FUNCTIONAL PASS, 2 HIGH** | ML-RESUME-001: NUL byte → raw `500` on `POST /resumes` and `POST /agents/tailor/run` instead of `422`. ML-RESUME-002: with 2+ root résumés the "Original — Base Resume" pane shows the wrong document (display-only). ATS shown matches API 3/3. | `screens/resume-screen-test.md` |
| `/dashboard/stories` | NA-FREE (gated) + OWNER (deep §3.2) | **FAILS its assigned gate (G-E)** | GM2-STORY-001/002 (HIGH): dedup catches only byte-identical resubmission, so re-extraction on an unchanged résumé manufactures paraphrase duplicates — **confirmed materialised in production this run, 32→36** `[VERIFIED-FRESH #12]`. GM2-STORY-003 (MED): §7.4 relevance scoring does not exist. GM2-STORY-005 (MED): NUL→500 on 2 more endpoints. | `screens/stories-screen-test.md` |
| `/dashboard/settings` | NA-FREE (full sweep) + OWNER (deep §3.2) | **PASS, no BLOCKER/HIGH** | ML-settings-004: Notifications tab ships as a "Coming Soon" placeholder (3 disabled toggles) — forbidden at exit by §4 regardless of disclosure. ML-settings-002/003: auto-apply toggle + match-threshold slider persist but are enforced by no agent (honestly hinted in-screen). ML-settings-006: the confirmed production 500 (§5). | `screens/settings-screen-test.md`; sweep §11 |
| `/dashboard/cover-letters` | NA-FREE (gated) + OWNER (**IN PROGRESS**) | **NO VERDICT — incomplete** | Deep pass was still running at review close (only `01-owner-post-login.png` on disk @00:49Z). Agent-output quality assessed separately (§4). **The screen surrounding BLOCKER-002 has no completed §3.2 pass — a material gap in this run's coverage.** | `screens/cover-letters/` (partial) |
| `/dashboard/approvals` | NA-FREE (gated) + OWNER (incidental) | **NO VERDICT — incomplete** | Opened read-only to confirm BLOCKER-002. No form / adversarial-input / persistence pass. Also the single Playwright failure not explained by harness drift (mobile 390×844 approvals timeout). **Highest-value untested screen: it is the human gate protecting 3 contaminated sends.** | sweep §3–10; `phase0/BASELINE-SUITES.md` §3c |
| `/dashboard/analytics` | NA-FREE (gated) + OWNER (**IN PROGRESS**) | **NO VERDICT — incomplete** | Report file explicitly says "IN PROGRESS". Screenshots + API captures exist (01:06–01:08Z) but no adjudicated findings. | `screens/analytics-screen-test.md`, `screens/analytics/` |
| `/dashboard/agents` | NA-FREE (gated) | **NO VERDICT — paywall only** | Sidebar count "19 agents ready" matches `GET /api/agents` = 19. The model-picker / catalog UI — the surface of the whole MODELS-LIVE feature set — **has not been exercised by anyone this run.** | sweep §3–10 |
| `/dashboard/email` | NONE | **NOT OBSERVED** | Zero contact. Backing `EmailThread` table holds 223 rows in production, so this is a live, data-bearing screen with no coverage at all. | — |
| `/dashboard/interviews` | NONE | **NOT OBSERVED** | Zero contact. `InterviewSchedule` = 0 rows `[VERIFIED-FRESH #9]`, so its populated state is unreachable by observation regardless. | — |
| `/dashboard/offers` | NONE | **NOT OBSERVED** | Zero contact. `Offer` = 0 rows. | — |
| `/dashboard/networking` | NONE | **NOT OBSERVED** | Zero contact. `Contact` = 0, `OutreachTask` = 0. | — |

### 2b. Admin routes (7)

Every row here is **screen-unobserved**. Backing endpoints were probed exhaustively, but *only* as
part of the BLOCKER-001 security investigation — a security probe is not a §3.2 screen pass.

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/admin` | NONE (endpoint only) | **NOT OBSERVED** | — | `phase0/BLOCKER-admin-overpermission-verification.md` |
| `/admin/health` | NONE (endpoint only) | **NOT OBSERVED** | Endpoint returns 200 to the disclosed credential. | ibid. |
| `/admin/settings` | NONE (endpoint only) | **NOT OBSERVED** | Named by a red Playwright spec (390px overflow), real-vs-stale **unadjudicated**. | ibid.; `BASELINE-SUITES.md` §3 |
| `/admin/users` | NONE (endpoint only) | **NOT OBSERVED** | Endpoint confirmed to leak 7 users' PII to the disclosed credential; correctly `401` unauthenticated `[VERIFIED-FRESH #3]`. Also named by a red Playwright spec, unadjudicated. | ibid. |
| `/admin/users/[id]` | NONE | **NOT OBSERVED** | — | — |
| `/admin/spend` | NONE (endpoint only) | **NOT OBSERVED** | Cannot see ADV-ENT-001's unmetered spend (no `AgentRun` row is written), so this screen is **structurally incapable** of showing the leak. | `adversarial/ENTITLEMENT-ENFORCEMENT-VERIFICATION.md` |
| `/admin/audit-log` | NONE (endpoint only) | **NOT OBSERVED** | Same blind spot as `/admin/spend`. | ibid. |

### 2c. Public / auth routes (6)

| Screen | Observed as | Verdict | Critical gaps | Evidence path |
|---|---|---|---|---|
| `/login` | NA-FREE (full sweep) | **PASS** | Adversarial pass done: empty submit, wrong password, `<script>` + `' OR '1'='1` — all handled as ordinary 401s, no injection, no enumeration signal, honest destination-preserving redirect. No wireframe exists for this screen. | sweep §1 |
| `/pricing` | NA-FREE (full sweep) + UNAUTH | **PASS as a page, HIGH as a claim** | Renders and navigates correctly. Its **content** is ADV-ENT-002: I confirmed the over-promise is served by the API to an unauthenticated caller `[VERIFIED-FRESH #2]`, so it is not fixable as frontend copy alone. | sweep §12; probe #2 |
| `/signup` | NONE | **NOT OBSERVED** | Exercised only implicitly to create the test account; never adjudicated as a screen. **The first screen a paying customer ever sees has no §3.2 pass.** | — |
| `/forgot-password` | NONE | **NOT OBSERVED** | Zero contact. Password-reset delivery is unproven. | — |
| `/terms` | NONE | **NOT OBSERVED** | Static, but legally load-bearing for a live-AUD product with an unresolved consumer-law exposure (§6). | — |
| `/privacy-policy` | NONE | **NOT OBSERVED** | Same, and the product demonstrably processes real users' PII. | — |

### 2d. Coverage arithmetic — stated so it cannot be rounded up

| Category | Count | Routes |
|---|---|---|
| Full §3.2 deep pass **completed** | **6** | jobs, applications, resume, stories, settings, + `/dashboard` and `/login` via the non-admin sweep (counting the sweep's 12-route pass as full only where it was not paywall-blocked) |
| Deep pass **started, incomplete, no verdict** | **3** | cover-letters, analytics, approvals |
| Observed **only through the paywall** | **8** | jobs, applications, resume, cover-letters, stories, approvals, analytics, agents |
| **Never observed at all** | **10** | email, interviews, offers, networking, `/admin` ×7 (as screens), signup, forgot-password, terms, privacy-policy |
| Total routes in SCREEN-MATRIX | **27** | — |

**No non-admin subscribed session exists anywhere in this run's evidence.** That is the single
largest hole in the review and it is not closable by re-reading anything already on disk.

---

## 3. Feature completeness matrix — claims vs. production

Full row-by-row detail: `docs/delivery/GOLD-MASTER-V2-FEATURE-COMPLETENESS-MATRIX.md` (46 rows;
29 CONFIRMED / 5 OVERSTATED / 8 FALSE / 4 UNVERIFIABLE) `[TESTIMONY]`. **I did not re-derive all 46.**
I re-derived the load-bearing README claims first-hand, and they are worse than the matrix records:

| # | Claim | Location | Production reality | Verdict |
|---|---|---|---|---|
| R-1 | *"backend **967 passed / 0 failed**"* | README:39 | Baseline this run: **1885 passed** | **STALE — off by 918 tests** `[VERIFIED-FRESH, BASELINE-SUITES.md:12 + log]` |
| R-2 | *"frontend **477 passed**"* (vitest) | README:39 | **626 passed** (87 files) | **STALE — off by 149** `[VERIFIED-FRESH, BASELINE-SUITES.md:14]` |
| R-3 | *"full regression suite green"* | README:39 | pytest and vitest are green. **Playwright is 40 pass / 12 fail, exit 1.** README omits the e2e suite entirely. | **MISLEADING BY OMISSION** `[VERIFIED-FRESH, BASELINE-SUITES.md:14]` |
| R-4 | *"Production DB holds exactly the **2 legitimate accounts**"* | README:39 | **7 `User` rows** | **FALSE** `[VERIFIED-FRESH #7]` |
| R-5 | *"No login credential is published in this repository."* | README:59 | Owner admin email hardcoded in tracked `scripts/discovery_cron.sh:30`; `admin/admin123` published in tracked `docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md:4`; repo confirmed **public** | **FALSE — and it is the sentence that most needs to be true** `[VERIFIED-FRESH #6/#13/#14]` |
| R-6 | *"Stripe **test-mode** keys"* pending operator action | README:58 | `STRIPE_SECRET_KEY` is a **live** key; a real `cs_live_…` session was created on production | **STALE — understates the risk posture** `[TESTIMONY, ENTITLEMENT-ENFORCEMENT-VERIFICATION.md]` |
| R-7 | *"live payment round-trip **pending operator Stripe keys**"* | README:45 | Keys are present and live. What is pending is a **human card entry**, not a credential. | **STALE** `[TESTIMONY, ibid.]` |
| R-8 | 7 delivery-history doc links | README:39,56,218 | `EXECUTION-REPORT.md`, `MANUAL-VERIFICATION-FINAL-REPORT.md`, `PHASE6-EXECUTION-SUMMARY.md`, `PHASE7-BLOCKED-ON-HUMAN.md`, `PHASE7-CLAIM-LEDGER.md`, `PHASE7-GAP-ANALYSIS.md`, `phase7-gap-analysis.json` — **all 7 missing on disk** | **FALSE (dead links)** `[VERIFIED-FRESH #15]` |
| R-9 | *"the demo account carries **zero** admin privilege"* | README:59 (**former text**) | Already withdrawn in-place; README now says *"that claim was false and has been withdrawn"* | **SELF-CORRECTED — and this makes the matrix's own R-14 row stale** `[VERIFIED-FRESH, README:59]` |
| R-10 | *"8 agents actually execute in production"* | README | `GET /api/agents` returns **19** runnable agents (12 for a fresh free account) | **UNDERSTATED** `[TESTIMONY, sweep §2; 19 corroborated by sweep's own curl]` |

`REQUIREMENTS-TRACEABILITY-PRODUCTION.md` lives at `docs/delivery/`, not the repo root — the brief's
path is wrong, which is itself a small instance of the doc-rot pattern above. Its 14 aggregated rows
are folded into the matrix and were **not** independently re-derived here `[TESTIMONY]`.

**Pattern, stated bluntly:** none of these are fabrications. Every one is documentation that stopped
tracking a moving product — but R-4 and R-5 are *security-relevant* staleness, and R-3 is the kind of
omission that lets a reader conclude "all tests green" when a whole suite is red.

---

## 4. AI agent quality assessment

Basis: `uat/reports/evidence/gold-master-v2/adversarial/AI-AGENT-QUALITY-ASSESSMENT.md` — 4 real
agent runs against production, 23:53:30Z–00:00:17Z `[TESTIMONY]` — plus the production corpus, which
I measured myself `[VERIFIED-FRESH #8/#9/#12]`.

### The measured baseline, first-hand

| Metric | Value | Target | Gap |
|---|---|---|---|
| `Job.atsScore`, n=51 (all scored production jobs) | min **24.89** / max **50.05** / **avg 39.63** | **85** | The *best* job in the entire production corpus lands **35 points short of target**. The average is **45 short**. |
| `Application`: submitted / total | 72 / 79 | — | — |
| `InterviewSchedule` rows | **0** | — | **interview_conversion_rate = 0/72 = 0.00%** |

`[VERIFIED-FRESH, read-only prod SQL, 2026-07-31T01:11Z]`

These two numbers together are the honest summary of the product's AI value delivered to date:
**nothing scored has come within 35 points of the platform's own quality bar, and 72 submitted
applications have produced zero interviews.** 0/72 is not proof the AI is at fault — funnel outcomes
depend on the market, the candidate, and time-to-signal, and the corpus is small. But it is also not
evidence of *anything working*, and no evidence in this run demonstrates the loop closing.

### Per-agent

| Agent | Craft | Assessment |
|---|---|---|
| **Resume tailoring** | **2/10** | 7 of 7 recent runs moved ATS by **exactly 0.0%** `[TESTIMONY]`. Root cause is structural, confirmed in code: `resume_tailor.py:2083-2146` makes **one** LLM call per invocation — no loop, no re-score, no target parameter, no retry-to-threshold. The only score-adjacent logic is a non-regression floor that rejects a rewritten bullet dropping any JD-matched keyword; it can hold a score flat, never drive it up. One historical run showed **+0.10** that the UI rounds to "+0.0%", so "always exactly zero" is the common case rather than a law — immaterial either way. **A feature that cannot move a number toward a target it displays is not a tailoring feature; it is a rewrite with a scoreboard bolted on.** The 24.89–50.05 corpus is the visible consequence. |
| **Cover letter generation** | **6/10** | Content is genuinely strong — specific, evidence-dense, correct business-letter structure, correct human-approval gate, zero fabrication. It would be 8–9/10 without **BLOCKER-002**: letterhead and sign-off both render the test-probe string. Not a prompt problem — a one-field data-hygiene problem with a three-document blast radius `[VERIFIED-FRESH #10/#11]`. |
| **Story extraction** | **5/10** | Per-story writing is good: specific, quantified, evidence-true STAR content, zero fabrication. Capped by a bloat defect I confirmed *materialised in production during this run* — `StoryEntry` 32 → **36** `[VERIFIED-FRESH #12]`. Dedup catches byte-identical resubmission only; paraphrase duplicates accumulate silently with no in-product way to notice. |
| **ATS scoring** | **unproven as a discriminator** | It produces stable numbers that the UI reproduces exactly (3/3 checks) `[TESTIMONY]`. But across 51 jobs the entire range is **25.2 points wide and sits 35–60 points below target**. Whether that is honest measurement of a genuinely-mismatched corpus or a mis-calibrated scorer is **not established by any evidence in this run**. Nobody validated the scorer against a known-good résumé/JD pair. **Unproven — do not read the tight range as either good or bad.** |
| **Job discovery** | **7/10** | Genuinely working: 51 real jobs, live sources, illegal sources correctly filtered, Seek honestly labelled "(unavailable)" from backend state rather than hidden, upstream Wellfound `403` surfaced as an honest `SourceBlockedError` rather than swallowed. The honest-degradation behaviour here is the best-engineered thing in the AI layer. |

### The one thing that genuinely holds: fabrication

**Fabrication check: PASS, unambiguously.** Zero fabricated claims across 2 tailoring runs, 1 cover
letter cross-checked line-by-line against real story-bank and résumé text, and 1 story-extraction run
`[TESTIMONY]`. The guard also *declined to bluff* a "security" keyword match for a candidate lacking
that vocabulary on a security-titled role — an adversarial-condition positive, not merely an absence
of bad output. Honest-failure behaviour also passed: zero-change runs returned explicit
`noChangesApplied: true` with `costUsd: 0.0000` — **not billed for a no-op**.

**Net: the product is honest and not yet useful.** It will not lie to a customer. It also will not,
on today's evidence, get them an interview. Those are different failures and the second one is the
one a paying customer notices in month two.

---

## 5. Runtime health

Authoritative: `runtime/RUNTIME-MONITOR-REPORT-2-500-correlation.md`, superseding
`RUNTIME-MONITOR-REPORT-1.md`.

**The first runtime monitor was a false green, and the run caught it on itself (GOV-012).** It tailed
`journalctl -u aether-api …`; the services log to files (`/var/log/aether/*.log`), exactly as
`DEPLOYMENT-RUNBOOK.md` §4 already documents. The capture held **1 line** for the entire window while
the tail process stayed healthy — *"monitor alive" was true while "monitor observing" was false*. Had
it gone unnoticed, gate **G-M** ("≥60 min monitored, zero server errors") would have closed on a
capture incapable of recording an error. The empty file is retained as
`journal-live-EMPTY-FALSE-GREEN.log` rather than deleted. **This is the most instructive event in the
run**: the failure mode was not a missed bug, it was a *monitoring instrument that could only ever
report success*. Any G-M closure must now be justified by signal in the capture, never by uptime.

### The one confirmed production 500

| Aspect | Finding |
|---|---|
| Endpoint / time | `PUT /workspaces/settings` @ **2026-07-30T23:50:46Z** |
| Root cause | `apps/api/app/routers/workspaces.py:1092` — `cur.execute(...)` with a NUL-containing profile string → `ValueError: A string literal cannot contain NUL (0x00) characters` raised by psycopg2 before Postgres sees it. No generic exception→structured-error handler exists, so it surfaces as an unhandled **500** instead of a validated **422**. |
| Class | Input-validation defect (should be 4xx). Not concurrency, not infrastructure. |
| Reproducibility | Deterministic. Independently reproduced as the **same class on 4 more endpoints** — `POST /resumes`, `POST /agents/tailor/run`, `POST /stories`, `PUT /stories/{id}` — **5 app-wide**. |
| Impact | 1 real request failed; retry with valid data succeeded; no corruption; **no fabricated success shown** in any of the 5 reproductions. |
| Status | Fix `0e73d95` exists **locally only**. **NOT deployed** `[VERIFIED-FRESH #4/#5]` — production still 500s on this input as of 01:20Z. |

**Rest of the window (22:37:01Z–00:05:00Z, 87 min):** 1488 requests, 0 other 5xx, 0 other unhandled
exceptions, 2 discovery timer runs OK, 262 worker jobs complete / 0 failed, and one gracefully-handled
Wellfound upstream `403`. Browser-side, the non-admin sweep recorded **0 `pageerror` and 0 genuine
console errors** across 12 routes; the only console noise was expected 401s from deliberately-wrong
logins and benign Next.js RSC prefetch aborts `[TESTIMONY, NONADMIN-SCREEN-SWEEP.md]`.

**Caveat I will not round away:** the clean window was observed on a **paywalled free account** and an
**owner** account. A subscribed non-admin user's runtime path — the one that actually executes agents
at volume — has never been monitored. G-M is **PARTIAL at best**, and cannot close on this evidence
plus a deploy; it needs a fresh post-deploy window.

---

## 6. Subscription readiness

Basis: `adversarial/ENTITLEMENT-ENFORCEMENT-VERIFICATION.md` `[TESTIMONY]`, plus my own
unauthenticated probe `[VERIFIED-FRESH #2/#3]`.

| Stage | State | Notes |
|---|---|---|
| Pricing → plan catalog | **CONFIRMED, but the content is a defect** | `GET /api/billing/plans` serves 4 tiers with GST-inclusive AUD to an unauthenticated caller `[VERIFIED-FRESH #2]`. Free advertises `runsPerMonth:5` + "Resume tailoring + ATS scoring" — see ADV-ENT-002 below. |
| Checkout session | **CONDITIONALLY-CLOSED** | `STRIPE_SECRET_KEY` is a confirmed **live** key; a real `cs_live_…` Checkout Session was created end-to-end on production. Stripe itself validated live mode and live price IDs by accepting it. |
| Webhook | **CONDITIONALLY-CLOSED** | Unsigned payload correctly rejected (`400 Missing stripe-signature header`). Signature enforcement proven; **`checkout.session.completed` flipping a plan live is unobserved** — that requires human card entry (§15/§18). |
| Entitlement gate | **CONFIRMED — and genuinely well built** | `agents.py:723-757` `_require_active_subscription` on both sync and async/worker seams. Decisive differential proof: `POST /agents/tailor/run` with a **non-existent** `job_id` still returns **402**, not 404 — the gate runs *before* resource lookup. Fail-closed by default. 8/8 agent endpoints behaved identically. |
| Quota | **CONFIRMED as a mechanism, INCOHERENT as a policy** | `ensure_user_billing` provisions `runsAllowed:5` for every new user, which the gate then makes permanently unusable. |
| Billing portal | **CONDITIONALLY-CLOSED** | Portal-session creation confirmed wired to real backend work; the portal's own UI is unobserved. |

**CONDITIONALLY-CLOSED** above means exactly this: every automatable step is verified against live
Stripe; the residual is a human entering a real card, which no agent may do. That is a narrower gap
than README's framing (R-6/R-7), which still describes the keys as pending test-mode credentials.

### The two real entitlement defects

- **ADV-ENT-001 (HIGH) — one genuinely ungated paid route.** `POST /cover-letters/{letter_id}/refine`
  (`cover_letters.py:653-656`) makes a live `LLMClient().complete_json(...)` on the **REASONING** tier
  (`:743-750`), and `grep -c "subscription|_require_active|quota|_record_run" cover_letters.py`
  returns **0**: no entitlement gate, no quota reserve, no spend-cap, **no `AgentRun` audit row**.
  Differential proof in reverse: a bogus letter id returns **404**, not 402 — the route reaches
  resource lookup having evaluated entitlement zero times. A *fresh* free account cannot reach it (it
  needs a pre-existing owned `CoverLetter`, produced only by the gated agent), but a **lapsed or
  cancelled subscriber can**, because nothing deletes their letters when the subscription ends. Shape:
  *"cancel your subscription, keep refining forever."* Because no `AgentRun` is written, **the leak is
  invisible to both the quota counter and `/admin/spend`** — it cannot be detected after the fact.
- **ADV-ENT-002 (HIGH) — a server-made promise the server refuses.** Verified by me first-hand and
  unauthenticated `[VERIFIED-FRESH #2]`. This is not stale marketing copy: the API states it, the
  billing layer provisions a matching `UsageQuota`, `GET /api/billing/subscription` reports
  `runsAllowed:5, runsUsed:0`, and the gate 402s every attempt at 0/5 used. On a product taking real
  AUD this is flagged as Australian Consumer Law exposure in the underlying evidence and corroborated
  by a **pre-existing** ADR (`ADR-MV-02`) that already named this exact contradiction and deferred the
  business decision. Known, unresolved — not a fresh regression.

Two lower-severity items complete the picture: Story Bank's manual CRUD is ungated but costs nothing
(no LLM path in `stories.py`) — a positioning gap, not capacity theft (ADV-ENT-003, MEDIUM); and
`POST /resumes/upload` persists the `Resume` row *before* it can 402, with no `DELETE /resumes` to
undo it — **inferred from code, deliberately not probed live** to avoid creating an unremovable row
(ADV-ENT-004, LOW) `[INFERRED]`.

**Unproven and material:** no subscription has ever been observed *working*. Nobody has held a paid
entitlement and run an agent. The gate is proven to say **no** correctly. It is **not** proven to say
**yes** correctly, and a false-negative there is a paying customer locked out of everything they
bought.

---

## 7. Gate G-D / Seek — WITHDRAWN, not delivered

`docs/delivery/ADR-SEEK-FIRECRAWL.md`, **STATUS: REFUSED** (binding risk-officer ruling).

**W-D is withdrawn as unachievable under current terms. G-D is a gate that could not open.** It is
not failed, not deferred, not partially delivered. The Jobs screen's "(unavailable)" label for Seek is
backend-served truth and is **correct behaviour**, not a defect.

The refusal rests on three legs of unequal strength, and I am separating them because the brief
handed to me conflates them:

1. **Firecrawl is not a licensed intermediary — its own terms say the opposite.** The adjudicator
   grepped Firecrawl's own documentation: `licensed intermediar` → **0 hits**, `robots.txt` → **0
   hits**. The premise is not merely unsupported; it is contradicted at source. **This is the load-
   bearing leg.** `[TESTIMONY, ADR §5, with the greps recorded]`
2. **`robots.txt` — strong evidence of owner intent, weaker as a bright line than commonly stated.**
   `au.seek.com/robots.txt` names **`anthropic-ai`** explicitly, grouped with `Bytespider`, `CCBot`,
   `Diffbot`, and disallows `*/job/`. The adjudicator's honest refinement: robots.txt does **not**, on
   its face, forbid the *search* URL the adapter requests — but it unambiguously closes `*/job/`, the
   postings themselves, which is precisely what the adapter ultimately obtains. `[TESTIMONY, ADR §3]`
3. **"Seek ToS clause 4(d)" — UNPROVEN, and the ADR gives it no weight.** The artifact
   `uat/reports/evidence/phase6/seek-tos-check.md` cited for clause 4(d) **does not exist**, and a
   grep for `automat`, `scrap`, `robot`, `written consent`, `4(d)` found nothing. The adjudicator
   marks it `[ASSUMED-PENDING-PROBE]` and rules **without relying on it**. `[TESTIMONY, ADR §6.2]`

**The brief given to me asserts leg 3 as established fact. It is not.** The refusal is nonetheless
correct and I endorse it on legs 1 and 2 plus the recorded 10/10 HTTP 403 probe result — but a
compliance position should not be recorded as resting on a clause nobody has read. Citing a ToS
clause from a non-existent artifact is the same epistemic error this run exists to eliminate, pointed
at a legal question instead of a technical one.

---

## 8. Verdict

# NOT-READY — BLOCKED-ON-ITEMS

This does not overrule, and is not in tension with, the binding ruling already on file
(`ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` §6): *"G-P is REFUSED while `AETHER_ADMIN_PASSWORD_HASH`
remains unrotated… This holds even after the full approved fix set is deployed and verified."* That
ADR controls the credential blocker. This verdict is broader.

### Blocking items, in required order

1. **[OPERATOR-GATED · CRITICAL]** Rotate `AETHER_ADMIN_PASSWORD_HASH` **and** `AETHER_CRON_PASSWORD`
   **together** — they currently share one value, so rotating one silently breaks scheduled discovery.
   No agent may choose or store this secret. **Additionally, and not yet tracked anywhere:** purge the
   credential from repository *history*, not just HEAD. `docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md`
   is a tracked file in a confirmed-public repo; deleting it now leaves it in the git history forever.
   Rotation is what actually closes this — file edits do not.
2. **[DATA + QUEUE PURGE · CRITICAL]** BLOCKER-002 is **larger than filed**. Correct the owner's
   `User.name` (still contaminated at 01:12Z), and purge/regenerate **all 3 contaminated pending
   approvals** — all of which are `type=application_submit`, i.e. one click from being sent to a real
   employer `[VERIFIED-FRESH #10/#11]`. The drafted code guard (`36d86c6`) prevents *new* contamination;
   it does nothing about the three already queued. **Do the data fix before the code fix.** Note also
   that the guard's rule (`probe`/`test`/`gap-`/8+ digits) matches **5 of 7** production `User.name`
   values — verify it will not deny cover letters to legitimate users before deploying it.
3. **[DEPLOY · BLOCKING EVERYTHING ABOVE]** Nothing is live. 11 unpushed commits; production running
   since 2026-07-30 12:27:09 UTC `[VERIFIED-FRESH #4/#5]`. Per GOV-011: no deploy of any BLOCKER-001
   change until the ADR-derived suite is green **and a reviewer who did not author the fix signs off**.
   Six of the eleven commits were self-directed without authorisation and one asserted closure of a
   security blocker it did not close — that history is reason to require the reviewer pass, not to
   waive it.
4. **[PRODUCT INTEGRITY · HIGH]** Resume tailoring must either gain the score-aware loop its UI
   implies, or stop implying it. Today: 0.0% movement in 7/7 runs, a 51-job corpus at avg 39.63 vs an
   85 target, and 0/72 interview conversion `[VERIFIED-FRESH #8/#9]`.
5. **[BUSINESS DECISION · HIGH]** ADV-ENT-001 (gate `/cover-letters/{id}/refine` like every other paid
   action) and ADV-ENT-002 (honour the advertised Free tier, or stop advertising and provisioning it).
   Both are open under GOV-011 and pre-existing ADR-MV-02.
6. **[COVERAGE · not a launch blocker, a confidence blocker]** **10 of 27 routes were never observed;
   3 more have incomplete passes; 8 were seen only through a paywall; no subscribed non-admin session
   exists anywhere in this run.** Priority order for the remaining sweep: `/dashboard/approvals` (the
   human gate protecting 3 contaminated sends), `/dashboard/cover-letters` (the BLOCKER-002 surface),
   `/dashboard/agents` (the entire model-selection feature, untested by anyone), `/signup` (first
   screen a customer sees), then email/interviews/offers/networking.
7. **[TEST BASELINE · must not be reported as green]** **Playwright: 40 pass / 12 fail, exit 1.** Of the
   12, **3 are known not to reproduce against production** (they target `127.0.0.1:3091`), 9 are
   attributed to harness/port/fixture drift `[TESTIMONY]`, and **1 — mobile approvals at 390×844 — is
   the one failure not explained by config drift and remains unadjudicated.** All 12 need individual
   real-vs-stale adjudication before G-N can close. pytest (1885/1885) and vitest (626/626) are
   genuinely clean; **the suite as a whole is not.**

### What is genuinely good, and should not be lost in the noise

The anti-fabrication architecture held under live adversarial conditions with **zero** exceptions,
including a correct refusal to bluff a keyword match. The server-side entitlement gate is competently
built — gate-before-work proven by differential probe, fail-closed by default, sync and async seams
both covered, constant-time secret compare, no bypass-by-omission. Honest-failure paths were honest
everywhere tested: quota denials, no-op tailoring (`costUsd: 0.0000` — not billed), 422 validation,
unauthenticated redirects, upstream `403` surfaced rather than swallowed. Job discovery degrades
truthfully rather than silently. The repo-wide grep for prohibited stub/placeholder patterns returned
**zero** hits across 432 matches inspected `[TESTIMONY]`. And this run caught **its own** monitoring
false-green (GOV-012) and **its own** unauthorised security-closure commit (GOV-011) — both by
controls that were load-bearing rather than ceremonial. That is a healthier signal about this
codebase's trajectory than any individual defect above is a bad one.

**But the honest bottom line is unchanged:** a public repo publishes a working production admin
credential; three contaminated documents sit one click from a real employer's inbox; the flagship AI
feature moves its own headline metric by zero; and none of the eleven commits written to address any
of it has reached a user. **NOT-READY.**

---

## Appendix — verification manifest for this review

| Probe | Method | Timestamp (UTC) |
|---|---|---|
| `GET /api/health` | curl | 2026-07-31T01:09:37Z |
| `GET /api/billing/plans` (unauth) | curl | 2026-07-31T01:09:37Z |
| `GET /api/admin/users` (unauth) → 401 | curl | 2026-07-31T01:09:37Z |
| `GET /api/agents` (unauth) → 401 | curl | 2026-07-31T01:09:37Z |
| Service start timestamps | `systemctl show` | 2026-07-31T01:10Z |
| Unpushed-commit count / `origin/main` head | `git log origin/main..HEAD` | 2026-07-31T01:14Z |
| Repo public visibility | GitHub REST, unauthenticated | 2026-07-31T01:13Z |
| `User` count / admin count | read-only SQL | 2026-07-31T01:11Z |
| `Job.atsScore` distribution (n/min/max/avg) | read-only SQL | 2026-07-31T01:11Z |
| `Application` submitted+total, `InterviewSchedule` | read-only SQL | 2026-07-31T01:11Z |
| `StoryEntry` count | read-only SQL | 2026-07-31T01:11Z |
| Owner `User.name` placeholder match | read-only SQL (boolean + length only; no PII printed) | 2026-07-31T01:12Z |
| Pending approvals by type; contaminated payload count | read-only SQL | 2026-07-31T01:13Z |
| Credential disclosure in tracked files | `git ls-files`, `git grep` | 2026-07-31T01:09Z |
| README internal link resolution | shell link check | 2026-07-31T01:13Z |

**Mutations:** none. Every probe in this review was read-only. No config was changed, no data written,
no service restarted, no commit, no push, no deploy. No secret value was printed at any point (the
owner's `User.name` was tested by boolean predicate and length only).

**Not done, and why:** I did not log in with the disclosed admin credential — the run forbids its use
for probes, and re-proving a live admin exploit adds no information beyond what GOV-011 already
records while adding real risk. BLOCKER-001's exploitability is therefore `[TESTIMONY]` from
`BLOCKER-admin-overpermission-verification.md` (23:28Z) and GOV-011 (00:35Z), reinforced to
near-certainty by `[VERIFIED-FRESH]` proof that the production binary has not changed since
2026-07-30 12:27:09 UTC.
