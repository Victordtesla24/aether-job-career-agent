# ORCH Reconciliation Delta — 2026-08-14

Produced per `orchestrator-execution-prompt.md` §1.4 by a 10-scout read-only recon swarm
(workflow `wf_5c8a6a55-d1f`, 2026-08-14T13:50–14:10Z) against repo snapshot `main@2ac2255`
(origin/main advanced to `42a02d0` during recon — ustory3a landed by a concurrent agent; the
4 new commits are web-only, agents-console linkage work). Verdicts are OBSERVED state with
evidence; sub-agents work from this column, never the prompt's claims.

Verdict legend: **DONE** = observed working/landed · **CODE** = code+tests landed, live behavior
not provable read-only · **PARTIAL** · **MISSING**.

| Item | Prompt claim | Observed (evidence in wf_5c8a6a55-d1f journal) | Verdict | Remaining work |
|---|---|---|---|---|
| A1 renderer whole-doc | Rebuilt renderer being landed | `resume_completeness.py` fail-closed routing wired at all 4 render branches (`resumes.py:798–915`); 43+ tests | CODE | none (live-artifact probe at final gate) |
| A1 surname / banners | Parse fixes in-flight | Landed: `_split_merged_banner()`, `_KNOWN_BANNER_WORDS`, real live-text fixture tests | CODE | none |
| A1 tracked-edit regression | Must still pass | `format_verification.py` + 12 tests intact, zero skips | CODE | none |
| A2 proof-or-no-claim | Fix being landed | `SubmissionResult` has no `submitted` field, only `transmission` evidence; guard live-verified (11 real writes marked, 0 false positives in prod) | DONE | none |
| A2 census | To be written | Census done + backfill APPLIED to prod (358/606 rows carry honest marker, 0 unmarked); reports are gitignored loose files | DONE | none |
| A2 per-card Submit | To be built | `submission_control.py` 8-state control wired end-to-end to UI | CODE | none |
| A3 Checkout code | Implement/verify to max | Real Stripe SDK path implemented + mocked pytest suite; **zero completed Checkouts ever** (DB-confirmed); no test-mode (`sk_test_*`) sandbox run exists | PARTIAL | Test-mode verification if key available; live rehearsal is §8.5 operator-gated |
| A3 rehearsal staged | Stage everything | No rehearsal checklist exists anywhere | MISSING | Author staged rehearsal checklist |
| A4 flagship UI | Needs coordinated deploy | Already LIVE in prod (merged commit == running BUILD_ID); **no beauty-verdict artifact exists** | PARTIAL | Produce beauty verdict (UI-Beauty judge) |
| B1 U-AGI kernel | Replace Supervisor stub | **Supervisor is still a one-line stub** (`agents.py:3404–3409` echoes hardcoded plan); no kernel, no AgentDirective table, no whitelist/rules stage; merged `feat/uagi-p1a` contained **no backend work** | MISSING | Full P1 build: kernel + directives migration + rules stage + display |
| B1 story via kernel | U-AGI P2 | No kernel to go through; `StoryExtractorAgent.run()` called directly, no corrective loop / rigor policy | MISSING | P2 after P1 |
| B2 threshold gates | Computed, not enforced | Confirmed: `quality_policy.py` floors + cover thresholds surface only; **nothing blocks output** below threshold | MISSING | Hard output gates + boundary tests |
| B3 relevance ranking | Never actually runs | Now wired unconditionally into live Tailoring/CoverLetter paths (`story_relevance.py`, call-site traced); pinned tests | DONE | none |
| B3 contradiction | Cover rejects resume claims | Closed via evidence-corpus symmetry (U-STORY-1) + regression tests | DONE | none |
| B4 corpus writer | Doesn't exist | Full Story Bank authoring UI + backend CRUD live; corpus mirror on create/update | DONE | Backfill 76 pre-mirror StoryEntry rows |
| B4 377-item import | Queued | **Complete**: 378 EvidenceCorpusItem rows in prod for owner (377 non-story source) | DONE | none |
| B5 email scheduling | Nothing crons it | Confirmed: 7 modes work, **no timer/cron exists** | MISSING | systemd timer (platform-sanctioned path, like `aether-discovery.timer`) |
| B6 parentRunId | Missing | Confirmed missing: 17 AgentRun columns, no parentRunId; map draws stage-order edges only | MISSING | Additive migration + populate + causal edges |
| B7 LinkedIn source | Not built | Built as compliant candidate-PASTE (`career_data.py:346+`), zero scraping paths; not file-UPLOAD | PARTIAL | Add file-upload ingestion path |
| C Jobs virtualization | 12,000px unvirtualized | main has 60-row render-window stopgap; true virtualization (`VirtualList`, @tanstack/react-virtual) sits on unmerged `feat/sui-b2` (2 ahead/0 behind, self-tested, conflict-free) | PARTIAL | Land `feat/sui-b2` |
| C Applications/Approvals | Complete surface | Code-complete (1553-line pipeline board, Sankey/Timeline) | CODE | none |
| C Resume Studio aha | Near-empty | Before/after defect class fixed across documented rounds | CODE | none |
| C Cover Letter Studio | Complete | 7 intelligence sub-panels wired | CODE | none |
| C Story Bank | "Section not found" | Refuted: dedicated 348-line CRUD page, live route in prod | DONE | none |
| C Interviews/Networking/Email/Offers | Thin | All four fleshed out (e.g. interviews 895 lines, real CRUD) | DONE | none |
| C marketing/login | Console error + redirect quirk | Double-hop redirect fixed in code (documented); console-error claim needs a browser probe | PARTIAL | Browser sweep in beauty pass |
| C old-shell deletion | Do last | Flagship shell renders in prod; **one superseded artifact remains**: `components/sidebar.tsx` + its test | PARTIAL | Delete after beauty verdict |
| D localStorage tokens | Plan migration | Confirmed `aether_token` in localStorage; **no migration plan exists** | PARTIAL | Author migration ADR (execute post-launch) |
| D alerting (GlitchTip) | Stand it up | Nothing exists (no SDK, DSN, unit hooks) | MISSING | Wire env-gated DSN + OnFailure hooks; DSN provisioning is operator ask |
| D queue-depth | Expose | No endpoint, no UI | MISSING | ARQ depth endpoint + UI element |
| D generic-route 524 | Remove exposure | Dedicated routes migrated to async+poll; **generic `POST /agents/{name}/run` still synchronous** (`agents.py:5391–5413`) | PARTIAL | Async background+poll for generic route |
| D MON-002/003/006/008 | Residuals | No MONITORING-LEDGER.md exists in-repo (cited by 15+ comments); no fix evidence for these 4 | MISSING | Recreate ledger; verify symptoms live; fix provable ones |
| D LLM budget tuning | Tuning needed | Actively-tuned env-knob system present; current 503/timeout rate unmeasured | CODE | Measure at gate; tune only on evidence |
| §8 PyMuPDF | Decision needed | fitz used across resume pipeline; no licensing decision doc | OPEN | Decision doc + operator ask |
| §8 Stripe branding | Assets staged | Assets NOT in repo (likely in unmerged market-perf worktree) | MISSING | Locate/stage + operator upload ask |
| §8 password leak | Flag, don't echo | Not found in `uat/reports`/`docs` (212 files searched); likely VM-local outside repo | OPEN | Bounded VM search; rotation ask stands |
| §8 sending domain | resend.dev | Confirmed still `onboarding@resend.dev` via Resend API branch | OPEN | Operator DNS ask (~5 min) |
| §9 paid walkthrough | Never done | Confirmed: only 2 pro Subscription rows, both `stripeSubscriptionId IS NULL` | MISSING | Blocked on §8.5 card step |
| §9 dress rehearsal | Required | 8 StripeEvents total, newest 2026-07-21 (A$0.50, refunded); predates gate | MISSING | Blocked on §8.5 card step |
| §9 U6 closing gate | Required | No artifact exists | MISSING | Produce at close of this run |

## Consequences for sequencing (observed-state backlog)

Wave A is essentially **landed** (A1/A2 done; A3 blocked on operator card; A4 needs only the
beauty verdict). Wave C is **landed except** `feat/sui-b2` + the sidebar deletion + beauty pass.
The genuinely open engineering work is: **B1 kernel (largest), B2 output gates, B5 timer,
B6 parentRunId, B7 upload path, D.524, D.queue-depth, D.alerting, MON residuals**, plus the
documentation/process artifacts and §8 operator asks listed above.
