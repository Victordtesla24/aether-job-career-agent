# Test-Data Cleanup Ledger (MANUAL-VERIFICATION run)

Disposable accounts/data created by testers on the shared production system. Adjudicate deletion at end-of-run (doc-updater/cleanup phase), same discipline as Phase-7 (delete sweep/test rows that own no real data; keep sarkar.vikram@gmail.com + admin seed). Deletion requires orchestrator adjudication before acting.

## Accounts created
| Source screen | identifier | notes |
|---|---|---|
| signup | mv-signup-xofzhxs6@mv-signup-test.dev | disposable, free plan, created 2026-07-17 |
| signup | mv-signup-nmgo8847@mv-signup-test.dev | disposable, free plan, created 2026-07-17 |
| register (qa-adversary prod-verify A/C) | mv-verify-adversary@mv-verify-test.dev · userId cb6d3c2e1325cd7eda353a8c3 | disposable; name/targetRole="Administrator"; temp Pro entitlement granted (ADR-MV-01 pattern) then REVERTED to free 2026-07-18; owns 8 `mv-verify://MV-verify-*` Job rows + generated cover-letter Application rows + pending approvals (all fresh evidence for prod-verify-A-C). Delete whole account+data at cleanup (orchestrator adjudication). |
| register (qa-adversary prod-verify F/G) | mv-verifyfg-20260718T031439Z@example.com · userId ca6e521cc0b19982537b3b4b5 | disposable, free plan, created 2026-07-18; used for authenticated billing API probes (subscription/checkout/portal) + pricing/settings UI checks. Checkout endpoint self-rate-limited (429, Retry-After ~2618s) by an intentional 429-induction probe — resets ~44min later, no lasting effect. No paid entitlement granted (stayed free). Delete at cleanup (orchestrator adjudication). |
| signup UI (qa-adversary prod-verify F/G) | mv-verifyfg-signup-2026-07-18T03-17-37-675Z@example.com | disposable, free plan, created 2026-07-18 via /signup consent-gate test (checked→submitted→navigated to /dashboard). Delete at cleanup (orchestrator adjudication). |
| register (qa-adversary PROD-VERIFY batch-2) | mv-vbatch2-pro-20260718T045405Z@example.com · userId cb0159b14ae4852ad0f401f84 | disposable; display name set to "Jordan Ellis"; TEMP Pro entitlement granted (ADR-MV-01 pattern) then REVERTED byte-for-byte to free 2026-07-18 (see fixes/prod-verify-batch2/ENTITLEMENT-GRANT-LEDGER-batch2.md). Owns ~15 `source='mv-vbatch2-adversarial'` Job rows + ~11 cover-letter Application rows + matching ApprovalRequest + AgentRun rows (fresh evidence for MV-cover-letter-studio-003 injection probes). Delete whole account+data at cleanup (orchestrator adjudication). |
| register (qa-adversary PROD-VERIFY batch-2, FREE control) | mv-vbatch2-free-20260718T045405Z@example.com · userId c57b9fb5fce9f882ba35b8a22 | disposable, free plan (NO grant), created 2026-07-18; used for free-tier settings/billing + paywall/fail-closed UI checks. Owns 0 data rows. Delete at cleanup (orchestrator adjudication). |
| register (qa-adversary PROD-VERIFY batch-3, Cluster H) | mv-vb3-signup001-1784355434@example.com · userId cd06395974c0e7a5fd42c865f | disposable, free plan, created 2026-07-18; MV-signup-001 72-byte-password probe account. Owns 0 data rows. Delete at cleanup. |
| register (qa-adversary PROD-VERIFY batch-3, Cluster H) | mv-vb3-signup004-1784355468@example.com · userId c67b50546071be90ab831225c | disposable, free plan, created 2026-07-18; MV-signup-004 unicode/markup-name probe account (name="Zoé <script>alert(1)</script> 日本語 Müller"). Owns 0 data rows. Delete at cleanup. |
| register (qa-adversary PROD-VERIFY batch-3, PRO) | mv-vb3-pro-1784355683@example.com · userId ce34e6ad8555f8a9a1f32fb4e | disposable; display name "MV VB3 Pro"; TEMP Pro entitlement granted (single INSERT into Subscription planId=pro/status=active; before-state = NO row) then REVERTED byte-for-byte 2026-07-18T06:28Z (Subscription grant row DELETED; entitlement now active_paid:false/plan=free — the residual `planId=free` Subscription + free UsageQuota rows are the app billing-bootstrap's normal free baseline, NOT the grant). Also staged + DELETED 4 synthetic `AgentRun` fixture rows (scout/fitScorer/matcher/tailor) used only to observe live Orchestration rendering. Owns 1 networking Contact ("MV-vb3 Contact <ts>" · Senior Recruiter · MV-vb3 TestCorp — real POST /networking/contacts persistence evidence). Delete whole account+contact at cleanup (orchestrator adjudication). Evidence: fixes/prod-verify-batch3/{pro-account.txt,grant-after.json,grant-entitlement-verify.json,grant-revert.txt}. |
| register attempt (REJECTED, no account) | mv-vb3-signup001b-1784355434@example.com | 422 rejected (>72-byte password) — account never created; nothing to clean up. |

## Data rows (prefixed MV-<screen>-)
To be enumerated at cleanup: any Job notes / Stories / Cover letters / Contacts / Applications created by testers carry the `MV-<screen>-` prefix. Enumerate via authenticated API list endpoints filtered by that prefix; delete only prefixed rows owned by test accounts; never touch sarkar.vikram data.

| Source screen | identifier(s) | notes |
|---|---|---|
| offer-comparison | `MV-offer-Acme`, `MV-offer-negbase`, `MV-offer-xss`, `MV-offer-Ünïçødé 日本語 🚀`, `MV-offer-BackForwardTest`, `MV-offer-unsaved-work-probe`, `MV-offer-SHOULD-NOT-PERSIST-cancel` (never added — cancel-path only) | **Nothing to clean up.** offer-comparison's "Add Offer" is client-side only (MV-offer-comparison-001, BLOCKER) — no POST/PUT/DELETE endpoint exists for offers at all, so none of these ever reached the database. Confirmed via `GET /api/workspaces/offers` at end of session returning `"offers": []` on the admin (`admin/admin123`) test account. |

---

## ORCHESTRATOR CLEANUP ADJUDICATION (2026-07-20, binding for the exit cleanup agent)

Later disposable accounts were logged in ENTITLEMENT-GRANT-LOG.md and sweep artifacts rather than this table (mv-qa-ej-2026-cebe@example.com, mv-qa-ej2-adv18@example.com [userId c88fc72d11082ac709fd6a801], mv-qa-final-a/b, mv-qa-pii-distinct-9f3k@example.com [c6c99121d1d2a26ae37543ddd], mv-qa-pii-noresume-9f3k@example.com [c43d8b2f3cbda5c787c107417], mv-verify-adversary, mv-vbatch2-*, mv-vb3-*, mv-verifyfg-*). The ruling below is PATTERN-BASED so it also covers any disposable account created after this adjudication (e.g. by the final spot-check sweep), provided that sweep logs its accounts here.

**DELETE (account + ALL owned rows in every table — Resume, Job, Application, CoverLetter, AgentRun, BackgroundJob, ApprovalRequest, EmailThread, StoryEntry, Contact, InterviewSchedule, Subscription, UsageQuota, ProviderCredential, etc.):**
Users whose email matches any of:
- `mv-signup-%@mv-signup-test.dev`
- `mv-verify%` (covers mv-verify-adversary@mv-verify-test.dev, mv-verifyfg-*@example.com)
- `mv-vbatch2-%@example.com`
- `mv-vb3-%@example.com`
- `mv-qa-%@example.com` (covers mv-qa-ej-2026-*, mv-qa-ej2-adv18, mv-qa-final-*, mv-qa-pii-*-9f3k)

**KEEP:**
- `sarkar.vikram@gmail.com` (owner's real account, if/when it exists post-re-signup) — NEVER touch.
- `admin` / admin seed account (ground-truth test login §1) — KEEP the account itself, but DELETE run-created test data it owns: rows whose title/name/source carries an `MV-` / `mv-verify://` / `mv-vbatch2-adversarial` prefix.

**EXECUTION RULES (same discipline as the grant/revert ops):** psycopg2/psql under `search_path=aether` with `current_schema()` asserted; `?schema=` param stripped via urllib (never sed); explicit single-account WHERE keys (userId or email equality/LIKE shown above); rowcounts logged per statement; NO TRUNCATE; NO unqualified DELETE; SELECT-count before + after for every table touched; full transcript appended to this ledger. Verify afterwards: (a) zero remaining Users matching the DELETE patterns, (b) zero Subscription rows with planId != 'free' other than legitimately-kept accounts (expected: NONE — all grants already reverted), (c) admin account still logs in via canonical recipe, (d) total row counts recorded.

**Offer rows:** none exist server-side (client-only Add pre-fix); post-fix offers created by sweeps belong to mv-qa-* accounts and are deleted with them.

---

## 2026-07-20 — admin account restored (MV-system-005/006 fix)

`admin` / `admin@aether.local` (userId `c6c8d0163d973a8048e7e33b8`) was
re-seeded 2026-07-20T01:05:37Z via the existing idempotent
`apps/api/scripts/seed_demo.py::seed_admin_user()` after being destroyed in
the 2026-07-18 prod-DB-wipe incident. Identifier/password unchanged
(`admin` / `admin123`), `isAdmin=false` (DB column default, no privilege
grant), zero `Subscription` rows (free plan, no entitlement granted).
Verified live: `POST /api/auth/login` → 200, `GET /api/auth/me` →
`isAdmin:false`, `GET /api/billing/entitlement` → `active_paid:false`.
Full transcript: `fixes/MV-system-005-006/restore-log.md`.

**KEEP** — this is the canonical ground-truth test login (§1 of this
ledger's KEEP rules), restored to its pre-wipe shape. Not a disposable
tester account; do not delete at cleanup.

Note: `sarkar.vikram@gmail.com` (the account the discovery cron actually
authenticates as, per MV-system-006 diagnosis) is a **separate** account,
also wiped by the same incident, and remains **not restored** — out of
this fix's authorized scope. See `fixes/MV-system-005-006/restore-log.md`
§3 for the escalation.

---

## 2026-07-20 — CLAIM-RESAMPLE disposable account (qa-adversary §6.4)

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary claim-resample §6.4) | userId **c90279607e7688144c3d73b4d** — registered as mv-qa-resample-ac3fb1@example.com, LOGIN EMAIL NOW `resample@aether.local` (changed by the CLM-012/025 settings-allowlist ACCEPT probe, which persists to User.email per CLM-013). **DELETE BY userId `c90279607e7688144c3d73b4d`** — the current email `resample@aether.local` does NOT match the `mv-qa-%@example.com` DELETE pattern, and it is NOT the KEEP `admin@aether.local` account (different userId), so the pattern sweep will MISS it: cleanup MUST target this userId explicitly. TEMP Pro granted 2026-07-20T01:24:09Z (reverted by orchestrator 03:05:45Z) and RE-GRANTED 2026-07-20T03:10:54Z then REVERTED by this agent at end of resample (both in ENTITLEMENT-GRANT-LOG.md). Owns test rows from paid re-proof: 41 scout Job rows, Resume v1 (upload) + v2 (tailored c9be2a8912ea125d8a74b3f89), AgentRun/BackgroundJob (scout/pipeline/tailor/cover-letter), ApprovalRequest (tailor approval). Delete whole account + all owned rows at cleanup (orchestrator adjudication). NOTE: `resample@aether.local` is an internal-allowlist domain, so this account bypasses the paywall regardless of plan — a further reason to ensure it is deleted. |

---

## qa-adversary FINAL-RESIDUALS sweep accounts (2026-07-20) — covered by the `mv-qa-%@example.com` DELETE pattern (§ORCHESTRATOR CLEANUP ADJUDICATION above)

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary final-residuals R1) | `mv-qa-resid-distinct-865c45@example.com` · userId `cf6bb0e8a91954a87e00c0ee0` | disposable; distinct synthetic résumé ("QUINCEY ADVERSARIO-RESIDUAL"). TEMP Pro granted 2026-07-20T~01:13Z, emergency-reverted by orchestrator 03:05:45Z, RE-GRANTED for §7 sweep 03:08Z, then REVERTED byte-for-byte by qa-adversary 03:13Z (confirmed active_paid:false). Owns: Resume=1 (`cf4da499d3500ab9cd6f750a5`), Job=2 (`c6a2617e478293c9f2ec62e5c` Empire-Life, `c506f7d61968f3c595294e55a` Redpanda — source='mv-qa-resid-final', crafted scraped-concatenation JDs), Application/CoverLetter=4 (cover-letter test-1 generations), AgentRun=4, BackgroundJob=4. Delete whole account + all rows at cleanup. |
| register (qa-adversary final-residuals R2) | `mv-qa-resid-noresume-865c45@example.com` · userId `c1561fd2195e1801d85872755` | disposable; NO résumé ever (the point of the account — async honest-refusal test). TEMP Pro granted 2026-07-20T~01:13Z, emergency-reverted 03:05:45Z, stayed FREE thereafter (never re-granted). Owns: Resume=0, Job=42 (scout-discovered during pipeline no-résumé runs), AgentRun=11 (all refused/completed honestly, 0 metered), BackgroundJob=7 (coverLetter/tailor/pipeline missingResume refusals, all completed+refunded). runsUsed stayed 0. Delete whole account + all rows at cleanup. |

Both accounts match the binding `mv-qa-%@example.com` DELETE pattern (line 39). No non-disposable/real-user data touched. All DB ops single-row WHERE-keyed via psycopg2 under search_path=aether, `?schema=` stripped via urllib (not sed), current_schema()==aether asserted, rowcounts logged; NO TRUNCATE, NO unqualified DELETE.

## ADJUDICATION ADDENDUM (orchestrator, 2026-07-20, from claim-resample observations)
1. **Delete-by-userId override:** the resample account's email mutated to `resample@aether.local` during the CLM-013 settings-email probe, so it NO LONGER matches the `mv-qa-%@example.com` pattern. DELETE BY USERID: `c90279607e7688144c3d73b4d` (all owned rows in every table).
2. **Orphaned-row rule (ADDED):** delete any Subscription/UsageQuota (or other user-owned) rows whose `userId` has NO matching User row. Known instance: Subscription `6f3839c0-…` planId=pro of pre-wipe admin `cc29a76e…` (ADR-MV-01 grant orphaned by the 2026-07-18 wipe). These are dangling artifacts, not live grants (no User can authenticate against them), but hygiene requires removal. Enumerate with an anti-join, log ids + rowcounts.
3. **KEEP (restored 2026-07-20, product accounts, NEVER delete):** `admin`/`admin@aether.local` (userId c6c8d0163d973a8048e7e33b8) and `sarkar.vikram@gmail.com` (restored owner/demo seed; owns cron-sourced Job rows — PRODUCT data, keep).


## qa-adversary FINAL-CLOSURE sweep accounts (2026-07-20) — covered by the `mv-qa-%@example.com` DELETE pattern

Last closure re-verify (PROD @main 7fbf4c3): CamelCase JD-keyword chips + async no-résumé refusal surfacing + agents/pipeline lead-chase. Both accounts TEMP Pro granted 2026-07-20T~06:23Z and REVERTED byte-for-byte by qa-adversary 2026-07-20T~06:46Z (confirmed active_paid:false; ENTITLEMENT-GRANT-LOG.md revert marker set). All DB ops single-row WHERE-keyed via psycopg2 under search_path=aether, ?schema= stripped via urllib (not sed), current_schema()==aether asserted, rowcounts logged; NO TRUNCATE, NO unqualified DELETE.

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary final-closure F1) | `mv-qa-fr-69d1e2@example.com` · userId `c6b1aca1f10731e9866b7dd38` | disposable; distinct synthetic résumé ("QUILL ADVERSARIUS", Principal Platform Engineer). Owns: Resume=1, Job=5 (source='mv-qa-fr-closure', crafted scraped-concatenation JDs J1/J2/J2b/J3/J4), Application=6 (cover-letter generations), AgentRun=11, BackgroundJob=11. Reverted to free (runsUsed reset 6→0 by revert). Delete whole account + all rows at cleanup. |
| register (qa-adversary final-closure F2) | `mv-qa-fr-69d1e2-nr@example.com` · userId `cd63b6832b67eb3aa3d9a58c2` | disposable; NO résumé EVER (the point of the account — async honest-refusal + lead-chase test). Owns: Resume=0 (confirmed 0 — no operator seed on any refusal), Job=42 (1 seed JF2 + ~41 scout-discovered during pipeline "Run All" runs), Application=0, AgentRun=17 (coverLetter/tailor/fitScorer all refused honestly + charged 0; scout/supervisor/emailAgent-triage completed), BackgroundJob=9 (missingResume refusals all completed+refunded). Only metered charge = 0.0006 on the emailAgent triage (legit work). Reverted to free. Delete whole account + all rows at cleanup. |
| register (qa-adversary final-closure WAF-UA probe) | `mv-qa-fr-probe1@example.com` · userId `c84f2710e9f146eeb86e9e511` | disposable, free plan (NO grant); one-off account created while diagnosing a WAF 403 on urllib's default User-Agent (register worked via curl). Owns 0 data rows. Delete at cleanup. |

All three emails match the binding `mv-qa-%@example.com` DELETE pattern (line 39). No non-disposable/real-user data touched. sarkar.vikram/admin never touched.

## qa-adversary FINAL-PASS sweep accounts (2026-07-20) — covered by the `mv-qa-%@example.com` DELETE pattern

§6 loop-exit condensed adversarial pass (PROD @f491170). Both accounts TEMP Pro granted 2026-07-20T~08:42Z and REVERTED byte-for-byte by qa-adversary 2026-07-20T~09:03Z (confirmed active_paid:false, byte_for_byte_match=True; ENTITLEMENT-GRANT-LOG.md revert marker set). All DB ops single-row WHERE-keyed via psycopg2 under search_path=aether, ?schema= stripped via urllib (not sed), current_schema()==aether asserted, rowcounts logged; NO TRUNCATE, NO unqualified DELETE.

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary final-pass Z1) | `mv-qa-final2-2a385f@example.com` · userId `c669c1cdb0ff1b2cd0a9b8bf9` | disposable; distinct synthetic résumé ("VESPER ADVERSARIA-FINAL2"). Owns: Resume=2 (base v1 + rich v2), Job=3 (source='mv-qa-final2': cc110aac… muni-precomposed, cb5e1a7c… novel-unicode, + 1 unicode-repro job), Application(coverLetter)=3+ (db-seeded letter fixtures for insights + any sweep Run-All/Regenerate outputs), AgentRun/BackgroundJob (cover-letter/pipeline runs from §3.2 sweep). Reverted to free. Delete whole account + all rows at cleanup. |
| register (qa-adversary final-pass Z2) | `mv-qa-final2-2a385f-nr@example.com` · userId `c472704ece8d0718539b47954` | disposable; NO résumé EVER (confirmed Resume count=0). Owns: Resume=0, Job=1 (cd168748… z2-plainjob seed), Application=0, AgentRun (tailor/coverLetter/fitScorer refused honestly at costUsd=0; scout/supervisor completed 0.0 from the pipeline Run-All), BackgroundJob (missingResume refusals, all completed+refunded). runsUsed stayed 0. Delete whole account + all rows at cleanup. |

Both emails match the binding `mv-qa-%@example.com` DELETE pattern (line 39). No non-disposable/real-user data touched. sarkar.vikram/admin never touched.

## qa-adversary FINAL-PASS-001 CLOSURE account (2026-07-20) — covered by the `mv-qa-%@example.com` DELETE pattern

Focused closure re-verify of NF-final-pass-001 (non-Latin CamelCase JD-keyword gluings) on PROD @main c158729. ONE disposable account, TEMP Pro granted 2026-07-20T12:26Z and REVERTED byte-for-byte by qa-adversary at end of run (see ENTITLEMENT-GRANT-LOG.md FINAL-PASS-001 CLOSURE block). All DB ops single-row WHERE-keyed via psycopg2 under search_path=aether, ?schema= stripped via urllib (not sed), current_schema()==aether asserted, rowcounts logged; NO TRUNCATE, NO unqualified DELETE.

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary final-pass-001 closure) | `mv-qa-lastcheck-be068b@example.com` · userId `c644b4d74664667b71f26e438` | disposable; minimal synthetic résumé ("Verity Lastcheck"). Owns: Resume=1, Job rows (source='mv-qa-lastcheck': crafted scraped-concatenation JDs for the 5 gluings + reverse variants + controls + novel adversarial), Application/CoverLetter rows (minimal seeded letters for the insights endpoint keyword read). Reverted to free at end of run. Delete whole account + all rows at cleanup. |

Email matches the binding `mv-qa-%@example.com` DELETE pattern (line 39). No non-disposable/real-user data touched. sarkar.vikram/admin never touched.

## qa-adversary FINAL-PASS-002 CLOSURE account (2026-07-20) — covered by the `mv-qa-%@example.com` DELETE pattern

Focused closure re-verify of NF-final-pass-002 (caseless-script CamelCase JD-keyword gluings) on PROD @main 54c28e5. ONE fresh disposable account, TEMP Pro granted 2026-07-20T13:38Z and REVERTED byte-for-byte by qa-adversary at end of run (see ENTITLEMENT-GRANT-LOG.md FINAL-PASS-002 CLOSURE block). All DB ops single-row WHERE-keyed via psycopg2 under search_path=aether, ?schema= stripped via urllib (not sed), current_schema()==aether asserted, rowcounts logged; NO TRUNCATE, NO unqualified DELETE.

| Source | identifier | notes |
|---|---|---|
| register (qa-adversary final-pass-002 closure) | `mv-qa-lastcheck2-ff967d@example.com` · userId `cc62794585997022a7897e2f0` | disposable; minimal synthetic résumé ("Verity Lastcheck Two"). Owns: Resume=1, Job rows (source='mv-qa-lastcheck2': caseless repro + Thai/Hebrew + label-first + mixed cased+caseless + cased controls + boundary probes), Application/CoverLetter rows (minimal seeded letters for the insights endpoint keyword read). Reverted to free at end of run. Delete whole account + all rows at cleanup. |

Email matches the binding `mv-qa-%@example.com` DELETE pattern (line 39). No non-disposable/real-user data touched. sarkar.vikram/admin never touched.

---

## EXECUTED — 2026-07-20T13:55–13:57Z (cleanup agent, exit-phase disposable-account/data purge)

**Prod HEAD @main 54c28e5** (healthy, unchanged by this run — DB-only operation, no code/deploy). DB host `db-fdc4e11da.db005.hosteddb.reai.io` / db `fdc4e11da` / schema `aether`. All operations via psycopg2, DSN loaded from repo `.env`, `?schema=` stripped via `urllib.parse.urlsplit`/`parse_qsl` (NOT sed), connection opened with `options='-c search_path=aether'`, `SELECT current_schema()` asserted `== 'aether'` immediately after connect and again at the start of every phase. No pytest run, no restarts, no code edits, no git operations (per brief). No TRUNCATE, no unqualified DELETE — every statement below has an explicit `WHERE`.

### Scope read first
Read this whole ledger (ORCHESTRATOR CLEANUP ADJUDICATION §29-47, ADJUDICATION ADDENDUM §92-95, and every later sweep section through FINAL-PASS-002) and the whole of `ENTITLEMENT-GRANT-LOG.md` (419 lines) before touching the DB. Confirmed: every temporary Pro/paid entitlement grant logged there already carries a matching REVERT APPLIED entry with `active_paid:false` / `plan.id=free` confirmed live — **no entitlement revert work was needed**, this run is data deletion only.

### Live-schema enumeration (authoritative — supersedes the brief's illustrative table list)
`information_schema` in the live `aether` schema was queried directly (not just grepped from code) to guarantee no user-owned table was missed. 31 base tables exist; 24 carry a `userId` column and are genuinely per-user (`AgentConfig, AgentProvider, AgentQuotaBlock, AgentRun, AnthropicOAuthState, AnthropicOAuthToken, Application, ApprovalRequest, BackgroundJob, CareerProfile, Contact, EmailThread, GmailAccount, GoogleCredential, InterviewSchedule, Job, JobSourceStatus, Offer, OutreachTask, Resume, StoryEntry, Subscription, UsageQuota, UserProviderCredential`), plus `JobEmbedding` (owned indirectly via `jobId → Job.userId`, no own `userId` column). `ProviderCredential` (no `userId` column at all — confirmed via `information_schema.columns`) is a **system-shared singleton**, not user-owned; correctly excluded from deletion (matches the ENTITLEMENT-GRANT-LOG.md note that its `lastVerifiedAt` refresh needed no revert). `Plan`, `StripeEvent`, `AdminSetting`, `AdminAuditLog` are non-user-owned reference/audit tables — excluded.

FK constraints (`information_schema.table_constraints`/`referential_constraints`) show only the Prisma-managed tables have real FKs to `User` (`Job/Resume/Application/ApprovalRequest/Contact/EmailThread/StoryEntry/AgentRun` all `ON DELETE CASCADE`; `Application.resumeId → Resume` is `RESTRICT`, forcing `Application` deletion before `Resume`; `JobEmbedding.jobId → Job` is `CASCADE`). The 16 raw-DDL/lazy-DDL tables (`AgentConfig, AgentProvider, AgentQuotaBlock, AnthropicOAuthState, AnthropicOAuthToken, BackgroundJob, CareerProfile, GmailAccount, GoogleCredential, InterviewSchedule, JobSourceStatus, Offer, OutreachTask, Subscription, UsageQuota, UserProviderCredential`) have **no FK to `User` at all** — deleting a `User` row does NOT cascade to them, so each was deleted explicitly by `userId` before the `User` row.

### User-matching (BEFORE audit)
Queried each binding pattern from the ORCHESTRATOR CLEANUP ADJUDICATION + the delete-by-userId override from the ADJUDICATION ADDENDUM, live against `"User"`:

| Pattern | Live matches |
|---|---|
| `mv-signup-%@mv-signup-test.dev` | 0 (already absent — presumably lost in the documented 2026-07-18 prod-DB-wipe incident along with the pre-wipe admin/sarkar.vikram rows; confirmed via a broader `ILIKE '%mv-signup%'` sweep too — zero) |
| `mv-verify%` | 3 |
| `mv-vbatch2-%@example.com` | 2 |
| `mv-vb3-%@example.com` | 3 |
| `mv-qa-%@example.com` | 18 |
| BY-USERID override `c90279607e7688144c3d73b4d` (email now `resample@aether.local`, no longer pattern-matched — ADJUDICATION ADDENDUM §1) | 1 |

**Total distinct users matched for deletion: 27** (no overlaps). Full id→email map logged verbatim in the Phase-1 transcript below. Sanity-checked BEFORE any delete: `sarkar.vikram@gmail.com` (id `c68e14a84e3eafb4644b48202`) and `admin@aether.local` (id `c6c8d0163d973a8048e7e33b8`) are present and match **zero** delete patterns.

**2 accounts found NOT covered by any binding pattern — NOT deleted, flagged for orchestrator per brief ("ambiguous → do not delete, list it"):**
| userId | email | footprint |
|---|---|---|
| `c24222b002a0437c38bc45b2e` | `fixture-user-d965c19c@example.com` (created 2026-07-18T00:41:18Z) | Subscription=1 (free), UsageQuota=1 (free), UserProviderCredential=1. No Job/Resume/Application/etc. Looks like a leftover pytest/fixture-seed account, not an MV-run tester account — name doesn't match any `mv-*` convention used by this run. |
| `c5dc9f214d581a28eb910671d` | `mv-vb45-pro-1784361227@example.com` (name "MV VB45 Adversary", created 2026-07-18T07:53:49Z) | Subscription=1 (free — no paid grant active), UsageQuota=1 (free). No other rows. Almost certainly a disposable tester account from an undocumented "batch 4/5" adversarial sweep (naming mirrors `mv-vb3-*`/`mv-vbatch2-*`) that was never logged in this ledger or ENTITLEMENT-GRANT-LOG.md — does not literally match the `mv-vbatch2-%` or `mv-vb3-%` LIKE patterns, so left untouched per instructions. **Recommend the orchestrator add an explicit pattern/userId rule and re-run cleanup for this one account** (trivial footprint, no paid data, low risk either way). |

### PHASE 1 — matched-user deletion (children before `User`, single transaction, committed 2026-07-20T13:55:37Z)
Order: `ApprovalRequest → EmailThread → JobEmbedding (via Job join) → Application → Job → Resume → Contact → StoryEntry → AgentRun → [16 non-FK tables, any order] → User`. Every statement's rowcount was compared against a live BEFORE-audit count (`SELECT count(*) WHERE "userId" = ANY(matched_ids)` per table, captured before Phase 1 began) with an abort-on-exceed guard; every single one matched exactly (no exceedance, no shortfall):

```
[2026-07-20T13:55:36.898305Z] current_schema() == aether asserted (start of cleanup)
[2026-07-20T13:55:36.898334Z] === PHASE 1: matched-user (pattern + userId-override) deletion, 27 users ===
[2026-07-20T13:55:36.910387Z] DELETE FROM "ApprovalRequest" WHERE "userId" = ANY(matched_ids)         -> rowcount=47  (expected 47)
[2026-07-20T13:55:36.921158Z] DELETE FROM "EmailThread"      WHERE "userId" = ANY(matched_ids)         -> rowcount=3   (expected 3)
[2026-07-20T13:55:36.931748Z] DELETE FROM "JobEmbedding"     WHERE "jobId" IN (SELECT id FROM "Job" WHERE "userId" = ANY(matched_ids)) -> rowcount=0 (expected 0)
[2026-07-20T13:55:36.942723Z] DELETE FROM "Application"      WHERE "userId" = ANY(matched_ids)         -> rowcount=73  (expected 73)
[2026-07-20T13:55:36.960471Z] DELETE FROM "Job"               WHERE "userId" = ANY(matched_ids)         -> rowcount=318 (expected 318)
[2026-07-20T13:55:36.971377Z] DELETE FROM "Resume"            WHERE "userId" = ANY(matched_ids)         -> rowcount=25  (expected 25)
[2026-07-20T13:55:36.980548Z] DELETE FROM "Contact"           WHERE "userId" = ANY(matched_ids)         -> rowcount=2   (expected 2)
[2026-07-20T13:55:36.989453Z] DELETE FROM "StoryEntry"        WHERE "userId" = ANY(matched_ids)         -> rowcount=16  (expected 16)
[2026-07-20T13:55:36.999860Z] DELETE FROM "AgentRun"          WHERE "userId" = ANY(matched_ids)         -> rowcount=137 (expected 137)
[2026-07-20T13:55:37.008914Z] DELETE FROM "AgentConfig"             WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.019978Z] DELETE FROM "AgentProvider"           WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.029032Z] DELETE FROM "AgentQuotaBlock"         WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.038419Z] DELETE FROM "AnthropicOAuthState"     WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.047256Z] DELETE FROM "AnthropicOAuthToken"     WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.058171Z] DELETE FROM "BackgroundJob"           WHERE "userId" = ANY(matched_ids)   -> rowcount=100 (expected 100)
[2026-07-20T13:55:37.067199Z] DELETE FROM "CareerProfile"           WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.076089Z] DELETE FROM "GmailAccount"            WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.084955Z] DELETE FROM "GoogleCredential"        WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.096493Z] DELETE FROM "InterviewSchedule"       WHERE "userId" = ANY(matched_ids)   -> rowcount=2   (expected 2)
[2026-07-20T13:55:37.105404Z] DELETE FROM "JobSourceStatus"         WHERE "userId" = ANY(matched_ids)   -> rowcount=60  (expected 60)
[2026-07-20T13:55:37.114286Z] DELETE FROM "Offer"                   WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.123324Z] DELETE FROM "OutreachTask"            WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.132597Z] DELETE FROM "Subscription"            WHERE "userId" = ANY(matched_ids)   -> rowcount=27  (expected 27)
[2026-07-20T13:55:37.142358Z] DELETE FROM "UsageQuota"              WHERE "userId" = ANY(matched_ids)   -> rowcount=27  (expected 27)
[2026-07-20T13:55:37.151341Z] DELETE FROM "UserProviderCredential"  WHERE "userId" = ANY(matched_ids)   -> rowcount=0   (expected 0)
[2026-07-20T13:55:37.162190Z] DELETE FROM "User" WHERE id = ANY(matched_ids)                            -> rowcount=27  (expected 27)
[2026-07-20T13:55:37.179557Z] POST-PHASE-1 sanity: sarkar.vikram row present = True (('c68e14a84e3eafb4644b48202','sarkar.vikram@gmail.com'))
[2026-07-20T13:55:37.179579Z] POST-PHASE-1 sanity: admin row present = True (('c6c8d0163d973a8048e7e33b8','admin@aether.local'))
[2026-07-20T13:55:37.189450Z] PHASE 1 COMMITTED.
```

27 users deleted (all owned rows across the 24 user-owned tables + JobEmbedding cascade join): `mv-verify-adversary@mv-verify-test.dev` (cb6d3c2e1325cd7eda353a8c3), `mv-verifyfg-20260718T031439Z@example.com` (ca6e521cc0b19982537b3b4b5), `mv-verifyfg-signup-2026-07-18T03-17-37-675Z@example.com` (cca237b8cf152d54a9cb887de), `mv-vbatch2-free-20260718T045405Z@example.com` (c57b9fb5fce9f882ba35b8a22), `mv-vbatch2-pro-20260718T045405Z@example.com` (cb0159b14ae4852ad0f401f84), `mv-vb3-pro-1784355683@example.com` (ce34e6ad8555f8a9a1f32fb4e), `mv-vb3-signup001-1784355434@example.com` (cd06395974c0e7a5fd42c865f), `mv-vb3-signup004-1784355468@example.com` (c67b50546071be90ab831225c), `mv-qa-ej-2026-cebe@example.com` (c45107cb322162ee83efae3bf), `mv-qa-ej2-adv18@example.com` (c88fc72d11082ac709fd6a801), `mv-qa-final-a-free18@example.com` (cc623625e6be90fc99b3fa4f4), `mv-qa-final-a-pro18@example.com` (cb2b03a9bebcab4b7617d1c3c), `mv-qa-final-a-rl-1784415107@example.com` (ccd254e547d3bee5f239f23c6), `mv-qa-final-b-8f2a@example.com` (cee0c8f5076a48a3f166dee94), `mv-qa-final-b-victim-7c1@example.com` (c87e7575be459ff9c2dd5ceef), `mv-qa-final2-2a385f-nr@example.com` (c472704ece8d0718539b47954), `mv-qa-final2-2a385f@example.com` (c669c1cdb0ff1b2cd0a9b8bf9), `mv-qa-fr-69d1e2-nr@example.com` (cd63b6832b67eb3aa3d9a58c2), `mv-qa-fr-69d1e2@example.com` (c6b1aca1f10731e9866b7dd38), `mv-qa-fr-probe1@example.com` (c84f2710e9f146eeb86e9e511), `mv-qa-lastcheck-be068b@example.com` (c644b4d74664667b71f26e438), `mv-qa-lastcheck2-ff967d@example.com` (cc62794585997022a7897e2f0), `mv-qa-pii-distinct-9f3k@example.com` (c6c99121d1d2a26ae37543ddd), `mv-qa-pii-noresume-9f3k@example.com` (c43d8b2f3cbda5c787c107417), `mv-qa-resid-distinct-865c45@example.com` (cf6bb0e8a91954a87e00c0ee0), `mv-qa-resid-noresume-865c45@example.com` (c1561fd2195e1801d85872755), and the by-userId override `c90279607e7688144c3d73b4d` (login email `resample@aether.local`).

### PHASE 2 — orphaned user-owned rows (anti-join, no matching `User` row; single transaction, committed 2026-07-20T13:55:55Z)
Per ADJUDICATION ADDENDUM §2 ("delete any Subscription/UsageQuota **(or other user-owned) rows** whose userId has NO matching User row... hygiene requires removal"), the anti-join was run across **all 24 user-owned tables**, not just the one `Subscription` instance the ledger names as a "known instance." This surfaced a larger orphan set than the single documented example — all confirmed to belong to `userId`s with zero matching `"User"` row (i.e., permanently unreachable via any login, dangling artifacts of prior wipe/test cycles, not live grants and not real users' current data):

```
[2026-07-20T13:55:54.790491+00:00] current_schema() == aether asserted (start of Phase 2)
[2026-07-20T13:55:54.801869+00:00] DELETE (orphan) FROM "AgentConfig"            -> rowcount=27 (expected 27)
[2026-07-20T13:55:54.813535+00:00] DELETE (orphan) FROM "AgentProvider"          -> rowcount=2  (expected 2)
[2026-07-20T13:55:54.878670+00:00] DELETE (orphan) FROM "BackgroundJob"          -> rowcount=43 (expected 43)
[2026-07-20T13:55:54.889015+00:00] DELETE (orphan) FROM "CareerProfile"          -> rowcount=6  (expected 6)
[2026-07-20T13:55:54.916539+00:00] DELETE (orphan) FROM "GmailAccount"           -> rowcount=1  (expected 1)
[2026-07-20T13:55:54.926438+00:00] DELETE (orphan) FROM "GoogleCredential"       -> rowcount=1  (expected 1)
[2026-07-20T13:55:54.954691+00:00] DELETE (orphan) FROM "JobSourceStatus"        -> rowcount=21 (expected 21)
[2026-07-20T13:55:54.974299+00:00] DELETE (orphan) FROM "OutreachTask"           -> rowcount=6  (expected 6)
[2026-07-20T13:55:55.001986+00:00] DELETE (orphan) FROM "Subscription"           -> rowcount=5  (expected 5)
[2026-07-20T13:55:55.010771+00:00] DELETE (orphan) FROM "UsageQuota"             -> rowcount=5  (expected 5)
[2026-07-20T13:55:55.019763+00:00] DELETE (orphan) FROM "UserProviderCredential" -> rowcount=1  (expected 1)
[2026-07-20T13:55:55.241539+00:00] POST-DELETE orphan re-check across all 24 tables (should be {}): {}
[2026-07-20T13:55:55.262599+00:00] POST-PHASE-2 sanity: sarkar.vikram row present = True
[2026-07-20T13:55:55.262627+00:00] POST-PHASE-2 sanity: admin row present = True
[2026-07-20T13:55:55.274886+00:00] PHASE 2 COMMITTED.  Total orphaned rows deleted: 118
```
(`AgentRun, Application, ApprovalRequest, Contact, InterviewSchedule, Job, Resume, StoryEntry, AgentQuotaBlock, AnthropicOAuthState, AnthropicOAuthToken, Offer` had 0 orphans each — real FK-CASCADE tables never accumulate orphans since Postgres enforces referential integrity on them; the 0-orphan tables were still queried/deleted defensively and correctly no-opped.) Orphaned `userId`s found: `c58996b5b105c17e50f1ef2f8`, `cc29a76e324fbf19f438eb8be` (this is the **pre-wipe admin** id the ledger's ADJUDICATION ADDENDUM §2 already names explicitly as safe to purge — "not live grants... hygiene requires removal"), `c56d86e1ca82a716dc005908e`, `ce00a2fcfcda3bee9b11d4233`, `c0c41b8c7cc8feb2ed4481350`, `c4db0e9ff2dc7b9c350083c63`, `cf1b71b09cc8d21ee2bde1225` — all pre-date this MV run (residue of earlier Phase-4/5/6/7/prud-remediation swarm runs per MEMORY.md), all unreachable by definition (no `User` row exists to authenticate against them), none touch `sarkar.vikram` (id `c68e14a84e3eafb4644b48202`) or current `admin` (id `c6c8d0163d973a8048e7e33b8`) — both excluded from every anti-join by construction (they have valid `User` rows).

### PHASE 3 — admin's MV-prefixed test rows (defensive re-check; per rule §4)
BEFORE-audit had already shown admin (`c6c8d0163d973a8048e7e33b8`) owns **zero** rows in any content table (only its own `free`-plan `Subscription`=1/`UsageQuota`=1 — the account was freshly re-seeded 2026-07-20T01:05:37Z per the "admin account restored" section above, with no test data ever attached to the *current* admin id). Defensive re-verification post-Phase-1/2:
```
admin Job.title MV-prefixed count: 0        admin Job.source MV-prefixed count: 0
admin StoryEntry.title MV-prefixed count: 0  admin Contact.name MV-prefixed count: 0
admin Application count (any): 0             admin total Job rows (any): 0
```
**Nothing to delete for rule §4** — confirmed, not assumed.

### AFTER-VERIFICATION (a)–(g)
```
(a) zero Users match any delete pattern:
    mv-signup-%@mv-signup-test.dev: 0    mv-verify%: 0    mv-vbatch2-%@example.com: 0
    mv-vb3-%@example.com: 0              mv-qa-%@example.com: 0
    userId override c90279607e7688144c3d73b4d: 0 remaining
    VERDICT: PASS

(b) zero orphaned user-owned rows remain (anti-join across all 24 tables): 0
    VERDICT: PASS

(c) zero Subscription rows with planId != 'free' anywhere in the DB: 0 rows
    VERDICT: PASS

(d) admin login works via canonical recipe:
    POST /api/auth/login {"email":"admin","password":"admin123"} -> HTTP 200
    GET /api/auth/me (bearer token, first 8 chars eyJhbGci...) -> HTTP 200
    {"id":"c6c8d0163d973a8048e7e33b8","email":"admin@aether.local","name":"Administrator",
     "targetRole":"","location":"","isAdmin":false}
    VERDICT: PASS (note: the login payload key is "email", not "username" — {"username":...}
    404s with a 422 field-required error; documented here for future cleanup/QA agents)

(e) sarkar.vikram user row + Job count UNCHANGED from before-count:
    User row: ('c68e14a84e3eafb4644b48202', 'sarkar.vikram@gmail.com') — present, untouched
    (no DELETE statement in this run ever referenced this userId — excluded by construction
    from both the pattern-match set and the orphan anti-join, since her User row is valid)
    Job count: 41 (== BEFORE total Job=359 minus matched-to-delete Job=318 minus orphan
    Job=0 minus admin/ambiguous-account Job=0 — arithmetically forced to be exactly her
    pre-existing count; independently confirmed by per-owner breakdown showing all 41
    remaining Job rows belong to sarkar.vikram@gmail.com)
    VERDICT: PASS

(f) final total row counts per table (BEFORE -> AFTER):
    AgentConfig:            27 ->  0      AgentProvider:            2 -> 0
    AgentQuotaBlock:         0 ->  0      AgentRun:               193 -> 56
    AnthropicOAuthState:     0 ->  0      AnthropicOAuthToken:      0 -> 0
    Application:            73 ->  0      ApprovalRequest:         47 -> 0
    BackgroundJob:         143 ->  0      CareerProfile:            6 -> 0
    Contact:                 2 ->  0      EmailThread:              3 -> 0
    GmailAccount:            1 ->  0      GoogleCredential:         1 -> 0
    InterviewSchedule:       2 ->  0      Job:                    359 -> 41
    JobSourceStatus:        91 -> 10      Offer:                    0 -> 0
    OutreachTask:            6 ->  0      Resume:                  25 -> 0
    StoryEntry:             16 ->  0      Subscription:            36 -> 4
    UsageQuota:             36 ->  4      UserProviderCredential:   2 -> 1
    User:                   31 ->  4      JobEmbedding:             0 -> 0

    Final per-owner breakdown of every surviving non-zero table (confirms nothing
    leaked to a deleted-pattern account — impossible by construction, verified anyway):
      AgentRun(56), JobSourceStatus(10), Job(41) -> all sarkar.vikram@gmail.com
      Subscription(4)/UsageQuota(4) -> 1 each: admin@aether.local, sarkar.vikram@gmail.com,
        fixture-user-d965c19c@example.com, mv-vb45-pro-1784361227@example.com
      UserProviderCredential(1) -> fixture-user-d965c19c@example.com
    The 4 surviving Users are exactly: admin (KEEP), sarkar.vikram (KEEP), and the 2
    ambiguous accounts explicitly left undeleted above (not orchestrator-adjudicated yet).

(g) prod /api/health: GET https://5cb5f0620.abacusai.cloud/api/health -> HTTP 200
    {"status":"ok","version":"0.2.0"}
    VERDICT: PASS
```

### Summary
- **27 disposable test accounts deleted** (+ all owned rows across 24 user-owned tables + JobEmbedding), matching the binding ORCHESTRATOR CLEANUP ADJUDICATION patterns + the resample-account userId override, byte-for-byte rowcount-verified against a live BEFORE-audit at every one of the ~40 DELETE statements across 2 committed transactions.
- **118 orphaned rows deleted** (anti-join, no matching `User` row) across 11 tables (`AgentConfig, AgentProvider, BackgroundJob, CareerProfile, GmailAccount, GoogleCredential, JobSourceStatus, OutreachTask, Subscription, UsageQuota, UserProviderCredential`) — a broader sweep than the ledger's single named example, authorized by the ADDENDUM's general "(or other user-owned) rows" wording; includes the pre-wipe admin id `cc29a76e324fbf19f438eb8be` the ledger explicitly names.
- **Admin's MV-prefixed rows: 0 found** (nothing to delete — current admin account owns no test data).
- **2 accounts intentionally left undeleted** as ambiguous/not-pattern-covered (`fixture-user-d965c19c@example.com`, `mv-vb45-pro-1784361227@example.com`) — flagged above for orchestrator adjudication, not touched.
- **Keepers verified unaffected:** `sarkar.vikram@gmail.com` (Job count 41, unchanged) and `admin@aether.local` (login 200, `isAdmin:false`, 0 test-data rows) both confirmed live post-cleanup.
- **No Subscription rows with `planId != 'free'` remain anywhere** — all temporary Pro grants across the entire MV run were already reverted (per ENTITLEMENT-GRANT-LOG.md) and/or removed by this cleanup.
- **Zero pytest, zero restarts, zero code/git changes** — this was a DB-only operation per the brief.

Evidence: `uat/reports/evidence/manual-verification/cleanup-exit-2026-07-20/` (committed to the repo — `01-matched-users.json`, `02-before-audit.json`, `03-phase1-transcript.txt`, `04-phase1-actual-rowcounts.json`, `05-phase2-transcript.txt`, `06-phase2-actual-rowcounts.json`, `07-after-verification-transcript.txt`, `08-final-totals.json`, plus the escalated-deletion addendum artifacts `09`-`12` below). The Python scripts that generated them (`db.py`, `connect.py`, `enumerate_schema.py`, `check_extra.py`, `find_users.py`, `audit_before.py`, `check_ambiguous.py`, `check_all_fks.py`, `do_cleanup.py`, `do_cleanup_phase2.py`, `verify_after.py`, `final_breakdown.py`, `audit_escalated.py`, `do_cleanup_escalated.py`, `verify_escalated.py`) remain at `/home/ubuntu/aether-cleanup-mv/` on the ops VM (not part of this git repo — scratch tooling only, not a deliverable).

---

## ADDENDUM — 2026-07-20T14:01–14:02Z (coordinator-adjudicated escalated-account deletion)

**Coordinator ruling (received mid-run, after the two accounts above were flagged as ambiguous/not-pattern-covered):** DELETE BOTH.
1. `fixture-user-d965c19c@example.com` (userId `c24222b002a0437c38bc45b2e`) — "'fixture-user' is a test-fixture identity, no legitimate user registers that."
2. `mv-vb45-pro-1784361227@example.com` (userId `c5dc9f214d581a28eb910671d`) — "this is the batch-4/5 prod-verify qa account (the `mv-vb45-` prefix simply wasn't in the LIKE patterns; its grant/revert history is in the batch-4/5 sections of the grant log)."

Same discipline as Phase 1: delete by userId across all 24 user-owned tables + `JobEmbedding` (via `jobId` join), FK-safe order, per-statement rowcounts, one transaction with a tripwire (abort if any rowcount exceeds a freshly-captured live BEFORE-count), `current_schema()=='aether'` asserted at the start.

**Fresh BEFORE-audit (captured live 2026-07-20T14:01:44Z, immediately before delete — both User rows re-confirmed present with the expected email first):**
```
User check c24222b002a0437c38bc45b2e: ('c24222b002a0437c38bc45b2e', 'fixture-user-d965c19c@example.com', False)
User check c5dc9f214d581a28eb910671d: ('c5dc9f214d581a28eb910671d', 'mv-vb45-pro-1784361227@example.com', False)
Subscription: 2   UsageQuota: 2   UserProviderCredential: 1   JobEmbedding (via Job): 0
(all other 21 of the 24 user-owned tables: 0)
```

**DELETE transcript (single transaction, FK-safe order `ApprovalRequest → EmailThread → JobEmbedding → Application → Job → Resume → Contact → StoryEntry → AgentRun → [16 non-FK tables] → User`, committed 2026-07-20T14:01:44Z):**
```
[2026-07-20T14:01:44.179691+00:00] current_schema() == aether asserted (start of ESCALATED cleanup)
[2026-07-20T14:01:44.189177+00:00] DELETE FROM "ApprovalRequest"        -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.197641+00:00] DELETE FROM "EmailThread"            -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.206697+00:00] DELETE FROM "JobEmbedding" (via Job) -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.214920+00:00] DELETE FROM "Application"           -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.223183+00:00] DELETE FROM "Job"                   -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.231439+00:00] DELETE FROM "Resume"                -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.239686+00:00] DELETE FROM "Contact"                -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.247829+00:00] DELETE FROM "StoryEntry"             -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.256010+00:00] DELETE FROM "AgentRun"               -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.264214+00:00] DELETE FROM "AgentConfig"            -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.272693+00:00] DELETE FROM "AgentProvider"          -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.280913+00:00] DELETE FROM "AgentQuotaBlock"        -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.289547+00:00] DELETE FROM "AnthropicOAuthState"    -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.297900+00:00] DELETE FROM "AnthropicOAuthToken"    -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.312644+00:00] DELETE FROM "BackgroundJob"          -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.321208+00:00] DELETE FROM "CareerProfile"          -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.331984+00:00] DELETE FROM "GmailAccount"           -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.340277+00:00] DELETE FROM "GoogleCredential"       -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.349320+00:00] DELETE FROM "InterviewSchedule"      -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.358008+00:00] DELETE FROM "JobSourceStatus"        -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.366275+00:00] DELETE FROM "Offer"                  -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.374870+00:00] DELETE FROM "OutreachTask"           -> rowcount=0 (expected=0)
[2026-07-20T14:01:44.383528+00:00] DELETE FROM "Subscription"           -> rowcount=2 (expected=2)
[2026-07-20T14:01:44.391747+00:00] DELETE FROM "UsageQuota"             -> rowcount=2 (expected=2)
[2026-07-20T14:01:44.400239+00:00] DELETE FROM "UserProviderCredential" -> rowcount=1 (expected=1)
[2026-07-20T14:01:44.409657+00:00] DELETE FROM "User" WHERE id = ANY(target_ids) -> rowcount=2 (expected 2)
[2026-07-20T14:01:44.426948+00:00] POST-DELETE sanity: sarkar.vikram present = True (('c68e14a84e3eafb4644b48202','sarkar.vikram@gmail.com'))
[2026-07-20T14:01:44.426979+00:00] POST-DELETE sanity: admin present = True (('c6c8d0163d973a8048e7e33b8','admin@aether.local'))
[2026-07-20T14:01:44.437187+00:00] ESCALATED DELETE COMMITTED.
```
No tripwire tripped — every rowcount matched the fresh before-count exactly (2 accounts, minimal footprint: 2 `Subscription` + 2 `UsageQuota` + 1 `UserProviderCredential`, 0 everywhere else).

**RE-VERIFICATION (coordinator-requested subset: a, c, d, e, g):**
```
(a) zero pattern matches AND zero of these two userIds anywhere:
    pattern-based User matches remaining: 0; resample-userId-override remaining: 0
    escalated userId c24222b002a0437c38bc45b2e remaining in User table: 0
    escalated userId c5dc9f214d581a28eb910671d remaining in User table: 0
    total rows remaining anywhere owned by the 2 escalated userIds (24 tables + JobEmbedding): 0
    VERDICT: PASS

(c) zero Subscription rows with planId != 'free': 0 rows -- VERDICT: PASS

(d) admin login works via canonical recipe:
    POST /api/auth/login {"email":"admin","password":"admin123"} -> HTTP 200
    GET /api/auth/me (bearer token, first 8 chars eyJhbGci...) -> HTTP 200
    {"id":"c6c8d0163d973a8048e7e33b8","email":"admin@aether.local","name":"Administrator",
     "targetRole":"","location":"","isAdmin":false}
    VERDICT: PASS

(e) sarkar.vikram unchanged:
    User row: ('c68e14a84e3eafb4644b48202','sarkar.vikram@gmail.com') — present
    Job count: 41 (identical to the pre-escalation verification — untouched, as expected:
    no DELETE statement in this addendum ever referenced her userId)
    VERDICT: PASS

(g) prod /api/health: GET https://5cb5f0620.abacusai.cloud/api/health -> HTTP 200
    {"status":"ok","version":"0.2.0"}
    VERDICT: PASS
```

**Final state: exactly 2 Users remain in the entire database — `admin@aether.local` (`c6c8d0163d973a8048e7e33b8`) and `sarkar.vikram@gmail.com` (`c68e14a84e3eafb4644b48202`).** No accounts remain flagged as ambiguous; the escalation is fully resolved.

Evidence: `uat/reports/evidence/manual-verification/cleanup-exit-2026-07-20/09-escalated-before.json`, `10-escalated-delete-transcript.txt`, `11-escalated-actual-rowcounts.json`, `12-escalated-verification-transcript.txt`.
