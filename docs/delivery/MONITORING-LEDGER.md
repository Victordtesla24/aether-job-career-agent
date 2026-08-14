# MONITORING-LEDGER — reconstructed

**Why this document exists:** `docs/delivery/ORCH-DELTA-2026-08-14.md:45` records: *"No
MONITORING-LEDGER.md exists in-repo (cited by 15+ comments); no fix evidence for these 4 [MON-002/
003/006/008] | MISSING | Recreate ledger; verify symptoms live; fix provable ones."* Grepping this
worktree (`apps/`, `docs/`, `scripts/`, tests) for `MON-0[0-9][0-9]` confirms the premise: **148
citation lines** across code comments, docstrings, and test filenames, referencing IDs MON-001
through MON-020, with **no tracked ledger file anywhere in this worktree** to look them up in.

## Source used to reconstruct this ledger

The canonical, actively-maintained ledger is **not missing from the project** — it exists at
`/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/market-perf/MONITORING-LEDGER.md`
(384 lines, last modified 2026-08-14T14:10, in a **sibling checkout of the same project**, a
directory outside this worktree). It is untracked/gitignored evidence output, which is why it does
not appear in `git log`/`git show` from this worktree and does not propagate across git worktrees
(worktrees share history, not untracked files). This document treats that file as the primary
source for symptom text and status, and **independently cross-checks every status claim against
this worktree's own code, tests, and merged commits** before recording FIXED — a status claim from
the source ledger alone, with no matching evidence in this worktree, is recorded as
**UNKNOWN-CONTENT / not independently verifiable here** rather than trusted at face value.

Method for cross-checks performed in this worktree:
- `grep -rn "MON-0NN"` across `apps/`, `scripts/`, `docs/` for citing comments (file:line quoted below)
- `find` for test files named `test_monNNN*` / `*monNNN*`
- `git branch -a` for `hotfix/mon-*` branches, then `git merge-base --is-ancestor <branch> HEAD` to
  confirm the fix actually landed on the branch this worktree is built from (`orch/exec-20260814`,
  HEAD `7be085a`)

---

## Ledger

| ID | Symptom | Status | Evidence |
|---|---|---|---|
| **MON-001** | `board_sweep` unbounded correlated-subquery read caused `psycopg2.QueryCanceled` — 100% sweep failure for one user, 96 occurrences historically | **FIXED** | Test `apps/api/tests/test_mon001_board_sweep_bounded_read.py` exists, no skip/xfail. Fix comments at `apps/api/app/workers/board_sweep.py` (14 citation lines in this worktree, e.g. lines documenting the bounded-read rewrite). 14 comment citations total in this worktree. |
| **MON-002** | Production `api.log` shows `googleapiclient` 403 `insufficientPermissions` on Calendar/Gmail-scoped calls, roughly every 2 minutes | **OPEN** | Only 1 citation in this worktree: `apps/api/scripts/send_missing_pieces_email.py:67` — *"Monitoring residuals MON-002/003/006/008..."* — an operator-facing draft-email listing it as unresolved. No handling code, no test, no fix commit found anywhere in this worktree. `ORCH-DELTA-2026-08-14.md:45` independently confirms "no fix evidence." |
| **MON-003** | `POST /approvals/{id}/approve` returning repeated 409s in rapid succession, suspected frontend double-submit | **OPEN** | Zero literal `MON-003` citations found in this worktree outside the same `send_missing_pieces_email.py:67` summary line. A double-submit guard does exist for a *different* endpoint family — `apps/api/app/routers/applications.py` (job-application submission, tested by `test_ml_w17_application_race_unique_index.py`) and `apps/api/app/routers/approvals.py:287` has related logic — but neither cites `MON-003` by name, so this cannot be confirmed as *the* fix for this specific finding. Treated as OPEN, unverified whether the existing approvals-router logic already happens to cover it. |
| **MON-004** | `discovery-cron` FATAL errors on service-restart races (HTTP 000), self-healing on retry | **FIXED** | Shell test `apps/api/tests/shell/test_mon004_discovery_cron_retry_backoff.sh` exists. Retry/backoff logic cited in `scripts/discovery_cron.sh` (3 citation lines in this worktree). |
| **MON-005** | Live JWT bearer token visible in `ps` argv via the discovery-cron `curl` invocation | **FIXED** | Shell test `apps/api/tests/shell/test_mon005_no_jwt_in_process_argv.sh` exists. Fix moves the token out of the command line (config-file based, per `scripts/discovery_cron.sh`, 5 citation lines in this worktree). |
| **MON-006** | `wellfound` job-board adapter returns HTTP 404 every cycle (source is gone); currently degrades gracefully but produces log noise | **OPEN** | Zero literal `MON-006` citations in this worktree outside the same `send_missing_pieces_email.py:67` line. No log-level change or adapter-disable code found. |
| **MON-007** | LLM 503 storm — wall-clock LLM budget exhaustion plus 402s from oversized `max_tokens`; `tailor` agent measured at 57.8% failure over a 14-day window in the source ledger | **UNKNOWN-CONTENT here / OPEN per source** | **Zero citations of `MON-007` anywhere in this worktree** (grepped `.py`/`.ts`/`.tsx`/`.sh`/`.md`, no hits). A real wall-clock LLM budget mechanism does exist — `apps/api/app/services/llm_client.py` (`shared_budget()`) — but it is not labeled `MON-007` anywhere, so it cannot be confirmed as *the* fix for this specific finding from this worktree's evidence alone. Recorded per the source ledger as still open/unclosed there (its own status table has no closed marker for this row). |
| **MON-008** | `apps/api/app/repositories/google_credential.py` — legacy `GoogleCredential` repository writes refresh/access tokens in **plaintext** | **OPEN** | Confirmed live in this worktree: `google_credential.py` (upsert/update paths write tokens unencrypted). Caveat worth flagging for the fix wave: `apps/api/app/repositories/gmail_account.py` calls a `_backfill_from_google_credential()`-style path into this table, so it is not a fully dead/unreachable code path — a fix must account for that backfill caller, not just delete the table. Cited in `send_missing_pieces_email.py:67` as an open residual. |
| **MON-009** | Adzuna API 429 rate-limiting against this VM's IP, plausibly self-inflicted by the app's own polling | **UNKNOWN-CONTENT here / WATCH per source** | Zero citations of `MON-009` in this worktree. Source ledger records this as an explicit **WATCH** status (neither open-unaddressed nor closed) — not independently verifiable from this worktree's code. |
| **MON-010** | Jobs screen "Clear all" button — reclassified during investigation as a UX label ambiguity, not a functional bug | **FIXED** (as a UX reclassification, not a code defect) | Cited in `apps/web/src/app/dashboard/jobs/__tests__/page.test.tsx` (2 citation lines in this worktree). |
| **MON-011** | Resume Studio "Format Integrity Check" compared a document to itself — trivially always true; real re-uploads always re-flow and should not always pass | **FIXED** | Test `apps/api/tests/test_mon011_honest_format_integrity.py` (backend) and `apps/web/src/app/dashboard/resume/__tests__/mon011-format-integrity-honesty.test.tsx` (frontend) both exist, no skip/xfail. 18 comment citations across this worktree. |
| **MON-012** | `.docx`/binary résumé uploads UTF-8-decoded into garbage text with no rejection | **FIXED** | Cited in `apps/api/tests/test_resume_upload.py`, `apps/web/src/__tests__/settings/resume-baseline-honesty.test.ts`, `apps/web/src/app/dashboard/settings/__tests__/u2a-resume-baseline.test.tsx`, and the upload UI itself (`apps/web/src/components/settings/resume-upload.ts`, `settings-client.tsx`). 21 comment citations, the most of any ID besides MON-020. |
| **MON-013** | Market Pulse "advertise the A$X band" sentence rendered nonsense text against an all-zero Adzuna salary histogram | **FIXED** | `apps/api/tests/test_analytics.py:914` — docstring quotes the exact original defect ("Adzuna's live `/histogram` can return every band at ..."). 4 comment citations in this worktree. |
| **MON-014** | Jobs-by-Source donut chart's percentages were normalized against only the top-5 subtotal, not the true total — silently dropped 175 jobs from the underlying math in the reported case | **FIXED** | `apps/api/tests/test_analytics.py:954` — docstring: "the Jobs-by-Source donut's percentages must be computed [against the true total]." 2 comment citations. |
| **MON-015** | Activity heatmap/weekly-trend bucketed application timestamps in UTC instead of Melbourne local time — 28% of one user's applications landed on the wrong calendar day | **FIXED** | `apps/api/tests/test_analytics.py:1011,1169` (two related tests, "part 2"). Also cited in `docs/delivery/DECISIONS.md:1540,1545` as grouped with the trend/heatmap fixes. 9 comment citations. |
| **MON-016** | Trend Indicators tooltip claimed "vs prior period" but the underlying `_pct_delta()` actually compared only the first vs. last point of the whole window — could show the wrong sign live | **FIXED** | `apps/api/tests/test_analytics.py:1183,1200` — docstring quotes `_pct_delta()`'s own claim directly. 8 comment citations. |
| **MON-017** | `arq` background worker's `run_agent_job` hit `TimeoutError` at its 600-second cap | **UNKNOWN-CONTENT here / FIXED per source** | Zero citations of `MON-017` anywhere in this worktree. Source ledger records this as closed with zero recurrence observed; not independently verifiable from this worktree's code, since nothing here names it. |
| **MON-018** | A class of UI visual defects: element overlaps, tooltip clipping, label collisions, notification-bell panel overlap, text overflow on mobile | **FIXED** | Four distinct test files exist, none skipped: `apps/web/src/__tests__/metric-tooltip-flip.test.tsx`, `apps/web/src/app/dashboard/analytics/__tests__/roi-mobile-grid.test.tsx`, `apps/web/src/components/__tests__/topbar-notification-panel.test.tsx`, `apps/web/src/components/agents/__tests__/agent-card-hover-description.test.tsx`. 4 comment citations. Note: `apps/web/src/components/topbar.tsx` is now a thin re-export shim pointing at a `CommandBar` component (an unrelated UI-rebuild effort), which is where the notification-panel fix actually lives. |
| **MON-019** | `claude-fable-5` model rejects the `temperature` request parameter with HTTP 400 — later root-caused as OpenRouter unconditionally sending `temperature` even for models that reject it | **FIXED** | Branch `hotfix/mon-019` exists and **is merged into this worktree's HEAD** (`7be085a`, confirmed via `git merge-base --is-ancestor hotfix/mon-019 HEAD`). Test `apps/api/tests/test_mon019_temperature_param_safety.py` exists. 3 comment citations. |
| **MON-020** | Jobs screen "Sync" button triggered a synchronous scout run inside the HTTP request path, which routinely exceeded the ingress proxy's ~100-second timeout and returned Cloudflare 524 | **FIXED — see discrepancy note below** | Branch `hotfix/mon-020` exists and **is merged into this worktree's HEAD** (confirmed via `git merge-base --is-ancestor`). Tests `apps/api/tests/test_mon020_async_scout.py` (backend) and `apps/web/src/app/dashboard/jobs/__tests__/mon020-async-sync.test.tsx` (frontend) both exist, unskipped. **48 comment citations** in this worktree — the most of any ID, consistent with a multi-file async-conversion fix (moving the scout run to the background job queue plus a server-side duplicate-run guard). |

### Discrepancy note — MON-020's status cell in the source ledger

The source ledger's own summary table still shows MON-020 as *"OPEN — fix dispatched,"* but that
cell was not updated after the fix landed; later narrative entries in the **same source file**
record a two-pass closure ("PASS-2 SEALED... Two-pass verification complete — MON-020 closure is
FINAL"). This worktree's independent evidence (merged `hotfix/mon-020` branch, two passing test
files, 48 in-code citations of the completed fix) agrees with the narrative closure, not the stale
table cell. **This document records MON-020 as FIXED** on that independent evidence, and flags the
source ledger's table row as needing its own housekeeping update — that correction was not made
here, since this document only writes to `docs/delivery/` in this worktree, not to the sibling
checkout.

---

## OPEN-items table (for a follow-up fix wave)

| ID | Symptom | What's missing |
|---|---|---|
| MON-002 | Google API 403 `insufficientPermissions` hammering, ~every 2 min in prod logs | No handling code or test found anywhere in this worktree. Needs: RCA on which OAuth scope is actually missing/expired, then either re-consent flow or honest degrade + reduced polling frequency. |
| MON-003 | Approvals double-submit producing repeated 409s | Unclear whether existing `approvals.py:287` / `applications.py` guards already cover this — needs an explicit reproduction against the approvals endpoint specifically, then either confirmation-and-close or a dedicated frontend submit-guard. |
| MON-006 | `wellfound` adapter 404 log noise (source gone) | Needs a decision: disable the adapter outright, or drop its failure to a lower log level so it stops looking like an active incident. |
| MON-007 | LLM 503 storm / tailor-agent failure rate | Not citable to any code in this worktree under this ID. Needs re-verification against current `tailor` failure rates before deciding whether `llm_client.py`'s existing wall-clock budget work already resolved it or whether a dedicated fix is still required. |
| MON-008 | Plaintext OAuth tokens in the legacy `GoogleCredential` table | Fix needs to account for the live `gmail_account.py` backfill caller, not just delete/deprecate the table — a naive removal would break that backfill path. |
| MON-009 | Adzuna 429s, possibly self-inflicted | Source ledger marks this WATCH, not OPEN — recommend confirming current polling cadence against Adzuna's documented rate limit before treating it as a defect to fix versus a config tuning item. |
| MON-017 | `arq` job timeout at 600s cap | Not citable to any code in this worktree under this ID; source ledger claims closure with zero recurrence — recommend a fresh log check before assuming it's still resolved, since nothing in this worktree pins that claim to a specific commit. |

## Not part of the numbered ledger (found for completeness, not verified further)

The source ledger's own "Watch list" section records a handful of single-occurrence items that
never received a MON-ID (a ~90-second deploy-stop timeout outage window, RSC prefetch aborts, and
email-route latency spikes). These are noted here only because they appear in the same source
document; they are out of scope for this reconstruction since they were never cited anywhere in
this worktree by any ID.
