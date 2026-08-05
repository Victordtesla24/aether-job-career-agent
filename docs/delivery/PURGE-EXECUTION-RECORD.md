# PURGE EXECUTION RECORD — production test-identity purge (GOLD-MASTER-V2 · G-K · §13.2)

**Status:** EXECUTED AND VERIFIED · **2026-08-05T07:31:28Z** · COMMIT successful, zero collateral damage
**Executor:** `janitor` — **not** the risk-officer who authored the manifest (C8)
**Approval:** [`ADR-PROD-TESTDATA-PURGE.md`](./ADR-PROD-TESTDATA-PURGE.md) — APPROVED-WITH-CONDITIONS (C1–C13, C5 superseded by C5-A)
**Full transcript:** `uat/reports/evidence/gold-master-v2/cleanup/PURGE-EXECUTION-2026-08-05.md` *(gitignored — this is the committed summary)*

**5,108 rows deleted across 16 tables, owned by the 13 approved `@mailinator.com` test identities.
Both genuine accounts untouched. Zero orphans. No service restarted. Production healthy.**

---

## What ran

Single transaction, explicit per-table DELETEs in the manifest's `deletion_order`, `psql` exit 0.

| # | Table | Deleted | | # | Table | Deleted |
|---:|---|---:|---|---:|---|---:|
| 01 | ApprovalRequest | 2 | | 14 | AgentProvider | 1 |
| 02 | EmailThread | 1 | | 15 | AgentConfig | 0 |
| 03 | BackgroundJob | 2 | | 16 | CareerProfile | 0 |
| 04 | OutreachTask | 1 | | 17 | GmailAccount | 0 |
| 05 | Offer | 1 | | 18 | GoogleCredential | 0 |
| 06 | InterviewSchedule | 0 | | 19 | UserProviderCredential | 0 |
| 07 | Application | 1 | | 20 | AgentQuotaBlock | 0 |
| 08 | Contact | 1 | | 21 | AnthropicOAuthState | 0 |
| 09 | Resume | 4 | | 22 | AnthropicOAuthToken | 0 |
| 10 | **Job** | **5011** | | 23 | UsageQuota | 13 |
| 11 | StoryEntry | 4 | | 24 | Subscription | 13 |
| 12 | AgentRun | 10 | | 25 | **User** | **13** |
| 13 | JobSourceStatus | 30 | | | **TOTAL** | **5,108** |

`Application` (step 07) ran before `Resume` (step 09), so the `Application.resumeId → Resume` **RESTRICT**
constraint was never violated. The ordering was load-bearing and held.

## Preconditions discharged before the first DELETE

- **Manifest integrity (C11).** In-tree manifest sha256 `2fc7e193085feb9e96cdc1f2db25dbc911df112cae29f62cddf956885e754d5a`
  — byte-identical to the off-tree snapshot and matching the orchestrator's recorded prefix. No concurrent writer.
- **Re-census (C5/C5-A).** The 02:07Z census was stale, as predicted. Drift **+21 rows**, all upward, all within
  the 13 approved identities and approved tables: `Resume` 3→4, `UsageQuota` 3→13, `Subscription` 3→13
  (5,087 → **5,108**). The 20 new billing rows were a single backfill batch at 03:07:41.376686Z and were
  class-checked before being treated as in scope: all `planId=free`, `status=active`, `stripeSubscriptionId
  IS NULL` — the §4.1-approved class, no money.
- **No scope change.** No 14th identity (15 users; 13 mailinator; the email-pattern set and the 13 enumerated
  ids agree **exactly**). No out-of-scope table — every `%userid%` column in schema `aether` was enumerated and
  the manifest's `deletion_order` is **set-equal** to the 25 user-scoped tables that exist.
- **Quiescence (C5-A).** Last test-identity write anywhere: 2026-08-04T11:10:30Z — ~20 hours before execution,
  against a ≥30-minute requirement. Zero test writes in the preceding 30 minutes.
- **Cross-user audit re-run fresh:** all 13 FK/soft-reference checks **0**.
- **Backup (C1) — `pg_dump` NOT used.** It is banned here (client 16.14 vs server 17.9 → abort + 0-byte file).
  Used the validated `psql -At` `row_to_json` JSONL capture. **G1–G5 all pass:** 5,108 lines exactly matching
  the re-census; every line JSON-parseable and owned by one of the 13; **zero protected rows captured**;
  33/33 sampled rows restore **byte-identically** from the actual files; `sha256sum -c` OK; off-VM copy
  verified by round-trip download.
  **Three verified copies**, one off-VM: in-tree (gitignored), `/home/ubuntu/aether-purge-backup-20260805T072800Z/`,
  and `s3://…/49362/gm2-cleanup-backup-20260805T072800Z/`.
- **SQL review (C13).** SQL generated mechanically from the hash-verified manifest, never hand-written, then
  machine-diffed: **26/26 checks clean** — statement order identical to `deletion_order`, exactly the 13 literal
  ids in every statement, **zero content-derived predicates**, one BEGIN/COMMIT, no DDL, DO-NOT-TOUCH tables
  never referenced, guards as deltas not literals, `pg_dump` absent.

## Verification after COMMIT

| Check | Result |
|---|---|
| Users remaining | **2** — owner `sarkar.vikram@gmail.com` + real free user `abhikadam28@gmail.com` |
| `%@mailinator.com` users | **0** |
| Residue — rows still owned by the 13, across all 25 in-scope tables | **0 everywhere** |
| Owner rows unchanged (no decrease in any table) | **YES** — `Job` 3074→3075, `AgentRun` 5621→5624, `Application` 258→259, `ApprovalRequest` 482→483; all *increases* from concurrent live traffic |
| Real free-tier user rows unchanged | **YES** — identical in every table |
| `AdminAuditLog` / `StripeEvent` untouched | **YES** — 216→216, 8→8 (also `Plan` 4, `ProviderCredential` 4, `AdminSetting` 2) |
| Orphans created | **0** across all 24 user-scoped tables |
| `GET /api/health` | **200** `{"status":"ok","version":"0.2.0"}` |
| New 5xx / tracebacks / FK violations in `aether-api`/`aether-web`/`aether-worker` | **0 in all three** |
| Services restarted | **none** — all three still `active` |

**C12's delta-guard rule was vindicated concretely.** The rejected literal guard asserted the owner's `Job`
count equalled 2,506; it was **3,074** before this purge and **3,075** after. That guard would have rolled back
a correct purge, and the "obvious fix" would have been to delete the only protection standing over owner data.

**C2 held.** The owner's 1,387 `Job` rows sharing a `sourceUrl` with a purged test copy all survived — owner
`Job` went *up*, never down. A content-derived predicate would have destroyed them.

## Rollback position (C7)

Row-scoped re-insert **only**, from the JSONL backup, in reverse deletion order (`User` first), per ADR §5.4
R1–R5. The restore transform was validated against these exact files. A full-DB / whole-schema / PITR restore
remains **PROHIBITED**: the owner wrote at least 6 rows during this operation alone, and a snapshot restore
would destroy them.

## Still open — not executor-actionable

1. **C10 / ADR §9 — blocks G-K full closure.** Two **live-mode** Stripe customer records remain, and the local
   `Subscription` rows that pointed at them are now deleted, so this record and the backup are the only
   remaining link:
   `cus_V0KsL1wgumpXag` (`aether.audit.qa.1785756940@mailinator.com`) and
   `cus_V0L97Kz0LbPZ3M` (`aether-paytest-1785758152@mailinator.com`).
   Both had `stripeSubscriptionId` NULL — customer objects only, no subscription, no charge. A human must
   delete or tag them in the Stripe live dashboard.
2. **C13 risk-officer counter-signature** on the executed SQL was not obtained — the 26/26 diff was machine-run
   by the janitor at the orchestrator's direction. An executor cannot self-grant that sign-off.
3. **Manifest defect (non-blocking, recorded).** `backup_spec.expected_line_counts` contradicts `rows_by_table`
   in the same file (`ApprovalRequest` 1 vs 2, `StoryEntry` 3 vs 4, `BackgroundJob` 1 vs 2, `AgentRun` 8 vs 10)
   and omits `EmailThread` and `Application` entirely — residue of the A.4 concurrent-authorship collision.
   Verification was performed against the re-census, per `verify_cmd` and C5. A janitor verifying against
   `expected_line_counts` would have "passed" a backup missing two tables.
4. **ADR §6.2** (BLOCKER-002 PRESERVE rows) and **§6.3** (17 user-scoped tables with no FK to `User`) — unchanged
   escalations, independent of this purge.

---

**Aborted:** no · **Rolled back:** no · **Rows deleted:** 5,108 · **Collateral damage:** none detected
