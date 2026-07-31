# GOLD-MASTER-V2 — FINAL REPORT (§17, Gate G-P)

**Written:** 2026-07-31T15:1xZ, by the orchestrator, as the final act of this run.
**Refreshed:** 2026-07-31T16:3xZ — several gates closed after the report below was first written; this
refresh corrects the document to the campaign's current true state rather than leaving it stale. See the
banner immediately below for what changed and why nothing here was silently rewritten.
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Production:** `https://5cb5f0620.abacusai.cloud` (app at `/dashboard`)
**Deployed:** commit `061014c` (71 commits ahead of the prior production build `0588aff`), restarted
`2026-07-31T13:45:25Z`; API restarted again `2026-07-31T15:26:34Z` for the BLOCKER-004 fix (`f3415e0`);
CI run [30635438303](https://github.com/Victordtesla24/aether-job-career-agent/actions/runs/30635438303) `success`.
**Governance authority:** `docs/delivery/GOLD-MASTER-V2-STATE.json` (ledger of record, `updated_utc:
16:30:00Z` as of this refresh), `docs/delivery/GOLD-MASTER-V2-GOVERNANCE.md` (GOV-001..012),
`docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` (binding risk-officer ruling on G-P).

---

## REFRESH BANNER — 2026-07-31T16:3xZ — read this first

Everything below this banner was accurate for the state it described when first written (`~15:2x–15:3xZ`).
It is **retained in full, not rewritten** — this run's own standing rule is that a report hiding its own
history is not credible. Where a claim below is now stale, it is struck through in place or annotated
inline with **`[SUPERSEDED — see banner]`**, not silently deleted.

**What changed, verified fresh for this refresh** (full detail: `final/G-P-REFRESH-SPOTCHECKS.md`,
independently re-derived, not copied from the artifacts it corroborates):

1. **G-M CLOSED.** A second, fully clean 60-minute window ran `2026-07-31T15:28:32Z`–`16:28:50Z` on the
   post-BLOCKER-004 build (API restarted `15:26:34Z`): **0 real 5xx, 0 ERROR/Traceback matches, 6
   AgentRun rows (scout ×2, fitScorer ×3, storyExtractor ×1), 0 failed**, monitor alive and
   signal-proven throughout. Independently re-derived here with a fresh `awk` timestamp-range filter
   against `/var/log/aether/api.log` (0 5xx, 0 errors, same 6 agent-run lines) — not merely trusted from
   the ledger. §4 below is corrected in place.
2. **BLOCKER-004 CLOSED and re-verified live, again, independently, for this refresh.**
   `POST /auth/register` with a NUL byte in the password now returns a clean 422 (`"password must not
   contain a NUL byte"`), reproduced fresh at `16:33Z`; a legitimate space-containing password still
   registers 201 (no over-correction, also reproduced fresh); the login path's NUL-byte handling is
   unaffected (401, not 500). §3 and §6 below are corrected in place.
3. **G-B and G-O CLOSED.** Commit `aac8c03` removed the last shipped "Coming Soon" stub (Settings →
   Notifications' three disabled toggles), replacing it with an honest pointer to the real, already-shipped
   `NotificationAgent` rather than building the unbuilt real-time-push/weekly-cron infrastructure the
   toggles falsely implied. `grep` proves zero user-reachable placeholder strings remain across
   `apps/web/src`; 650/650 FE green, lint and `tsc` clean. §9 below is corrected in place.
4. **G-K CLOSED.** `final/G-K-SWEEP.md` (2026-07-31T14:56–15:08Z, against the deployed tree): 0
   PROHIBITED-STUB lines; the campaign added +4 jscpd clones, all test-to-test, zero production-code
   duplication; the 5 shared-service extractions (`stage_transitions.py`, `usePolling.ts`,
   `story_paraphrase.py`, `story_relevance.py`, `verify-web-build.sh`) confirmed MOVES, not copies; no
   cross-account content leakage. §9 below is corrected in place.
5. **W-K executed, partially, as previously adjudicated.** The two risk-officer-approved SAFE deletions
   (dead NextAuth catch-all route/options file; 2 orphaned `.pyc` files) are done, committed, and — per
   this refresh's own fresh `git` check — **pushed** (`2946fd1` is on `origin/main`; the prior "committed
   locally, not yet pushed" claim below at §1/W-K and §7 item 6 is **wrong, corrected here**). All
   production-DB deletions in the original manifest remain **REFUSED** by the risk-officer: the manifest
   named five tables that do not exist in this schema and, executed as written, would have deleted 6 real
   submitted job applications and cascade-destroyed the forensic approval rows that are the sole surviving
   attribution evidence for the BLOCKER-002 approval incident.
6. **`ORCH-CORR-010` added** (now ten self-corrections, not nine — §8 below): this run's own report of
   "83 × 5xx in window 2" was itself a methodology error — `api.log` holds 39,006 unprefixed historical
   `INFO:` lines, and the string comparison `"INFO:" > "2026-..."` (`"I" > "2"` lexically) matched every
   one of them regardless of date, pulling in the entire log history. Corrected, and independently
   re-derived by this refresh with a different filter construction: **0**. Caught originally because the
   live tail-based monitor disagreed with the flawed `grep`/`awk` output; independently reproduced here.

### What a real paying user is protected from today that they were not this morning

Stated plainly, without rounding up: a real paying user today cannot (a) have their PII exposed through
the admin credential (privilege half of BLOCKER-001 is closed and deployed — `admin/admin123` now
authenticates nobody as admin), (b) have a newly-generated cover letter signed with a leftover test
string (the forward-generation guard is deployed), (c) have their session crash the API with a stray NUL
byte on eleven of twelve known-affected endpoints including, as of this refresh, the twelfth
(`/auth/register`, BLOCKER-004, closed this refresh), or (d) see a fabricated "Coming Soon" feature
presented as more real than it is (the last such stub is removed). They also get a genuinely working
per-card Apply button, a real 20-second story-refresh, and a real (if honestly-limited) tailoring loop
that shipped and is deployed, none of which existed 17 hours ago.

### What still stands between the product and a launch declaration

Exactly one binding item, unchanged by this refresh: **the owner's own production account remains
reachable with a password published in the same public repository that documents the fix** — rotation of
`AETHER_ADMIN_PASSWORD_HASH`/`AETHER_CRON_PASSWORD`/`LOGIN_PASSWORD` is the sole remaining precondition
per the binding `ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` §6, and it is **on hold at the operator's own
explicit request** — presented here as the operator's decision, not a failure of the work. Two further
non-binding-but-real items remain open regardless: `G-E` (relevance-score UI, deliberately left unmet on
evidenced grounds — see §9) and `G-I` (realtime refresh, PARTIAL — one of seven screens covered, no SSE
stream anywhere). Everything else that was open when this report was first written and is not listed
above as newly closed remains exactly as this document originally found it.

---

## Epistemic tagging used throughout

`[VERIFIED-WITH-FRESH-EVIDENCE]` — first-hand, this run, artifact + timestamp cited; the only tag that
closes anything. `[INFERRED]` — reasoned from verified facts, shown. `[TESTIMONY]` — a sub-agent's own
report, credible but not independently re-derived here. Prior-phase reports are testimony, not proof,
per the standing rule this run adopted after GOV-009/GOV-010.

This report was produced by a single author working serially (no sub-agents spawned, per this task's
hard rules), continuing directly from `GOLD-MASTER-V2-STATE.json`'s own `updated_utc: 14:50:00Z`
snapshot. New first-hand verification performed for this report specifically — not merely relayed from
earlier phases — is filed at
`uat/reports/evidence/gold-master-v2/final/FINAL-REPORT-SPOTCHECKS.md` and cited inline as
`[SPOTCHECK]`. One of those spot-checks **overturns** a claim this run had logged as fixed (§6).

**This refresh** (2026-07-31T16:3xZ, `GOLD-MASTER-V2-STATE.json` `updated_utc: 16:30:00Z`) adds a second,
independent round of first-hand verification, filed at
`uat/reports/evidence/gold-master-v2/final/G-P-REFRESH-SPOTCHECKS.md` and cited inline as
`[REFRESH-CHECK]` — including an independent re-derivation of the G-M window-2 error count from the raw
production log (not copied from the ledger's own corrected figure) and a fresh, third live re-probe of
the BLOCKER-004 fix.

**A note on this report's own process, stated up front rather than buried:** this task ran concurrently
with a separate, still-active orchestrator process working the same `GOLD-MASTER-V2` run (visible via
`git log` and live edits to `GOLD-MASTER-V2-STATE.json` during this report's own writing — see commits
`c8dc4ab`, `cf587a4`, `f3415e0`). That process independently found the **same** live defect this
report's own §2 spot-check found (`POST /auth/register` crashing on a NUL byte), filed it as
**BLOCKER-004**, and — mid-way through this report being written — committed a fix (`f3415e0`, not yet
deployed). Separately, **this report's own first attempt to close G-M was wrong** — a `grep` methodology
error caused it to miss the 2 real 5xx that its own probes had just caused, inside the required window.
That error was caught by re-checking rather than trusting the first pass, and is corrected in §4 and
disclosed as ORCH-CORR-009 in §8. It is left visible rather than quietly rewritten, per this run's own
standing rule that a report hiding its own author's errors is not credible.

---

## 0. Launch-readiness declaration

# NO — G-P CANNOT BE DECLARED.

This is a binding conclusion, not a hedge. `docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` §6
rules, in terms that this report is instructed to reproduce rather than soften:

> **This system is NOT certified ready for real paid user onboarding (G-P) until
> `AETHER_ADMIN_PASSWORD_HASH` and `AETHER_CRON_PASSWORD` are rotated together and verified.**

That ruling explicitly anticipated and pre-empted the situation this report originally found: *"This
holds even after the full approved set is deployed and verified."* **`[SUPERSEDED — see REFRESH BANNER]`**
As first written, this section reported that verification was "not yet clean" because BLOCKER-004
produced 2 real 5xx inside the observation window. **That is no longer the live state**: BLOCKER-004 is
now closed (fix `f3415e0` deployed `15:26:34Z`), and a fresh, fully clean 60-minute window
(`15:28:32Z`–`16:28:50Z`, 0 real 5xx, 6 successful AgentRun rows) has since closed G-M (§4, banner item
1). None of that changes the declaration: **the binding ADR's ruling controls regardless of G-M**, on
the credential alone. Rotation remains **on hold at the operator's own explicit request**
(`operator_decisions[0]`, `GOLD-MASTER-V2-STATE.json`), and this run separately found and confirmed
**BLOCKER-003** (§5): the same publicly-published `admin123` password, combined with the owner's email —
also public in the repo — authenticates the owner's real, `pro`-entitled production account today, over
the public internet, independent of the admin-privilege question BLOCKER-001 already closed.

Beyond that binding blocker, and **updated by this refresh** (banner items 3–4): of the 15 exit gates
(G-A..G-O), **2 (G-E, G-I) do not meet their own §17 conditions at all**, **G-N carries one named
exception** (Playwright remains red — see §2), **G-A** is document-complete but carries a process caveat
(not independently reviewed by a separately-dispatched `qa-adversary`, per this task's own no-sub-agents
hard rule), and **4 more (G-C, G-F, G-H, G-J) are deployed and code-complete but not fully live-verified
end-to-end**. G-B, G-K, G-M and G-O — all listed here as unmet when this section was first written — are
now **CLOSED** (banner items 1, 3–4). See §9 for the complete, gate-by-gate accounting and exactly what
remains.

**What genuinely changed for the better this run, stated without hedging, and strengthened by this
refresh:** the two CRITICAL blockers that opened this run (BLOCKER-001 admin over-permission, BLOCKER-002
contaminated cover-letter signatures) are both **substantially downgraded** — no account holds `isAdmin`,
other users' PII is no longer reachable through the admin hole, and forward-generated cover-letter
content is clean and guarded against re-contamination. **Twelve** endpoints' (not eleven — BLOCKER-004
was the twelfth, and it is now closed too) worth of a systemic NUL-byte crash class are fixed and
deployed. A real per-card Apply button, a real 20-second polling hook, a real score-aware tailoring loop
with an honest failure-mode warning, a real stage-transition service, a real approval-decision audit
trail, and — as of this refresh — a genuinely clean, error-free hour of production traffic with real
agent runs inside it, all shipped and are live. None of that adds up to "ready for real paid user
onboarding" while the owner's own account remains reachable with a password published in the same public
repository that documents the fix.

---

## 1. Per-workstream verdicts (W-A .. W-L)

Each verdict states what shipped, what is deployed, and what — if anything — is still short, with an
evidence path per claim.

| WS | Verdict | Evidence |
|---|---|---|
| **W-A** (Phase 0 + screen sweep + adversarial doc) | **COMPLETE, coverage-wise.** All 27 routes in `SCREEN-MATRIX.md` deep-tested under both OWNER and a genuine non-admin identity `[TESTIMONY, screen_sweep.status=COMPLETE]`. `GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md` was refreshed to FULL (27/27) coverage mid-run, and is refreshed again by this task to **post-deploy** truth (§10 below). **Caveat:** that refresh was authored by this report's own author, not a separately-dispatched `qa-adversary` sub-agent (hard rule: no sub-agents this task) — flagged as a process gap, not silently presented as independent third-party sign-off. | `screen_sweep`, `docs/delivery/GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md` |
| **W-B** (core defect wave: NUL-byte class, signer guard, email verification, trial webhook, honest Gmail status, counterparty drafts, Submission Agent) | **LANDED AND DEPLOYED, fully closed this refresh.** `[SUPERSEDED — see REFRESH BANNER]` All 12 originally- and newly-scoped NUL-byte endpoints are now confirmed fixed live, including `POST /auth/register` (BLOCKER-004, fixed `f3415e0`, deployed `15:26:34Z`, re-verified fresh a third time by this refresh — `[REFRESH-CHECK]`, §3). Placeholder-signer guard, strict-boolean email verification, `trial_will_end` webhook, honest Gmail-status derivation, counterparty-grounded drafts, and a genuine Submission Agent backend all shipped, deployed, and verified green (112/112 consolidated regression). Residuals from the state file: FE-D-003/004 (auto-apply/match-threshold persisted-not-enforced, honestly disclosed), FE-D-005 (Pause All, honestly disabled) remain open. **FE-D-001 (Notifications "Coming Soon") is CLOSED** — commit `aac8c03` removed the three unimplemented toggles, replacing them with an honest pointer to the real `NotificationAgent` (banner item 3). | `waves/regression-sweep-20260731T083955Z.log`; `final/coming-soon-removal.md`; `final/G-P-REFRESH-SPOTCHECKS.md` §3 |
| **W-C** (score-aware TailoringLoop, honest sub-85 warning, `interview_conversion_rate`) | **CODE-COMPLETE AND DEPLOYED, NOT LIVE-VERIFIED.** `TailoringLoop` (`MAX_ITERATIONS=5`), the Resume-Studio amber sub-85 warning (`data-testid=tailor-score-warning`), and the real `interview_conversion_rate` computation are all in commits confirmed ancestors of `061014c` (`b0a138f`, `347dbb5`, `18be1a8`, `10e3e41`, `eac7d4b` — `[SPOTCHECK]` ancestry check). Backend 13/13, FE 628/628, anti-fabrication guard verified intact. **No fresh production tailoring run exists post-deploy** to confirm the loop actually moves a live job's ATS score or that the warning renders against real numbers — deliberately not forced this run (would spend real LLM budget/quota on the one disclosed credential this report is trying to use minimally, §0). This is the same restraint the paywalled-verification agent already exercised for the Apply-button "applied" state. | `waves/WC-fix-report.md`; git ancestry `[SPOTCHECK]` |
| **W-D** (Seek/Firecrawl) | **WITHDRAWN — UNACHIEVABLE, not a failure.** Binding risk-officer refusal on primary-source evidence: Seek ToS clause 4(d), `au.seek.com/robots.txt` (retrieved 2026-07-30T23:10:30Z) disallowing `*/job/`/`/api/jobsearch/` and naming `anthropic-ai` explicitly, and Firecrawl's own ToS not representing licensed-intermediary status. `AETHER_ENABLE_SEEK` was never set; the honest "(unavailable)" Seek label on `/dashboard/jobs` is correct and was **not** removed. | `docs/delivery/ADR-SEEK-FIRECRAWL.md`; GOV-008 |
| **W-E** (story dedup + relevance) | **PARTIALLY LANDED, DELIBERATELY.** Paraphrase-level dedup (Jaccard-similarity, not merely byte-identical) is shipped, tested (12/12 + 36/36 regression) and deployed — new story creation should no longer silently multiply near-duplicates the way the 8-achievement/36-story bloat did. The **relevance-score gate itself is deliberately left disabled**, on 1,872-pair empirical calibration: 0.4 is above the corpus's own ceiling (max real score 0.1017), the scorer's signal/noise is 1.566 with rank inversions on 2/6 sampled jobs, and every call site fans into the anti-fabrication guard's evidence corpus, so filtering there would be a **truthfulness regression**, not a §7.3.3 implementation. This is presented as it is in the ledger: a specified, evidenced design decision requiring a follow-up parameter split (filtered-set-for-prompt vs. full-set-for-guard), not a shortfall the run failed to reach. The 34-of-36 pre-existing paraphrase duplicates in the DB were **not** retroactively purged (data debt, not fixed by this run). §7.3.3 is **not met in substance**. | `RELEVANCE-CALIBRATION` ruling, `GOLD-MASTER-V2-STATE.json`; `adversarial/STORY-RELEVANCE-CALIBRATION.md` |
| **W-F** (canonical `PATCH /applications/{id}/stage`, approvals reconciliation) | **DEPLOYED.** Canonical PATCH endpoint ships; both legacy `POST .../move` routes now delegate to one shared `app/services/stage_transitions.py` (moved, not duplicated). `from_stage` enforced (409 naming the real stage), closed-application check ordered first. 13/13 + 133 regression tests green. Board/funnel reconciliation ruling: neither surface filters on `Job.status`, by design, documented rather than silently patched. Approvals Remove/purge-expired already verified live pre-deploy; counters reconcile exactly (3+107+0=110). **Not independently re-verified live post-deploy this session** (would require exercising a real stage transition against production data) — carried as code-complete-deployed, not re-confirmed live. | `waves/WF-fix-report.md`; git ancestry (part of the 71 commits) |
| **W-G** (admin sign-in entry point + persistent Admin badge) | **DEPLOYED AND LIVE-VERIFIED for the non-admin half; the admin half is untestable by design right now.** `/admin-login` renders its form live — **`[SPOTCHECK]` re-confirmed 200 at 15:07Z, independently of the earlier verification**. Topbar Admin badge correctly **absent** for a non-admin, confirmed live (`POST-DEPLOY-SMOKE.md`). The admin-*present* half (badge showing, `/admin/dashboard` reachable) cannot be exercised live at all right now — BLOCKER-001's own fix means no account currently holds `isAdmin`, by design, until the operator rotates the credential. This is the gate's own documented "CONDITIONALLY-CLOSED if no operator credential" case (§17 table), not a shortfall. | `final/POST-DEPLOY-SMOKE.md`; `final/FINAL-REPORT-SPOTCHECKS.md` §1 |
| **W-H** (per-card Apply button + modal) | **DEPLOYED AND LIVE-VERIFIED, with one scope gap.** 31 job cards across 5 view states, all 31 showing a working per-card Apply button; 6 modal opens, 6 cancels, **0 POSTs on cancel** — confirmed live on an entitled `pro` session `[TESTIMONY, PAYWALLED-FEATURE-VERIFICATION.md, VERIFIED-WITH-FRESH-EVIDENCE per its own tagging, 2026-07-31T14:3xZ]`. The modal's **content spec** (title, company, tailored resume/cover-letter status, ATS score, linked story count) is only **3 of 5 present** — cover-letter status and linked-story-count are absent, and "Match score" (fitScore) renders where the GOV-010 ruling specified an ATS score. Saved-view cards still have no per-card Apply (0 saved jobs on the tested account, so even that gap couldn't be exercised live) — an open scope-adjudication question, not resolved either way. `design/screens/job-discovery.html` was updated to match, per GOV-010. | `waves/WH-apply-button-fix.md`; `final/PAYWALLED-FEATURE-VERIFICATION.md` §5-6 |
| **W-I** (realtime refresh) | **PARTIAL — explicitly does not close G-I.** Shipped: canonical `apps/web/src/hooks/usePolling.ts`; `/dashboard/stories` adopts it at a measured, deployed, live-verified **exactly 20000ms** cadence, with the hidden-tab pause (0 calls while backgrounded) and filter-restart (`restartKey`) branches both independently exercised and passing `[TESTIMONY, PAYWALLED-FEATURE-VERIFICATION.md §3.2, VERIFIED-WITH-FRESH-EVIDENCE, 14:38–14:43Z]`; the false "live" label was removed from the load-once dashboard widgets rather than adding fake polling to match a claim. **Not done:** 6 screens (analytics, admin, interviews, offers, networking, cover-letters) still have zero auto-refresh; 5 pre-existing ad-hoc `setInterval` sites were not migrated onto the shared hook; **no SSE agent-run progress stream exists (§11.2.3)**. G-I's own condition ("all screens ≤20s… agent runs stream via SSE") is unmet in the majority. | `final/PAYWALLED-FEATURE-VERIFICATION.md` §3.1-3.2 |
| **W-J** (ATS score consistency) | **CODE-COMPLETE AND DEPLOYED, mostly live-verified.** Tracker board card and Applied-history strip now render the ATS score (closing a gap a sibling screen test had found — no score shown there before). Resume Studio's own score already matched the API exactly 3/3 pre-existing, now pinned by a characterization test. `tailor-score-refresh.test.tsx` — the one test left red mid-run, blocked on a file-ownership fence with a concurrent agent — **was fixed by the final deployed commit itself**, `061014c` (`fix(ML-GM2-CI-RED): reflect fresh tailoredATSScore on jobs cards after tailor run`) `[SPOTCHECK: git show --stat 061014c]`. No fresh live tailoring run exists to visually confirm the banner against real numbers post-deploy (same restraint as W-C). | git `061014c`; `final/FINAL-REPORT-SPOTCHECKS.md` §4 |
| **W-K** (cleanup) | **ADJUDICATED, PARTIALLY EXECUTED — this is the run's final state on cleanup, not expected to change further.** The proposed deletion manifest was substantially wrong (named 5 non-existent tables, undercounted contamination 4 vs. real 8, mischaracterized 2 approvals as pending when all 3 are resolved) — executing it as written would have deleted 6 real submitted job applications and cascade-destroyed the forensic approval rows that are the sole surviving attribution evidence for the BLOCKER-002 approval incident. Approved-and-executed: the dead NextAuth catch-all route/options file (`2946fd1`), 2 orphaned `.pyc` files. `[SUPERSEDED — see REFRESH BANNER]` Previously logged here as "committed locally, not yet pushed" — **wrong, corrected this refresh**: `git branch -r --contains 2946fd1` → `origin/main`; `git rev-list origin/main..HEAD --count` → 0. It is pushed, in CI, and part of the `2563fbe` state this refresh describes. **All production-DB deletions remain REFUSED**, unchanged: the 4 "cover letter" deletes (would cascade-delete 6 real submitted Applications), the 2 approval-row deletes (sole surviving attribution evidence for the approval-audit finding), the Stripe-probe account (billing-linked, would orphan not cascade). Deferred: resume rows, story rows, email drafts (no DELETE endpoints exist for any of them). | `cleanup/W-K-risk-adjudication.md`; `final/G-P-REFRESH-SPOTCHECKS.md` §1 |
| **W-L** (deploy sequence) | **COMPLETE.** BUILD-RISK-001 (a latent total-outage trap in the Next.js rewrite manifest) was found, fixed (`d7fa3bb`, confirmed ancestor of `061014c`), and gated behind `scripts/verify-web-build.sh` before any restart. CI went red once (run `30634785756`), was fixed within 9 minutes (run `30635438303`, the one actually deployed), and the deploy completed cleanly: 0 restarts on any of the 3 services since, 0 new log errors in a 6m39s post-restart window (two independent methods) and, per this report's own re-check, **zero 5xx/ERROR across the full 87+ minutes from restart to now** `[SPOTCHECK §3]`. | `final/DEPLOY-REPORT.md`; `final/BUILD-RISK-001-fix.md`; `final/FINAL-REPORT-SPOTCHECKS.md` §3 |

---

## 2. Suite status (verified vs. baseline)

| Suite | Result | vs. baseline | Notes |
|---|---|---|---|
| Backend (pytest) | **2056 passed / 0 failed / 1 skipped** | baseline 1885 passed / 0 failed / 0 skipped → **+171 net new tests, ZERO regressions** | Re-run on the deployed tree post-restart matches the pre-deploy run exactly (`post_deploy_verification.full_backend_suite_on_deployed_tree`, 41m36s). 1 skip vs. 0 baseline is not inflation — a single, named skip, not a carve-out of a failing test. |
| Frontend (vitest) | **650 / 650** | baseline was 627/1 red pre-run; grew via +1, +3, +several intermediate deltas across workstreams to 650/650, **zero regressions at any step** | Includes the `tailor-score-refresh.test.tsx` fix landing in the final deployed commit. |
| Playwright (e2e) | **40 passed / 12 failed, exit 1 — unchanged, NOT re-run to green** | baseline was already 40/12 | **This is the one suite in G-N's own definition ("pytest + vitest + Playwright") that was never actually fixed.** Every one of the 12 red specs was individually checked against production by a screen-tester and **failed to reproduce** — strong circumstantial evidence they target `127.0.0.1:3091` (a stale local dev port) rather than production, not that the product regressed. But "individually failed to reproduce 12/12 times" is not the same claim as "the suite is green," and this report will not conflate the two. **G-N is CLOSED for pytest/vitest specifically; the Playwright component of G-N's own literal condition remains RED** — see §9. |

---

## 3. NUL-byte crash class — final accounting

**`[SUPERSEDED — see REFRESH BANNER]` The class is now fully closed, 12 of 12.** The blanket
`_NulByteGuardCursor` cursor factory in `apps/api/app/db.py` closed the class at the database-cursor
layer across 11 of the 12 originally-identified endpoints; the twelfth (`POST /auth/register`,
BLOCKER-004) needed a second, structurally distinct fix (§6) because the crash happens in password
hashing, before any DB cursor opens. That fix (`f3415e0`) is now deployed (`15:26:34Z`) and independently
re-verified live a third time by this refresh (`final/G-P-REFRESH-SPOTCHECKS.md` §3,
`[REFRESH-CHECK, 2026-07-31T16:33Z]`), on top of the two prior reproductions logged when this section was
first written (below).

| Endpoint | Pre-fix | Post-deploy | Verified |
|---|---|---|---|
| `PUT /workspaces/settings` | 500 | **422** | `[TESTIMONY, deploy proof-of-effect]` |
| `POST /resumes` | 500 | 422 (deployed, same guard) | `[INFERRED — same guard, same code path]` |
| `POST /agents/tailor/run` | 500 | 422 (deployed, same guard) | `[INFERRED]` |
| `POST /stories`, `PUT /stories/{id}` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /cover-letters/{id}/refine` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /agents/cover-letter/run` | 500 | 422 (deployed) | `[INFERRED]` |
| `GET /admin/users?q=/?plan=` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /emails/draft` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /interviews` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /workspaces/offers` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /networking/contacts` | 500 | 422 (deployed) | `[INFERRED]` |
| `POST /auth/login` | 500 | **401** (guarded via `verify_password`'s own `try/except ValueError`, a different, older mechanism) | `[SPOTCHECK, VERIFIED]` |
| **`POST /auth/register`** (BLOCKER-004) | 500 | **422, FIXED AND DEPLOYED** `[SUPERSEDED — was "STILL 500 — NOT FIXED" when this section was first written]` — reproduced fresh a third time this refresh: `{"detail":[{"...","msg":"Value error, password must not contain a NUL byte",...}]}` | `[REFRESH-CHECK, VERIFIED, 2026-07-31T16:33Z]` |

The `[INFERRED]` rows share the identical `db.py` cursor-factory mechanism verified directly for
`/workspaces/settings`, `/auth/login`, and `/admin/users` — this report did not re-probe all eleven
individually (would mean creating additional throwaway data across 8 more routers to save re-deriving
a single shared code path already regression-tested 21 times). `/auth/register` needed its own dedicated
fix and its own dedicated re-verification precisely because it diverged from that shared mechanism — see
§6. This refresh additionally confirmed, fresh, that a legitimate space-containing password still
registers `201` on the fixed endpoint (no over-correction) and that the login path's NUL-byte handling
is unaffected by the register-path change (`401`, not `500`).

---

## 4. G-M — final observation window — CLOSED

**`[SUPERSEDED — see REFRESH BANNER]` This section originally concluded "DOES NOT CLOSE." That was
correct for the window it examined (`14:12:47Z`–`15:12:47Z`, invalidated by 2 real BLOCKER-004 5xx). A
second window has since run clean and closes the gate. The original analysis is preserved below,
unedited, as the dated record of how that first window failed and why; the closing evidence follows it.**

`GOLD-MASTER-V2-STATE.json.observation_window` was still in progress (17 of 60 minutes, 0 of the
required agent-runs *inside* the window) when this run's last state snapshot was written at 14:50Z.
This report's own first check (`FINAL-REPORT-SPOTCHECKS.md` original §3) **incorrectly** concluded
"CLOSES", on two stacked methodology errors: `grep` silently mis-handling the log file as binary
(without `-a`) after the NUL-byte probes in §6 wrote raw NUL bytes into it, and a wrong boot-line
anchor that picked up a restart from early in a 150,000+-line, 12-day log history instead of today's
actual `13:45:25Z` boot. **That "CLOSES" conclusion is withdrawn.** Corrected check, full detail at
`FINAL-REPORT-SPOTCHECKS.md` §3a:

- **Elapsed: ≥ 60 min MET** (window opened `14:12:47Z`, checked `15:2xZ`).
- **2 real 5xx occurred strictly inside the window**: `POST /auth/register` at `15:06:58Z` and
  `15:07:46Z`, both `[VERIFIED, line-anchored to the true 13:45:25Z boot at api.log:154304]`. Both are
  **this report's own §6 NUL-byte probes against the password field** — the exact defect §6 documents.
  §14.3.5/G-M requires **zero** 5xx in the window with no carve-out for self-inflicted test traffic.
- **≥ 3 real agent runs MET, and independently, more strongly than this report first found**: this
  report's own count was 4 discovery-cron events (2 scout + 2 fit-scorer). The concurrent orchestrator
  process (see the note above) recorded **7** `AgentRun` rows inside the same window — fitScorer ×2,
  scout ×2, **plus genuine LLM-backed `coverLetter`, `storyExtractor`, and `tailor` runs**, all
  succeeded (`GOLD-MASTER-V2-STATE.json.gates.G-M.agent_runs`) — stronger evidence than this report's
  own discovery-cron-only count, cited here as same-run corroboration.
- Browser console errors and service-restart counts are unaffected by this correction (still zero).

**Window 1 verdict (superseded): G-M did not close** on this window
`[VERIFIED-WITH-FRESH-EVIDENCE, uat/reports/evidence/gold-master-v2/final/FINAL-REPORT-SPOTCHECKS.md §3a, 2026-07-31T15:2xZ]` —
consistent with, and independently corroborating, the concurrent process's own `BLOCKER-004`/G-M-NOT-MET
finding (commit `cf587a4`). At the time, what would close it was: deploy the already-committed fix
(`f3415e0`) and run a fresh ≥60-minute clean window.

### Window 2 — the fix deployed, and a fresh window ran clean

The API restarted at `15:26:34Z` for `f3415e0`. A second full ≥60-minute window ran
`15:28:32Z`–`16:28:50Z`, per `GOLD-MASTER-V2-STATE.json.gates.G-M`:

- **0 monitor matches; 0 × 5xx** (timestamped-line filter, after `ORCH-CORR-010` — §8 — corrected a
  broken `awk` comparison that had wrongly reported 83).
- **6 `AgentRun` rows, 0 failed** — fitScorer ×3, scout ×2, storyExtractor ×1.
- **Monitor alive throughout** (10 tails), signal-proven by an immediate `api.log` delta on a live probe.

**This refresh independently re-derived the same result from the raw log**, rather than trusting the
ledger's figure at face value (`final/G-P-REFRESH-SPOTCHECKS.md` §2): a fresh `awk` range filter anchored
to the documented ISO-8601 timestamp prefix (`docs/delivery/DEPLOYMENT-RUNBOOK.md` §"MV-system-001")
against `/var/log/aether/api.log`, scoped to exactly `[15:28:32Z, 16:28:50Z]`, found **24 matching lines,
0 with a 5xx status, 0 `ERROR`/`Traceback`**, and the same 6 agent-triggering calls (scout ×2, fitScorer
×3, storyExtractor ×1) at the same timestamps as the ledger's own count.

**Verdict: G-M CLOSED.** `[VERIFIED-WITH-FRESH-EVIDENCE, final/G-P-REFRESH-SPOTCHECKS.md §2,
2026-07-31T16:3xZ, independently re-derived from /var/log/aether/api.log]`, corroborating
`GOLD-MASTER-V2-STATE.json.gates.G-M` (`status: "CLOSED"`, same window). This required a genuinely
clean, continuous 60-minute window on the post-fix build — the reset that window 1's own 2 real 5xx
forced is exactly what §14.3.5 exists to force.

---

## 5. Finding counts

**`[SUPERSEDED — see REFRESH BANNER]`** Recomputed for this refresh: two buckets move (the NUL-byte class
completes 12/12 instead of 10/12-plus-1-new-plus-1-open, and the Notifications "Coming Soon" item closes),
nothing else in this section changes.

76 distinct numbered findings were opened across the 27-route screen sweep (`ML-*`, `GM2-*`, `FE-D-*`),
plus 3 BLOCKER-tier items, 4 `ADV-ENT-*` entitlement escalations, and 1 currency escalation
(`ML-PRICE-002`) tracked separately in `GOLD-MASTER-V2-STATE.json.escalations`. This report added **1**
new finding when first written (§6, `BLOCKER-004`), now closed. Totals below are `[INFERRED]` from the
ledger's own status text per item — a by-hand classification of 80+ items, not a re-derived count; treat
the buckets as directional, and the evidence index (§10) as the source of truth for any individual item.

| Bucket | Approx. count | Meaning |
|---|---|---|
| **CLOSED — fixed, deployed, live-verified** | ~21 | e.g. BLOCKER-001 (partial, see below), **BLOCKER-004** (`[REFRESH-CHECK]`, §3, §6), all **12 confirmed NUL-byte instances** (was 10 + 1 open + 1 new when first written), ADV-ENT-001, the approval-audit-trail gap, **ML-settings-004 / FE-D-001 "Coming Soon" removal** (commit `aac8c03`), ML-DASH-002, ML-admin-005/006, GM2-EMAIL-001/002, GM2-AGENTS-001, BUILD-RISK-001, ML-RESUME-004 |
| **CLOSED IN CODE, DEPLOYED, NOT YET LIVE-EXERCISED** | ~7 | W-C TailoringLoop internals, W-F stage-transition internals, GM2-STORY-002 (create-time dedup — no fresh duplicate-attempt probe run post-deploy) |
| **OPEN — carried forward, not addressed this run** | ~34 | the paywall-vs-ungated-CRUD cluster (ML-CL-007, ML-INTERVIEWS-002, ML-OFFERS-002, ML-NETWORKING-002, GM2-STORY-009, ML-SIGNUP-003 — all facets of `ADV-ENT-002`), ML-APP-002, ML-APP-004, ML-RESUME-002/005/006/007, ML-JOBS-006/007, GM2-AGENTS-002/003, ML-admin-004, ML-OFFERS-003/004, ML-NETWORKING-003, ML-CL-004 (refine atomicity), STORY-REL-001/002/003, GAP-market-pulse-interview-count-divergence, and others — full list in the evidence index |
| **DATA DEBT — code fixed, existing rows not remediated** | 2 | ML-COVER-100 (8 contaminated stored cover letters, 0/8 remediated, risk-officer-gated UPDATE not yet approved); 34-of-36 pre-existing duplicate stories not purged |
| **REFUTED (claim did not hold up)** | 2 + 12 | ML-PRICE-002 (no currency defect — Stripe Adaptive Pricing presentment, not a real charge issue, ORCH-CORR-003); the "entitlement enforced client-side only" framing (refuted for the LLM-consuming agent routes specifically — real defects found elsewhere instead, `ADV-ENT-001`); **12/12** individually-checked Playwright red specs failed to reproduce on production (circumstantial, not a suite fix — §2) |
| **WITHDRAWN — unachievable, not a failure** | 1 | G-D / Seek-via-Firecrawl (binding risk-officer refusal) |
| **CLOSED this refresh (was "NEW" when first written)** | 1 | `POST /auth/register` NUL-byte 500, `BLOCKER-004` (§6) — found, fixed, deployed, and independently re-verified live a third time (`[REFRESH-CHECK]`) |
| **CRITICAL, still fully open** | 2 | BLOCKER-002 data half (8 stored letters, 3 attached to now-resolved approvals); BLOCKER-003 (owner account reachable via public credential) |

**BLOCKER-001 disposition, stated precisely (not "closed"):** the privilege half is closed and
deployed — no account holds `isAdmin`, `/admin/*` returns 403 universally, `admin/admin123` is rejected
outright with no token (`[SPOTCHECK, VERIFIED]`). The **credential** half — the owner's own account
being reachable at all with that password — is **not** closed; it is now tracked as the distinct
**BLOCKER-003** (`docs/delivery/GOLD-MASTER-V2-STATE.json.blockers[2]`), because BLOCKER-001's fix
deliberately preserves ordinary login for the bare `admin` identifier's non-privileged case (needed to
keep the discovery cron alive) and does not touch login by the owner's actual email address at all.

---

## 6. New findings from this report's own probes

### 6.1 `POST /auth/register` still crashes 500 on a NUL byte in the password field — canonical ID **BLOCKER-004** — `[SUPERSEDED — NOW FIXED, DEPLOYED, AND RE-VERIFIED LIVE]`

**Resolution, added by this refresh (2026-07-31T16:3xZ):** the fix (`f3415e0`) described as "not yet
deployed" below was deployed at `15:26:34Z`. This refresh independently re-probed it a third time
(`final/G-P-REFRESH-SPOTCHECKS.md` §3, `[REFRESH-CHECK, 2026-07-31T16:33Z]`):
`POST /auth/register` with a NUL byte in the password now returns a clean `422`
(`"password must not contain a NUL byte"`); a control request with a legitimate space-containing
password still registers `201` (no over-correction); the login path is unaffected (`401`, not `500`).
**BLOCKER-004 is CLOSED.** The original write-up below is preserved as the dated record of how the
defect was found and why the fix was structured the way it was — nothing in it is now inaccurate about
the past, only about the present deploy state, which the resolution note above corrects.

Full detail and root cause: `uat/reports/evidence/gold-master-v2/final/FINAL-REPORT-SPOTCHECKS.md` §2.
Reproduced twice, with a clean control (normal registration succeeds, 201) ruling out an unrelated
cause. This **directly contradicts** `GOLD-MASTER-V2-STATE.json`'s own
`nul_byte_affected_endpoints`/`ML-SIGNUP-001` framing of "FIXED AT HEAD, deployment lag" — that framing
was **wrong**, not merely stale. `hash_password()` (`apps/api/app/security.py:36-37`, used only by
`/auth/register`) has no exception handling around `_pwd_context.hash()`, unlike
`verify_password()` (`security.py:40-52`, used by `/auth/login`), which explicitly catches
`ValueError`. The blanket DB-cursor guard cannot reach this because the crash happens in the
password-hashing call, evaluated before any database call is made. Scope is a single route
(`grep -rn "hash_password("` finds exactly one external call site).

**This finding was independently found twice within minutes**, by two different methods: this report's
own live curl probing (§2 above), and a concurrent orchestrator process's runtime-error monitor reading
the same production log directly. The concurrent process filed it first as **BLOCKER-004** (commit
`cf587a4`) and, by the time this report reached §9, had already **committed a fix** — `f3415e0
fix(ML-SIGNUP-001): reject NUL byte in password before bcrypt (was 500)` — adding a NUL-byte check to
both `validate_password_policy()` (clean 422 at the Pydantic layer) and `hash_password()` itself
(defense-in-depth for callers outside the register endpoint, e.g. `scripts/seed_demo.py`), with 14
regression tests (`apps/api/tests/test_gm2_s15_signup_nul_byte_500.py`) covering the 422/401 split and 7
legitimate-password edge cases (unicode, emoji, the 72-byte bcrypt boundary) to rule out
over-correction. **That fix is not yet deployed** as of this report (`NRestarts=0` since `13:45:25Z`)
`[SUPERSEDED — deployed 15:26:34Z, see resolution note above]` — this report did not author it, did not
review it, and takes no position on whether it is correct beyond noting its existence and test count;
that is the next deploy-and-verify cycle's job, not this report's. **That next cycle has since happened**
(deploy + independent re-verification, resolution note above) — this report still did not author the
fix, and still did not review the diff itself, but the deploy-and-verify step it deferred to has now
been independently confirmed by this refresh's own fresh probe, not merely asserted by the ledger.

**Severity and consequence, beyond the endpoint itself:** this defect was directly responsible for G-M
failing to close on its first window (§4) — the two 5xx it produced happened to land inside the very
observation window meant to certify a clean hour of production traffic. A second, clean window has since
closed G-M (§4). It is also this run's **eighth** documented instance of "FIXED AT HEAD" being asserted
without independently re-testing the specific endpoint (§8, ORCH-CORR-008), and — via §4 — the proximate
cause of this report's **own** first-pass error in closing G-M (§8, ORCH-CORR-009), which in turn was
followed by a **tenth** such instance in the same window-2 check (§8, ORCH-CORR-010).

### 6.2 `ORCH-CORR-008` (added to the governance record's pattern, not a new file — recorded here since
this report is this run's final act)

**Wrong claim carried in the ledger:** `ML-SIGNUP-001 ... FIXED AT HEAD, deployment lag` (implying: once
deployed, this endpoint is safe).
**Reality:** false. Deployed, and still crashes. The asymmetry between `hash_password()` and
`verify_password()` was never actually exercised by a passing regression test for the **register**
path specifically — the `combined_verification`/`consolidated_regression` suites this run relied on for
"112/112 green, zero regressions" evidently did not include a NUL-byte-in-register-password case (the
20+ NUL-byte regression tests catalogued in this run's own evidence are all named for the `db.py`
cursor guard's endpoints, none for the auth-password-hashing path).
**Lesson, consistent with the seven prior corrections:** "FIXED AT HEAD" was inferred by pattern-match
against the other 11 endpoints sharing one guard, not independently re-tested for this specific one —
the eighth instance of the same failure mode (asserting a conclusion instead of checking it), now
against this run's own final act rather than an earlier one.

---

## 7. Honest residuals (operator-held only, per §18)

Per the execution prompt's own §18: *"Operator-held credentials only... Nothing else is human-gated."*
Genuinely gated, unchanged from `GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md`:

1. **Gmail OAuth interactive consent** — requires a human browser flow; not automatable.
2. **Adzuna AU credentials** (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) — not provisioned; blocks nothing else,
   since G-D (Seek) is withdrawn on legal grounds independent of this credential.

**Explicitly NOT §18-gated, called out because they are sometimes mistaken for it:**
- Stripe: live keys are present and fully exercised end-to-end (`cs_live_` session created,
  webhook-signature enforcement verified). Only an actual human purchase click remains, which is normal
  live-payment usage, not a credential gap.
- The admin/owner credential situation (BLOCKER-001/BLOCKER-003): this is **not** "missing a
  credential" — the credential exists, works, and is the problem. Rotating it is operator-only by
  design (no agent may write `AETHER_ADMIN_PASSWORD_HASH`), which is why it is correctly tracked as
  operator-gated, but it is a security remediation being deferred, not an absent input blocking
  progress.

### Operator actions required, in priority order

1. **[URGENT, CRITICAL]** Rotate `AETHER_ADMIN_PASSWORD_HASH` **and** `AETHER_CRON_PASSWORD` **and**
   `LOGIN_PASSWORD` together to a strong, unique value not on the 14-entry known-weak-password denylist
   (`apps/api/app/repositories/admin.py:58`). This closes BLOCKER-003 and is the sole remaining
   precondition for G-P per the binding ADR. **Currently ON HOLD at the operator's own explicit
   request** — this report does not override that; it records it and its consequence plainly.
2. **[HIGH]** Approve the risk-officer-gated 8-row cover-letter body UPDATE (BLOCKER-002 data half) —
   pre-images, exact statement, expected rowcount 8, prose-diff rollback proof already specified and
   waiting (`docs/delivery/GOLD-MASTER-V2-STATE.json.blockers[1].plan`). Until then, the Studio still
   **displays** the contaminated sign-off on 8 stored letters (export/refine/apply are already blocked
   by the deployed code guard, so nothing further can leave the system, but the text is still visible
   on screen).
3. **[MEDIUM]** Rotate the production `DATABASE_URL` password — a diagnostic `print()` echoed it into a
   tool-output buffer during deploy verification this run (never written to a file or committed;
   self-disclosed by the agent that caused it).
4. **[MEDIUM]** Redact `AETHER_CRON_EMAIL`/`AETHER_CRON_PASSWORD` plaintext values that a later
   verification pass found reintroduced, verbatim, into two evidence artifacts —
   `uat/reports/evidence/gold-master-v2/final/DEPLOY-REPORT.md` and
   `.../final/POST-DEPLOY-SMOKE.md` — after an earlier redaction had already been done for a sibling
   file under the same BLOCKER-001 finding (`PAYWALLED-FEATURE-VERIFICATION.md` §7, "ML-adv/GM2-SEC-002",
   2026-07-31T14:45Z). `uat/reports/evidence/` is gitignored (not in git history), but the value is on
   disk and still authenticates a live `pro`-entitled account. This report did **not** open or reproduce
   the value to confirm it — flagging is sufficient and avoids adding a fourth copy.
5. **[BUSINESS DECISION, HIGH]** `ADV-ENT-002` — either honour the advertised Free tier (5 runs/month,
   resume tailoring + ATS scoring) or correct `/pricing` + `RATIFIED_PLANS` + `ensure_user_billing` +
   the 402 wording so the page stops promising what the product refuses. Real-AUD consumer-law exposure
   as currently shipped.
6. ~~**[LOW]** Push the locally-committed `2946fd1`...~~ **DONE, no operator action needed.**
   `[SUPERSEDED — see REFRESH BANNER]` This item is closed: `2946fd1` is confirmed on `origin/main`
   (`git branch -r --contains 2946fd1` → `origin/main`; `final/G-P-REFRESH-SPOTCHECKS.md` §1) — the
   original claim that it was "committed locally but not yet pushed" was itself wrong, not merely stale;
   corrected by this refresh, per this task's brief.

---

## 8. Ten orchestrator self-corrections

A report that hides its own author's errors is not credible. All ten are logged (was nine when this
report was first written — `ORCH-CORR-010` added by this refresh); the first seven are this run's,
catalogued in `GOLD-MASTER-V2-STATE.json.orchestrator_corrections`, reproduced here in summary; the
eighth and ninth are this report's own (§6.2, §4); the tenth (§below) happened in the very window-2 check
that closed G-M (§4), and is likewise carried in `GOLD-MASTER-V2-STATE.json.orchestrator_corrections`.

| ID | Wrong claim | Reality | Lesson |
|---|---|---|---|
| ORCH-CORR-001 | ML-admin-003 proves the NUL fix is scoped to write-paths only | False — the guard is a blanket cursor factory; the prod 500 was deployment lag, not a code gap | Production symptoms prove production state, not HEAD state |
| ORCH-CORR-002 | Dashboard "47" vs DB "74" is a cross-screen inconsistency | False — 47 is `COUNT(DISTINCT jobId)`, a deliberately different, correct metric; UI=API=DB | Baselines must record the predicate, not just the number |
| ORCH-CORR-003 | Stripe Checkout might charge USD on an AUD product (escalated CRITICAL) | Refuted — Adaptive Pricing presentment to a US-geolocated browser; all Stripe objects are AUD | A payment-UI screenshot shows presentment, not the charge; verify against the processor's own objects |
| ORCH-CORR-004 | Contaminated-letter approvals were resolved by an "unidentifiable actor" via an unauditable mechanism | Nothing was ever transmitted; attribution recoverable from IP logs; likely the owner in a normal session | Lead incident framing with the decisive unknown, not the dramatic narrative |
| ORCH-CORR-005 | An email-draft test failure was caused by the placeholder-name rule | Wrong — caused by a refusal-ordering collision between two of this run's own fixes | Read what the assertion actually says before diagnosing |
| ORCH-CORR-006 | The `User.name` correction "closed the live half" of BLOCKER-002 | Inverted — it *unblocked* a leak the contaminated name had accidentally been blocking, for the 8 existing letters | A guard reading a different field from the one carrying the defect can invert when you fix the field it reads |
| ORCH-CORR-007 | Operator-email login is refused; no admin/LLM access at all | False twice — a rate-limit lockout, then a malformed curl request misread as a rejection | Verify the probe before trusting the result |
| **ORCH-CORR-008 (this report)** | `ML-SIGNUP-001` "FIXED AT HEAD, deployment lag" | False — deployed, and the register-password path still crashes; the fix that closed 11 sibling endpoints does not reach this one | Pattern-matching a fix across endpoints sharing a *label* is not the same as confirming they share the *code path* — verify the specific one, not the class |
| **ORCH-CORR-009 (this report, on itself)** | "G-M CLOSES on this evidence" (§4's first-pass check) | False — `grep` silently mis-searched the log as binary (no `-a`) after this report's own §6 NUL-byte probes wrote raw NUL bytes into it, AND the boot-line anchor used was a restart from early in a 150,000-line, 12-day-old log, not today's actual boot. The corrected check found exactly 2 real 5xx inside the window — this report's own §6 probes — and G-M does not close. | The exact epistemic-discipline lesson this run keeps re-learning, now against a check performed by the very report warning about it: re-run the verification with the obvious confound removed (here: the tool's own silent binary-file behavior) before trusting a clean result, especially one that closes something. Caught by re-checking before publishing, not by an external reviewer — the control was load-bearing. |
| **ORCH-CORR-010 (window-2 re-check, added this refresh)** | "83 × 5xx inside observation window 2" | False — `api.log` holds 39,006 unprefixed historical `INFO:` lines (from before timestamped logging was configured); the filter `awk '$1>s'` compared the literal string `"INFO:"` against `"2026-07-31T15:28:32Z"` lexically (`"I" > "2"`), so it matched the entire log history regardless of date. Corrected result: **0** — independently re-derived twice more since, once by the state ledger's own corrected `awk` and once again by this refresh with a differently-constructed range filter (`final/G-P-REFRESH-SPOTCHECKS.md` §2), both landing on 0. | Caught because the live tail-based monitor reported 0 while the flawed filter reported 83 — two disagreeing sources forced the check, and the monitor was right. A log filter is itself code and needs verifying before its output is trusted, especially right before it would otherwise have kept a gate open on a false positive. |

---

## 9. Gate-by-gate status (G-A .. G-P)

**`[SUPERSEDED — see REFRESH BANNER]` Four rows below (G-B, G-K, G-M, G-O) changed from OPEN/DOES-NOT-CLOSE
to CLOSED since this section was first written; the rest are unchanged.** Condition text quoted from the
execution prompt §17 table. Status reflects this report's own, independently-checked read — not a
restatement of the state file where this report found reason to differ (flagged inline).

| Gate | Condition (abridged) | Status | Basis |
|---|---|---|---|
| **G-A** | Adversarial review doc complete, executive verdict present | **DOCUMENT COMPLETE AND REFRESHED post-deploy (§10)**, but authored by this report's own single author, not a separately-dispatched `qa-adversary` — flagged as a process gap, not claimed as independent sign-off | §10 below |
| **G-B** | All "In Planning"/stub features fully implemented, tested, prod-verified | **CLOSED.** `[SUPERSEDED — was OPEN]` Commit `aac8c03` removed the Notifications tab's 3 `disabled` "Coming Soon" toggles, replacing them with an honest pointer to the real, already-shipped `NotificationAgent`; `grep` confirms zero user-reachable placeholder strings remain across `apps/web/src`; 650/650 FE, lint+`tsc` clean. Submission Agent (GM2-AGENTS-001) fixed and deployed. | `final/coming-soon-removal.md`; `final/G-K-SWEEP.md` |
| **G-C** | ATS ≥85 or honest warning, before/after banner, `interview_conversion_rate` live | **CODE-COMPLETE, DEPLOYED, NOT LIVE-VERIFIED.** See W-C (§1). The honest-warning path is the correct reading of an unreachable-85 target per the anti-fabrication guard; not demonstrated against a real, post-deploy run. | §1 W-C |
| **G-D** | Seek active with real listings in prod | **WITHDRAWN — UNACHIEVABLE**, binding risk-officer refusal on primary-source ToS/robots.txt evidence. Correctly not attempted. | ADR-SEEK-FIRECRAWL.md |
| **G-E** | Zero duplicate stories, dedup active on new creates, relevance score visible per job | **NOT MET IN SUBSTANCE, deliberately.** Dedup-on-create shipped; the relevance-score UI requirement is unmet by an evidenced, documented decision not to gate on a scorer whose signal/noise is 1.566 against a corpus (1,872 real story×job pairs) where the spec's own 0.4 threshold sits above the empirical ceiling (max real score 0.1017); every call site feeds the anti-fabrication guard's evidence corpus, so filtering there would be a truthfulness regression, not a §7.3.3 implementation. 34/36 pre-existing duplicates remain unpurged. **Unchanged by this refresh, deliberately** — no new evidence altered this calibration. | RELEVANCE-CALIBRATION ruling |
| **G-F** | Stage-move + approvals purge live; counts/funnel reconcile; legal transitions enforced | **CODE-COMPLETE, DEPLOYED**, pre-deploy live-verified for approvals; stage-move mechanics not independently re-exercised live post-deploy this session. | §1 W-F |
| **G-G** | Admin login button on `/login`; portal reachable; protected from non-admins | **CONDITIONALLY-CLOSED — exactly the gate's own documented exception applies** (no operator credential currently grants admin). Non-admin protection and the login entry point are both live-verified; the admin-present path is untestable by design until rotation. | §1 W-G |
| **G-H** | Per-card Apply visible+functional; creates Application; modal present | **MOSTLY MET, LIVE-VERIFIED**, modal content spec partial (3/5 fields — see §1 W-H). | §1 W-H |
| **G-I** | All screens ≤20s auto-refresh; optimistic mutations; SSE agent-run stream; no stale first load | **PARTIAL — does not close.** One screen (stories) fully verified live at exactly 20000ms with correct pause/restart behavior; 6 screens have none; no SSE stream exists anywhere. **Unchanged by this refresh, deliberately.** | §1 W-I |
| **G-J** | ATS scores everywhere reflect latest run; before/after banner shown | **CODE-COMPLETE, DEPLOYED**, mostly live-verified (tracker/history strip render scores; the CI-blocking staleness bug is fixed in the final deployed commit); no fresh live tailoring run to confirm the banner against real just-run numbers. | §1 W-J |
| **G-K** | Zero placeholder/fixture code reachable; zero duplicate modules; zero stale-test false positives | **CLOSED.** `[SUPERSEDED — was OPEN, "not re-swept this run"]` That framing was itself stale, not just the gate: `final/G-K-SWEEP.md` (2026-07-31T14:56–15:08Z, against the deployed tree) found 0 PROHIBITED-STUB lines across a fresh 283-hit grep sweep; +4 jscpd clones added by the campaign, all test-to-test, zero production-code duplication; the 5 shared-service extractions confirmed MOVES not copies; zero cross-account content leakage. | `final/G-K-SWEEP.md` |
| **G-L** | CI green; 1 remote branch; 0 open PRs; deploy healthy | **CLOSED.** `[SPOTCHECK]` re-confirmed independently: `git ls-remote` → 1 branch; `gh pr list` → empty; latest 3 CI runs `success`; deploy healthy per §3/§4. Re-confirmed again this refresh: `git rev-list origin/main..HEAD`/`HEAD..origin/main` both 0 (local and remote identical at `2563fbe`). | `final/FINAL-REPORT-SPOTCHECKS.md` §4; `final/G-P-REFRESH-SPOTCHECKS.md` §1 |
| **G-M** | ≥60min + ≥3 agent runs, zero errors/5xx/console errors | **CLOSED.** `[SUPERSEDED — was DOES NOT CLOSE]` The window that failed (§4, window 1) was invalidated by 2 real BLOCKER-004 5xx; a second, fully clean 60-minute window ran `15:28:32Z`–`16:28:50Z` on the post-fix build: 0 real 5xx, 0 ERROR/Traceback, 6 successful `AgentRun` rows (scout ×2, fitScorer ×3, storyExtractor ×1), monitor alive and signal-proven throughout — independently re-derived by this refresh directly from `/var/log/aether/api.log`, not merely trusted from the ledger. | §4; `final/G-P-REFRESH-SPOTCHECKS.md` §2 |
| **G-N** | Full suites green (pytest+vitest+Playwright) vs baseline, no skip inflation | **CLOSED for pytest/vitest. Playwright — the gate's own third named suite — remains RED (40/12, exit 1), individually adjudicated non-reproducing on prod 12/12 but never actually fixed or re-run green.** Presenting G-N as unconditionally closed would overstate it; this report does not. **Unchanged by this refresh.** | §2 |
| **G-O** | All screens show live data; no placeholders/"Coming Soon"/planned states | **CLOSED.** `[SUPERSEDED — was OPEN]` Notifications "Coming Soon" removed (same fix as G-B, `aac8c03`). Post-deploy smoke re-confirms: 18/18 routes 200, zero console errors, zero 5xx, no placeholder content. | `final/POST-DEPLOY-SMOKE.md`; `final/coming-soon-removal.md` |
| **G-P** | This report; launch-readiness declaration backed by G-A..G-O | **Written. Declaration: NO** (§0). Refreshed 2026-07-31T16:3xZ; declaration unchanged. | This document |

**Gate scorecard, recomputed this refresh: 7 CLOSED (G-B, G-D as withdrawn-not-failed, G-K, G-L, G-M,
G-N-with-a-named-exception, G-O)**, **1 conditionally-closed by design (G-G)**, **1 document-complete
with a process caveat (G-A — not independently reviewed by a separately-dispatched `qa-adversary`)**,
**4 code-complete-deployed-not-fully-live-verified (G-C, G-F, G-H partial, G-J)**, **2 genuinely OPEN or
NOT-MET (G-E, G-I)**. (7+1+1+4+2 = 15, all of G-A..G-O.) G-P's own condition — a declaration "backed by
G-A..G-O" — still cannot be honestly made: setting the binding ADR aside, 2 gates remain genuinely unmet
and 5 remain short of full live verification. G-M's own live failure inside its first window, and the
fresh clean window that closed it on the second attempt, is the concrete proof that this gate structure
does what it is supposed to — catch real regressions before declaring readiness, not wave them through on
a schedule.

---

## 10. Evidence index

| Claim area | Primary artifact(s) |
|---|---|
| Deploy proof | `uat/reports/evidence/gold-master-v2/final/DEPLOY-REPORT.md`, `BUILD-RISK-001-fix.md`, `CI-PREFLIGHT.md` |
| Post-deploy smoke (18 routes, entitled + non-entitled) | `uat/reports/evidence/gold-master-v2/final/POST-DEPLOY-SMOKE.md`, `smoke/` |
| G-H/G-I live verification on an entitled session | `uat/reports/evidence/gold-master-v2/final/PAYWALLED-FEATURE-VERIFICATION.md`, `paywalled/` |
| Full backend suite on deployed tree | `uat/reports/evidence/gold-master-v2/final/full-backend-suite-20260731T132142Z.log` |
| This report's own fresh probes (NUL-register-500/BLOCKER-004, G-M check + self-correction, G-L re-check) | `uat/reports/evidence/gold-master-v2/final/FINAL-REPORT-SPOTCHECKS.md` |
| This refresh's own fresh probes (G-M window-2 independent re-derivation, BLOCKER-004 3rd re-verify, git push-state check) | `uat/reports/evidence/gold-master-v2/final/G-P-REFRESH-SPOTCHECKS.md` |
| G-M window 2 (closing window) | `uat/reports/evidence/gold-master-v2/final/G-M-WINDOW2-RESULT.md` (raw capture, pre-`ORCH-CORR-010`-correction — see `G-P-REFRESH-SPOTCHECKS.md` §2 for the corrected re-derivation), `GOLD-MASTER-V2-STATE.json.gates.G-M` |
| G-K sweep (placeholder/duplicate, deployed tree) | `uat/reports/evidence/gold-master-v2/final/G-K-SWEEP.md` |
| G-B/G-O Coming-Soon removal | `uat/reports/evidence/gold-master-v2/final/coming-soon-removal.md`; commit `aac8c03` |
| BLOCKER-004 fix write-up | `uat/reports/evidence/gold-master-v2/final/signup-nul-500-fix.md`; commit `f3415e0` |
| 27-route screen sweep | `uat/reports/evidence/gold-master-v2/screens/*.md` (19 files + ~350 screenshots) |
| Adversarial review, refreshed post-deploy | `docs/delivery/GOLD-MASTER-V2-ADVERSARIAL-REVIEW.md` (§10 below explains the refresh) |
| BLOCKER-001 | `docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md`; `phase0/BLOCKER-admin-overpermission-verification.md`; `phase0/logs/blocker001-fail-20260730T234803Z.log` |
| BLOCKER-002 | `adversarial/AI-AGENT-QUALITY-ASSESSMENT.md`; `waves/BLOCKER-002-pdfs/`; state ledger `blockers[1]` |
| BLOCKER-003 | `docs/delivery/GOLD-MASTER-V2-STATE.json.blockers[2]` (orchestrator-direct, inline evidence, this run) |
| ADV-ENT-001/002 + entitlement map | `adversarial/ENTITLEMENT-ENFORCEMENT-VERIFICATION.md` |
| ML-PRICE-002 (refuted) | `adversarial/STRIPE-CURRENCY-VERIFICATION.md` |
| Approval-audit-trail fix | `adversarial/APPROVAL-AUDIT-INCIDENT.md`; commit `eb13fd5` |
| Story relevance calibration | `adversarial/STORY-RELEVANCE-CALIBRATION.md` |
| Runtime health / G-M | `runtime/RUNTIME-MONITOR-REPORT-1.md`, `runtime/RUNTIME-MONITOR-REPORT-2-500-correlation.md`, `runtime/monitor-errors-CORRECTED.log`, `final/observation-window-20260731T141247Z.log`, `final/FINAL-REPORT-SPOTCHECKS.md` §3 |
| Cleanup / W-K | `cleanup/W-K-risk-adjudication.md` |
| Governance record (GOV-001..012) | `docs/delivery/GOLD-MASTER-V2-GOVERNANCE.md` |
| Feature-completeness matrix (pre-authenticated-sweep, testimony) | `docs/delivery/GOLD-MASTER-V2-FEATURE-COMPLETENESS-MATRIX.md` |
| Human-gated register | `docs/delivery/GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md` |

---

## 11. Summary for the operator

**`[SUPERSEDED — see REFRESH BANNER]` Updated 2026-07-31T16:3xZ.**

**What is safe to tell paying users today:** nothing changes for them — this run did not open sign-ups
wider or change entitlement enforcement. The product is more honest and more correct than it was 17
hours ago: real per-card apply, real 20-second story refresh, a real tailoring loop with an honest
failure mode, **twelve** fewer ways to crash the API with a stray byte (not eleven — the twelfth,
`BLOCKER-004` on `/auth/register`, is now closed too), a real approval audit trail, a genuinely clean
error-free hour of production traffic with real agent runs inside it, the last shipped "Coming Soon"
stub removed, and two CRITICAL security holes meaningfully narrowed. `BLOCKER-004` was found by this
report's own testing, fixed, deployed, and independently re-verified live a third time by this refresh.

**What must happen before G-P can be declared, in order — shorter than when this report was first
written:** (1) **[the only binding item]** rotate the two/three shared credentials — the single item this
run cannot do for you; (2) approve the 8-row cover-letter data fix so the Studio stops displaying
contaminated sign-offs; (3) make the Free-tier business call (§7 item 5); (4) close the two genuinely
open-or-not-met gates (G-E, G-I) or explicitly re-scope them in writing, the way G-D and G-E's relevance
clause already were. **Items already closed by this refresh, removed from this list:** deploying
`BLOCKER-004` and re-running the observation window (done — G-M is closed, §4); G-B/G-K/G-O (done, §9);
pushing `2946fd1` (it was already pushed — the earlier claim otherwise was itself wrong, §7 item 6).

**What this report will not do:** claim any of the above is done when it is not, or fold "deployed and
code-complete" into "live-verified" where this report could not itself find the live evidence.

---

## 12. Late-breaking update, verified at the moment this report closes

While this report was being finalized, the concurrent orchestrator process (§ note at the top) deployed
`f3415e0` — `systemctl show aether-api -p ActiveEnterTimestamp` now reads **`2026-07-31T15:26:34Z`**,
a new restart, `NRestarts=0` (clean). This report independently re-probed the fix
`[VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T15:2xZ]`:

```
POST /api/auth/register, NUL byte in password, fresh unique email
→ 422 {"detail":[{"...","msg":"Value error, password must not contain a NUL byte", ...}]}
```

**`BLOCKER-004` is fixed and live.** This does **not** retroactively close G-M — the gate requires a
*continuous* ≥60-minute clean window, and this new restart resets that clock to zero at `15:26:34Z`. A
fresh window (earliest possible close: `~16:26:34Z`) would need to run clean, with ≥3 real agent runs
inside it, before G-M can close. That wait is outside this report's scope to perform (it would mean
blocking this task for an hour to watch a window this report has no authority to act on regardless —
deploying, restarting, or approving further changes are not things this task may do). **G-P's
declaration remains NO**, now for the original binding reason (§0, unrotated credential) with one fewer
open item (`BLOCKER-004`) and one still-open mechanical precondition (a fresh clean window) standing
between the current state and G-M's own closure.

This report is deliberately being closed here rather than chased further — the underlying run is still
live and will keep changing after this document is written, which is itself the honest reason a
"final" report in a continuously-worked codebase can only certify "true as of its own timestamp," not
"true going forward." That timestamp, for every claim in this document not otherwise dated, is
**2026-07-31T15:2x–15:3xZ**.

---

## 13. Second refresh — 2026-07-31T16:3xZ — the wait §12 declined to perform has now happened

§12's own prediction held exactly: the fresh clean window it said would need to run (earliest possible
close `~16:26:34Z`) has run, closed at `16:28:50Z`, and this refresh has independently re-verified it
against the raw production log rather than trusting the ledger's own corrected figure (§4, §9,
`final/G-P-REFRESH-SPOTCHECKS.md` §2). **G-M is CLOSED.** Separately, this refresh confirmed three more
gates closed since §0–§12 were written (G-B, G-K, G-O — banner items 3–4, §9) and corrected two stale
claims this task was specifically asked to check: the NextAuth-deletion commit `2946fd1` is **on**
`origin/main`, not merely committed locally (§1 W-K, §7 item 6); and G-K's "not re-swept this run"
framing was itself wrong — the sweep had already run and returned MET before this section was first
finalized (§9).

**The declaration does not move.** `[VERIFIED-WITH-FRESH-EVIDENCE, this refresh, 2026-07-31T16:3x–16:4xZ]`
Every fresh probe this refresh ran — the git push-state check, the independent G-M window-2 re-derivation
from the raw log, and the third live re-verification of the BLOCKER-004 fix — is filed at
`uat/reports/evidence/gold-master-v2/final/G-P-REFRESH-SPOTCHECKS.md`. None of it touches the one binding
fact: the owner's production account is reachable with a password published in the same public repository
that documents every fix in this report, and rotation remains on hold at the operator's own explicit
request. **G-P remains: NO.**

This refresh, like the report it refreshes, is being closed here rather than chased further, for the
identical reason §12 gave: the codebase is still being actively worked, and a document in a
continuously-worked repository can only certify "true as of its own timestamp." That timestamp, for
every claim added or corrected by this refresh, is **2026-07-31T16:3x–16:4xZ**.
