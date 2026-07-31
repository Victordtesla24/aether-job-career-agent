# BLOCKER VERIFICATION — `admin`/`admin123` over-permission on PRODUCTION

- Verifier: independent qa-adversary (did NOT author the claim, the fix, or the original test)
- Production target: https://5cb5f0620.abacusai.cloud
- Run window (UTC): 2026-07-30T23:27:44Z → 2026-07-30T23:35:10Z (COMPLETE — all 7 task sections probed)
- Repo HEAD at verification: `297946d`
- Mode: VERIFICATION AND ROOT-CAUSE ONLY. No source, `.env`, config, or DB row was modified. All SQL was `SELECT` only.

## Claim under test

> "The seeded test credential `admin` / `admin123` currently authenticates as the REAL admin account (the same
> userId as the operator/owner account) and returns `isAdmin: true`, granting access to admin-only endpoints on
> PRODUCTION. Stated root cause: the real admin account independently has `username='admin'` set, so the
> demotion-then-regrant logic nets out to isAdmin=true."

## VERDICT: **CONFIRMED** — with a material correction to the stated root cause

The security outcome is real, reproduced live on production, and worse than "theoretical": five admin-only
endpoints returned HTTP 200 with real production data including **other users' email addresses**.

The stated *mechanism* is only **half right**. The `username='admin'` demotion/regrant race does explain
`isAdmin=true`. It does **not** explain why the *password* `admin123` works. The real reason the password works
is that **`AETHER_ADMIN_PASSWORD_HASH` in the production `.env` is itself a bcrypt hash of the string
`admin123`** — i.e. the operator/owner's own configured admin password *is* `admin123`. This matters because it
**invalidates the obvious fix**: repairing the demotion logic or deleting the seed account would NOT close this
hole.

---

## §1 — Production login probe

`[VERIFIED]` 2026-07-30T23:28:13Z

```
POST https://5cb5f0620.abacusai.cloud/api/auth/login
Content-Type: application/json
{"email":"admin","password":"admin123"}

HTTP 200
{
  "access_token": "<REDACTED — JWT, 268 chars, prefix eyJhbGci>",
  "token_type": "bearer",
  "userId": "c6c8d0163d973a8048e7e33b8",
  "email": "sar***@gmail.com"
}
```

### Decoded JWT (signature redacted)

```
header:  {"alg":"HS256","typ":"JWT"}
payload: {
  "sub":    "c6c8d0163d973a8048e7e33b8",
  "userId": "c6c8d0163d973a8048e7e33b8",
  "email":  "sar***@gmail.com",
  "iat":    1785454093,
  "exp":    1785540493
}
signature: <REDACTED, 43 chars>
```

`[VERIFIED]` Token TTL = `exp - iat` = **86400 s = 24 hours** (`apps/api/app/security.py:12` `TOKEN_TTL = timedelta(hours=24)`).

`[VERIFIED]` **The JWT carries NO `isAdmin` claim and no scope claim.** Privilege is resolved *live from the
database row* on every request (`apps/api/app/middleware/auth.py:48-55`). This is an aggravating factor, not a
mitigating one: the token is a plain 24-hour bearer for the full owner identity, and it inherits whatever
privileges that row holds at request time.

`[VERIFIED]` 2026-07-30T23:28:21Z — `GET /api/auth/me` with that bearer:

```
HTTP 200
{"id":"c6c8d0163d973a8048e7e33b8","email":"sar***@gmail.com",
 "name":"GAP-P7-DEF-B Probe 1785452243543",
 "targetRole":"Business Analyst/Project Manager/Scrum Master",
 "location":"Melbourne","isAdmin":true}
```

**`isAdmin: true` — CONFIRMED on production.**

---

## §2 — Escalation test: admin-only endpoints

`[VERIFIED]` 2026-07-30T23:28:35Z — all five calls carried only the `admin`/`admin123` bearer.

| Endpoint | HTTP | Evidence of real data returned |
|---|---|---|
| `GET /api/admin/health` | **200** | `{"agents":{"totalRuns":3524,"succeeded":3363,"failed":160,...,"successRate":0.9546},"cron":{...,"lastRunAt":"2026-07-30T23:00:34.855000+00:00"},"providers":{"configuredTiers":["REASONING","STRUCTURED","FAST"...` |
| `GET /api/admin/users` | **200** | Full user list **with other users' email addresses**, plan, subStatus, signup/last-login timestamps, spend. First rows: `gm2-phase0-probe-1785453738@example.com`, `qa-deepsweep-20260729@example.com` |
| `GET /api/admin/audit-log` | **200** | Immutable audit entries: `{"actorUserId":"c6c8d0163d973a8048e7e33b8","action":"application.stage_move","targetType":"application",...}` |
| `GET /api/admin/spend` | **200** | `{"totalUsd":0.5368,"perUser":[{"userId":"c6c8d0163d973a8048e7e33b8","email":"sar***@gmail.com",...,"spendUsd":0.5368,"runCount":3524}]}` |
| `GET /api/admin/settings` | **200** | `{"signupEnabled":true,"emailVerificationEnabled":false}` |

**Over-permission is CONFIRMED and REAL, not theoretical.** 5/5 admin endpoints returned 200.

### Are the admin endpoints "harmless read-only"? — NO

`[VERIFIED]` `apps/api/app/routers/admin.py` route inventory (grep of `@router.<verb>`):

```
:40  @router.get("/health")
:51  @router.get("/users")
:66  @router.get("/users/{user_id}")
:104 @router.post("/users/{user_id}/spend-cap")     <-- MUTATING
:124 @router.post("/users/{user_id}/suspend")       <-- MUTATING
:141 @router.post("/users/{user_id}/unsuspend")     <-- MUTATING
:165 @router.get("/spend")
:204 @router.get("/settings")
:209 @router.post("/settings")                      <-- MUTATING
:239 @router.get("/audit-log")
```

Four state-changing POST routes exist behind the **same** `AdminUser` dependency
(`apps/api/app/routers/admin.py:21` `from app.middleware.auth import AdminUser`; module docstring line 5:
*"EVERY route depends on `AdminUser`"*). The GETs returning 200 prove the `AdminUser` gate passes for this
token, therefore the POSTs are equally reachable. `POST /admin/settings` can disable signup platform-wide;
`POST /users/{id}/suspend` can lock any user out of every authenticated route
(`apps/api/app/middleware/auth.py:52-53` raises 403 on every route for a suspended user).

> Per this task's no-mutation rule, the four POST routes were **NOT** executed. Their reachability is
> `[INFERRED]` from the identical `AdminUser` dependency plus the verified 200s on the GETs sharing it — a
> single-gate design with no second factor anywhere in the module.

---

## §3 — Identity comparison (read-only SQL against the production DB)

`[VERIFIED]` 2026-07-30T23:30:34Z. Only `SELECT` statements plus `SET search_path` were issued. DSN never printed.

Env facts read from the production repo-root `.env` (values never printed):

```
AETHER_ADMIN_EMAIL             = sar***@gmail.com        (the operator/owner address)
AETHER_ADMIN_PASSWORD_HASH set = True   scheme=$2b$  len=60
ADMIN_PASSWORD set             = False  (so the seed default literal "admin123" applies)
OPERATOR-HASH verifies "admin123"  ==>  True     <<<<<< KEY FINDING
```

Query: `SELECT id, email, username, "isAdmin", suspended, "passwordHash", "createdAt" FROM "User"
WHERE lower(username)='admin' OR email='admin@aether.local' OR email=<AETHER_ADMIN_EMAIL>`

```
--- rows matching username=admin OR email=admin@aether.local OR email=AETHER_ADMIN_EMAIL ---
  id=c6c8d0163d973a8048e7e33b8  email=sar***@gmail.com  username='admin'  isAdmin=True
  suspended=False  createdAt=2026-07-20 01:05:41.071000
      passwordHash_scheme=$2b$  sha256_prefix=40ffd677
      == AETHER_ADMIN_PASSWORD_HASH? True      verifies("admin123")=True

total isAdmin=true rows: 1
   admin row: c6c8d0163d973a8048e7e33b8  sar***@gmail.com  'admin'
total users: 6
```

### Conclusions, definitively

1. `[VERIFIED]` **EXACTLY ONE row matched.** There is **no separate seeded `admin@aether.local` account** on
   production. The seed identity and the operator identity are the **same database row**.
2. `[VERIFIED]` **`same_user_as_operator = TRUE`.** The `admin`/`admin123` login `userId`
   (`c6c8d0163d973a8048e7e33b8`, §1) is byte-identical to the id of the row whose `email` equals
   `AETHER_ADMIN_EMAIL`. Logging in as `admin` **is** logging in as the owner.
3. `[VERIFIED]` That row carries `username='admin'` and `isAdmin=true`.
4. `[VERIFIED]` The row's stored `passwordHash` is **byte-identical to `AETHER_ADMIN_PASSWORD_HASH`**, and that
   hash **verifies the plaintext `admin123`**. This is the decisive fact for root cause (see §4).
5. `[VERIFIED]` There is exactly **one** `isAdmin=true` row in the entire production `User` table (6 users
   total) — so this single credential is the whole admin surface.

---

## §4 — Root cause in source

### 4.1 Where the identifier resolves to a user

`apps/api/app/routers/auth.py:53-57` — `LoginRequest.email` is deliberately a plain `str`, not `EmailStr`,
*"so a bare username like \"admin\" validates"*.

`apps/api/app/routers/auth.py:114` — `user = UserRepository().get_by_username_or_email(body.email)`

`apps/api/app/repositories/user.py:114-134` — the lookup:

```sql
SELECT ... FROM "User"
 WHERE "email" = %s OR lower("username") = lower(%s)
 ORDER BY ("email" = %s) DESC LIMIT 1
```

`[VERIFIED]` Because the operator row has `username='admin'` (§3), the bare identifier `admin` resolves to the
**owner** row. There is no separate account to land on.

### 4.2 Where `isAdmin` is decided at request time

- `apps/api/app/middleware/auth.py:48-55` — `get_current_user` loads the row via
  `UserRepository().get_auth_context(user_id)` and sets `user["isAdmin"] = bool(user.get("isAdmin"))`. **The
  flag comes from the DB row, not from the token.**
- `apps/api/app/middleware/auth.py:60-67` — `get_admin_user` raises 403 only `if not current_user.get("isAdmin")`.
- `apps/api/app/middleware/auth.py:70` — `AdminUser = Annotated[dict, Depends(get_admin_user)]`, the sole gate
  on every `/admin/*` route.
- `apps/api/app/routers/auth.py:165` — `/auth/me` surfaces `"isAdmin": bool(current_user.get("isAdmin"))`.

### 4.3 Where the seed account is created

`apps/api/scripts/seed_demo.py:56-108` — `seed_admin_user()`:

- `:57-58` `ADMIN_USERNAME = "admin"`, `ADMIN_EMAIL = "admin@aether.local"`
- `:62-69` `_admin_password()` returns `os.environ.get("ADMIN_PASSWORD") or "admin123"` — with the comment
  *"The owner's explicit product decision is a default of `admin123`"*. `ADMIN_PASSWORD` is **not set** in the
  production `.env` (§3), so the literal default applies.
- `:82-87` the idempotency guard: `SELECT "id" FROM "User" WHERE lower("username") = 'admin' OR "email" =
  'admin@aether.local'` → **returns early if any row already has `username='admin'`**.

`[INFERRED]` Because the operator row already holds `username='admin'`, the seeder's guard short-circuits and
never creates `admin@aether.local` — which is exactly the DB state observed in §3 (one row, no
`admin@aether.local`). The seed script is a *bystander* here, not the live cause.

### 4.4 The demotion / regrant logic — the stated mechanism

`apps/api/app/main.py:157-174` — `_lifespan` calls `apply_admin_rotation()` on every app boot; failures are
swallowed with a warning (`:170-174`).

`apps/api/app/repositories/admin.py:569-613` — `apply_admin_rotation()`:

```
:43   _SEED_ADMIN_USERNAME = "admin"
:44   _SEED_ADMIN_EMAIL    = "admin@aether.local"

:588-592   STEP 1 — DEMOTE
           UPDATE "User" SET "isAdmin"=false,"updatedAt"=now()
            WHERE lower("username")=%s OR "email"=%s     -- ('admin', 'admin@aether.local')

:601-608   STEP 2 — REGRANT (only if AETHER_ADMIN_EMAIL + AETHER_ADMIN_PASSWORD_HASH are both set)
           INSERT INTO "User" (...,"isAdmin",...) VALUES (...,true,...)
           ON CONFLICT ("email") DO UPDATE SET
             "passwordHash"=EXCLUDED."passwordHash","isAdmin"=true,
             "suspended"=false,"updatedAt"=now()
```

The docstring at `:580-582` states the design intent explicitly: *"The env admin is applied AFTER the demotion
so an operator who deliberately points `AETHER_ADMIN_EMAIL` at the seed address still gets an admin (their
explicit choice)"*.

### 4.5 Is the stated mechanism CORRECT? — **PARTIALLY. It is right about `isAdmin`, wrong about the password.**

**`stated_mechanism_correct = false` (incomplete/misleading).**

- `[VERIFIED]` **The `isAdmin=true` half is correct.** Step 1 matches the operator row on
  `lower("username")='admin'` and sets `isAdmin=false`; Step 2 matches the *same* row on
  `"email" = AETHER_ADMIN_EMAIL` and sets `isAdmin=true`. Net effect: `isAdmin=true`. The demotion is
  self-cancelling for this row. Observed DB state (`username='admin'` AND `isAdmin=true` on one row, §3) is
  exactly what this predicts.

- `[VERIFIED]` **The password half of the story is WRONG.** The claim implies a stale seeded `admin123`
  credential survived. It did not — and could not. `apps/api/app/repositories/admin.py:605` **overwrites**
  `"passwordHash"=EXCLUDED."passwordHash"` on *every single app boot*. The row's hash is therefore, by
  construction, `AETHER_ADMIN_PASSWORD_HASH` — and §3 proves byte-equality. The reason `admin123` authenticates
  is that **`AETHER_ADMIN_PASSWORD_HASH` in the production `.env` is a bcrypt hash of `admin123`**
  (`verifies("admin123") = True`, §3). The operator's *deliberately configured* admin password **is** `admin123`.

- **Consequence for remediation (this is why the correction matters):** fixing `apply_admin_rotation`, deleting
  the seed account, or removing `seed_demo.py`'s `admin123` default would **NOT** close this hole. Even with a
  perfect demotion, `POST /auth/login {"email":"admin","password":"admin123"}` would still authenticate as the
  owner (via `username='admin'`) — only `isAdmin` would flip to false. And even if `username='admin'` were
  removed, the owner's real email + `admin123` would still be a valid **admin** login. **Two independent
  defects** must both be fixed.

**Two distinct defects, therefore:**

| # | Defect | Evidence | Effect |
|---|---|---|---|
| **D1** | The production operator admin password is literally `admin123` (`AETHER_ADMIN_PASSWORD_HASH` = bcrypt(`admin123`)) | §3 `verifies("admin123")=True` | Owner account guessable by anyone who reads the repo |
| **D2** | The operator row carries `username='admin'`, so the seed identifier resolves to the owner AND self-cancels the §14.7 demotion | §3 `username='admin'`; `admin.py:588-592` vs `:601-608` | GATE-31's demotion is inert; `admin` is an alias for the owner |

---

## §5 — Blast radius and severity

### Reachable unauthenticated from the public internet?

`[VERIFIED]` **YES.** Every probe in §1 and §2 was an unauthenticated `curl` from this VM to the public
production hostname `https://5cb5f0620.abacusai.cloud` over the internet — no VPN, no local port, no privileged
network position, no prior session. Knowledge of the string `admin`/`admin123` is the *entire* attack
prerequisite. The data returned (3524 agent runs, live cron `lastRunAt` 2026-07-30T23:00:34Z, real user rows)
confirms this is the **production** deployment, not a local instance.

### Is the credential publicly documented in the repo?

`[VERIFIED]` 2026-07-30T23:35Z — **YES, extensively.** `git grep -l "admin123" | wc -l` → **57 tracked files**,
including top-level and delivery documentation (`README.md:59` and `docs/delivery/PROGRESS.md:53`, one hit each):

```
README.md
docs/delivery/PROGRESS.md
docs/delivery/TRACEABILITY-MATRIX.md
docs/delivery/LAUNCH-READY-STATE.json
docs/delivery/MODELS-LIVE-GAPS.json
docs/delivery/MODELS-LIVE-FINAL-REPORT.md
docs/delivery/GOLD-MASTER-V2-BLOCKED-ON-HUMAN.md
docs/delivery/LAUNCH-READY-FINAL-REPORT.md
docs/delivery/LAUNCH-READY-GOVERNANCE-AUDIT.md
docs/delivery/EXTERNAL-CLIENT-ACCESS-FIX-2026-07-29.md
docs/delivery/OPEN-ITEMS-RECONCILIATION-2026-07-29.md
docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md
docs/subscription/admin-guide.md
docs/subscription/billing-architecture.md
apps/api/scripts/seed_demo.py          (source default)
apps/api/app/main.py, apps/api/app/repositories/admin.py   (docstrings)
... plus tests and e2e specs
```

`README.md` — the first file any reader opens — contains it. `[INFERRED]` If this repository is or ever becomes
public (or is shared with a contractor, reviewer, or CI provider), the production owner credential is disclosed
by reading the README.

### Rate limiting

`[VERIFIED]` Login *is* rate-limited: `apps/api/app/routers/auth.py:108-113` calls `guard_login_attempt(request,
body.email)` keyed on the **normalized identifier** (per the comment, *"never client IP"*), with
`record_login_failure` / `reset_login_failures` around the password check, and the limiter built at
`apps/api/app/main.py` (`app.state.login_rate_limiter = build_login_rate_limiter()`).

`[VERIFIED]` **This provides ZERO mitigation here.** The limiter only throttles *failed* attempts; a correct
password is never throttled, and `apps/api/app/routers/auth.py:~129` explicitly *"clears the counter"* on
success. An attacker who knows the credential authenticates on the first try. Rate limiting defends against
guessing, and nothing here needs to be guessed.

### Other mitigations checked (all fail to mitigate)

| Candidate innocent explanation | Result |
|---|---|
| "`/api/admin/*` is gated by something else too" | `[VERIFIED] REFUTED` — `apps/api/app/routers/admin.py:5` module docstring and every route signature use exactly one dependency, `AdminUser`. No IP allowlist, no second factor, no separate admin session. 5/5 GETs returned 200. |
| "The token is short-lived or scoped" | `[VERIFIED] REFUTED` — 24 h TTL (`security.py:12`), no scope/audience claim, no `isAdmin` claim; privilege is re-read live from the DB each request (`middleware/auth.py:48-55`). Full owner identity. |
| "The admin endpoints are harmless read-only" | `[VERIFIED] REFUTED` — 4 mutating POSTs behind the same gate (§2); the read endpoints alone already leak other users' emails and the full audit log. |
| "This is only a local instance, not production" | `[VERIFIED] REFUTED` — public hostname, live cron timestamp 28 min old, 3524 real agent runs, 6 real users. |
| "Not the same user as the owner — it's a separate seeded account" | `[VERIFIED] REFUTED` — one matching row; login `userId` == the `AETHER_ADMIN_EMAIL` row's id (§3). |
| "`admin@aether.local` seed row is the one at fault" | `[VERIFIED] REFUTED` — that row **does not exist** on production. |

### Severity

**CRITICAL.** Unauthenticated internet-reachable full-owner + platform-admin takeover via a credential printed
in the repository README. Confidentiality (all users' PII and the audit log), integrity (suspend any user,
alter spend caps, disable signup), and non-repudiation (the audit log records the owner's `actorUserId`, so an
attacker's actions are indistinguishable from the owner's) are all compromised. It is also the **only**
`isAdmin=true` account on the platform, so it is the complete administrative surface.

---

## §5b — Safe escalation proof on a MUTATING route + negative controls

`[VERIFIED]` 2026-07-30T23:33:50Z. `admin_suspend_user` (`apps/api/app/routers/admin.py:124-138`) resolves the
`AdminUser` dependency **first**, then calls `admin_repo.user_exists(user_id)` and 404s **before** any write and
**before** any audit row. A POST against a nonexistent id is therefore a zero-side-effect probe that
distinguishes "admin gate passed" (404) from "admin gate blocked" (403).

```
POST /api/admin/users/ZZZ-nonexistent-qa-adversary/suspend   Authorization: Bearer <admin/admin123 token>
  HTTP 404   {"detail":"User not found"}        <-- ADMIN GATE PASSED on a MUTATING route

POST /api/admin/users/ZZZ-nonexistent-qa-adversary/suspend   (no token)
  HTTP 401   {"detail":"Not authenticated"}     <-- negative control: the gate is real
GET  /api/admin/users                                        (no token)
  HTTP 401   {"detail":"Not authenticated"}     <-- negative control: the gate is real
```

**404, not 403** — the mutating suspend route is fully reachable with this credential. A real target id would
have suspended that user. The negative controls prove the guard genuinely exists and that it is *this
credential*, not a missing guard, that defeats it.

`[VERIFIED]` **Zero mutations were made by this verification.** `AdminAuditLog` action counts, re-read at
2026-07-30T23:34:02Z (after the POST probe), are byte-identical to the pre-probe read at 23:33:05Z:
`suspend_user: 4`, `unsuspend_user: 4`, `set_spend_cap: 13`, `update_settings: 8`.

### One genuine mitigating fact (recorded honestly)

`[VERIFIED]` 2026-07-30T23:34:11Z — the production `/login` page HTML does **not** display the credential:
`curl https://5cb5f0620.abacusai.cloud/login | grep -i "admin123|admin / admin|demo credential"` returned
**no matches**. The credential is not advertised in the UI. It is, however, in the README of a public repo (§5).

### Secondary observation (not the blocker, but caused by the same design)

`[INFERRED]` The login limiter is keyed on the submitted **identifier**, not the client IP
(`apps/api/app/routers/auth.py:117,127,131`; defaults `max_calls=5` / `window=900 s` at
`apps/api/app/rate_limit.py:43-44`). Because `admin` and the owner's email both resolve to the **same** row, an
unauthenticated attacker can send 5 deliberately wrong passwords for the identifier `admin` and lock the sole
platform administrator out of their own account for 15 minutes, repeatably. Not exploited here (it would have
locked out the live owner); reported as reasoning from source only.

---

## §6 — The contradicted GATE-31 claim

### 6.1 Verbatim quote — `docs/delivery/PROGRESS.md:52-53`

> `admin/admin123` demoted to `isAdmin=false` unconditionally on every boot
> (GATE-31 verified live). Full GATE-17 closure needs operator-rotated `AETHER_ADMIN_EMAIL`/`AETHER_ADMIN_PASSWORD_HASH`.

### 6.2 The same false claim also lives in the PUBLIC README — `README.md:59`

> 2. **Admin credential** (`AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`) → formally closes the
>    admin gate. The demo `admin/admin123` account already carries **zero** admin privilege in production.

`[VERIFIED]` 2026-07-30T23:32Z — `gh repo view --json visibility,nameWithOwner` →
`{"nameWithOwner":"Victordtesla24/aether-job-career-agent","visibility":"PUBLIC"}`.

**This repository is PUBLIC on GitHub.** The production admin credential is therefore published to the open
internet in `README.md`, next to a sentence falsely asserting it is harmless. `.env` itself is correctly
gitignored (`git check-ignore -v .env` → `.gitignore:2:.env`), so the *hash* is not published — but the
*plaintext* is, and it is the same password. This escalates severity beyond the original claim.

Related stale assertions: `docs/delivery/TRACEABILITY-MATRIX.md:85` marks
`GAP-P6-SEC-001 | admin/admin123 must not hold admin privilege | **VERIFIED-CLOSED**`; and `README.md:39`
describes a production DB holding `admin@aether.local, demoted, isAdmin:false` — a row that **no longer exists**
(§3).

### 6.3 Was it wrong when written, or has it regressed? — **REGRESSED**

`[VERIFIED]` `docs/delivery/archive/PHASE6-RERUN-EXECUTION-SUMMARY.md:73`:

> 3. **GATE-03 `/admin` redirect** — redirects cleanly because **no DB user has `isAdmin=true`** (pre-existing
>    GATE-31 state, left untouched).

and `:61`:

> **Admin credential** (GATE-17): ... formal closure needs operator `AETHER_ADMIN_EMAIL` + bcrypt hash. Demo
> `admin/admin123` has **zero** admin privilege in production (correct).

`[VERIFIED]` So at Phase-6-rerun time the claim was **TRUE**: `AETHER_ADMIN_EMAIL`/`AETHER_ADMIN_PASSWORD_HASH`
were unset, the regrant branch at `apps/api/app/repositories/admin.py:598` was skipped, the demotion at `:588`
stood, and the DB genuinely had zero `isAdmin=true` rows.

`[INFERRED]` **The regression was introduced by configuration, not by a code change.** `git log` on
`apps/api/app/repositories/admin.py` shows the rotation logic has been untouched since `63dfddd`
(`feat(GAP-P6-ADMIN-001,ADMIN-003,SEC-001): Admin Tier 1 + credential rotation`); `git log -S` on the demotion
predicate returns only that same commit. The intervening commits (`4e3ae07`, `f98461e`, `c21507d`) do not touch
the demote/regrant predicates — `4e3ae07` only ensures the `username` **column** exists, never its value. What
changed is the environment: the operator later set `AETHER_ADMIN_EMAIL` (to their own address) and
`AETHER_ADMIN_PASSWORD_HASH` (to bcrypt of `admin123`), turning on the regrant branch — while the owner row
carried `username='admin'`, which turns the demotion into a no-op for that row.

`[VERIFIED]` **The regression was already observable, and observed, by 2026-07-23T15:41:29Z.**
`uat/reports/evidence/launch-ready/canonical-login.md` records `admin`/`admin123` → HTTP 200 →
`"isAdmin":true`, and its own verdict says:

> Note: this account carries `isAdmin: true` on production (the spec §1.1 lead described it as "non-admin user"
> — drift noted for later workstreams; not acted on here).

**A prior run saw this exact defect, wrote it down as "drift", and never filed or fixed it — while
`PROGRESS.md`, the `TRACEABILITY-MATRIX`, and the public `README` continued to assert the opposite for a
further seven days.** That documentation-vs-reality gap is itself a governance finding.

`gate31_wrong_or_regressed = **REGRESSED**` (correct when written at Phase-6 rerun; regressed no later than
2026-07-23T15:41:29Z; still regressed at 2026-07-30T23:28:35Z).

---

## §7 — Proposed remediation (NOT implemented — this is a verification report)

> Reminder: **two independent defects** (D1, D2 in §4.5). Fixing only one leaves a hole. Neither option below is
> sufficient alone.

### 7.1 The two options the task asked me to distinguish

**(a) Make `admin`/`admin123` a genuine non-admin, as §1.1 documents.**
On production today this is *impossible without also changing the operator's password*, because `admin` and the
operator are the **same row**: there is no `admin` identity left to demote. Implementing (a) literally would mean
re-creating a separate `admin@aether.local` non-admin row and clearing `username` from the owner row — i.e.
re-introducing a weak, publicly-documented credential on production purely to satisfy a doc sentence. It also
leaves D1 wide open: the owner's *email* + `admin123` would still be a full admin login.

**(b) Remove the seeded weak credential entirely.**
Closes the aliasing, but on its own does **not** close D1 either — because the weak password is not the seed's,
it is the operator's configured `AETHER_ADMIN_PASSWORD_HASH`.

### 7.2 RECOMMENDATION — **(b), extended to cover D1**

Recommend **(b) plus a credential rotation**, and explicitly *reject* (a). Reasoning: (a) preserves a known-weak
credential on an internet-facing production system to keep a documentation sentence true; that is optimising the
doc, not the security. (b) removes the aliasing entirely, and the credential rotation removes the actual
guessable password. Minimal, genuine, in this order:

1. **Rotate the operator credential (fixes D1 — do this FIRST; it is the only step that closes the live
   exposure).** Operator action: generate a strong random password, set `AETHER_ADMIN_PASSWORD_HASH` to its
   bcrypt hash in the production `.env`, restart `aether-api` per `docs/delivery/DEPLOYMENT-RUNBOOK.md`
   (`apps/api/app/repositories/admin.py:605` re-writes the row's hash on boot, so no manual SQL is needed).
   **Human-gated:** an agent must not choose or store the owner's password.
2. **Clear the alias (fixes D2).** One-row update: `UPDATE "User" SET "username"=NULL WHERE "id"=<owner id>` —
   after which `get_by_username_or_email('admin')` (`apps/api/app/repositories/user.py:114-134`) matches nothing
   and the §14.7 demotion at `admin.py:588-592` stops firing against the owner row.
3. **Remove the weak default from source.** `apps/api/scripts/seed_demo.py:62-69` — make `_admin_password()`
   *require* `ADMIN_PASSWORD` (raise when unset) instead of returning the literal `"admin123"`; or drop
   `seed_admin_user()` altogether, since production has not used it since the 2026-07-18 DB-wipe restoration.
4. **Make the rotation refuse to self-cancel (defence in depth).** In `apply_admin_rotation()`
   (`apps/api/app/repositories/admin.py:569-613`), guard the demote so it never demotes-then-regrants the same
   row silently, and — importantly — **fail loudly** rather than proceed when `AETHER_ADMIN_PASSWORD_HASH`
   verifies a known-weak password, or when `AETHER_ADMIN_EMAIL`'s row also matches the seed predicate. Today
   `apps/api/app/main.py:170-174` swallows every rotation exception into a stderr warning, so a partial rotation
   is invisible.
5. **Purge the credential from public documentation.** `README.md:59` (and `:39`), `docs/delivery/PROGRESS.md:52-53`,
   `docs/delivery/TRACEABILITY-MATRIX.md:85`, `docs/subscription/admin-guide.md`, and the other 30+ hits. The
   PUBLIC-repo exposure means the plaintext should be treated as burned regardless of what else is fixed.
6. **Reopen GATE-31 / GAP-P6-SEC-001** in the ledger; it is currently `VERIFIED-CLOSED` against reality.

### 7.3 What a failing test MUST assert

A test that passes against today's production/DB state is itself a defect. The suite must assert:

1. `POST /auth/login {"email":"admin","password":"admin123"}` returns **401** — not 200. *(Directly fails today.)*
2. **No `User` row exists whose `passwordHash` verifies any weak password** in a small denylist
   (`admin123`, `password`, `admin`, `changeme`). *(Fails today: the owner row's hash verifies `admin123`.)*
   This is the assertion that actually catches D1, and the one an obvious "fix the demotion" patch would sneak past.
3. **No `User` row has `lower(username)='admin'` while `isAdmin=true`** — i.e. the §14.7 demote predicate and
   the regrant predicate must never select the same row. *(Fails today.)*
4. A unit test over `apply_admin_rotation()` with `AETHER_ADMIN_EMAIL` pointed at a row that also has
   `username='admin'`: assert the function **raises or reports the conflict**, rather than silently netting out
   to `isAdmin=true`. *(No such test exists.)*
5. If any `admin`-identifier account is retained at all: assert a token minted from it gets **403** on
   `GET /api/admin/health`, `GET /api/admin/users`, `GET /api/admin/audit-log`, and **403 (not 404)** on
   `POST /api/admin/users/{any}/suspend` — the 403-vs-404 distinction is what proves the gate blocked rather
   than the target merely being absent. *(All five return 200/404 today.)*
6. A repo-hygiene test: `grep -r "admin123"` finds **zero** hits outside a dedicated fixture allowlist — with
   `README.md` explicitly disallowed. *(Fails today: 35+ files, README included.)*

### 7.4 Impact on THIS run's own testing — read before fixing

`[VERIFIED]` `uat/reports/evidence/launch-ready/canonical-login.md` is the canonical login recipe and it uses
`admin`/`admin123`. Every screen tester, QA agent, and evidence probe in this run — and in MODELS-LIVE,
LAUNCH-READY and earlier phases — has been authenticating with this credential, i.e. **as the owner, with
`isAdmin=true`**.

Two consequences the run must absorb:

1. **Applying step 1 or 2 above will break every existing test recipe mid-run.** A replacement canonical login
   must be published *in the same change*, and it should be a **purpose-made non-admin test account** — most
   prior testing was supposed to be exercising ordinary-user behaviour, not owner behaviour.
2. `[INFERRED]` **Any prior finding closed on the basis of "the screen rendered / the endpoint returned 200" may
   be invalid**, because the session used was an admin/owner session. Non-admin authorization behaviour has, in
   effect, not been tested at all: `GATE-03` (`/admin` redirect for non-admins), per-user data scoping, and any
   403-path assertion are all suspect. Recommend the run re-samples authorization-sensitive screens with a
   genuine non-admin account once the replacement credential exists.

---

## Evidence index

| Artifact | Timestamp (UTC) |
|---|---|
| Login probe + JWT decode (§1) | 2026-07-30T23:28:13Z |
| `/api/auth/me` → `isAdmin:true` (§1) | 2026-07-30T23:28:21Z |
| 5× admin endpoint escalation (§2) | 2026-07-30T23:28:35Z |
| Read-only DB identity + hash probe (§3) | 2026-07-30T23:30:34Z |
| DB timestamps + audit baseline (§5b) | 2026-07-30T23:33:05Z |
| Mutating-route gate proof + negative controls (§5b) | 2026-07-30T23:33:50Z |
| Post-probe zero-mutation re-check (§5b) | 2026-07-30T23:34:02Z |
| `/login` page credential-exposure check (§5b) | 2026-07-30T23:34:11Z |
| Public-repo visibility check (§6.2) | 2026-07-30T23:32Z |

**Restoration statement:** no source file, `.env`, config, systemd unit, or database row was modified. No data
was left behind — the only write-shaped probe (§5b) 404'd before reaching any write path, verified by identical
pre/post `AdminAuditLog` counts. Probe scripts live outside the repo in the session scratchpad. No secret value
was printed or logged at any point (token shown as an 8-char prefix; password hashes shown as scheme + an
8-char SHA-256 fingerprint; the DSN was never rendered).

