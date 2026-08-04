# ADR-PROD-TESTDATA-PURGE — Production test-identity purge (GOLD-MASTER-V2 · G-K · §13.1.3 + §13.2)

**Status:** APPROVED-WITH-CONDITIONS (13 binding conditions, C1 … C13 — see §8.1)
**Role:** risk-officer (sole approver of RISKY-class deletions and destructive/irreversible operations)
**Date:** 2026-08-04
**Proposal origin:** orchestrator, verified first-hand 2026-08-04T01:55Z. **NOT self-proposed** — see §0.1.
**Executor:** `janitor`. **This agent executed nothing.** Zero DELETE/UPDATE/DDL was issued against production.
**Machine-readable manifest:** `uat/reports/evidence/gold-master-v2/cleanup/DELETION-MANIFEST-PROD-TESTDATA.json`

Claim tags: **[VERIFIED]** = query run this session against the live production database, output reproduced
here. **[INFERRED]** = reasoned from verified facts, not directly observed.

---

## 0. Headline

**APPROVED-WITH-CONDITIONS: 5,087 rows across 16 tables, owned by 13 `@mailinator.com` test identities.**

The two genuine accounts are structurally excluded, and I can prove it: **every** cross-user reference check
in this data model returns **zero**. Deletion is safe *if and only if* it is driven by `userId`.

> **The row count is a MOVING TARGET and the manifest is a census, not a contract.** During the ~15 minutes I
> spent authoring this, the in-scope set grew from 5,079 → 5,087 (`AgentRun` 7→10, `Application` 0→1,
> `EmailThread` 0→1, `ApprovalRequest` 1→2, `StoryEntry` 3→4) and the **owner's** `Job` count drifted
> 2,506 → 2,538. The 13 test identities are **still generating traffic**. Condition **C5 (quiescence gate)**
> is therefore not boilerplate — executing against a stale census would both miss rows and trip the guards.

| Question | Answer |
|---|---|
| Are Job rows shared/deduplicated across users? | **NO — strictly per-user.** §1 |
| Would the owner or the real free user lose anything? | **No.** §2 |
| Any shared/global rows destroyed? | **No.** §2.4 |
| Any audit or billing row destroyed? | **No audit rows at all.** 6 billing rows (free-tier, no money) — ruled deletable, §4 |
| Reversible by `git revert`? | **No.** Backup is mandatory and blocking. §5 |
| Safest correct answer "quarantine, don't delete"? | **No — delete is correct here**, and I explain why I rejected quarantine. §7.4 |

**The single most dangerous thing about this cleanup is the *predicate*, not the *scope*.** See §1.3 —
a `sourceUrl`-based DELETE would destroy **1,387 of the owner's genuine Job rows**. Condition **C2** bans it.

### 0.1 Governance note on my dual role

The brief names me both APPROVER and MANIFEST AUTHOR, which brushes against "never approve work you
proposed". I record the distinction explicitly: the **proposal** (that these 13 identities are §13.1.3
stale test data and must go) originated with the orchestrator and was independently verified by it before I
was engaged. My authorship is **scoping** — converting that proposal into an exact, executable row list —
not origination. I approve the orchestrator's proposal, not my own initiative. If the orchestrator considers
this insufficient separation, the correct remedy is a second risk-officer instance to counter-sign; I have
made that cheap by making every claim below independently re-runnable.

---

## 1. THE DECISIVE QUESTION — are Job rows per-user or shared?

### 1.1 Ruling: **Job rows are STRICTLY PER-USER. There is no row sharing. `shared_rows_risk = false`.**

**Schema proof [VERIFIED]** — `Job` carries a scalar owner column and a *per-user* uniqueness constraint:

```
Job_userId_sourceUrl_key | CREATE UNIQUE INDEX "Job_userId_sourceUrl_key"
                           ON aether."Job" USING btree ("userId", "sourceUrl")
Job_userId_fkey | Job.userId -> User.id | ON DELETE CASCADE
```

The unique key is `(userId, sourceUrl)` — **not** `(sourceUrl)`. Deduplication is scoped *inside* a user.
There is no join table, no `Job.ownerIds[]`, no many-to-many: a `Job` row has exactly one owner, always.

**Row-count proof [VERIFIED]** — the same job posting genuinely appears many times, as *separate rows*:

```
sourceUrls held by MORE THAN ONE user ............................. 1625
owner Job sourceUrls ALSO present as a mailinator-user copy ....... 1387
```

If rows were shared, those 1,625 URLs would be 1,625 rows with multiple owners. Instead they are ≥3,250
distinct rows with distinct primary keys, one per (user, URL) pair. **The overlap is in the *values*, not in
the *rows*.**

### 1.2 What this means for strategy

Deleting `Job WHERE userId IN (<13 test ids>)` removes 5,011 rows and **cannot** touch the owner's 2,506 rows
or the real free user's 0 rows, because no row satisfies both predicates — `userId` is scalar.

### 1.3 …and the trap this creates — **the most important finding in this ADR**

Because 1,387 job *URLs* are common to the owner and the test users, any cleanup written against **content**
rather than **ownership** is catastrophic:

```sql
-- CATASTROPHIC. NEVER RUN. Would delete 1,387 of the OWNER's genuine jobs.
DELETE FROM "Job" WHERE "sourceUrl" IN (SELECT "sourceUrl" FROM "Job" WHERE "userId" IN (<test ids>));
```

This is exactly the class of error the prior W-K adjudication caught (a manifest whose SQL would have
destroyed real submitted applications). It is a live hazard here because the overlap is large and
non-obvious. **Condition C2 makes `userId` the only permitted predicate and bans every content-derived one.**

---

## 2. NON-INTERFERENCE PROOF

### 2.1 The population [VERIFIED]

15 users. 13 `@mailinator.com` created 2026-08-03/04; 2 genuine `@gmail.com`. Confirms the orchestrator.

| Class | id | email | isAdmin | createdAt |
|---|---|---|---|---|
| **PROTECTED — owner** | `c6c8d0163d973a8048e7e33b8` | sarkar.vikram@gmail.com | **true** | 2026-07-20 |
| **PROTECTED — real free user** | `c4dc7f26c8b6adea37c5a6c75` | abhikadam28@gmail.com | false | 2026-08-03 |
| DELETE ×13 | see manifest `users_to_delete` | `%@mailinator.com` | false | 2026-08-03/04 |

### 2.2 How the two genuine accounts are excluded — three independent mechanisms

1. **Enumeration, not pattern.** The manifest lists 13 literal `userId` values. Neither protected id is among
   them. This holds even if someone later registers a `@mailinator.com` address.
2. **Scalar ownership.** Every table in scope filters on a single-valued `userId`. A row owned by a protected
   id cannot match a test id. There is no row with two owners anywhere in this schema.
3. **Pattern is a cross-check only.** `email LIKE '%@mailinator.com'` yields exactly the same 13 ids
   [VERIFIED]; C12 requires the janitor to assert that both sets agree **and** that the count is exactly 13
   before touching anything.

### 2.3 Cross-user reference audit — **8 FK checks + 4 soft-reference checks, ALL ZERO** [VERIFIED]

I enumerated the **real** FK graph from `pg_constraint` (not from `schema.prisma`), then tested every edge in
both directions for cross-user linkage:

| # | Edge | Cross-user rows |
|---|---|---|
| X1 | `Application.jobId` → `Job` | **0** |
| X2 | `Application.resumeId` → `Resume` *(RESTRICT)* | **0** |
| X3 | `Resume.sourceJobId` → `Job` | **0** |
| X4 | `Resume.parentId` → `Resume` (self) | **0** |
| X5 | `EmailThread.applicationId` → `Application` | **0** |
| X6 | `EmailThread.contactId` → `Contact` | **0** |
| X7 | `ApprovalRequest.applicationId` → `Application` | **0** |
| X8 | `ApprovalRequest.resolvedByUserId` | owner→owner only (60 rows), never test |
| S1 | `StoryEntry.mergedIntoId` → `StoryEntry` (soft, no FK) | **0** |
| S2 | `OutreachTask.contactId` → `Contact` (soft) | **0** |
| S3 | `BackgroundJob.runId` → `AgentRun` (soft) | **0** |
| S4 | `EmailThread.gmailAccountId` → `GmailAccount` (soft) | **0** |

The `<>` comparison is symmetric, so these simultaneously prove **(a)** no test-user row references a
protected-user row and **(b)** no protected-user row references a test-user row. There is no dangling
pointer to create in either direction.

### 2.4 No shared or global rows are touched [VERIFIED]

Tables with **no** user column are entirely out of scope and must not be referenced by any statement:

| Table | Rows | Ruling |
|---|---|---|
| `Plan` | 4 | **DO-NOT-TOUCH** — global pricing catalogue |
| `AdminSetting` | 2 | **DO-NOT-TOUCH** — global config |
| `ProviderCredential` | 4 | **DO-NOT-TOUCH** — global admin LLM credentials (`ciphertext`) |
| `StripeEvent` | 8 | **DO-NOT-TOUCH** — see §4.2 |
| `JobEmbedding` | **0** | empty; zero orphans [VERIFIED] |

---

## 3. WHAT WOULD BE DELETED, AND IN WHAT ORDER

### 3.1 Scope: 5,079 rows / 14 tables [VERIFIED]

Exact primary keys, owning user and `createdAt` for **every** row are in the manifest under `rows.<Table>`.

Census at final authoring (02:07Z). **Re-run before executing — see C5.**

| # | Table | Rows | Notes |
|---|---|---|---|
| 1 | `ApprovalRequest` | 2 | both **pending**, never resolved — §4.3 |
| 2 | `EmailThread` | 1 | appeared during authoring |
| 3 | `BackgroundJob` | 2 | |
| 4 | `OutreachTask` | 1 | |
| 5 | `Offer` | 1 | |
| 6 | `Application` | 1 | **appeared 02:06:48Z** — makes the RESTRICT ordering hazard live, §3.3 |
| 7 | `Contact` | 1 | |
| 8 | `Resume` | 3 | one parent/child pair, intra-user |
| 9 | `Job` | **5011** | 1563 + 1637 + 1811 across 3 test users |
| 10 | `StoryEntry` | 4 | |
| 11 | `AgentRun` | 10 | grew 7→8→10 during authoring |
| 12 | `JobSourceStatus` | 30 | composite PK `(userId, source)` |
| 13 | `AgentProvider` | 1 | composite PK `(userId, provider)` |
| 14 | `UsageQuota` | 3 | §4.1 |
| 15 | `Subscription` | 3 | §4.1 |
| 16 | `User` | 13 | last |

**Total 5,087.** Every row's primary key, owner and `createdAt` is enumerated in the manifest under
`rows.<Table>`.

Zero test-user rows currently exist in: `AgentConfig`, `CareerProfile`, `GmailAccount`, `GoogleCredential`,
`InterviewSchedule`, `AgentQuotaBlock`, `UserProviderCredential`, `AnthropicOAuthState`,
`AnthropicOAuthToken`, `AdminAuditLog`, `JobEmbedding` [VERIFIED]. They stay in the deletion order as
**assert-zero no-ops**, never as blind DELETEs — because "currently zero" is not "permanently zero":
`Application` and `EmailThread` were both on this list an hour ago and are not any more (§7.2).

**Discharging the prior W-K corollary.** That ruling required any proposal deleting an `Application` row to
first prove `SELECT count(*) FROM "ApprovalRequest" WHERE "applicationId" = <id>` is 0 **or explicitly own
the cascade**. There is now exactly one test-owned `Application` (`c04a0aa05ec83d4459c8da25e`, `draft`), and
the count is **not** zero — `ApprovalRequest c85069f643459be54016a6cb2` references it [VERIFIED]. **I
therefore explicitly own the cascade:** that approval is a `pending`, never-resolved request belonging to a
test identity, carrying no decision, no `resolvedByUserId` and no forensic content (§4.3). C3 deletes it
explicitly *before* the Application so the row count stays auditable rather than silently cascaded — which
is what the prior ruling actually asked for.

### 3.2 Cascade behaviour — **do not rely on it** [VERIFIED]

The live schema has **only 16 FK constraints across 31 tables**. `ON DELETE CASCADE` from `User` reaches
just 8 children: `AgentRun, Application, ApprovalRequest, Contact, EmailThread, Job, Resume, StoryEntry`.

**17 further tables carry a `userId` with no FK at all** — `Subscription`, `UsageQuota`, `JobSourceStatus`,
`AgentProvider`, `BackgroundJob`, `Offer`, `OutreachTask`, `AgentConfig`, `CareerProfile`, `GmailAccount`,
`GoogleCredential`, `AgentQuotaBlock`, `AnthropicOAuthState`, `AnthropicOAuthToken`, `UserProviderCredential`,
plus `AdminAuditLog.actorUserId` and `ApprovalRequest.resolvedByUserId`.

**Consequence:** `DELETE FROM "User"` alone silently orphans billing rows (`Subscription`, `UsageQuota`) and
7 other row classes. A cascade-only purge would look successful and leave **40 orphaned rows** behind.
This is not hypothetical — §6.1 documents pre-existing orphans from an earlier deletion. **C3 requires
explicit per-table DELETEs in the order below; cascade is a backstop, never the mechanism.**

### 3.3 Mandatory deletion order

Children before parents; soft references respected as if they were FKs.

```
 1. ApprovalRequest    8. Contact            15. AgentConfig
 2. EmailThread        9. Resume             16. CareerProfile
 3. BackgroundJob     10. Job                17. GmailAccount
 4. OutreachTask      11. StoryEntry         18. GoogleCredential
 5. Offer             12. AgentRun           19. UserProviderCredential
 6. InterviewSchedule 13. JobSourceStatus    20. AgentQuotaBlock
 7. Application       14. AgentProvider      21. AnthropicOAuthState/Token
                                             22. UsageQuota
                                             23. Subscription
                                             24. User   (LAST)
```
Tables currently at zero rows stay in the order as **assert-zero no-ops**, so the sequence remains correct
when C5's re-census finds new rows in them — as it already did for `Application` and `EmailThread`.

Every statement takes the identical form — no other predicate is permitted:

```sql
DELETE FROM "<Table>" WHERE "userId" IN (<the 13 literal ids from the manifest>);
```

**Ordering rationale:**
- **`Application` BEFORE `Resume` — CRITICAL, and no longer hypothetical.** `Application.resumeId → Resume`
  is **RESTRICT**, which (unlike `NO ACTION`) is checked immediately and **cannot** be satisfied by deleting
  parent and child in the same statement. When I began, there were 0 test Applications and this was a
  theoretical note. At **02:06:48Z a test-owned `Application` appeared** (`c04a0aa05ec83d4459c8da25e`,
  status `draft`) referencing `Resume c98808f2ce0485cfb741c69c5` [VERIFIED]. **Deleting `Resume` first now
  raises an FK violation and aborts the whole transaction.** **[INFERRED]** from PostgreSQL's documented
  RESTRICT-vs-NO-ACTION timing; **[VERIFIED]** that the constraint is RESTRICT and that the referencing row
  now exists.
- `ApprovalRequest` **before** `Application` — the FK is CASCADE, but the prior W-K ruling requires cascades
  be *owned explicitly* rather than fired silently. A new `ApprovalRequest c85069f643459be54016a6cb2`
  referencing that Application appeared in the same minute [VERIFIED].
- `EmailThread` before `Application`/`Contact` (`SET NULL`), `InterviewSchedule` before `Application`
  (no FK at all).
- `Resume` **before** `Job` — `Resume.sourceJobId → Job` is `SET NULL`; deleting resumes first avoids a
  pointless UPDATE pass over rows about to disappear.
- `BackgroundJob` **before** `AgentRun` — `runId` has no FK, so nothing would stop the orphan.
- `User` **last** — so that a mid-run abort leaves the account still present and re-derivable, never a
  half-deleted identity.

---

## 4. AUDIT AND BILLING RULING

### 4.1 Billing rows (`Subscription` ×3, `UsageQuota` ×3) — **APPROVED for deletion**

[VERIFIED] All three subscriptions are `status=active`, `planId=free`, `stripeSubscriptionId` **NULL** —
free-tier placeholder records auto-created at signup. **No money moved. No invoice, charge, or refund exists
against them.** They carry no financial-integrity value; the authoritative money record lives in Stripe, not
here. Deleting them destroys no accounting trail.

The owner's `pro` subscription and the real free user's row are **not** in scope [VERIFIED].

### 4.2 `StripeEvent` (8 rows) — **DO-NOT-TOUCH (hard)**

Global webhook table, no `userId`. All 8 rows date from 2026-07-21 (the payment-pipeline run) — **none**
relate to the 13 test identities [VERIFIED]. It is the **webhook idempotency ledger**: deleting a
`processed` row invites Stripe redelivery to be reprocessed as new, i.e. double-billing. Untouched, and it
would not be touched even if a test identity had generated one.

### 4.3 The 2 `ApprovalRequest` rows — **APPROVED, and neither is a BLOCKER-002 row**

The prior W-K adjudication designated 3 approval rows PRESERVE-DO-NOT-DELETE as the sole forensic record of
an unattributed privileged action. I checked directly — **neither in-scope row is one of them** [VERIFIED]:

| id | owner | status | `resolvedByUserId` | `applicationId` |
|---|---|---|---|---|
| `cfd7ee9ae7f591fef2c0673c9` | test `cb2aba1a…` | `pending` | NULL | NULL |
| `c85069f643459be54016a6cb2` | test `cb2aba1a…` | `pending` | NULL | `c04a0aa05ec83d4459c8da25e` |

Both are unresolved requests owned by a test identity. Neither records a decision, an actor, or an IP — the
three properties that made the BLOCKER-002 rows forensically load-bearing. **The PRESERVE designation is not
engaged by this purge.** The second row is the cascade I explicitly own per §3.1.

Ruling for future manifests: an `ApprovalRequest` that is **resolved** (`resolvedAt`/`resolvedByUserId`
non-NULL) is evidence of a privileged action and is **not** deletable as test data, even when its owner is a
test identity. Only unresolved, never-actioned requests qualify. **See §6.2 — a separate, serious finding
about the original PRESERVE rows.**

### 4.4 `AdminAuditLog` (216 rows) — **DO-NOT-TOUCH. Zero rows deleted.**

The strongest possible outcome: **no audit row is in scope at all** [VERIFIED].

- No test identity is ever an **actor**: `actorUserId` is only the owner (211) and one pre-existing orphan (5).
- No test identity is ever a **target**: rows matching a mailinator id *or* email as `targetId` = **0**.

So the "must audit rows be retained despite belonging to a test identity?" question does not arise on the
facts. I rule on it anyway, to bind future manifests: **YES — audit rows are retained unconditionally.**
An audit log whose entries can be deleted by the subject of the entry is not an audit log. Where a purge
leaves `actorUserId`/`targetId` pointing at a removed user, **the dangling reference is the correct
outcome** — the log records that an action happened, which remains true after the account is gone. This is
also the established behaviour of this system (§6.1). `AdminAuditLog` is hereby DO-NOT-TOUCH for this and
every subsequent test-data purge.

---

## 5. BACKUP AND ROLLBACK — blocking precondition

**This deletion is not reversible by `git revert`, by re-running a migration, or by any repo operation.
The backup IS the rollback. If the backup is absent or unverified, the deletion must not start.**

### 5.0 `pg_dump` IS UNUSABLE ON THIS VM — verified, and it changes the plan

I very nearly shipped a `pg_dump`-based backup plan. It would not have run:

```
$ pg_dump --version                          → pg_dump (PostgreSQL) 16.14
$ psql -c 'select version()'                 → PostgreSQL 17.9
$ pg_dump "$DB_URL" --schema=aether --schema-only -f /tmp/testdump.sql
pg_dump: error: aborting because of server version mismatch
pg_dump: detail: server version: 17.9; pg_dump version: 16.14
$ ls /usr/lib/postgresql/*/bin/pg_dump      → /usr/lib/postgresql/16/bin/pg_dump   (only v16 exists)
```
**[VERIFIED 2026-08-04]** Output file: **0 bytes**.

This is precisely the failure mode the prior W-K adjudication condemned (a manifest whose commands are
"factually unexecutable"). A janitor following a `pg_dump` instruction would produce an **empty** backup, and
— if it only checked "did the file appear" — could proceed to delete 5,079 production rows with no rollback
at all. **The mandated mechanism below uses `psql` only, which talks to the 17.9 server correctly** (every
query in this ADR ran through it).

### 5.1 The mandated backup — row-scoped JSONL via `psql`

`uat/reports/evidence/` is **gitignored** [VERIFIED: `uat/reports/.gitignore:1 → evidence/`]. Good — the
capture contains `passwordHash` and must never reach the public GitHub remote. But it also means the backup
is **not** version-controlled and lives only on this VM's disk. **C11 therefore makes an off-VM copy
blocking.**

```bash
BK=uat/reports/evidence/gold-master-v2/cleanup/backup; mkdir -p "$BK"
export PGOPTIONS='-c search_path=aether,public'
for T in ApprovalRequest BackgroundJob OutreachTask Offer Contact Resume Job \
         StoryEntry AgentRun JobSourceStatus AgentProvider UsageQuota Subscription User; do
  COL=$([ "$T" = User ] && echo id || echo userId)
  psql "$DB_URL" -v ON_ERROR_STOP=1 -c \
    "\\copy (select to_jsonb(t)::text from \"$T\" t where t.\"$COL\" in (<13 literal ids>)) \
     TO '$BK/$T.jsonl' WITH (FORMAT csv, QUOTE e'\\b', DELIMITER e'\\x1f')" || exit 1
done
sha256sum "$BK"/*.jsonl > "$BK/SHA256SUMS"
```

`to_jsonb(t)` captures **every column** including ones added after this ADR was written, so the capture
cannot silently drift out of date with the schema.

### 5.2 I validated the restore transform myself — it is byte-lossless

I did not take this mechanism on trust. Using **SELECT-only** statements (no writes, no temp tables, nothing
executed against production state), on 3 real production `Job` rows:

```sql
select to_jsonb(json_populate_record(null::aether."Job", '<captured line>'::json)) = '<captured line>'::jsonb;
→ t   t   t        -- 3/3 rows byte-identical
```
**[VERIFIED 2026-08-04]** The capture → restore round-trip loses nothing.

### 5.3 Verification gates — ALL of G1–G5 must pass BEFORE the first DELETE

1. **G1** All 14 `.jsonl` files exist and line counts equal `rows_by_table` **exactly** — `Job`=5011,
   `JobSourceStatus`=30, `AgentRun`=7, `Resume`/`StoryEntry`/`UsageQuota`/`Subscription`=3, `User`=13, the
   remaining five =1. Total **5,079**.
2. **G2** Every line parses as JSON and every owner column is one of the 13 ids — proof that no protected
   row was captured (and therefore none was in the delete set).
3. **G3** Spot-restore proof (§5.2 identity) on ≥3 rows per non-empty table.
4. **G4** `sha256sum -c SHA256SUMS` passes.
5. **G5** **Off-VM copy** to the project S3 path, object keys + sha256 recorded in `$BK/OFFVM.txt`.

### 5.4 Restore procedure — and why a full restore is FORBIDDEN

> **A whole-database or whole-schema point-in-time restore is PROHIBITED. Rollback MUST be a row-scoped
> re-insert.**

The owner's account is generating **live production traffic right now** (5,136 `AgentRun` rows; new
`ApprovalRequest` rows written within seconds of this analysis). Rolling the database back to a pre-deletion
snapshot would **destroy every row the owner created after the backup** — converting a reversible cleanup
into genuine data loss. That is the inverse-risk trap, and it is a worse outcome than the problem being
fixed.

- **R1** Stop at the first failed check. If still inside the transaction, `ROLLBACK` — nothing is lost.
- **R2** If already committed, restore in **reverse** of §3.3 (`User` **first**, then parents before
  children) so FK targets exist before referents.
- **R3** Per table:
  ```sql
  CREATE TEMP TABLE _restore(line text);
  \copy _restore FROM '<BK>/<T>.jsonl' WITH (FORMAT csv, QUOTE e'\b', DELIMITER e'\x1f')
  INSERT INTO aether."<T>" SELECT (json_populate_record(null::aether."<T>", line::json)).* FROM _restore;
  ```
- **R4** Verify restored counts against `rows_by_table`, and re-run the §5.2 identity on a sample.
- **R5** File the restore transcript to the governance evidence directory.
- **Honest limitation [INFERRED]:** restore returns the *rows*, not anything the application derived from
  them elsewhere (Stripe-side state, external caches). For 13 disposable identities that is immaterial —
  part of why deletion is proportionate here.
- **Irreversibility window:** between `COMMIT` and a successful R3, the data exists **only** in the JSONL
  files. If they are lost or were never verified, the deletion is **permanent**. G1–G5 exist to close that
  window; C11's off-VM copy is what makes it survivable if this VM is reset.

---

## 6. GOVERNANCE ESCALATIONS (out of scope — orchestrator must adjudicate)

These are **not** part of the purge and I take no action on them, but I will not file a clean report while
they are unrecorded.

### 6.1 Pre-existing orphans prove prior deletions ran without a manifest [VERIFIED]

`AdminAuditLog.actorUserId = cfa7006ffb1c374f2a43116f5` (5 rows, 2026-07-16) references a user that no longer
exists. `targetType='user'` rows point at four further non-existent ids (`c56667cb…`, `c2a429173…`,
`cc8076565…`, `c8f03fb3a…`). All 7 `@example.com` identities in `test-accounts-to-purge.txt` are gone from
`"User"` [VERIFIED: 0 rows]. So production users **have** been deleted before. I found no execution record
proving it followed §13.2. This raises the stakes on C1/C9 (verified backup and executed-manifest evidence).

### 6.2 The 3 BLOCKER-002 PRESERVE rows are **NOT IN THE DATABASE** — escalate

The prior adjudication designated `cd8c0a3e0382fae35a68be0d3`, `c36175418153a9925bc1318f1`,
`c7301be81ac6368902c8c2c78` as PRESERVE-DO-NOT-DELETE "for the remainder of the campaign" — the only
surviving attribution for an unexplained privileged action. **A direct lookup returns 0 rows** [VERIFIED].
`ApprovalRequest` still holds rows back to 2026-07-21, so this is not wholesale table loss.

I cannot distinguish between (a) the rows were deleted in violation of a standing PRESERVE designation and
(b) the ids were mis-transcribed in the prior ADR. **Both readings are filed for orchestrator adjudication
per the UNSURE rule.** Either way it is independent of this purge — **but it means the campaign currently
has an unverified claim that forensic evidence is preserved.** This should be resolved before G-K closes.

### 6.3 Missing FK constraints are a latent integrity defect

17 user-scoped tables have no FK to `User` (§3.2). Adding `ON DELETE CASCADE` would make future purges
one-statement and orphan-proof. **Not part of this manifest** — it is schema DDL, needs its own migration and
approval, and must not be bundled into a deletion. Filed as a recommendation only.

---

## 7. ADVERSARIAL REVIEW OF MY OWN MANIFEST

I am required to attack this. What follows is the honest list.

### 7.1 What would turn this from cleanup into irreversible harm

| # | Failure mode | Severity | Mitigation |
|---|---|---|---|
| 1 | Predicate written on `sourceUrl`/content → **1,387 owner jobs destroyed** | **CATASTROPHIC** | **C2** (userId-only, content predicates banned) |
| 2 | Backup skipped, truncated, or unverified → total unrecoverability | **CATASTROPHIC** | **C1** + gates G1–G5 (§5.3) |
| 3 | `DELETE FROM "User"` relying on cascade → 40 silent orphans, purge looks green | HIGH | **C3** (explicit per-table order) |
| 4 | Id typo / transcription error hitting a protected id | HIGH | **C12** (pre-flight assertions, count = 13) |
| 5 | Not run in one transaction → partial delete, inconsistent prod | HIGH | **C4** (single `BEGIN … COMMIT`) |
| 6 | Row counts drifted since I wrote the manifest (live system) | MEDIUM | **C5** (re-validate counts; drift ⇒ abort) |
| 7 | Backup copied into a tracked path → credentials pushed to public GitHub | HIGH | evidence/ is gitignored [VERIFIED]; **C11** requires S3, not a tracked path |
| 8 | Janitor follows a `pg_dump` instruction → **0-byte backup**, deletion proceeds unprotected | **CATASTROPHIC** | **C1** + §5.0 (pg_dump proven unusable here) |
| 9 | Full/PITR restore used as rollback → destroys concurrent owner writes | **CATASTROPHIC** | **C7** (row-scoped rollback only, §5.4) |

### 7.2 The concurrency risk I cannot fully eliminate

My census is a point-in-time read. Production is **live**, and this is not a theoretical caveat — **it
happened while I was writing this document**:

| Observation during authoring (~01:55Z → 02:07Z) | Before | After |
|---|---|---|
| Test-owned `AgentRun` | 7 | **10** |
| Test-owned `Application` | 0 | **1** |
| Test-owned `EmailThread` | 0 | **1** |
| Test-owned `ApprovalRequest` | 1 | **2** |
| Test-owned `StoryEntry` | 3 | **4** |
| **Owner** `Job` (protected) | 2,506 | **2,538** |

Two conclusions follow, and both changed the ruling:

1. **The 13 test identities are still active.** Something is still driving UAT traffic through them. This is
   why **C5's quiescence gate** is a hard precondition rather than a formality: executing against a stale
   census leaves residue and defeats the purge's purpose (§13.1.3 would still be violated afterwards).
2. **The owner's counts are not stable either** — which invalidates any literal guard (§7.5).

What *is* genuinely mitigated: the deletion is driven by *ownership*, and **no concurrent activity by a
protected user can create a row owned by a test user**. So drift can cause an **abort**, never a wrong
deletion. That is the correct failure direction — but it does mean the janitor should expect to re-census.

### 7.5 The bug I found in my own manifest — literal guards

An earlier revision of this manifest (authored by this same role, before the drift above was observed)
contained this guard, to be run immediately before `COMMIT`:

```sql
SELECT count(*) INTO n FROM aether."Job" WHERE "userId"='c6c8d0163d973a8048e7e33b8';
IF n <> 2506 THEN RAISE EXCEPTION 'GUARD FAILED: owner Job count changed: % (expected 2506)', n; END IF;
```

accompanied by the note *"Owner Job/AdminAuditLog/StripeEvent counts are stable (no owner job sourcing
running)."* **That note is false** — I measured the owner's `Job` count at 2,538 [VERIFIED], 32 rows above
the hardcoded 2,506.

This is worse than a harmless mistake, and it is worth naming precisely:

- The guard fires on **every** run, so the purge always rolls back — it looks like a broken cleanup.
- The obvious "fix" for whoever hits it is to **update the literal or delete the guard**. Deleting it removes
  *the only in-transaction protection on the owner's data*. A safety check that cries wolf trains the
  operator to disable safety checks.

**Corrected rule (C12):** every protected-side guard is a **delta captured inside the same transaction** —
owner `Job` count must not *shrink*; non-test `User` count must not *change*; only the true DO-NOT-TOUCH
tables (`AdminAuditLog`, `StripeEvent`, `Plan`, `ProviderCredential`) are asserted as exact equalities, and
even those against an in-transaction baseline rather than a number typed into a document. The corrected
`guard_sql` is in the manifest.

### 7.3 Where my own evidence is weakest — stated plainly

- **JSONB payloads are not reference-audited.** `ApprovalRequest.payload`, `AgentRun` detail and
  `AdminAuditLog.detailJson` may embed job/application ids as free text. No FK, no integrity guarantee, and
  I did not exhaustively scan them. **[INFERRED]** impact: a historical audit entry may quote a job id that
  no longer resolves. That is cosmetic — it is the same dangling-reference outcome §4.4 already rules
  correct — but I did not prove it, and I am not claiming I did.
- **RESTRICT-vs-NO-ACTION timing** is documented behaviour I reasoned from, not something I executed
  (correctly — executing it would be a write). Moot at 0 test Applications.
- **I did not verify the janitor's SQL**, because it does not exist yet. C13 requires it to come back to a
  risk officer for a read-only diff against this manifest before it runs.

### 7.4 Why I did NOT rule "quarantine instead of delete"

Quarantine (e.g. setting `User.suspended = true`, which this schema supports) was the serious alternative and
I rejected it on the facts:

- It **does not satisfy §13.1.3**. The requirement is that stale test data stop producing false-positive
  results. Suspended users' 5,011 `Job` rows still inflate every global count, sampling floor and
  dashboard aggregate. G-K would remain dishonestly closed. Quarantine would be *theatre*.
- The data has **no evidentiary value** — unlike the BLOCKER-002 approvals, which I would refuse to delete.
  These are 13 disposable mailinator identities from this run's own UAT, with no audit rows, no money, and
  no forensic content.
- **Reversibility is already provided** by the mandatory verified backup, which is strictly stronger than a
  soft-delete flag (it restores exact rows and PKs).

Had any of those three facts differed — an audit row in scope, a real payment, or an absent backup — my
verdict would have been REFUSE or quarantine. **The approval is contingent on those facts, not general.**

---

## 8. VERDICT PER CLASS

| Class | Rows | Verdict |
|---|---|---|
| Test-identity `User` rows (13) | 13 | **APPROVED-WITH-CONDITIONS** |
| Test-owned content (`Job`, `Resume`, `StoryEntry`, `AgentRun`, `Contact`, `Offer`, `OutreachTask`, `BackgroundJob`, `JobSourceStatus`, `AgentProvider`, `EmailThread`, `Application`) | 5,065 | **APPROVED-WITH-CONDITIONS** |
| Test-owned free-tier billing (`Subscription`, `UsageQuota`) | 6 | **APPROVED-WITH-CONDITIONS** (§4.1) |
| Test-owned `ApprovalRequest` (2, both pending, unresolved) | 2 | **APPROVED-WITH-CONDITIONS** (§4.3) |
| `AdminAuditLog` | 0 in scope | **REFUSED / DO-NOT-TOUCH** (§4.4) |
| `StripeEvent` | 0 in scope | **REFUSED / DO-NOT-TOUCH** (§4.2) |
| `Plan`, `AdminSetting`, `ProviderCredential` | 0 in scope | **REFUSED / DO-NOT-TOUCH** (§2.4) |
| Owner + real free-tier accounts | — | **PROTECTED — auto-reject any manifest naming them** |
| Stripe live-mode customer records (2) | — | **OPERATOR-DEFERRED** (§9) |
| Schema FK remediation | — | **DEFERRED** — separate migration + approval (§6.3) |
| BLOCKER-002 PRESERVE rows missing | — | **ESCALATED** to orchestrator (§6.2) |

### 8.1 Binding conditions (C1–C12 — identical numbering in the manifest)

- **C1 — BACKUP BEFORE DELETE, VERIFIED.** `pg_dump` is **unusable** on this VM (client 16.14 vs server
  17.9, §5.0). Use the §5.1 JSONL capture and pass **all** of G1–G5. No verified non-empty backup ⇒ no
  deletion. **Not waivable.**
- **C2 — IDENTITY PREDICATE ONLY.** Every statement filters on `"userId" IN (<13 literal ids>)` (`"id"` for
  `User`). Predicates on `sourceUrl`, `title`, `company`, `description`, `externalId`, `createdAt` ranges or
  any content-derived value are **BANNED** — §1.3 shows a content predicate would destroy 1,387 owner rows.
  A manifest violating C2 is auto-rejected.
- **C3 — EXPLICIT PER-TABLE DELETES** in the §3.3 order. Do **not** rely on `ON DELETE CASCADE`: 17
  user-scoped tables have no FK to `"User"` and would be silently orphaned (§3.2).
- **C4 — SINGLE TRANSACTION.** All DELETEs plus the guard assertions inside one `BEGIN … COMMIT`; abort the
  whole transaction on any error.
- **C5 — RE-VALIDATE COUNTS** immediately before deleting. Any drift from `rows_by_table` ⇒ **ABORT** and
  return to the risk officer (see §7.2 — drift is expected on a live system; abort is the correct response).
- **C6 — `AdminAuditLog` and `StripeEvent` ARE DO-NOT-TOUCH.** Zero rows in scope; do **not** "tidy" their
  dangling references (§4.2, §4.4). Likewise `Plan`, `AdminSetting`, `ProviderCredential` (§2.4).
- **C7 — ROW-SCOPED ROLLBACK ONLY.** A full-DB / whole-schema / PITR restore is **PROHIBITED** — it would
  destroy concurrent owner writes (§5.4).
- **C8 — JANITOR EXECUTES.** The authoring risk officer must not run the deletion.
- **C9 — FILE THE TRANSCRIPT.** Pre-census, backup verification, transaction log and post-checks to
  `uat/reports/evidence/gold-master-v2/cleanup/`, plus a governance record naming the approver under
  `uat/reports/evidence/launch-ready/governance/`.
- **C10 — STRIPE IS NOT COVERED.** G-K may not be recorded as fully closed until the §9 operator items are
  dispositioned by a human.
- **C11 — OFF-VM COPY IS BLOCKING.** The backup lives in a gitignored, unversioned directory on one VM.
  Copy to S3 with recorded object keys + sha256 **before** the first DELETE (gate G5).
- **C12 — PRE/POST-FLIGHT ASSERTIONS, inside the transaction — AS DELTAS, NEVER LITERALS.**
  *Pre* (before the first DELETE): the id-set matching `email LIKE '%@mailinator.com'` equals
  `users_to_delete` **exactly**; neither protected id appears in it; and **capture a baseline** into a temp
  row — `n_other_users`, `n_owner_jobs`, `n_audit`, `n_stripe`, `n_plan`, `n_provcred`.
  *Post* (before `COMMIT`): both protected ids still present; `"User"` rows **not** in the delete set
  unchanged vs `n_other_users`; mailinator users = **0**; owner `Job` count **≥** `n_owner_jobs` (never
  less); `AdminAuditLog`/`StripeEvent`/`Plan`/`ProviderCredential` unchanged vs baseline.
  Any mismatch → **ROLLBACK**. Executable `guard_sql` is in the manifest under `verification.guard_sql`.
  **See §7.5 — a literal guard here is itself a defect.**
- **C13 — SQL REVIEW.** The janitor's actual SQL must be diffed read-only against the manifest by a risk
  officer before it runs.

---

## 9. OPERATOR-DEFERRED (cannot be completed from inside this VM)

These are **not** DB rows and are **not** approved for any in-VM action. They require the human operator in
the Stripe dashboard.

1. **Live-mode Stripe customer records — 2** [VERIFIED, from `Subscription.stripeCustomerId`]:
   - `cus_V0KsL1wgumpXag` — `aether.audit.qa.1785756940@mailinator.com` (`ca70e965df3e3e7cf22f0c080`)
   - `cus_V0L97Kz0LbPZ3M` — `aether-paytest-1785758152@mailinator.com` (`c39d2dfe1afa1cdc7ee76c489`)

   Both have `stripeSubscriptionId` NULL — customer objects only, no live subscription, no charge.
   **Ordering matters:** the local `Subscription` rows are the *only* pointer to these customer ids. Once
   deleted, the link is recoverable only from the backup or this ADR — hence they are recorded here in
   plaintext (customer ids are identifiers, not credentials). Recommended operator action: delete both
   customers in the Stripe **live** dashboard, or tag them `test-identity` if Stripe retention forbids
   deletion. Deferred, not approved — I have no authority over the Stripe account.
2. **The §18/Stripe-probe disposable account.** Its `@example.com` identity is **already absent** from
   `"User"` [VERIFIED: 0 rows]. Nothing remains to delete in-DB. Any residual Stripe-side artefact falls
   under item 1.
3. **Pre-existing orphaned audit references** (§6.1) — retained by design per §4.4. No operator action;
   recorded so a future integrity scan does not re-raise them as new.

---

**Approver:** risk-officer (GOLD-MASTER-V2 · G-K)
**Executed:** nothing. Read-only queries against production only; zero writes.
**Manifest:** `uat/reports/evidence/gold-master-v2/cleanup/DELETION-MANIFEST-PROD-TESTDATA.json`

---
---

# ADDENDUM A — second risk-officer instance (2026-08-04T02:00–02:08Z)

**Author:** a *second* risk-officer sub-agent, dispatched on the same G-K task and working concurrently with
the author of §§0–9 above. Neither instance was aware of the other until a read-modify-write collision on the
manifest path was detected at 02:01:48Z.

**Disposition: the ruling above is ENDORSED, not replaced.** I re-derived the substantive findings
independently and reached the same conclusions — per-user `Job` rows, `shared_rows_risk = false`, the
content-predicate trap, the 17 tables with no FK to `"User"`, `AdminAuditLog`/`StripeEvent` DO-NOT-TOUCH, the
`pg_dump` failure, the prohibition on full-DB restore, and the BLOCKER-002 escalation. **Independent
convergence on all of these raises confidence in the ruling.** Two claims above I re-verified first-hand
before endorsing them:

- Stripe customer ids `cus_V0KsL1wgumpXag` (`aether.audit.qa…`) and `cus_V0L97Kz0LbPZ3M`
  (`aether-paytest…`), both with `stripeSubscriptionId` NULL, `planId=free` — **confirmed exactly** [V].
- `pg_dump` 16.14 vs server 17.9 aborts **and leaves a 0-byte file** — reproduced [V].

This addendum records only what §§0–9 do **not** contain. Where they conflict, **this addendum governs**,
because it rests on later observations.

## A.1 EXECUTION-BLOCKING: the test identities are NOT quiesced — a UAT session is still running

§7.2/C5 treat scope drift as a possibility to be caught by re-validation. **Drift is not hypothetical — it is
happening now, and its cause is an active session.** [V]

| Time (UTC) | Observation |
|---|---|
| 01:59 | 20-minute look-back: **0** writes for every mailinator identity. Quiescence appeared satisfied. |
| 02:02:48 | **New** `AgentRun` `c43ed09590ee96b454dbf51e1`, user `cb2aba1a9ec4787b28d460d22`, `status=completed`. |
| 02:03 | In-scope total moved **5,079 → 5,080** *during manifest generation*. |
| 02:06:58 | Test-user `AgentRun` count now **9** (7 → 8 → 9); **2** writes in the preceding 10 minutes. |

`Job` held steady at 5,011 throughout; all drift is in `AgentRun`. Some UAT sub-agent is **still driving a
`@mailinator.com` identity**.

**Why this is blocking, not cosmetic.** Under C5 as written, an executor re-validates, sees drift, aborts —
and can loop indefinitely while the session keeps writing. Worse, if a re-validation happens to land in a
quiet gap, the purge would delete rows out from under a running session, producing FK/500 errors in
production for that session and corrupting whatever verification it is performing.

**C5-A (supersedes C5, binding) — QUIESCENCE GATE.** Before re-validation is even attempted:

1. **0** new rows for any mailinator identity across
   `AgentRun`/`Job`/`ApprovalRequest`/`Application`/`Resume` for **≥ 30 consecutive minutes**; **and**
2. explicit orchestrator confirmation that **every UAT sub-agent using a mailinator identity has
   terminated**; **and**
3. re-run the census — any row in the live scope but **absent from the manifest** must be listed and
   **re-approved by a risk officer**. Never widen the scope silently.

**The approval stands on the merits; the timing does not.** As of 02:06:58Z the janitor must **not** execute.

## A.2 The manifest now carries every primary key

The version of `DELETION-MANIFEST-PROD-TESTDATA.json` in place at the collision listed table names and counts
only. The current file enumerates **the exact primary key, owning user and creation timestamp of every row**,
across **26 steps** (14 with rows, 12 confirmed empty and listed to prove they were checked). A §13.2 manifest
without exact rows is not executable as written, and cannot support C13's read-only SQL diff.

Self-checks that pass on the current file [V]: row-id count equals `total_rows_to_delete`; **no** enumerated
row belongs to either protected id; **no** generated statement references `sourceUrl`/`title`/`company`/
`description` (machine-enforced C2).

**The `total_rows_to_delete` figure is a snapshot, not a constant** — it read 5,079, then 5,080, and by
02:06:58Z the live scope was 5,081. The enumerated list is a **review artifact and integrity baseline**; the
identity predicate plus the C5-A re-validation is what actually bounds the deletion. Treat any exact total in
this ADR or the manifest as "as-of", never as an assertion about execution time.

## A.3 Restore-path validation (independent reproduction)

Reproduced the §5.2 result on different data [V]: 5,011 `Job` rows captured via tuples-only
`row_to_json` → 5,011 lines, **0 unparseable**, NULLs preserved as JSON `null`; 3 rows reconstructed through
`json_populate_record` into a session-local TEMP table and compared `to_jsonb(restored) = to_jsonb(live)` →
**3/3 byte-identical**. No production table was written.

One capture-format trap worth recording: `\copy (…) TO <file>` in the **default text format** escapes
backslashes and corrupts the emitted JSON (verified by a failed parse of all 5,011 lines). Tuples-only
stdout (`psql -At -c …`) does not. Read the JSONL back with
`\copy … FROM … WITH (FORMAT csv, QUOTE e'\b', DELIMITER e'\x1f')`.

## A.4 Concurrent authorship is itself a governance hazard

Two risk-officer instances wrote to the same manifest and ADR paths within minutes. The manifest was
observed in a **merged state** at 02:01:48Z, carrying one author's identity fields and row counts alongside
the other author's `deletion_order` and backup command — including the **`pg_dump` command this ADR
rejects as provably broken**. Had that merged file been executed, C1 would have been satisfied on paper by a
backup step that produces a 0-byte file.

This is the `MQ-3` defect named in the 2026-07-31 W-K ruling — `[VERIFIED]` tags from one author migrating
onto another author's unverified content — reproduced live.

**Required of the orchestrator:**

- Ensure a **single** authoring agent owns each governance path; do not dispatch duplicate risk officers onto
  one artifact.
- **Re-read the manifest immediately before authorising execution** and confirm it has not been overwritten.
  sha256 as written by this instance:
  `ac43a9a805d3b2c9b5fa5822730d67a31245856c13c9d9c3dcb868083dd3e3d3`
  (recompute and compare; a mismatch means a third write landed).
- Note that neither ADR nor manifest is committed. `docs/delivery/` **is** tracked, so this ADR is
  committable and should be committed (`git commit --only docs/delivery/ADR-PROD-TESTDATA-PURGE.md` —
  the tree is shared with another session, so never `git add -A`). The manifest is **not** committable:
  `uat/reports/.gitignore` line 1 is `evidence/` [V], which is exactly why C11's off-VM copy is blocking.

## A.5 Summary of this addendum

| Item | Effect |
|---|---|
| §§0–9 ruling | **ENDORSED** — independently re-derived, no correction required |
| C5 | **SUPERSEDED by C5-A** — quiescence gate added (A.1) |
| Execution status | **BLOCKED** as of 2026-08-04T02:06:58Z — UAT session still active |
| Manifest | Now row-exact (5,080 PKs at snapshot); self-checks pass (A.2) |
| Restore path | Independently reproduced byte-lossless (A.3) |
| New governance escalation | Concurrent authorship / merged-manifest hazard (A.4) |

**Second approver:** risk-officer (second instance), GOLD-MASTER-V2 · G-K
**Executed:** nothing. Production reads only; two session-local TEMP tables for restore validation; **zero
writes to any production table.**
