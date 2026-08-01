# GOLD-MASTER-V3/V4 — ADVERSARIAL PRODUCT REVIEW (Workstream A §3.3, gate G-A)

**Author:** `qa-adversary` sub-agent (opus tier), GOLD-MASTER-V4 Workstream A §3.3.
**Independence declaration:** I did not test, fix, review, deploy or author any of the work
assessed below. I wrote no production code and closed no finding other than gate G-A itself.
**Authored (UTC):** 2026-07-31T18:51Z–19:0xZ.
**Production under review:** `https://5cb5f0620.abacusai.cloud`
**Repo HEAD at review time:** `5c8da67484ba8e0fea0d190e6f41e94d657b55af`
("test(gm-v4): SSE contract amended per ADR-GMV4-002 (7/7); Culture Fit test strengthened to RED")
**Findings ledger snapshot:** `docs/delivery/MODELS-LIVE-GAPS.json`, mtime `2026-07-31T18:47:42Z`,
read `2026-07-31T18:50:36Z` — **64** findings tagged `run == "GOLD-MASTER-V4"** (the brief said 63;
the ledger is being written concurrently and grew by one, `GMV4-ats-007`, during this review).
**My own fresh-probe artifact:**
`uat/reports/evidence/gold-master-v3/adversarial/G-A-prod-probe-20260731T185102Z.txt`
**DocuGenerate PDF:** NOT generated. `DOCUGENERATE_API_KEY` is absent from the repo-root `.env`
(key-name probe, artifact above). §3.3 explicitly permits skipping the PDF when DocuGenerate is
CONDITIONALLY-CLOSED. This markdown is the sole deliverable.

### Epistemic legend (applies to every claim in this document)

| Tag | Meaning |
|---|---|
| `[VERIFIED]` | I opened the named artifact **this session** and the claim is in it. Artifact path + timestamp given. |
| `[INFERRED]` | Derived by reasoning over verified facts. Not sufficient to close anything. |
| `[UNVERIFIED]` | Asserted by a prior report, a filename, or a tester, and **not tied to an artifact I could open**. Not sufficient to close anything, and deliberately not laundered into a stronger tag. |

**Prior reports are testimony, not evidence.** The 39 GMV2/LAUNCH-READY/MODELS-LIVE claims in
`docs/delivery/GMV2-CLAIM-LEDGER.md` remain `UNVERIFIED-THIS-RUN` in this document except where a
specific artifact from this run re-proves them; §3 marks each one explicitly.

---

## 1. Executive summary — for the owner, not the engineer

**You should not onboard paying customers tomorrow. Aether is BLOCKED-ON-ITEMS.**

The honest position is narrower and more awkward than "the product is broken". Two things are true
at once:

1. **The AI is real.** I verified first-hand, from production API response bodies captured this run,
   that Aether makes genuine paid LLM calls, that two runs of the same feature produce genuinely
   different output at genuinely different cost, and that the anti-fabrication guard actively
   *refuses* to publish a cover letter it cannot support with the user's own evidence. This is not a
   demo wired to canned text. `[VERIFIED]`
2. **The number the product uses to tell the user "this is good" is not trustworthy today**, the fix
   for it is written but **has not been deployed**, and on the one real measurement taken this run the
   quality target was missed by roughly 39 points out of 85.

Beyond that, this campaign is **approximately 10% executed**. The run's own state file records 17 of
19 workstreams as `NOT-STARTED`, and its `last_deploy_sha` is `null`. `[VERIFIED —
docs/delivery/GOLD-MASTER-V3-STATE.json]` The evidence directories for deployment, server-log runtime
monitoring, and the Submission Agent are **all empty**. `[VERIFIED — my probe artifact, 18:51Z]`
Nothing repaired during this run has reached the site your customers would use.

**Top 5 blockers, in the order I would fix them:**

| # | Blocker | Why it matters to a paying customer | Ledger id(s) |
|---|---|---|---|
| **B1** | **The résumé quality score is an approximation presented as a measurement, and the target is missed by a wide margin.** Production scores resumes by counting shared words with the job ad, not by understanding meaning — the semantic model is not installed on the API server. On the one real run measured, the score moved **44.06% → 46.28%** after the loop exhausted **all 5** attempts against a target of **85**. The fix exists in the working tree; an independent reviewer FAILed it twice and Round 3 is required. | The customer is paying for "your resume is now an 85% match". They are being shown a number derived by a method the product does not disclose, and the underlying goal is not being reached. | `GMV4-ats-001`, `GMV4-ats-003`, `GMV4-ats-004`, `GMV4-ats-007`, `GMV4-resume-001` |
| **B2** | **Synthetic QA test data is still rendered on a live customer-facing screen.** An approval row whose own text reads `SYNTHETIC TEST DATA (models-live qa)` is visible on `/dashboard/approvals` today. It was deliberately retained so I could reproduce it. | A customer opening Approvals sees a fake item from a test campaign. Zero-tolerance under this run's own rules. | `GMV4-approvals-001` |
| **B3** | **Nothing fixed this run is live, and most of the run never started.** 17/19 workstreams `NOT-STARTED`; `last_deploy_sha: null`; `deploy/`, `runtime/` and `submission-agent/` evidence folders empty. | Every "fixed" status in the ledger describes the source tree, not the website. The gap between the two is the entire risk. | `GMV4-suites-002` (adjacent), process |
| **B4** | **The test suite is red and nobody knows by how much.** Baseline run 1: 36 failed / 9 errors, straddling a package install. Baseline run 2: 50 failed / 46 errors, taken while other agents were running tests against the same shared database. Both are contaminated. **G-N cannot be adjudicated — the genuine backend failure count is UNKNOWN.** | Without a trustworthy baseline you cannot tell a new regression from old noise, so "zero regression" cannot be claimed at all. | `GMV4-suites-001`, `GMV4-suites-002`, `GMV4-suites-003` |
| **B5** | **The production database password was exposed by this run and must be rotated.** The orchestrator echoed the full `DATABASE_URL` including the role password into a session transcript while verifying a deletion. Self-reported. | An operator action, not an engineering one, but it is a live credential exposure caused by the work itself. | `GMV4-secret-001` |

**Immediately behind the top five** (user-visible, all `[VERIFIED]` from artifacts this run):
drag-and-drop on the Applications board fires no request and moves nothing; the Jobs "submit
application" flow never renders a confirmed state and shows **0** applied badges after reload; a
second résumé tailoring run waits **300.8 s** behind a spinner and then fails; Story Bank's "create"
returns `201 Created` while **silently overwriting an existing story**; and `GET /api/stories?category=…`
ignores the category filter server-side.

**What I am *not* saying.** I am not saying the product is fraudulent, that the agents are fake, or
that the team's testers were dishonest. The per-screen testing I audited was, with one exception,
careful and self-critical — several testers filed findings *against their own screens* and one
withdrew its own earlier claim when first-hand evidence contradicted it. The exception is the
Approvals screen, which has **no machine evidence at all** (see §2).

---

## 2. Per-screen findings table

**Method.** 14 dashboard routes were tested by `screen-tester` agents in 4 batches on
2026-07-31 between 17:23Z and 18:44Z, all against production. **8 of 14 have a `REPORT.md`. 6 do not**
— a Write-tool restriction blocked those sub-agents from authoring report files (`GMV4-evidence-001`).
For those six I read the **raw JSON as the primary evidence** and I say so per row. One of the six,
`/dashboard/approvals`, has **no JSON at all** — only screenshots — and I have marked its verdict
accordingly rather than inheriting the tester's conclusions.

**Evidence-quality key:** **A** = REPORT.md + network/console/results JSON + screenshots ·
**B** = raw JSON + screenshots, no report (primary evidence is the JSON) ·
**C** = screenshots only, filenames assert conclusions no machine artifact corroborates.

| Screen (route) | Verdict | Ev. | Critical gaps (all `[VERIFIED]` unless tagged) | Evidence path |
|---|---|---|---|---|
| `/dashboard` (main) | **PASS (reduced depth)** | A | No defects found, but this was an explicitly time-boxed, lowest-priority pass: state-changing controls (Approve/Reject, Tailor & Apply) were **not** exercised. Market Pulse honestly says "not connected" rather than fabricating benchmarks. | `.../screens/dashboard-main/REPORT.md` + `results.json` (18:12–18:14Z) |
| `/dashboard/jobs` | **FAIL** | B | Tailor run polled **38×**, every poll `status:"processing"`, never reached a terminal state inside the capture. `POST /jobs/{id}/apply` returned 200 but the UI **never rendered a submitted state** (`submittedVisible:false`) and after reload `appliedBadgeAfterReload:0, cardsAfterReload:0`. Apply gate omits the linked-story count (`hasStoryCountMention:false`). Match-score slider set to 90 reads back `"0%"` and does not persist. Tailor button not found in batch 1. Cleanup FAILED — test application left in prod. 0 console errors, 0 page errors, 0 non-2xx across 195 captured requests. | `.../screens/dashboard-jobs/events-part1..4.json`, `network-part1..3a.json`, `scout-sources-availability-response.json` (17:23–17:36Z) |
| `/dashboard/applications` | **FAIL** | B | **Drag-and-drop does not work**: three attempts, `dndMoveNetwork: []`, `cardNowInReviewColumn:false`. The move that *does* work fires the **legacy** `POST /applications/{id}/move`, not the canonical `PATCH /applications/{id}/stage` (`GMV4-apps-001`). **Counts do not reconcile** — `sumStageCounts 51` vs `appsCount 49`; Submitted badge reads 45 while 25 cards render (`+20 more`). All 49 fit scores ≤ 50, so the "Match ≥ 85" filter yields an entirely empty board. Back-nav lands on `/dashboard`, board not visible. Illegal transitions honestly 422/409 with clear messages (one grammar defect: "a application"). | `.../screens/dashboard-applications/main-report-part1.json`, `part2/3b/4/5/6-report.json`, `dnd-synthetic-result.json`, `verify-twice-report.json` (17:24–17:36Z) |
| `/dashboard/approvals` | **NOT-VERIFIED (evidence insufficient)** | **C** | **23 PNGs, zero JSON, no REPORT.md.** All 23 files were written inside a **0.2-second** burst (17:38:04.483→.683), so their mtimes carry no information about when the browser actions happened. The screen's BLOCKER (`GMV4-approvals-001`, synthetic fixture rows live) and its BUG claim (forward-nav modal not restored) rest on **filenames and pixels**, with no network log, no console log, and no results JSON. The BLOCKER is independently corroborated by a **database** artifact (`PROD-DATA-INVENTORY.md` §3: `ApprovalRequest ccbe2e7518343e818809f8009`, payload `"SYNTHETIC TEST DATA (models-live qa)"`), so I accept the *finding* — but **not** on this screen's evidence. Separately: `GMV4-approvals-002` (zero auto-refresh) has no artifact I can open. | `.../screens/dashboard-approvals/*.png` (23 files) + `uat/reports/evidence/gold-master-v3/PROD-DATA-INVENTORY.md` |
| `/dashboard/resume` | **FAIL** | B | **The headline blocker.** Run 1: 263.3 s, `44.06% → 46.28%`, warning "stopped after 5 iteration(s) without reaching the target ATS score of 85. Best score achieved: 46.3/100". Run 2 back-to-back: **300.8 s** then `status:"failed"`, `error:"The AI service is temporarily unavailable."` Resume **version count stayed at 8** before, after run 1, after run 2 and after reload — two multi-minute runs produced no new version card. Export control is labelled "Download", wireframe says "Export PDF". No semantic-degradation disclosure anywhere in the UI. | `.../screens/dashboard-resume/results-2.json` (17:36:21–17:46Z), `results.json`, `downloaded-resume.pdf` |
| `/dashboard/cover-letters` | **PASS with 1 UNSURE** | B | Positive: fabrication guard **withheld** a letter rather than fabricate (`coverLetterUnavailable:true`, reason `['AI-driven','LLMs']`); a second, grounded run produced a real 307-word letter; PDF export produced a real 23 KB file. Defect: a >2000-char "Request Changes" instruction produced `POST …/refine` → `net::ERR_ABORTED` with **zero** network entries and no user-facing error (`GMV4-cover-001`, honestly filed as UNSURE and **not re-run with a bounded input** — still unresolved). | `.../screens/dashboard-cover-letters/results.json`, `requestfailed.json`, `exported-letter.pdf` (17:38–17:42Z) |
| `/dashboard/stories` | **FAIL** | B | **New, previously unfiled:** (a) submitting a duplicate story returns **`201 Created`** but the response body carries the **pre-existing story's id** (`c0a658fc48e4eb81c8c50e82b`) with a bumped `updatedAt` — a silent overwrite presented as a create; card count delta **0**, no duplicate warning shown. (b) `GET /api/stories?category=Leadership|Delivery|Technical|Risk%20%26%20Compliance` each return **all 37 stories unfiltered** — the server ignores the parameter; filtering is client-side only. (c) An adversarial payload (`<script>alert(1)</script>` title, ~330 chars, `<img src=x onerror=…>` in `action`) was stored raw with `201`, no sanitisation and no length limit. (d) Relevance score is **absent from both the UI and the API payload** (`GMV4-story-003`). (e) A test edit — story title now ends `"(updated)"` — was **left in production**. Story-extractor run was genuine and honest: `created:0`, `dropped:[8 titles]`, `model qwen/qwen3-coder-next`, `costUsd 0.001986`. | `.../screens/dashboard-stories/results.json`, `network-log.json` (17:38–17:41Z) |
| `/dashboard/agents` | **PASS with 3 spec gaps** | A | 22 agent cards render, all "Active"; Submission Agent card present. Run-history table exposes only Agent/Status/Started/Error and shows 20 rows — §14.5.5 requires last 10 **with** `jobs_submitted` / `jobs_skipped` / `ats_avg_delta` (`GMV4-agents-001`). No `submission_ats_threshold` / `submission_auto_approve` control exists (`GMV4-agents-002`). Idle refresh exceeds the ≤20 s requirement (`GMV4-agents-003`). Realtime is **polling, not SSE** — confirmed. 0 console errors, 0 page errors. | `.../screens/dashboard-agents/REPORT.md`, `results.json`, `network-log.json` (17:59–18:05Z) |
| `/dashboard/analytics` | **PASS** | A | Two positive verifications I accept: the canonical design-time funnel `847→412→156→23→4` is **absent** — live funnel is the account's real `52→48→2→0→0` (`GMV4-screens-001`); and CLS measured **0.0794**, so the §17.3 CLS-0.67 problem is already fixed (`GMV4-gsc-001`). Genuine gap: `interview_conversion_rate` is computed correctly and honestly at 0% but **never rendered** (`GMV4-analytics-002`, HIGH). | `.../screens/dashboard-analytics/REPORT.md`, `results.json` (18:05–18:08Z) |
| `/dashboard/email` | **FAIL (honesty gap)** | A | Both linked Gmail accounts are in `needs_reauth` and **the user cannot tell** — no visible warning (`GMV4-email-001`, HIGH). AI triage / analyse / draft-reply all genuinely fired with real model attribution and the draft was diffed against the test-suite fixture with **zero overlap** (non-fixture confirmed). A second synthetic `EmailThread` row (`cfc2cce71b52d38ffeff2db29`, subject `GOLD…`) is now in production and cannot be deleted through the UI (`GMV4-email-002`). | `.../screens/dashboard-email/REPORT.md`, `inbox.json`, `agent-runs-audit.json` (18:29–18:35Z) |
| `/dashboard/interviews` | **PASS** | A | Full CRUD exercised; empty / adversarial (script + unicode + long-string) / negative-duration submissions all handled. Calendar-claim dishonesty explicitly ruled out by full-text scan + source corroboration (`GMV4-cal-001` — the screen makes **no** calendar claim, which is the honest state given `calendarIntegration: False`). Interview-prep agent verified genuine and non-fixture via direct API run. | `.../screens/dashboard-interviews/REPORT.md`, `agent-run-1.json`, `agent-run-2.json` (18:24–18:27Z) |
| `/dashboard/networking` | **PASS** | A | Honest CRUD surface. Dishonest "Import from LinkedIn" label and dead "Review all drafts" button confirmed **already removed**. Adversarial submit correctly rejected server-side with 422 (the single console error in the entire 14-screen corpus, and it is the app behaving correctly). | `.../screens/dashboard-networking/REPORT.md`, `console.json` (18:40–18:44Z) |
| `/dashboard/offers` | **PASS** | A | Honest, complete small CRUD surface. Weights UI absent **by deliberate documented removal**, not defect (`GMV4-offers-001`, filed as a positive finding + a stale test). Negotiation coach confirmed template-only with zero network calls — i.e. it does not pretend to be AI. | `.../screens/dashboard-offers/REPORT.md` (18:3xZ) |
| `/dashboard/settings` | **PASS with 1 doc defect** | A | All three §10.5/§18.3 absence requirements confirmed (no Calendar status, no Feedback form, no bug-report link). Screen honestly discloses that auto-apply / approval-gate / threshold settings are not yet enforced. **No model/provider picker exists on this screen at all** — SCREEN-MATRIX claims `GET /agents/providers` here; it is wrong (`ML-SETTINGS-002`). | `.../screens/dashboard-settings/REPORT.md`, `results.json` (18:2xZ) |

### 2b. Routes NOT covered by the 14-screen pass

| Route(s) | Status |
|---|---|
| `/admin`, `/admin/users`, `/admin/audit-log`, `/admin/health`, `/admin/settings`, `/admin/spend` | **UNVERIFIED — content never rendered.** The only working account is non-admin; all 6 redirect to `/dashboard`. `[VERIFIED — browser/sweep-results.json finalUrl]`. `GMV4-admin-002`, CONDITIONALLY-CLOSED-PENDING-OPERATOR. |
| `/admin/users/[id]` | **NOT SWEPT AT ALL** — no user-id link discoverable from the non-admin session. `[VERIFIED — sweep-results.json dynamicUserRouteNote]` |
| `/admin-login` | Loaded, 200, no redirect. Content not exercised. |
| `/login`, `/signup`, `/pricing`, `/terms`, `/privacy-policy`, `/forgot-password`, `/` | 200 each on my own fresh probe, 18:51Z. Only smoke-level coverage. |
| `agent-monitor.html` wireframe | **No route exists.** `GMV4-wireframe-001`. |

### 2c. Adversarial audit of the testers themselves

Per the brief, a review that only indicts the codebase is not adversarial. Auditing the testers'
own artifacts against what they claimed:

1. **Two Jobs-screen screenshot filenames assert outcomes their own machine evidence contradicts.**
   `29-submit-confirmed.png` sits alongside `"submitted-state","submittedVisible":false,"submittedText":null`;
   `17-tailor-run1-step2.png` sits alongside a 90 s `waitForSelector('[data-testid="apply-step2"]')`
   timeout. `[VERIFIED — events-part2.json, events-part3a.json]` Filenames are not evidence.
2. **`GMV4-ats-004` cites the wrong artifact.** Its `evidence` field points at
   `screens/dashboard-resume/results.json`, which does **not** contain `44.06`/`46.28` — that file
   ends `"status":"ERROR"` on a 90 s timeout. The numbers are in `results-2.json`.
   `[VERIFIED — grep, both files, this session]` The finding is true; its citation is not.
3. **Four findings are marked `VERIFIED-CLOSED` by agents with no closure authority.**
   `GMV4-gsc-001`, `GMV4-screens-001`, `GMV4-cal-001` are all `verifiedBy: "screen-tester batch3/4"`
   — i.e. closed by the same role that opened them — and `GMV4-sse-004` is
   `verifiedBy: "test-author … (ADR-GMV4-002 amendment)"`, which is the **author of the amendment
   closing its own work**. §24 assigns closure to `qa-adversary`; §0.4 forbids self-approval.
   `[VERIFIED — MODELS-LIVE-GAPS.json, 18:47Z snapshot]` I am not reversing their substance (the
   three screen findings are positive verifications I independently agree with, per §2 above); I am
   recording that **the closure act was performed by the wrong party** and filing it (see §9, ADV-004).
4. **The Approvals screen produced no machine evidence** and its conclusions were nonetheless carried
   into the ledger as a BLOCKER and a BUG. The BLOCKER survives only because a *different* artifact
   (the DB inventory) independently proves it.
5. **Good faith observed, and worth recording.** `GMV4-analytics-001` was **withdrawn by its own
   author** after first-hand probing contradicted it; `GMV4-jobs-003` was **corrected** by later
   first-hand evidence; `GMV4-tailor-001` was **narrowed** from "computation broken" to "plumbing".
   Testers filing against themselves is the behaviour this process is supposed to produce.

---

## 3. Feature completeness matrix — README + REQUIREMENTS-TRACEABILITY vs actual production

Sources: `README.md` (HEAD `5c8da67`), `docs/delivery/REQUIREMENTS-TRACEABILITY-PRODUCTION.md`
(dated **2026-07-12** — stale by three campaigns; its "DEFERRED SCREENS" table lists five screens
that have shipped, and I treat that table as **wrong**, not as a requirement),
`docs/delivery/GOLD-MASTER-V3-FEATURE-COMPLETENESS-MATRIX.md` (28 rows, code-presence only),
`docs/delivery/GMV2-CLAIM-LEDGER.md` (39 claims).

`PROD` column = state of the **deployed site**, which is HEAD-minus-the-uncommitted-tree, because
`last_deploy_sha` is `null`.

| # | Feature (claim source) | Claimed state | Actual production state | Tag |
|---|---|---|---|---|
| 1 | Job discovery, multi-source, honest per-source status (README:71, REQ-3) | "Live: 33 jobs / 5 sources" | **Works and is honest.** `GET /agents/scout/sources/availability` returns per-source truth: `seek → available:false, "compliance-gated (ADR-P6-SEEK)"`; `indeed`/`linkedin → false, "no live discovery implementation (fixture-only legacy adapter)"`; `wellfound → blocked, "HTTP Error 403: Forbidden"`. Jobs table holds **52** rows, README says 33. Last sweep persisted **0** new jobs across all sources. | `[VERIFIED]` |
| 2 | Fit scoring, deterministic, zero-token (README:72) | Live | Renders; 49 scores observed, **max 50**, none ≥85. Zero-token claim not re-probed against AgentRun cost rows. | `[VERIFIED]` render / `[UNVERIFIED]` zero-cost |
| 3 | Résumé tailoring, content-only + entailment guard (README:73, REQ-4) | "Live-verified, zero fabrication survivors" | **Guard demonstrably active**: run body carries a `rejected:[…]` array of 5 proposed bullets the guard refused. Tailoring itself completes but is slow (263 s) and the 2nd concurrent run fails after 300 s. | `[VERIFIED]` |
| 4 | **Score-aware TailoringLoop, target ATS ≥85** (GMV2 W-C; `CL-B03`, `CL-F03`, `CL-F06`) | GMV2: "CODE-COMPLETE AND DEPLOYED, NOT LIVE-VERIFIED" | **NOW LIVE-VERIFIED — AND FAILING ITS TARGET.** Loop runs, iterates, stops at 5, emits an honest warning naming the target and the best score. `44.06 → 46.28`. | `[VERIFIED]` — this re-proves `CL-B03`/`CL-F03` as *present* and refutes any implication the target is met |
| 5 | Cover letters, evidence-grounded, corrective loop (README:74, REQ-7) | Live | **Works, and refuses honestly.** Two production runs, different cost/tokens/length; one withheld by the fabrication guard. | `[VERIFIED]` |
| 6 | Approval gate on every outbound action (README:75, REQ-8) | Live | Approval rows are created (`approval_id` returned on the cover-letter run). Screen itself NOT-VERIFIED (§2). `submission` is **not** in `_APPROVAL_GATED` (`GMV4-submission-001`). | `[VERIFIED]` backend / `[UNVERIFIED]` screen |
| 7 | Applications tracker, 8-stage kanban, canonical stage-move (README:75, REQ-6; `CL-B06`, `CL-F04`) | GMV2: "DEPLOYED, not independently re-verified live" | **Re-verified and PARTIALLY REFUTED.** The canonical `PATCH …/stage` is never what the UI fires — the shipped client uses legacy `POST …/move`. Drag-and-drop fires nothing. Counts do not reconcile (51 vs 49; 45 vs 25). Illegal transitions correctly 422/409. | `[VERIFIED]` |
| 8 | Billing: 4 tiers, atomic reserve-before-run, honest 429 (README:76) | "pending operator Stripe keys" | `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are **both present** in `.env` (key-name probe; values never read). Whether they are test-mode or live-mode is **unknown**. No purchase was attempted. | `[VERIFIED]` presence / `[UNVERIFIED]` mode + round-trip |
| 9 | Admin panel (README:77) | "pending operator admin credential" | Routes exist; **no admin content rendered this run** — all 6 redirect for the non-admin account. `AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` are **present** in `.env`. `admin`/`admin123` now returns **401**, which *refutes* `CL-D07`/`CL-A01`'s reachability claim as of today. | `[VERIFIED]` 401 + redirects / `[UNVERIFIED]` panel behaviour |
| 10 | Multi-Gmail inbox (README:50) | "pending a 2nd Gmail consent" | Two accounts linked, **both `needs_reauth`, invisible to the user**. Genuinely human-gated to fix; the *silence* is not. | `[VERIFIED]` |
| 11 | Dual-mode Anthropic credential (README:51) | "Live-verified" | Not probed this run. | `[UNVERIFIED]` |
| 12 | "Connect with Anthropic (subscription)" OAuth (README:52; `CL-C04`) | "Live: real authorize URL + exchange/refresh verified" | Not probed this run. `AnthropicOAuthToken` table holds 1 row. | `[UNVERIFIED]` |
| 13 | Per-agent live OpenRouter model picker, 333 models (README:53; `CL-C01`) | "Live: fresh pull returned 333 models (2026-07-24)" | **Not re-sampled this run.** No catalog pull, no selection sweep, no run sweep in this run's evidence tree. The count is a moving target by design. | `[UNVERIFIED]` |
| 13b | No silent model substitution (README:127, `ADR-ML-3`; `CL-C05`) | "proven live" | **Not re-proved this run.** However, every production run body I opened records the model actually used (`deepseek/deepseek-v4-pro`, `qwen/qwen3-coder-next`) plus a `billingAudit` block — the *mechanism* for detecting substitution is present and populated. | `[UNVERIFIED]` claim / `[VERIFIED]` mechanism |
| 14 | Async background generation, ARQ/Redis (README:54) | "Live, 20/20 soak, 0 503s" | **Live and observable**: `POST /agents/tailor/run → 202 {"status":"enqueued"}` then `GET /agents/jobs/{id}` polling, with terminal `completed`/`failed` states. One `failed` observed in 2 runs. | `[VERIFIED]` present / `[UNVERIFIED]` soak claim |
| 15 | Story Bank: extraction, STAR form, paraphrase dedup (REQ-5; `CL-B05`, `CL-F01`, `CL-F02`) | GMV2: "PARTIALLY LANDED, 34/36 dups not purged" | **Re-verified with fresh DB evidence and PARTLY REFUTED, PARTLY CONFIRMED.** Exact duplicates: **0 of 37** (byte-dedup works, all `contentHash` distinct). Near-duplicates: **5 clusters covering 16/37 rows (43%)** — paraphrase dedup does **not** work. `merge_duplicate_stories` has **zero production call sites** (`GMV4-story-002`). Relevance score never reaches the UI (`GMV4-story-003`) and is absent from the API payload. **Plus the new create-overwrites-existing defect (§2).** | `[VERIFIED]` |
| 16 | Analytics: funnel, ATS distribution, agent ROI, conversion, market pulse (REQ-10) | Confirmed | All render on real data. `interview_conversion_rate` computed honestly, **never displayed**. | `[VERIFIED]` |
| 17–20 | Interview Center, Networking, Offers, Settings | REQUIREMENTS-TRACEABILITY says "DEFERRED" | **That document is stale.** All four are built, wired and passed this run's screen tests. | `[VERIFIED]` |
| 21 | Mobile dashboard / mobile approval | Split: dashboard VERIFIED, approval deferred | Two mobile Approvals screenshots exist; **no machine evidence**. | `[UNVERIFIED]` |
| 22 | **Agent Monitor screen** | README lists it among 17 screens | **DOES NOT EXIST.** No route. `GMV4-wireframe-001`. | `[VERIFIED]` absent |
| 23 | Agent counts ("8 agents actually execute"; "AgentConfig holds 22 keys") | README:103,116 | **README is wrong on both.** `/dashboard/agents` renders **22** active cards; the `AgentConfig` **table** holds **17** rows. | `[VERIFIED]` |
| 24 | 22-card agent build-out (wave-4) | "5 agents LIVE-VERIFIED" (prior run) | 22 cards render "Active". Individual agent behaviour verified this run for: tailor, coverLetter, storyExtractor, emailAgent, interviewPrep. The rest: not exercised. | `[VERIFIED]` for 5 / `[UNVERIFIED]` for 17 |
| 25 | Scheduling agent — no calendar (ADR-AG-1) | `calendarIntegration: False` always | Honest: Interviews screen makes **no** calendar claim. | `[VERIFIED]` |
| 26 | **SSE / realtime streaming** (`CL-F07`, `CL-B09`) | Consistently documented as ABSENT | Still absent in production. Realtime is polling (~20 s). An SSE module now exists **uncommitted** in the tree (`apps/api/app/services/agent_run_stream.py`) — not deployed, and its consumer cannot send an auth header (`GMV4-sse-003`). | `[VERIFIED]` |
| 27 | **Submission Agent** — autonomous executor (§14, G-SUB) | Matrix: "fully buildable as promised" | **It is a tracking/gate agent, by its own docstring — no browser automation, no form filling.** `GMV4-submission-002`, BLOCKER, `OPEN`. `submission-agent/` evidence dir is **empty**. | `[VERIFIED]` |
| 28 | Route/screen counts ("17 screens", "28 live app routes") | README:150-151 | 17 wireframes correct. Route count is **29**, README says 28, SCREEN-MATRIX header says 32 while its own table lists 30 rows. README's cited evidence path does not exist. `GMV4-readme-001`. | `[VERIFIED]` |

### 3b. Status of the 39 GMV2 claims — stated plainly

`docs/delivery/GMV2-CLAIM-LEDGER.md` opens every row at `UNVERIFIED-THIS-RUN` **by rule**. As of this
review that is still the correct status for **31 of 39**. This run produced fresh evidence bearing on
only eight:

| Claim | Effect of this run's fresh evidence |
|---|---|
| `CL-A01` / `CL-D07` (`admin`/`admin123` reaches an `isAdmin` account) | **REFUTED as of today** — the credential returns `401 {"detail":"Invalid email or password"}`. `[VERIFIED — browser/BASELINE-SWEEP-AUTH.md, 17:14Z]` The *hash-identity* half is still unprobed. |
| `CL-B03` / `CL-F03` (TailoringLoop deployed, not live-verified) | **NOW LIVE-VERIFIED as present** — and simultaneously shown to miss its target. |
| `CL-B05` / `CL-F02` (story dedup partial) | **SPLIT**: exact-duplicate half **confirmed working** (0/37); paraphrase half **confirmed not working** (16/37). |
| `CL-B06` / `CL-F04` (canonical stage-move deployed) | **PARTIALLY REFUTED** — canonical endpoint exists but the shipped UI does not use it. |
| `CL-B08` (apply modal 3/5 fields) | **CONFIRMED** — story count still absent. |
| `CL-B09` (no SSE, 6 screens without auto-refresh) | **CONFIRMED** — polling only. |
| `CL-E01`/`CL-E04` (Seek off, honest label) | **CONFIRMED** — `AETHER_ENABLE_SEEK` absent from `.env`; availability endpoint returns the compliance reason. `[VERIFIED]` |
| `CL-G01`/`CL-G02` (route-count drift) | Already fresh-verified by the scout; unchanged. |

**Everything else in that ledger — including all seven MODELS-LIVE model-catalog claims (`CL-C01`…`CL-C07`),
the entire LAUNCH-READY §D block, the NUL-byte remediation block (`CL-A05`/`CL-A06`), and the "0 OPEN
findings" declarations — remains `UNVERIFIED-THIS-RUN`.** No artifact in this run's evidence tree
re-proves any of them. They must not be counted as closed.

---

## 4. AI agent quality assessment

### 4.1 The AI is genuine — this is the strongest positive finding of the run

I treated "is this actually an LLM, or a dressed-up fixture?" as the null hypothesis to be disproved,
and it is disproved on four independent axes, all from **production response bodies** captured
2026-07-31:

| Axis | Evidence |
|---|---|
| **Output varies run-to-run** | Two cover-letter runs on the same job: **258 words** vs **307 words**, different opening dates, different body. `[VERIFIED — dashboard-cover-letters/results.json]` |
| **Real, varying per-run cost** | Cover letter A `costUsd 0.009634` (`tokensIn 19442 / tokensOut 1352`); cover letter B `costUsd 0.006679` (`13597 / 878`); tailoring run `costUsd 0.043056`; story extraction `costUsd 0.001986`. Fixtures do not bill. `[VERIFIED]` |
| **Named model + billing audit on every run** | `deepseek/deepseek-v4-pro`, `qwen/qwen3-coder-next`, each with `billingAudit: {authMode:"api_key", provider:"openrouter", quotaPath:"metered_api", credentialSource:"database"}`. `[VERIFIED]` |
| **The fabrication guard actively refuses** | Cover-letter run A returned `coverLetterUnavailable: true`, `reason: "['AI-driven', 'LLMs']"`, and the honest user-facing message *"An auto-generated cover letter couldn't be produced without unverifiable wording, so it was withheld."* Tailoring run 1 returned a `rejected: […]` array of five proposed bullets the entailment pass reverted. Story extraction returned `created: 0` with `dropped: [8 titles]`. **Three different agents each chose to produce nothing rather than produce something unsupported.** `[VERIFIED]` |

A product that fabricates would not withhold. This behaviour should be protected in any future
refactor, and it is worth saying to the owner directly: the guard is the most valuable thing in the
codebase.

### 4.2 Tailoring loop convergence — the target is not met, by a wide margin

`[VERIFIED — uat/reports/evidence/gold-master-v3/screens/dashboard-resume/results-2.json,
run 2026-07-31T17:36:26Z–17:40:48Z]`

```
Before: 44.06%  →  After: 46.28%      (+2.22 points)
warning: "Tailoring stopped after 5 iteration(s) without reaching the target ATS score
          of 85. Best score achieved: 46.3/100. Please review this resume manually
          before submitting."
model: deepseek/deepseek-v4-pro   costUsd: 0.043056   changes: 1
```

Three things follow, and they must not be collapsed into one another:

1. **The loop works mechanically.** It iterates, it stops at `MAX_ITERATIONS = 5`, and it emits a
   warning that names the target and the best achieved score. This is honest engineering. `CL-B03`
   is re-proved *as a mechanism*.
2. **The target is missed by ~39 points.** `[VERIFIED]`
3. **This measurement was taken with the OLD token-overlap scorer and MUST be re-measured after the
   semantic fix deploys.** The size of the gap is therefore **not final**. It could shrink
   substantially, or the true semantic score could be lower. Anyone quoting "44 → 46" as the
   post-fix number would be laundering a pre-fix measurement. `[VERIFIED — the fix is uncommitted;
   `last_deploy_sha: null`]`

Two supporting defects make the loop worse than the number suggests: the run takes **163–263 s**
behind a **static spinner with no elapsed time or step feedback** (`GMV4-jobs-001`), and a
back-to-back second run waits **300.8 s** and then fails with *"The AI service is temporarily
unavailable"* (`GMV4-resume-002`). `[VERIFIED — the failure is in the API job body:
`{"status":"failed","error":"The AI service is temporarily unavailable. Please try again in a moment."}`]`.
I note the UI-layer half of that finding — whether the error was actually *shown* — is **not**
established by the artifact: the captured `tailor_run2_state` block has no error field at all.

### 4.3 ATS scoring accuracy — an approximation presented as a measurement

`[VERIFIED — uat/reports/evidence/gold-master-v3/services/SERVICE-REGISTRY.md, and
apps/api/app/services/ats_engine.py:208-213]`

Production computes "semantic similarity" as `100 × |JD_tokens ∩ resume_tokens| / |JD_tokens|` —
shared-word counting — because `sentence-transformers` is not importable in the API environment and
`all-MiniLM-L6-v2` is not cached. When even that fails, a **neutral placeholder of 50.0** is
substituted.

The remediation is **in the working tree and has FAILED independent review twice**:

- Round 1 review: **FAIL** — engine internals correct, but *no consumer checked `semantic_path`*, so
  the placeholder leaked outward and was consumed as a real measurement at four call sites, including
  the loop's own convergence check — *an automated decision made off a fabricated number*.
- Round 2 review (`uat/reports/evidence/gold-master-v4/suites/GMV4-ats-002-round2-adversarial-review-20260731T183940Z.md`,
  **2026-07-31T18:39:40Z**): **FAIL. Round 3 required.** Two live leak sites remain — the Jobs
  insights radar/risk panel (`culture_fit`, `north_star`, "Industry Match", and the
  "X% semantic overlap" narrative are all still computed unconditionally from the placeholder, and
  `jobs/page.tsx` never declares the `semanticPath`/`semanticDegraded` fields the backend now emits)
  and the résumé conversion-impact panel. The reviewer additionally flags that
  `ATSScore.semantic_path`'s default was changed from `"degraded"` to `None` — **fail-open on the one
  axis this workstream exists to protect** — "adopted substantially to keep pre-existing tests green,
  which is the reasoning §0.5 forbids." `[VERIFIED]`
- A test for the remaining culture-fit leak was **strengthened to RED at 18:45:37Z** and is red now.
  `[VERIFIED — GMV4-ats-002-culturefit-strengthened-RED-20260731T184537Z.txt; git HEAD subject]`

A second, compounding defect: **the existing test suite encoded the bug as correct behaviour** —
three tests asserted the token-overlap result (`GMV4-ats-002`). Green tests were, on this axis,
evidence of nothing.

**User-visible consequence today:** no degradation disclosure anywhere in the UI (`GMV4-resume-001`),
and the "Estimated interview conversion improvement +0.1%" figure shown to the user is derived from
the same contaminated number.

### 4.4 Story dedup and relevance

`[VERIFIED — uat/reports/evidence/gold-master-v3/PROD-DATA-INVENTORY.md §5, psql, 17:49:41Z]`
37 stories · **0 exact duplicates** (all `contentHash` distinct, 0 NULL) · **5 near-duplicate
clusters covering 16 rows = 43%** ("ANZ core banking transformation" ×5, "JIRA analytics dashboard"
×5, and three ×2 clusters). Byte-dedup works; paraphrase dedup does not, and its merge function has
zero production call sites. Relevance score reaches neither the API payload nor the UI. Plus the new
create-overwrites-existing defect in §2. **G-E is not met.**

### 4.5 Seek sourcing — REFUSED-ON-COMPLIANCE, and that is the correct answer

**W-D is not "done" and it is not "failed". It is deliberately, defensibly REFUSED.**

An independent `risk-officer` (opus tier) re-derived the question first-hand — Seek ToS, Seek
robots.txt, WebScraping.AI AUP, Firecrawl AUP, each with URL and retrieval timestamp — explicitly
declining to treat the prior refusals as binding, and explicitly looking for a vendor licence that
would let it approve. `docs/delivery/ADR-SEEK-V3.md`, **STATUS: REFUSED**, 2026-07-31T17:26:18Z.
`[VERIFIED]`

The grounds: Seek ToS **clause 7(d)** categorically prohibits automated collection without prior
written consent; **clause 9(b)/9(d)** make circumvention independently sanctionable; WebScraping.AI's
own §4.4/§6.2 place a *false-authorization warranty* on the customer with §13 indemnity, so routing
through the vendor **adds** a second breach rather than curing the first. No consent, no licence, no
credential.

**Verification that the refusal is being honoured:** `AETHER_ENABLE_SEEK` is **absent** from the
repo-root `.env` `[VERIFIED — key-name probe, 18:52Z]`, and the live availability endpoint returns
`{"source":"seek","available":false,"reason":"compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping;
enable only via AETHER_ENABLE_SEEK"}` `[VERIFIED]`.

**G-D as written ("Seek returning real listings") cannot close and should not.** It should be
restated as a compliance gate: *pass = Seek verifiably OFF, honest UI, licensed-source volume
maintained*. The legitimate remaining work in W-D is `GMV4-seek-003`: surface the backend `reason`
string to the user so the disabled state is **explained**, not merely shown. The correct answer to
"we need more Australian jobs" is the **Adzuna AU credential** (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`,
absent from `.env` `[VERIFIED]`), which the risk-officer pre-approved in principle.

### 4.6 Realtime

Not SSE. Polling at ~20 s, measured on three screens. An SSE module exists uncommitted; the agent
pipeline does not journal 4 of the 6 progress steps §14.5.5 requires, so those events have no real
backing (`GMV4-sse-002`), and the browser `EventSource` API cannot send the `Authorization: Bearer`
header this app authenticates with (`GMV4-sse-003`). **G-I is not met.**

---

## 5. Service integration status — all 9 services

Source: `uat/reports/evidence/gold-master-v3/services/SERVICE-REGISTRY.md` (probed 2026-07-31),
re-checked by my own key-name probe at 18:52Z (values never read, never printed).

| # | Service | Status | Exact operator step |
|---|---|---|---|
| 1 | **GitHub** | **LIVE** | — (token auto-discovered via IMDS) |
| 2 | **DocuGenerate** | **CONDITIONALLY-CLOSED** | Obtain an API key from the DocuGenerate dashboard; add `DOCUGENERATE_API_KEY=…` to repo-root `.env`; restart `aether-api`. **Consequence today: no PDF export from Resume/Cover-Letter Studio via DocuGenerate, and no PDF version of this report. G-DG cannot close.** |
| 3a | **Google Cloud (GCS)** | **CONDITIONALLY-CLOSED** | Add a service-account JSON path as `GOOGLE_APPLICATION_CREDENTIALS=…` to `.env` — **only if** you prefer GCS over the Abacus S3 bucket, which is already working. Not required. |
| 3b | **Evidence store (Abacus S3)** | **LIVE** | — (`aws s3 ls` succeeds via IMDS) |
| 4 | **Google Search Console** | **CONDITIONALLY-CLOSED** | Create a service account with Search Console permission on the property; add `GSC_SERVICE_ACCOUNT_JSON=/path/to/key.json` to `.env`. **G-GSC cannot close** (sitemap submission unverifiable). |
| 5 | **Hugging Face** | **CONDITIONALLY-CLOSED** | Create a token at huggingface.co/settings/tokens; add `HF_TOKEN=…` to `.env`. **Note the nuance:** §25 of the execution prompt asserts `HF_TOKEN` is "present (or auto-discovered)"; it is **not** — the registry and my probe both find it absent. The semantic-scoring fix works around this with a **local** model cache, so HF is only needed for the Inference-API fallback path. **G-HF is therefore closeable without this credential, but the HF Inference path itself is not.** |
| 6 | **WebScraping.AI** | **CONDITIONALLY-CLOSED — and should stay closed** | `WEBSCRAPING_AI_API_KEY=…`. **Do not add this for the Seek use case.** ADR-SEEK-V3 refuses it on the vendor's own §4.4/§6.2/§13 terms. Adding the key does not make the Seek path permissible. |
| 7 | **Google Forms** | **CONDITIONALLY-CLOSED** | Enable the Forms API in Google Cloud Console; add `GOOGLE_FORMS_API_KEY=…` to `.env`. **G-GF cannot close** (no feedback button, no bug link — both confirmed absent from Settings). |
| 8 | **Gmail + Calendar OAuth** | **LIVE (client) / DEGRADED (user tokens)** | Client id+secret are present. **Two operator actions:** (a) add the `https://www.googleapis.com/auth/calendar.events` scope to the OAuth client in Google Cloud Console and re-consent in Settings → Connect Google — the scope is **not** in `GOOGLE_SCOPES` (`google_oauth.py:54-61`); (b) **both existing Gmail accounts are in `needs_reauth` right now and the UI does not say so** — re-consent, and fix the silence (`GMV4-email-001`). |
| 9 | **YouTube Data** | **CONDITIONALLY-CLOSED** | Create an API key in Google Cloud Console with YouTube Data API v3 enabled; add `YOUTUBE_DATA_API_KEY=…` to `.env`. **G-YT cannot close.** |

**Non-gated core (must be live, and is):** Abacus LLM **LIVE**, OpenRouter **LIVE** (and demonstrably
serving production runs), Firecrawl **LIVE**.

**Two service-registry defects I found:** the registry's own "PRODUCTION READINESS CHECKLIST" marks
ATS semantic scoring `⚠ DEGRADED … (non-blocking)` — it is **blocking**, per three BLOCKER findings;
and the registry pre-dates the ADR-SEEK-V3 ruling, so its WebScraping.AI operator step reads as a
neutral option rather than a refused path.

---

## 6. Runtime health summary

### 6.1 Browser-side — clean, and I checked rather than accepted it

I read every console/pageerror/requestfailed artifact across all 14 screens myself.
`[VERIFIED — file-size and content sweep, this session]`

- **Console errors across all 14 screens: 4 total.** One `422` on Networking (the server correctly
  rejecting an adversarial submit — the app behaving well) and three self-inflicted on Applications
  (two `422`, one `409`) from the tester's own deliberate illegal-transition API probes.
- **Uncaught page errors: 0.** Every `pageerrors*.json` in the corpus is literally `[]`.
- **Failed requests:** all `net::ERR_ABORTED`, and all but one are Next.js RSC prefetches or font
  fetches cancelled by navigation — benign. **The exception matters:**
  `POST /api/cover-letters/{id}/refine → net::ERR_ABORTED` with no response and no user-facing error
  (`GMV4-cover-001`, still UNSURE, never re-run with a bounded input).
- **Baseline authenticated sweep (17:14–17:16Z, 27 routes):** all 27 `mainDocStatus 200`,
  `consoleErrorCount 0`, `badResponseCount 0`. The only 2 console errors in the whole sweep are the
  two deliberate `401`s from credential discovery on `/login`.
- **My own fresh unauthenticated probe (18:51Z):** `/api/health → {"status":"ok","version":"0.2.0"}`;
  7 public routes 200; `GET /api/agents → 401`; `GET /api/admin/users → 401`. Auth guards hold.

### 6.2 Server-side — NO EVIDENCE EXISTS, AND THAT IS ITSELF A FINDING

`uat/reports/evidence/gold-master-v3/runtime/` is **empty** (0 files). `[VERIFIED — 18:51Z]` §23
mandates an always-on `runtime-monitor` tailing `journalctl` for `aether-api`/`web`/`worker`
throughout the run; the state file records the monitor as "armed" at Step 4, but **it filed no
artifact**.

Therefore:
- **I cannot make any claim about server-log errors, tracebacks or 5xx counts during this session.**
  `[UNVERIFIED]` — and I will not infer "clean" from silence, which is exactly the error that produced
  VIOL-001.
- **G-M (≥60 min monitored window, zero server errors, zero 5xx) has no evidence whatsoever and
  cannot be adjudicated.**
- The only server-side signal available is indirect: across ~400 captured production requests in the
  screen corpus, **zero 5xx responses** were observed, and one application-level `failed` job
  (`"The AI service is temporarily unavailable"`) which was returned as a well-formed 200 poll body.

---

## 7. Subscription-readiness assessment

| Question | Answer |
|---|---|
| Are Stripe keys configured? | **Yes.** `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are both present in the repo-root `.env`. `[VERIFIED — key-name probe 18:52Z; values never read]` This **contradicts** README's "pending operator Stripe keys" and §25's framing. |
| Test-mode or live-mode? | **UNKNOWN.** `[UNVERIFIED]` — determining this requires reading the key prefix, which I will not do. Two prior reports already disagree on this point; an operator should resolve it in one glance. |
| Has a real payment round-trip been proven? | **No.** No checkout, webhook or portal action was attempted this run. `[UNVERIFIED]` — remains the legitimate §25 human-gated item (a human must click "pay"). |
| Billing plumbing present? | Yes — `Plan` (4 rows), `Subscription` (15 rows), `StripeEvent` (8 rows), `UsageQuota` (15 rows) exist in production, and every LLM run body carries a `billingAudit` block naming provider, auth mode and quota path. `[VERIFIED]` |
| **How many real paying customers have data in production today?** | **ZERO.** `[VERIFIED — PROD-DATA-INVENTORY.md §4, psql COUNT(*) FILTER, 17:49:41Z]` |

**This last point reframes everything above and deserves to be stated plainly.** Every single row of
user-generated content in production — 3,663 AgentRun, 230 EmailThread, 196 BackgroundJob, 112
ApprovalRequest, 84 Application, 77 Resume, 52 Job, 37 StoryEntry — belongs to **one account**
(`c6c8d0163d973a8048e7e33b8`, the operator's own cron/test identity). The `User` table holds 15 rows:
that one account plus **14 empty leftover QA signup shells** from prior campaigns.

Two consequences, and they pull in opposite directions:

1. **The blast radius today is zero.** The synthetic approval row (B2) is being shown to the
   *operator's own test account*, not to a customer. No customer data can be cross-contaminated
   because no customer data exists. Cleanup is safe.
2. **Nothing has been proven at multi-tenant scale.** Every "it works in production" claim in this
   document was established on a single, long-lived, data-rich account. Tenant isolation, cold-start
   empty states, first-run onboarding, and quota enforcement against a *fresh paying user* are
   **UNVERIFIED**. `GMV4-schema-001` (only 8 of 26 user-referencing tables declare
   `ON DELETE CASCADE`) is a latent multi-tenant hazard that has never been exercised because there
   has never been a second tenant to delete.

**Subscription readiness verdict: NOT READY.** Not because the billing code is wrong — it looks
present and instrumented — but because the paid experience has never been exercised by a paying
identity, and the product currently ships blockers B1 and B2 that a first paying user would meet
within minutes.

---

## 8. Verdict

# BLOCKED-ON-ITEMS

Not READY, and not NOT-READY-in-principle — the architecture is sound, the AI is genuine, and most
screens are honest. It is blocked on a specific, enumerable list.

### 8.1 Must be cleared before any paying customer is onboarded

| # | Item | Ledger id | Current state |
|---|---|---|---|
| 1 | Semantic ATS scoring active in production **and** every consumer honest about degradation | `GMV4-ats-001`, `GMV4-ats-003`, `GMV4-ats-007` | Round 3 required; reviewer FAIL 18:39Z; culture-fit test RED 18:45Z; **not deployed** |
| 2 | ATS ≥85 met, **or** the shortfall surfaced as structured, user-visible data rather than a free-text warning | `GMV4-ats-004` | 46.28 vs 85; **must be re-measured post-deploy** |
| 3 | Zero synthetic/fixture rows on any user-reachable path | `GMV4-approvals-001` | 1 row deliberately retained for my reproduction; **must be deleted in W-K** |
| 4 | Trustworthy suite baseline, then green | `GMV4-suites-001/002/003` | **G-N unadjudicable** — see §8.3 |
| 5 | Production DB role password rotated | `GMV4-secret-001` | Operator action outstanding |
| 6 | Applications stage-move: DnD functional, canonical `PATCH …/stage` used, counts reconcile | `GMV4-apps-001` + new ADV-002 | Broken/legacy/non-reconciling |
| 7 | Jobs apply flow: confirmed state renders and survives reload | new ADV-001 | `submittedVisible:false`, 0 badges after reload |
| 8 | Story Bank: create must not silently overwrite; category filter must filter; input validated | new ADV-005/006/007 | All three live |
| 9 | Gmail `needs_reauth` visible to the user | `GMV4-email-001` | Invisible |
| 10 | Long agent runs show progress; concurrent runs get backpressure not a 5-minute failure | `GMV4-jobs-001`, `GMV4-resume-002` | 163–300 s static spinner |
| 11 | Submission Agent is either built as specified or the claim is withdrawn from the product surface | `GMV4-submission-002` | Tracking-only; 0 evidence |
| 12 | Every fix above **deployed and re-verified on production** | — | `last_deploy_sha: null` |

### 8.2 Legitimately CONDITIONALLY-CLOSED (§25) — not blockers, but disclose them

DocuGenerate · Google Search Console · Google Forms · YouTube Data · WebScraping.AI (and it should
stay closed) · Hugging Face Inference path · GCS · Google Calendar `calendar.events` consent ·
Gmail 2nd-account consent · the live Stripe purchase click · admin-panel content verification
(no admin account available to this run).

### 8.3 Gates that CANNOT be adjudicated at all

**G-N — the genuine backend failure count is UNKNOWN.** Both baselines are contaminated:

- Run 1 (17:06–17:50Z): `36 failed, 2027 passed, 1 skipped, 9 errors` — **straddled a package
  install**, so it did not measure one tree.
- Run 2: `50 failed, 46 errors` — taken **while other agents were running pytest against the same
  shared `aether_test` schema**.

`BASELINE-SUITES.md` asserts the 36 failures are "genuine failures, not DB schema contention
flakiness" — that assertion is **UNVERIFIED** and is contradicted by `GMV4-suites-003` (evidence
that a large share are flakiness) and by two screen-testers who investigated their screens'
correlated test failures and could not reproduce them on production. **Nobody knows the number.**
Until a clean, exclusive, single-tree run exists, "zero regression" is unclaimable.

Also unadjudicable: **G-M** (no runtime artifacts at all), **G-SUB** (empty evidence dir),
**G-B/G-O** (17/19 workstreams never started), **G-L** (no CI check this run).

### 8.4 The honest bottom line for the owner

Aether is a real product with real AI and a genuinely admirable refusal-to-fabricate discipline. It
is **not** a demo. But on 2026-07-31 it ships a quality score computed by a method it does not
disclose, misses its own quality target by ~39 points on the one real measurement taken, shows a
synthetic QA row on a live screen, has a broken drag-and-drop and an apply flow that never confirms,
cannot prove its test suite is green, and has deployed **none** of the fixes written during this
campaign. Onboarding paying customers tomorrow would mean charging money for a measurement the
product cannot currently make.

**Recommended sequence:** deploy the semantic-scoring fix once Round 3 passes → re-measure ATS →
purge the synthetic rows → fix the apply/stage-move/story-create defects → obtain one clean suite
baseline → run the ≥60-minute monitored window with real server logs → then re-adjudicate.

---

## 9. New findings raised by this review

Filed here in §5 schema shape. They are **not** written into `MODELS-LIVE-GAPS.json` by me: that file
is being mutated concurrently by other agents (it grew by one row mid-review) and ledger sequencing is
the orchestrator's. Ids are namespaced `ADV-` to avoid collision.

| id | screen | sev | category | summary | evidence | status |
|---|---|---|---|---|---|---|
| `ADV-001` | Jobs | HIGH | defect | `POST /jobs/{id}/apply` returns 200 but the UI never renders a submitted state (`submittedVisible:false`, `submittedText:null`) and after reload `appliedBadgeAfterReload:0, cardsAfterReload:0`. The screenshot named `29-submit-confirmed.png` asserts the opposite. G-H's "application created in tracker" is not demonstrated end-to-end. | `.../screens/dashboard-jobs/events-part3a.json`, `events-part3-error.json` | OPEN |
| `ADV-002` | Applications | HIGH | defect | Stage counts do not reconcile: `sumStageCounts 51` vs `appsCount 49`; Submitted badge 45 vs 25 cards rendered (`+20 more`). G-F explicitly requires "stage counts/funnel reconcile". | `.../screens/dashboard-applications/part2-report.json`, `main-report-part1.json` | OPEN |
| `ADV-003` | Applications | MEDIUM | defect | Native drag-and-drop produces **no** network call and **no** stage change across three independent attempts; only the menu fallback works, and it fires the legacy endpoint. G-F requires "drag + accessible menu". | `.../screens/dashboard-applications/part3b-report.json`, `dnd-synthetic-result.json` | OPEN |
| `ADV-004` | n/a (process) | HIGH | governance | Four findings carry `VERIFIED-CLOSED` set by agents without closure authority — three by `screen-tester` (the role that opened them) and `GMV4-sse-004` by `test-author`, closing its own contract amendment. §24 assigns closure to `qa-adversary`; §0.4 forbids self-approval. Substance of all four is agreed; the **closure act** is void and must be re-performed. | `docs/delivery/MODELS-LIVE-GAPS.json` (18:47Z snapshot), `verifiedBy` fields | OPEN |
| `ADV-005` | Story Bank | HIGH | defect | `POST /api/stories` with duplicate content returns **`201 Created`** but the body carries the **pre-existing** story's id with a bumped `updatedAt`; card count delta 0; no duplicate warning. A silent overwrite presented to the user as a create — a data-loss class defect. | `.../screens/dashboard-stories/results.json` (`duplicate_create_network`, `post_stories_bodies`) | OPEN |
| `ADV-006` | Story Bank | MEDIUM | defect | `GET /api/stories?category=X` returns all 37 stories unfiltered for all four categories tested; filtering is client-side only, so the parameter is a no-op contract lie. | `.../screens/dashboard-stories/results.json` (`key_bodies`) | OPEN |
| `ADV-007` | Story Bank | MEDIUM | security | A `<script>alert(1)</script>` title (~330 chars) with `<img src=x onerror=…>` in `action` was accepted with `201`, stored raw, and rendered as a card. No sanitisation, no length limit, no server-side validation. React escaping mitigates reflected execution today; the **stored** data is unvalidated and any non-React consumer (PDF export, email body) is exposed. | `.../screens/dashboard-stories/results.json` (`adversarial_create_network`), `13-adversarial-card-rendered.png` | OPEN |
| `ADV-008` | n/a (evidence) | HIGH | governance | `/dashboard/approvals` has **zero machine evidence** — 23 PNGs written in a 0.2 s burst, no JSON, no report — yet a BLOCKER and a BUG were entered into the ledger from it. The BLOCKER survives only via an independent DB artifact. The screen must be re-tested with network/console capture before any approvals-related gate closes. | `.../screens/dashboard-approvals/` (23 files, 0 non-PNG) | OPEN |
| `ADV-009` | n/a (evidence) | HIGH | governance | `uat/reports/evidence/gold-master-v3/runtime/`, `deploy/` and `submission-agent/` are all **empty**. The §23 always-on runtime monitor filed nothing, so **no server-log evidence exists for this entire run**. G-M and G-SUB cannot be adjudicated, and §3.3's runtime-health section can only be answered browser-side. | my probe artifact `.../adversarial/G-A-prod-probe-20260731T185102Z.txt` (18:51Z) | OPEN |
| `ADV-010` | Resume Studio | MEDIUM | defect | Two multi-minute tailoring runs produced **no new résumé version**: `version_count` = 8 before run 1, after run 1, after run 2, and after reload. Either versioning is broken or the list is silently truncated with no affordance. | `.../screens/dashboard-resume/results-2.json` | OPEN |
| `ADV-011` | n/a (process) | LOW | governance | `GMV4-ats-004`'s `evidence` field cites `dashboard-resume/results.json`, which does not contain the quoted numbers (that file terminates `"status":"ERROR"`); they are in `results-2.json`. Correct citation before the finding is used to close anything. | grep, both files, this session | OPEN |
| `ADV-012` | n/a (process) | LOW | governance | `docs/delivery/GOLD-MASTER-V3-STATE.json` is stale: `updated_utc 17:26:22Z`, `findings_delta.open: 15` against an actual 49 OPEN, and it still shows `W-A: screen batch 1 running` after all four batches finished. Resume-from-checkpoint would restart from a false position. | STATE.json vs ledger, both read 18:50Z | OPEN |
| `ADV-013` | Story Bank | LOW | cleanup | A test edit was left in production: `final_titles[0]` now ends `"(updated)"` and its `situation` ends `"…across disciplines, specifically."` The cleanup log only records deleting the adversarial story. | `.../screens/dashboard-stories/results.json` (`cleanup_log`, `final_titles`) | OPEN |
| `ADV-014` | n/a (cleanup) | INFO | cleanup | **Disproved candidate, recorded so nobody re-raises it.** `settings-client.tsx:1233` contains a literal "Coming soon" badge, which would violate G-O. It is rendered only when `Toggle` receives `disabled`; **neither of the 2 `<Toggle>` usages passes it**, so the badge is unreachable dead code. Likewise `base_adapter.py:91-98` will serve recorded fixture JSON whenever `AETHER_DISCOVERY_FIXTURE_DIR` is set — **that variable is absent from `.env` and from the deploy units**, so the fixture path is not armed in production. Both should be deleted for hygiene; neither is a live G-O/G-K violation. | my probe artifact, appended section (18:52Z) | CLOSED-NOT-A-DEFECT |

---

## 10. What this run got wrong about itself

A review that only indicts the codebase is not adversarial. Three self-inflicted failures, all
recorded in `docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md` §4, all confirmed by me against the
underlying artifacts:

**(a) The first production baseline was unauthenticated and reported "CLEAN" from 22 identical
login-page screenshots.** (`VIOL-001`) The Phase-0 browser sweep reported "28/28 routes 200, 0 console
errors, all routes live data, verdict CLEAN". It had never logged in. I independently reproduced the
proof: in `_VOIDED/baseline-VOID-VIOL-001/`, md5 `17fedcb8e6bd45a5bdee623c1f5473fd` appears **exactly
22 times** across 28 PNGs, and 15 of the 16 routes with a detail section record
`Final URL: https://5cb5f0620.abacusai.cloud/login` while the summary table above them still says
`live | OK`. `[VERIFIED]` **A "clean" result was an artifact of never reaching the application** —
the most dangerous failure mode in this entire discipline, because it is indistinguishable from
success unless someone checks the hashes. The report was voided and the re-run was required to prove
authentication three independent ways (URL, DOM landmark `[data-testid="sidebar-plan-quota"]`,
`localStorage` token). The re-run's self-audit numbers I reproduced exactly, including its honest
disclosure that 5 of its own 27 screenshots share a hash because 4 admin routes genuinely redirect to
the same `/dashboard` render.

**(b) The orchestrator echoed the production database password into a session transcript, and a
rotation is now required.** (`VIOL-006`) While independently verifying a deletion, it ran
`set -a; . ./.env; set +a`; bash echoed the assignment lines, printing `DATABASE_URL` and
`DATABASE_URL_TEST` **including the role password**. This breached the same §0.5 zero-tolerance rule
the orchestrator had been enforcing against sub-agents all run. It self-reported, adopted a standing
rule (never source `.env` in a shell; parse in Python and pass via `env=`), and filed
`GMV4-secret-001` as **caused by this run** rather than quietly folding it into the pre-existing
§25 list. The rotation is outstanding and is blocker B5. The disclosure is exactly right; the
exposure is still real.

**(c) Two of the orchestrator's own findings were withdrawn after first-hand evidence contradicted
them.** `GMV4-analytics-001` (a claimed analytics degrade path) was withdrawn — `CLOSED-NOT-A-DEFECT`
— when probing showed `GET /analytics/dashboard` returns 200 on all five observed products and the
premised path does not occur in production; it is a stale code comment, not a live defect.
`GMV4-jobs-003` was **corrected** by batch-2 first-hand evidence after its original text claimed no
before→after ATS delta is rendered — the delta *is* rendered. `[VERIFIED — ledger text of both]`
This is the correct behaviour and it should be read as a strength of the process, not a weakness.

**A fourth I add on my own account:** the run's own governance log is the only reason (a) and (b) are
visible at all. Two further process defects are recorded there — `VIOL-005` (projected pytest counts
offered in a results-shaped block instead of measured ones; discarded) and `PROCESS-DEFECT-001`
(sub-agents stalling on background waits, ~420k tokens for zero artifacts across three occurrences) —
and one escalation, `ESC-001`. **A governance log that only ever indicts sub-agents is not a
governance log.** This one indicts its own author, which is why I am prepared to treat the rest of
its contents as testimony worth weighing.

---

## 11. Evidence index

All paths relative to the repo root. Every artifact below was opened by me during this review.

| Artifact | What it establishes |
|---|---|
| `uat/reports/evidence/gold-master-v3/adversarial/G-A-prod-probe-20260731T185102Z.txt` | My own fresh prod probe (18:51–18:52Z): 9 route status codes, `/api/health`, 401 auth guards, ledger snapshot, empty deploy/runtime/submission dirs, `.env` key-name presence, dead-code and fixture-path disproofs |
| `uat/reports/evidence/gold-master-v3/screens/*/` | 14 dashboard routes; 8 with `REPORT.md`, 5 with raw JSON only, 1 (`dashboard-approvals`) with screenshots only |
| `uat/reports/evidence/gold-master-v3/screens/dashboard-resume/results-2.json` | ATS 44.06→46.28, 5 exhausted iterations, `costUsd 0.043056`, run-2 failure |
| `uat/reports/evidence/gold-master-v3/screens/dashboard-cover-letters/results.json` | Fabrication guard withholding; two runs, differing cost/tokens/length |
| `uat/reports/evidence/gold-master-v3/screens/dashboard-stories/results.json` | Create-overwrites-existing; category filter no-op; unsanitised input; extractor `created:0 dropped:8` |
| `uat/reports/evidence/gold-master-v3/screens/dashboard-jobs/events-part1..4.json`, `scout-sources-availability-response.json` | Apply-flow failure; honest per-source availability incl. Seek compliance gate |
| `uat/reports/evidence/gold-master-v3/screens/dashboard-applications/part2/3b/4/6-report.json` | DnD failure; legacy `/move`; count mismatch; honest 422/409 |
| `uat/reports/evidence/gold-master-v3/browser/BASELINE-SWEEP-AUTH.md`, `sweep-results.json` | Authenticated 27-route sweep; `admin/admin123 → 401`; admin routes redirect |
| `uat/reports/evidence/gold-master-v3/_VOIDED/` | The voided unauthenticated baseline; 22× identical md5 reproduced |
| `uat/reports/evidence/gold-master-v3/PROD-DATA-INVENTORY.md` | 31 tables; 17 synthetic rows; **zero non-test-account content**; 0 exact / 16 near-duplicate stories |
| `uat/reports/evidence/gold-master-v3/services/SERVICE-REGISTRY.md` | 9-service probe; token-overlap fallback location |
| `uat/reports/evidence/gold-master-v3/suites/BASELINE-SUITES.md` | Contaminated baseline #1 (36F/9E), vitest 650/650, lint/tsc clean, Playwright NOT-RUN |
| `uat/reports/evidence/gold-master-v4/suites/GMV4-ats-002-round2-adversarial-review-20260731T183940Z.md` | Round-2 **FAIL**, two remaining leak sites, fail-open default |
| `uat/reports/evidence/gold-master-v4/suites/GMV4-ats-002-culturefit-strengthened-RED-20260731T184537Z.txt` | Culture-fit leak test RED at 18:45Z |
| `docs/delivery/ADR-SEEK-V3.md` | Independent risk-officer REFUSAL, 17:26:18Z, with what would change the ruling |
| `docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md` | VIOL-001..006, ESC-001, ADR-GMV4-001/002, PROCESS-DEFECT-001 |
| `docs/delivery/MODELS-LIVE-GAPS.json` | 64 GMV4 findings @ 18:47Z: 8 BLOCKER, 18 HIGH, 25 MEDIUM, 13 LOW; 49 OPEN |
| `docs/delivery/GMV2-CLAIM-LEDGER.md` | 39 prior claims, 31 still `UNVERIFIED-THIS-RUN` |
| `docs/delivery/GOLD-MASTER-V3-STATE.json` | 17/19 workstreams `NOT-STARTED`; `last_deploy_sha: null` |

---

**Signed:** `qa-adversary` sub-agent, GOLD-MASTER-V4 Workstream A §3.3, 2026-07-31.
I authored no code, tested no screen, fixed no defect and deployed nothing. I closed exactly one
thing — gate G-A — and the ruling is in
`uat/reports/evidence/gold-master-v3/G-A-ADJUDICATION.md`. Every other gate is left open.
No agent message was treated as consent or approval.
