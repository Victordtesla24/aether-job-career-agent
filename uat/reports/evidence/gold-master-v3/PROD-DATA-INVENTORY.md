# PRODUCTION DATABASE SYNTHETIC/TEST-DATA INVENTORY — WORKSTREAM K §20.1.3

**Run:** GOLD-MASTER-V4 | **Role:** scout (read-only, SELECT only, zero writes issued) | **Generated (UTC):** 2026-07-31T17:49:41Z

**Database connected:** physical DB `fdc4e11da` on `db-fdc4e11da.db005.hosteddb.reai.io:5432`, schema **`aether`** (confirmed PRODUCTION schema via `SELECT current_database(), current_schema()` — distinct from the `aether_test` schema that lives on the same physical instance, referenced by `DATABASE_URL_TEST` in `.env`). `[VERIFIED-WITH-FRESH-EVIDENCE psql session, this run]`

Companion machine-readable manifest: `cleanup/DELETION-MANIFEST-1.json` (status `PROPOSED-AWAITING-APPROVAL`). A prior, differently-shaped manifest that previously occupied that filename (GOLD-MASTER-V2, path-based cleanup candidates) has been preserved at `cleanup/DELETION-MANIFEST-1-GOLD-MASTER-V2-PRIOR.json`.

---

## 1. Schema enumeration — all 31 tables, row counts

`[VERIFIED-WITH-FRESH-EVIDENCE psql COUNT(*) per table, this run]`

| Table | Rows |
|---|---:|
| AgentRun | 3663 |
| EmailThread | 230 |
| BackgroundJob | 196 |
| AdminAuditLog | 150 |
| ApprovalRequest | 112 |
| Application | 84 |
| Resume | 77 |
| Job | 52 |
| StoryEntry | 37 |
| AgentConfig | 17 |
| UsageQuota | 15 |
| User | 15 |
| Subscription | 15 |
| JobSourceStatus | 10 |
| StripeEvent | 8 |
| CareerProfile | 6 |
| ProviderCredential | 5 |
| Plan | 4 |
| AgentProvider | 2 |
| GmailAccount | 2 |
| AdminSetting | 2 |
| AnthropicOAuthToken | 1 |
| AnthropicOAuthState | 1 |
| AgentQuotaBlock | 0 |
| GoogleCredential | 0 |
| Contact | 0 |
| UserProviderCredential | 0 |
| InterviewSchedule | 0 |
| OutreachTask | 0 |
| JobEmbedding | 0 |
| Offer | 0 |

Note: there is no dedicated `notifications` or `workspaces` table in this schema — the app is single-tenant per `User` row (no workspace/org layer), and there is no notifications table to inventory. `cover_letters` is not a separate table; cover-letter text lives in `Application.coverLetter`.

---

## 2–3. Synthetic/test/fixture hunt — pattern search across all user-content tables

Searched (case-insensitive `ILIKE`) every text/JSONB column of `ApprovalRequest`, `Application` (coverLetter/answers), `Job`, `Resume`, `StoryEntry`, `EmailThread`, `AgentRun` (input/output/error), `User`, `Contact`, `InterviewSchedule`, `Offer`, `OutreachTask`, and `BackgroundJob` (params/result/error) for: `SYNTHETIC`, `TEST DATA`, `models-live`, `qa)`, `FIXTURE`, `PLACEHOLDER`, `DUMMY`, `lorem`, `ipsum`, `John Doe`, `Jane Doe`, `Acme`, `example.com`, `example.org`, `test@`, `foo@bar`, `XYZ Company`, `[Your Name]`, `TODO`, `SAMPLE`, `DO NOT USE`, `no "to" field on purpose`. `[VERIFIED-WITH-FRESH-EVIDENCE psql scan, this run — raw output cached at cleanup/_scan_raw_output.txt]`

### Hit summary by table

| Table | Hits | Classification |
|---|---:|---|
| ApprovalRequest | 1 | SYNTHETIC-FIXTURE |
| Resume | 1 | SYNTHETIC-FIXTURE |
| EmailThread | 1 | SYNTHETIC-FIXTURE |
| User | 14 | SYNTHETIC-FIXTURE (all 14) |
| Application, Job, StoryEntry, AgentRun, Contact, InterviewSchedule, Offer, OutreachTask, BackgroundJob | 0 | — clean |

### Confirmed SYNTHETIC-FIXTURE rows (full manifest detail in `cleanup/DELETION-MANIFEST-1.json`)

1. **ApprovalRequest** `ccbe2e7518343e818809f8009` — owner `c6c8d0163d973a8048e7e33b8` (sarkar.vikram@gmail.com, the live cron/test account). `payload.preview` = `"SYNTHETIC TEST DATA (models-live qa) — no \"to\" field on purpose."`; `payload.why` = `"MODELS-LIVE QA synthetic test row — deliberately missing recipient so approve cannot send a real email."` Created 2026-07-22T14:15:05.249Z. Rendered on `/dashboard/approvals` (`GET /approvals`). **This is the row the orchestrator flagged as evidence — proposed disposition KEEP-AS-EVIDENCE, not delete.** Its sibling `cbf83a2061808d8526c298f2a` is confirmed **absent** from the DB (already deleted by the earlier tester).
2. **Resume** `c969dbcecd27c827a80f6bea0` — same owner. `label` = `"Uploaded — valid-resume"`; `sections.raw_text` begins `"Jane Doe Test Resume\nSoftware Engineer specializing in Python and distributed systems\n...Senior Engineer at Test Corp..."`. Created 2026-07-31T00:20:58.605Z. Rendered on `/dashboard/resume` (`GET /resumes`). Proposed: DELETE.
3. **EmailThread** `cd677a32f603c19a2d56f6725` — same owner. `subject` = `"NUL byte test subject"`; message body references `nul-byte-test@example.com`. Created 2026-07-31T07:48:49.963Z. Rendered on `/dashboard/email` (`GET /emails`). Proposed: DELETE. (This exact id was also flagged in a **prior, unrelated** GOLD-MASTER-V2 manifest that previously occupied this filename — corroborating independent evidence it has sat in prod, unactioned, across at least two campaigns.)
4. **14 User rows** — clearly-labeled QA/test signup probes from prior campaigns (Phase 7A, ML-Adv, Gold Master V2, QA DeepSweep), e.g. `test-phase7a@example.com`, `qa-deepsweep-20260729@example.com`, `ml-adv-storyleak-20260723051146@example.com`, `mltest+001@example.com`, `gm2-phase0-probe-1785453738@example.com`, `spotcheck-control-1785510466@example.com`, `gm2-legitcheck-1785511626@example.com`, `用户名テスト😀@example.com`, `gm2-report-refresh-legit-1785515581@example.com`, `gm2-nonadmin-1785454990@example.com` ("Gold Master V2 Test User"), `gm2-nultest-1785488126@example.com`, `definitely-nonexistent-signup-probe-xyz@example.com`, `gm2-signup-1785488210@example.com`, `gm2-signup-1785488691@example.com`. All 14 have **zero** rows in every content table (see §4) — empty leftover signup shells. Visible on `/admin/users` (`GET /admin/users`, admin-only). Proposed: DELETE. Six of these fourteen were already named in the prior GOLD-MASTER-V2 manifest's operator-purge list and were never actioned.

No hits at all in `Application`, `Job`, `StoryEntry`, `AgentRun`, `Contact`, `InterviewSchedule`, `Offer`, `OutreachTask`, `BackgroundJob` — clean.

### Ambiguous escalation (not in the deletion manifest as DELETE)

- **5 near-duplicate StoryEntry clusters** (see §5 below) — flagged `AMBIGUOUS` / `ESCALATE`, not `SYNTHETIC-FIXTURE`, because content doesn't self-announce as fake and hashes/titles differ (paraphrase, not byte-copy).

---

## 4. Test-account vs. other-user breakdown (risk context)

`[VERIFIED-WITH-FRESH-EVIDENCE psql COUNT(*) FILTER, this run]`

**Critical finding: every row of user-generated content in production currently belongs to the single live test/operator account (`c6c8d0163d973a8048e7e33b8`, sarkar.vikram@gmail.com = `AETHER_CRON_EMAIL`). Zero rows belong to any other user.**

| Table | Cron/test-account rows | Other-user rows | Total |
|---|---:|---:|---:|
| AgentRun | 3663 | 0 | 3663 |
| EmailThread | 230 | 0 | 230 |
| BackgroundJob | 196 | 0 | 196 |
| ApprovalRequest | 112 | 0 | 112 |
| Application | 84 | 0 | 84 |
| Resume | 77 | 0 | 77 |
| Job | 52 | 0 | 52 |
| StoryEntry | 37 | 0 | 37 |
| Contact | 0 | 0 | 0 |
| Offer | 0 | 0 | 0 |
| OutreachTask | 0 | 0 | 0 |

`User` table total = 15 = 1 (the cron/test account) + 14 (leftover QA signup-probe accounts enumerated in §3). **There are currently zero real paying-customer accounts with any content in production.** This substantially lowers the blast radius of any cleanup: deleting the 3 confirmed fixture rows and the 14 empty test-signup `User` rows touches no genuine customer data, because none exists yet. It also means the "leak onto a real user's screen" the tester observed was a leak onto the **operator's own long-lived test/cron account**, not a random paying customer — still a zero-tolerance violation per §0.5 since that account is used for real production logins/demos, but the specific risk of cross-customer contamination is currently zero (there are no other customers to contaminate).

---

## 5. Story-bank duplicate check (§8.1(a) fresh evidence, feeds W-E / G-E)

`[VERIFIED-WITH-FRESH-EVIDENCE psql, this run]`

- **Total StoryEntry rows:** 37
- **Exact duplicates** (normalized lowercase/whitespace-collapsed `situation+task+action+result`): **0** — all 37 normalized texts are unique; all 37 `contentHash` values are distinct; 0 NULL hashes.
- **Distinct titles:** 37 of 37 (no title repeats either).
- **Near-duplicates** (looser check: first 40 chars of normalized `situation` text): **5 clusters covering 16 of 37 rows (43%)** — same underlying achievement re-generated as a paraphrase across multiple dates/runs:
  - "ANZ core banking transformation" — 5 variants (2026-07-21, 07-22 ×2, 07-23, 07-31)
  - "JIRA analytics dashboard for sprint velocity" — 5 variants (2026-07-21, 07-22, 07-24, 07-30, 07-31)
  - "LLM evaluation stack" — 2 variants (2026-07-22, 07-23)
  - "COBOL/mainframe test automation at ATO" — 2 variants (2026-07-23, 07-24)
  - "NTP function testing war room" — 2 variants (2026-07-22, 07-23)
  - All 16 rows belong to the same cron/test account.

**Interpretation:** the byte-exact dedup migration appears effective (0 exact duplicates found today), but it does not catch paraphrase-level near-duplicates produced by repeated tailoring/extraction runs against the same underlying test resume. 43% of the current story bank is near-duplicate content. Filed as an `AMBIGUOUS`/`ESCALATE` item in the manifest rather than a delete proposal, since these are not self-announcing fakes.

---

## Evidence artifacts on disk

- `cleanup/DELETION-MANIFEST-1.json` — GOLD-MASTER-V4 manifest (this run), status `PROPOSED-AWAITING-APPROVAL`
- `cleanup/DELETION-MANIFEST-1-GOLD-MASTER-V2-PRIOR.json` — preserved prior manifest content (different schema/run)
- `cleanup/_table_counts_raw.txt` — raw psql output, full table/row-count enumeration
- `cleanup/_scan_raw_output.txt` — raw psql output, full pattern-search results across all tables
- `uat/reports/evidence/gold-master-v3/PROD-DATA-INVENTORY.md` — this file
