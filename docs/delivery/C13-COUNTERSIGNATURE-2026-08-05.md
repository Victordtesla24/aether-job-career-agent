# C13 COUNTER-SIGNATURE — retrospective review of the executed production purge

**Condition:** C13 (`ADR-PROD-TESTDATA-PURGE.md` §8.1) — *"The janitor's actual SQL must be diffed read-only
against the manifest by a risk officer before it runs."*
**Reviewer:** risk-officer (third instance) — did **not** author the manifest, did **not** author the ADR, did
**not** execute the purge.
**Reviewed:** 2026-08-05 · **Purge executed:** 2026-08-05T07:31:28Z (already committed)
**Executed against production:** nothing. `SELECT` only — zero DELETE/UPDATE/INSERT/DDL, zero temp tables.

## VERDICT: **COUNTERSIGNED-WITH-EXCEPTIONS**

**The SQL that ran is the SQL that was approved.** 25 statements, identity-predicate only, exact manifest
order, one transaction, no table outside the approved set, no protected row touched. I verified the outcome
against production myself and it is clean. **The backup is genuinely restorable — I proved it on all 5,108
rows, not a sample.** This was a reversible operation, not a permanent one.

Four exceptions are recorded below. None of them changed what was destroyed. One of them
(**EX-3**) is a live, unresolved defect in the operator handoff that I found in the backup and that appears in
no other artifact — read it.

---

## Inputs and their integrity

| Artifact | sha256 | Status |
|---|---|---|
| `…/backup-20260805T072800Z/purge-executed.sql` | `9c4374f5e7725fb3298e6354f0be86eda9139dc9a62e925cfa539490c0ac088e` | matches brief ✔ |
| `…/cleanup/DELETION-MANIFEST-PROD-TESTDATA.json` | `2fc7e193085feb9e96cdc1f2db25dbc911df112cae29f62cddf956885e754d5a` | matches ADR/orchestrator prefix ✔ |
| `…/backup-20260805T072800Z/MANIFEST-as-executed.json` | `2fc7e193085feb…` | **byte-identical** to the approved manifest ✔ |

The manifest consumed at execution was not a different file from the one approved. Verified by full JSON diff,
not by hash alone.

---

## 1. Did the SQL match the approval?  **YES**

Machine-parsed every statement in `purge-executed.sql` and checked each against the manifest.

| Check | Result |
|---|---|
| Statements that write | **25 `DELETE` + 1 `CREATE TEMP TABLE`**. Nothing else. No `UPDATE`, `INSERT`, `TRUNCATE`, `DROP`, `ALTER`, `GRANT`, `COPY` |
| Table sequence vs `deletion_order` | **identical, position for position, all 25** |
| Tables deleted but not in `deletion_order` | **none** |
| Tables in `deletion_order` but not deleted | **none** |
| Id list per statement | **set-equal to the manifest's 13 `users_to_delete`** in all 25 statements — no more, no fewer |
| Predicate column | `"userId"` on 24 tables, `"id"` on `User` — correct in all 25 |
| Protected ids in any DELETE predicate | **0** (`c6c8d0163d973a8048e7e33b8`, `c4dc7f26c8b6adea37c5a6c75`) |
| Row counts (transcript) vs re-census | **25/25 exact**; total **5,108** |

The one non-DELETE write-shaped statement is `CREATE TEMP TABLE _base … ON COMMIT DROP` (line 76), which
**C12 mandates** ("capture a baseline into a temp row"). It is session-local, dropped at COMMIT, and touches no
production table.

**Independent scope check.** I enumerated every base table in schema `aether` carrying a `userId` column: there
are exactly **24**, plus `User` = **25 user-scoped tables**. The manifest's `deletion_order` is *set-equal* to
that list. No user-scoped table was omitted, and none outside it was touched. Schema has 31 base tables; the
6 non-user-scoped ones are the DO-NOT-TOUCH set plus `JobEmbedding` (0 rows).

## 2. C2 — identity predicates only?  **YES, and I proved the trap was real**

Every DELETE predicate is literally `WHERE "userId" IN (<13 literal ids>)` / `WHERE "id" IN (…)`. Zero
occurrences anywhere in the file of `sourceUrl`, `title`, `company`, `description`, `externalId`, `createdAt`,
`updatedAt`, `ILIKE`, `~~`, or any subquery predicate.

Three `LIKE` occurrences exist — **lines 13, 15 and 145** — all of the form `email LIKE '%@mailinator.com'`,
all inside `SELECT count(*)` guard assertions that C12 explicitly requires (*"the id-set matching
`email LIKE '%@mailinator.com'` equals `users_to_delete` exactly"*). **None is a delete predicate.** C2 is not
engaged by a read-only cross-check.

**The C2 hazard was live, and here is post-hoc proof it was contained.** The ADR's central warning was that
1,387 of the owner's `Job` rows share a `sourceUrl` with a test copy. Counting is not proof — a count can rise
while rows are lost. So I counted the owner's surviving `Job` rows *created before the purge instant*:

```
owner Job rows now                                       3083
owner Job rows with createdAt < 2026-08-05T07:31:28Z     3074
owner Job baseline recorded at 07:29Z                    3074
```

Exactly equal. **Not one owner `Job` row that existed before the purge is missing.** A content-derived
predicate would have destroyed 1,387 of them.

## 3. C6 — `AdminAuditLog` / `StripeEvent` absent?  **C6 SATISFIED — but they are NOT absent, and I will not sign that they are**

The brief asked me to confirm these tables "appear nowhere in the executed SQL." **They appear — four times.**

| Line | Statement |
|---|---|
| 79 | `(SELECT count(*) FROM aether."AdminAuditLog") AS n_audit,` |
| 80 | `(SELECT count(*) FROM aether."StripeEvent") AS n_stripe,` |
| 149 | `SELECT count(*) INTO n FROM aether."AdminAuditLog";` |
| 151 | `SELECT count(*) INTO n FROM aether."StripeEvent";` |

All four are `SELECT count(*)`. `Plan` and `ProviderCredential` appear the same way (lines 81/82, 153/155);
`AdminSetting` and `JobEmbedding` appear not at all.

**Ruling: C6 is satisfied.** C6's text is *"ARE DO-NOT-TOUCH … do not 'tidy' their dangling references"* — it
bans mutation, not observation. And C12 **requires** these exact reads: *"`AdminAuditLog`/`StripeEvent`/`Plan`/
`ProviderCredential` unchanged vs baseline."* A file in which they appeared nowhere would violate C12.
The two conditions are jointly satisfiable only by precisely what this SQL does.

The brief's phrasing is stricter than the condition it cites. I am recording the distinction rather than
signing a statement that is false on the text.

## 4. C4 — one transaction?  **YES, and provably so**

- One `BEGIN;` (line 5), one `COMMIT;` (line 159). Zero `ROLLBACK`, `SAVEPOINT`, `START TRANSACTION`, `\c`.
- All 25 DELETEs and both `DO` guard blocks lie between them. Nothing follows `COMMIT;` but a newline.
- `\set ON_ERROR_STOP on` (line 4) — any error aborts psql with the transaction open, i.e. implicit rollback.

**Proof it was one transaction in one session at runtime, not merely on paper:** `_base` is a `TEMP … ON COMMIT
DROP` table created *before* the deletes (line 76) and read *after* them by the post-flight guard (line 140,
`SELECT * INTO b FROM _base`). A temp table exists only inside its session, and `ON COMMIT DROP` destroys it at
the first COMMIT. The transcript shows that read succeeding and `PSQL EXIT CODE: 0`. Had the file been run
statement-by-statement, or had any intermediate commit occurred, the post-flight guard would have failed with
*relation "_base" does not exist*. It did not. **One session, one transaction, atomic.**

## 5. Ordering vs the `RESTRICT` constraint?  **YES — and the hazard was live**

I re-derived the FK graph from `pg_constraint` myself: **16 FK constraints**, exactly as the ADR claimed.

```
Application_resumeId_fkey | Application.resumeId -> Resume.id | ON DELETE RESTRICT | deferrable = f
```

Executed order: **`Application` = step 07, `Resume` = step 09.** Referent deleted before target. Correct.

This was not theoretical. The backup shows the deleted `Application c04a0aa05ec83d4459c8da25e` carried
`resumeId = c98808f2ce0485cfb741c69c5`, and that Resume is in `Resume.jsonl`. Reversing steps 07 and 09 would
have raised an immediate FK violation and aborted the transaction. The ordering was load-bearing and held.

Other ordering constraints, all satisfied: `ApprovalRequest`(01) before `Application`(07) — CASCADE owned
explicitly rather than fired silently, per the prior W-K ruling; `Resume`(09) before `Job`(10) — `SET NULL`
edge; `BackgroundJob`(03) before `AgentRun`(12) — soft reference, no FK; `User` last (25).

---

## 6. Independent verification against production

Run by me, read-only, today. I took no number from the executor or the orchestrator on trust.

**Users**

```
c6c8d0163d973a8048e7e33b8 | sarkar.vikram@gmail.com | isAdmin=t | 2026-07-20
c4dc7f26c8b6adea37c5a6c75 | abhikadam28@gmail.com   | isAdmin=f | 2026-08-03
(2 rows)
```
`%@mailinator.com` users: **0**. Of the 13 purged ids, still present as a `User`: **0**.

**Residue and orphans — swept across all 24 user-scoped tables, not a sample**

| Metric | Result |
|---|---|
| Rows still owned by any of the 13, any table | **0 in all 24** |
| Rows whose `userId` has no `User` row (orphans) | **0 in all 24** |
| Dangling references on surviving rows (10 hard + soft edges: `Application.jobId/resumeId`, `Resume.sourceJobId/parentId`, `EmailThread.applicationId/contactId`, `ApprovalRequest.applicationId`, `StoryEntry.mergedIntoId`, `OutreachTask.contactId`, `BackgroundJob.runId`) | **0 on every edge** |
| `AdminAuditLog.actorUserId` referencing any of the 13 | **0** |
| `AdminAuditLog.actorUserId` dangling | **5** — the pre-existing 2026-07-16 orphans from ADR §6.1, unchanged. Not created by this purge |

**DO-NOT-TOUCH tables**

`AdminAuditLog` **216** · `StripeEvent` **8** · `Plan` **4** · `AdminSetting` **2** · `ProviderCredential` **4**
· `JobEmbedding` **0** — every one identical to the 07:29Z pre-deletion baseline.

**Protected rows — stronger than "did not decrease"**

A rising count can hide a deletion. For every protected-user table carrying `createdAt`, I counted surviving
rows *created before the purge instant* and compared to the 07:29Z baseline:

| | owner baseline | owner pre-purge rows surviving | lost |
|---|---|---|---|
| Job | 3074 | 3074 | **0** |
| AgentRun | 5621 | 5624 | **0** |
| Application | 258 | 259 | **0** |
| ApprovalRequest | 482 | 483 | **0** |
| Resume | 275 | 275 | **0** |
| EmailThread / StoryEntry / BackgroundJob / GmailAccount / CareerProfile / AgentConfig / AgentProvider / JobSourceStatus / Anthropic* / Subscription / UsageQuota | unchanged | unchanged | **0** |

**Zero protected rows lost, in any table.** The second genuine user (`abhikadam28@gmail.com`) is byte-for-byte
identical in every table: 1 `Subscription`, 1 `UsageQuota`, 1 `User`, 0 everywhere else — before and after.
(Surpluses of 1–3 in `AgentRun`/`Application`/`ApprovalRequest` are rows the owner created in the ~2 minutes
between baseline capture and COMMIT — live traffic, exactly as the ADR predicted.)

**Row-level proof the deletion actually happened.** Counts prove absence in aggregate; I checked identity. All
**5,108** backed-up primary keys, queried against production: **0 still present**, in all 16 tables. The purge
deleted precisely the rows it captured — no more, no fewer.

---

## 7. Is the backup genuinely restorable?  **YES — proven on 5,108 of 5,108 rows**

This is the finding that decides whether the operation was reversible. I did not sample it.

**Completeness**

| Check | Result |
|---|---|
| Files | 16 `.jsonl` — exactly the 16 tables with non-zero deletions |
| Lines | **5,108** total; per-table line count **equals the transcript DELETE count for all 16 tables** |
| JSON parse | **5,108/5,108**. Line count equalling row count also proves no row spans a line break — the `\copy` text-format corruption trap ADR A.3 warned about did not occur |
| Owner column | every row ∈ the 13 approved ids. **Zero protected rows captured** — which independently confirms none was in the delete set |
| Primary keys | present, non-null, unique within every table (incl. the composite PKs `JobSourceStatus(userId,source)`, `AgentProvider(userId,provider)`) |
| **Column fidelity** | the JSON key set is **exactly** the live table's column set for all 16 tables — no missing column that would silently restore as `NULL`, no extra key that `json_populate_record` would discard. This is the check that separates a real backup from a plausible-looking one |
| NULLs | preserved as JSON `null` (e.g. 50,012 in `Job`), not dropped |

**Restore-transform proof — complete coverage**

I re-ran the ADR §5.2 identity against the *actual backup files*, as a pure `SELECT`:

```sql
to_jsonb(json_populate_record(null::aether."<T>", <captured line>::json)) = <captured line>::jsonb
```

| Scope | Tested | Byte-identical | Mismatches |
|---|---|---|---|
| All 15 non-`Job` tables — **every row** | 97 | 97 | **0** |
| `Job` — **every row**, 26 batches of 200 | 5,011 | 5,011 | **0** |
| **Total** | **5,108** | **5,108** | **0** |

Every single deleted row reconstructs byte-identically. The ADR validated this on 3 rows; it now holds on all
of them.

**Would a reverse-order re-insert actually work?**

- **Referential closure.** All 15 hard-FK edges and 4 soft edges among the backed-up rows resolve **inside the
  backup**. Not one backed-up row depends on a row that no longer exists. A restore needs nothing but these
  files.
- **Reverse `deletion_order` is FK-sound.** Checked against all 16 live FK constraints: every parent precedes
  its child under reversal — `User` → … → `Job`(16th) → `Resume`(17th) → `Contact`(18th) →
  `Application`(19th) → … → `EmailThread`(24th) → `ApprovalRequest`(25th). The `RESTRICT` edge
  `Application.resumeId → Resume` is satisfied because `Resume` re-inserts first.
- **The self-referential edge is safe.** `Resume.parentId → Resume` (`SET NULL`, non-deferrable): all 4 rows
  re-insert in one statement, and PostgreSQL fires non-deferred RI triggers at end of statement, so
  intra-statement ordering is irrelevant. The one non-null `parentId` (`c98808f2…` → `c08f74b0…`) resolves
  within the file.
- **No unique-key collision.** 13 distinct `@mailinator.com` emails, none of which exists in `User` today;
  5,011 distinct `(userId, sourceUrl)` pairs for the `Job_userId_sourceUrl_key` index; and all 5,108 PKs are
  confirmed absent from production. Nothing blocks the insert.

**Durability — three copies, all independently verified by me**

| Copy | Result |
|---|---|
| In-tree `uat/reports/…/backup-20260805T072800Z/` (gitignored) | `sha256sum -c` **23/23 OK** |
| `/home/ubuntu/aether-purge-backup-20260805T072800Z/` | `sha256sum -c` **20/20 OK** |
| `s3://abacusai-apps-…-us-west-2/49362/gm2-cleanup-backup-20260805T072800Z/` | downloaded fresh, `sha256sum -c` **20/20 OK**, and all 16 `.jsonl` **byte-identical** to in-tree (`cmp`) |

C1 and C11 are discharged on evidence, not on assertion. `pg_dump` appears nowhere.

**Honest limits of this finding.** I proved the data is complete and the transform lossless; I did not execute
an `INSERT`, because that is a production write and outside my authority — the final millimetre is untested by
design. And a restore returns rows, not external derived state (Stripe-side objects, caches), exactly as ADR
§5.4 states.

**Conclusion: the backup is a real rollback, not a ceremonial one.** Had this purge been wrong, it could have
been undone.

---

## 8. Ruling on the manifest defect — **REAL, non-invalidating; the substitution was CORRECT, not merely acceptable**

The executor's report is accurate. Confirmed directly from the manifest:

| Table | `rows_by_table` | `backup_spec.expected_line_counts` |
|---|---|---|
| ApprovalRequest | 2 | **1** |
| StoryEntry | 4 | **3** |
| BackgroundJob | 2 | **1** |
| AgentRun | 10 | **8** |
| EmailThread | 1 | **absent** |
| Application | 1 | **absent** |

And it is worse than reported — there are **three** mutually inconsistent number sets in the approval package:

```
manifest rows_by_table total ............... 5087
manifest expected_line_counts total ........ 5080   (14 tables, 2 missing)
ADR §5.3 G1 prose total .................... 5079   ("AgentRun=7, StoryEntry=3")
actually deleted and backed up ............. 5108
```

**Ruling: the approval stands.**

1. **The defective field was never the binding gate.** The operative condition is C1 + gate G1, and G1's own
   text keys off **`rows_by_table`**, not `expected_line_counts`. The latter is a redundant restatement that
   drifted — residue of the A.4 concurrent-authorship collision the ADR itself flagged as a governance hazard.
2. **The ADR makes the live re-census authoritative over every static field**: *"the manifest is a census, not a
   contract"*; *"treat any exact total … as 'as-of', never as an assertion about execution time."* By the
   approval's own terms, no number typed into the file could have governed.
3. **What the executor substituted is strictly stronger than any of the three.** The invariant that actually
   protects recoverability is *"the backup covers 100% of what this transaction deletes."* The executed SQL
   enforces exactly that with **25 in-transaction C5 assertions** (lines 23–72), each aborting if the live count
   differs from the backed-up count by even one row. That is a machine-enforced runtime invariant, not a
   documented intention. It is the right check.

**But the defect is filed as a mandatory correction, because it is a live trap.** Had the janitor verified
against `expected_line_counts` it would have "passed" a backup **missing `EmailThread` and `Application`
entirely** — two rows, including the very `Application` whose `RESTRICT` edge the whole deletion order was
designed around, permanently unrecoverable. A verification field weaker than the thing it verifies is worse
than no field, because it converts a blocking gate into a rubber stamp. **Required of future manifests:**
derive expected backup counts mechanically from `rows_by_table`, or omit the field. Never hand-maintain a
second copy of a number that a gate depends on.

The executor gets explicit credit here: it declined the field that would have let it through.

---

## 9. Ruling on the +21-row drift — **RATIFIED retrospectively; EXCEPTION recorded**

Drift: `Resume` 3→4, `UsageQuota` 3→13, `Subscription` 3→13 (5,087 → 5,108).

**I verified the class-check myself, from the backup rather than from the executor's report.**

- All **13** `Subscription` rows: `planId=free`, `status=active`, `stripeSubscriptionId = NULL`. No money moved
  against any of them. This is precisely the class ADR §4.1 approved.
- All **13** `UsageQuota` rows likewise, free-tier placeholders.
- The **+20 billing rows carry an identical `createdAt` of `2026-08-04T03:07:41.376686+00:00`** — to the
  microsecond, across 10 users, in both tables. That is a single backfill batch, exactly as the executor
  reported. Not organic user activity.
- The **+1 `Resume`** is `c1653ff67050f4c81a0691621` (user `cb2aba1a…`, `2026-08-04T11:10:30.151`,
  `parentId` NULL, `sourceJobId` NULL) — the production-verification row, as reported.
- Both scope tripwires negative, re-verified by me: no 14th identity (the email-pattern set and the 13
  enumerated ids agree exactly), and no table outside the 25 user-scoped tables that exist in the schema.
- Quiescence, independently derived from the backup's own timestamps: the latest content write across all
  5,108 purged rows is **2026-08-04T11:10:30Z**, ~20 h before execution. (The only later stamp anywhere is a
  `User.lastLoginAt` of 2026-08-04T12:46:28Z — a session event, still ~19 h clear of the ≥30-minute
  requirement.) **C5-A(1) satisfied with a wide margin.**

**Substantively, this was inside the approval.** Same 13 identities, same tables, same row class, same
free-tier billing ruling. Nothing new in kind was destroyed. Asked at 07:29Z, I would have approved all 21
rows on this evidence without hesitation, and I ratify them now.

**Procedurally, it was outside the letter of C5-A(3)**, which says: *"any row in the live scope but absent from
the manifest must be listed and re-approved by a risk officer. Never widen the scope silently."* The 21 rows
were absent from the manifest's enumerated `rows.*`. The executor listed them and documented them — nothing was
silent — but it made the in-class determination itself. That determination is the one C5-A reserved to a risk
officer, and it is being supplied now, after the fact.

**I do not lay this primarily at the executor's door, because the approval contradicts itself.** ADR Addendum
A.2 states the enumerated list is *"a review artifact and integrity baseline"* and that *"the identity predicate
plus the C5-A re-validation is what actually bounds the deletion."* Read that way the executor was correct.
Read C5-A(3) literally, it was not. The ADR also predicted that a literal reading does not terminate on a live
system: *"an executor re-validates, sees drift, aborts — and can loop indefinitely."* Faced with two readings,
the executor chose the one that preserved the invariant that matters and reported the deviation in full.

**Required correction to the ADR (binding on the next purge):** reconcile C5-A(3) with A.2. State explicitly
that drift confined to *(approved identities × approved tables × approved row class)* is executor-dispositionable
with recorded evidence, and that a **new identity**, a **new table**, or a **row failing the class test** halts
for a fresh risk-officer signature. As written, the condition is unsatisfiable on a live database, and an
unsatisfiable condition trains executors to route around conditions.

---

## 10. EXCEPTIONS

### EX-1 — C13 was discharged out of order (unfixable)

C13 requires the risk-officer diff **before** the SQL runs. It ran first. I can attest that the SQL matched the
manifest; I cannot attest that C13 was satisfied as written, and no counter-signature can retro-fit "before."
The purge proceeded for ~9 minutes with one of thirteen binding conditions undischarged. The executor was right
to refuse to self-grant it. Recorded as a **timing breach of C13**, severity low given the clean result, but it
is the difference between a control and a formality: a pre-execution review can stop a purge, a post-execution
one cannot.

### EX-2 — C5-A(3) scope re-approval was not obtained before execution

See §9. **Retrospectively ratified**, no harm, root cause is an internal contradiction in the ADR. Fix is on the
ADR, not the executor.

### EX-3 — **A third live-mode Stripe customer exists and is recorded nowhere** *(open, actionable)*

**This is a new finding. It is not in the executor's report, the orchestrator's verification, the ADR, or the
manifest.**

I scanned all 5,108 backed-up rows for Stripe object identifiers (`cus_`/`sub_`/`pi_`/`ch_`/`in_`/`evt_`).
There are exactly **three**, all `cus_`, all in `Subscription`:

| Stripe customer | User | Email | Recorded in ADR §9 / OD-1 / execution records? |
|---|---|---|---|
| `cus_V0KsL1wgumpXag` | `ca70e965df3e3e7cf22f0c080` | aether.audit.qa.1785756940@mailinator.com | yes |
| `cus_V0L97Kz0LbPZ3M` | `c39d2dfe1afa1cdc7ee76c489` | aether-paytest-1785758152@mailinator.com | yes |
| **`cus_V0YuIMVS4i2vyA`** | **`cb2aba1a9ec4787b28d460d22`** | **aether-uat-1785805899201@mailinator.com** | **NO — absent from every artifact** |

ADR §9 and manifest `operator_deferred.OD-1` both say *"**2** in-scope `Subscription` rows carry a non-null
`stripeCustomerId`."* There were three. `PURGE-EXECUTION-RECORD.md` (lines 97–98, 162–163) and
`PURGE-EXECUTION-2026-08-05.md` (lines 323–324) repeat the pair.

**Cause — a race, honestly explicable.** That `Subscription` row was created `2026-08-04T01:11:50.258796Z` and
`updatedAt` `2026-08-04T02:08:56.614724Z` — **34 seconds before the manifest was authored** at
`02:09:30.375620Z`. The `stripeCustomerId` was written into the row inside that window, after the ADR's §9
census had been taken. The manifest *did* enumerate the row (`rows.Subscription` includes PK
`798142bd-fa2b-4860-8210-a318629e8234`); only the operator-facing summary of Stripe ids missed it.

**Why it matters.** C10 is the item that **blocks G-K closure** and is human-only. The operator has been handed
2 of 3. ADR §9 warned exactly this: *"the local `Subscription` rows are the only pointer to these customer ids.
Once deleted, the link is recoverable only from the backup or this ADR."* Those rows are now deleted, and until
this document the third id existed **only** in a gitignored JSONL file.

**Disposition.** Not a purge defect — the row was in scope, correctly class-checked, correctly deleted, and
correctly backed up. It is a defect in the **operator handoff**, and recording it here in tracked
`docs/delivery/` remediates the provenance half. The operator action stands amended:

> **C10 / OD-1 (amended):** three live-mode Stripe customer objects require human disposition —
> `cus_V0KsL1wgumpXag`, `cus_V0L97Kz0LbPZ3M`, **`cus_V0YuIMVS4i2vyA`**. All three have
> `stripeSubscriptionId = NULL`: customer objects only, no subscription, no charge, no financial exposure.

I verified exhaustively that there is no fourth.

### EX-4 — C12's guard set is count-based and therefore blind to `SET NULL` collateral *(advisory)*

The in-transaction post-flight guards assert **counts**: protected ids present, non-test `User` count unchanged,
mailinator = 0, owner `Job` not shrunk, four DO-NOT-TOUCH tables equal. Four live FK edges are
`ON DELETE SET NULL` — `EmailThread.applicationId`, `EmailThread.contactId`, `Resume.sourceJobId`,
`Resume.parentId`. If a protected row had referenced a test row across any of them, deleting the test row would
have **silently mutated a column in a protected row**, and **no count-based guard would have moved**.

It did not happen here — the ADR's X3–X6 cross-user checks were 0 at authoring and the executor re-ran all 13
fresh before execution. But that is *pre-image* evidence: after the fact, the change is undetectable, because
no pre-image of those columns was captured for protected rows. For the record, current protected-side state:
owner `EmailThread` 336 rows with `applicationId` and `contactId` **all NULL** (nil exposure on that edge);
owner `Resume` 276 rows, 271 with non-null `sourceJobId`, 5 null.

**Required of future purges:** either capture a pre-image (or hash) of every `SET NULL` edge column on
protected rows, or add a guard asserting `count(*) FILTER (WHERE <col> IS NULL)` is unchanged. The protection
here was structural, not enforced.

---

## 11. Conditions — final status

| | Condition | Status |
|---|---|---|
| C1 | Verified backup before delete | **DISCHARGED** — 5,108/5,108 rows verified restorable by me |
| C2 | Identity predicate only | **DISCHARGED** — and proven post-hoc: 3,074/3,074 pre-purge owner `Job` rows survive |
| C3 | Explicit per-table deletes in order | **DISCHARGED** — 25/25, no reliance on cascade |
| C4 | Single transaction | **DISCHARGED** — proven by the `_base` temp-table read after the deletes |
| C5 / C5-A | Re-census + quiescence | **DISCHARGED with EX-2** — quiescence ~20 h; +21 drift ratified retrospectively |
| C6 | `AdminAuditLog`/`StripeEvent` do-not-touch | **DISCHARGED** — read-only references only; counts byte-stable |
| C7 | Row-scoped rollback only | **DISCHARGED** — no full/PITR restore performed or planned; rollback path proven viable |
| C8 | Janitor executes, not the author | **DISCHARGED** |
| C9 | File the transcript | **DISCHARGED** |
| C10 | Stripe not covered | **OPEN — AMENDED by EX-3: three customers, not two** |
| C11 | Off-VM copy blocking | **DISCHARGED** — three copies, S3 round-trip verified byte-identical by me |
| C12 | Pre/post-flight guards as deltas | **DISCHARGED with EX-4 advisory** — deltas confirmed, no literals |
| C13 | Risk-officer SQL diff | **DISCHARGED LATE — see EX-1.** Substance: clean. Timing: breached |

---

## 12. Verdict

**COUNTERSIGNED-WITH-EXCEPTIONS.**

The SQL that ran is the SQL that was approved — statement for statement, id for id, in the approved order, in
one atomic transaction, against nothing outside the approved set. The outcome verifies clean against production
on my own queries: 2 genuine users intact, 0 residue, 0 orphans, 0 dangling references, audit and billing
tables byte-stable, and **zero protected rows lost in any table**. The backup is a genuine rollback: all 5,108
deleted rows reconstruct byte-identically, the FK closure is complete, the reverse-order re-insert is sound,
and three checksum-verified copies exist including one off-VM.

The exceptions are governance, not damage. **EX-1** and **EX-2** are process breaches with clean outcomes whose
root cause is contradictory text in the approval itself, and the ADR must be corrected before the next purge.
**EX-4** is a latent guard-coverage gap that this schema's zero cross-user graph happened to render moot.
**EX-3 is live and requires action**: a third live-mode Stripe customer, `cus_V0YuIMVS4i2vyA`, was handed to no
one, and C10 cannot be closed against a list of two.

I do not countersign C13 as *satisfied*, because it required a pre-execution review that did not happen. I
countersign that the executed SQL **matched the approval**, that the purge **destroyed nothing it was not
approved to destroy**, and that it was — and while these files survive, remains — **reversible**.

---

**Counter-signing risk officer:** risk-officer (third instance), GOLD-MASTER-V2 · G-K · C13
**Authored the manifest:** no. **Executed the purge:** no. **Wrote to production:** no — `SELECT` only.
**Approves own work:** no — this document reviews another agent's execution of a third agent's manifest.
**Evidence:** `uat/reports/evidence/gold-master-v2/cleanup/backup-20260805T072800Z/` ·
`uat/reports/evidence/launch-ready/governance/C13-COUNTERSIGNATURE-PROD-TESTDATA-PURGE.json`
