# BLOCKER-001 — restart-safety fix: de-privilege, not de-boot

**Agent:** fixer-hard **Date:** 2026-07-31 (UTC)
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Binding input:** `docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` (risk-officer, BINDING)
**Failing tests implemented against:** `apps/api/tests/test_blocker001_admin_overpermission.py` (test-author; NOT modified by me)
**Status:** code fix complete, all targeted tests green, **NOT pushed, NOT deployed, no service restarted, `.env` untouched**

> **Secrets discipline.** No credential value appears in this document. The weak password is referred to
> as *the denylist head entry* (`app.repositories.admin._KNOWN_WEAK_ADMIN_PASSWORDS[0]`) or shown as
> `<denylist head>`. Env vars are named, never valued. Test-only literals in captured output belong to
> throwaway rows in the `aether_test` schema.

---

## 1. The hazard I was asked to remove — verified first-hand

`7f82105` (local only, never deployed) made `apply_admin_rotation()` raise `AdminCredentialSecurityError`
in production when `AETHER_ADMIN_PASSWORD_HASH` verifies a denylisted password, and `app.main._lifespan`
re-raised it. systemd runs the API straight out of this working tree, production's live hash is exactly
what that guard rejects, and `aether-api.service` sets `Restart=on-failure` / `RestartSec=5`.

**[VERIFIED] Pre-fix behaviour, executed against the production *shape* (`AETHER_ENV=production` + a
bcrypt hash of the denylist head entry) on the `aether_test` schema — never against the production DB:**

```
2026-07-31T00:28Z  (code at 7f82105, working-tree changes stashed)
PROBE-RESULT outcome=BOOT_ABORTED exc=AdminCredentialSecurityError: BLOCKER-001: refusing to grant
admin privilege to 'owner-eba1ca2d@aether.io' — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak
password '<denylist head>'. ...
```

The ASGI app never came up. Under `Restart=on-failure` that is a permanent crash loop: any restart —
VM reboot, crash, deploy, manual `systemctl restart` — would have taken production down for paying
customers, with no self-recovery, to punish a condition a restart cannot fix.

**[VERIFIED] I also confirmed the credential collision the coordinator flagged**, reading `.env` and
comparing values in-process (booleans only, no values printed), 2026-07-31T00:27Z:

| Check | Result |
|---|---|
| `AETHER_ENV` | `production` |
| `AETHER_ADMIN_PASSWORD_HASH` is bcrypt-shaped | true |
| hash verifies the denylist head entry | **true** |
| `AETHER_CRON_EMAIL` == `AETHER_ADMIN_EMAIL` (case-insensitive) | **true — same identity** |
| `AETHER_CRON_PASSWORD` verifies `AETHER_ADMIN_PASSWORD_HASH` | **true** |
| `AETHER_CRON_PASSWORD` == denylist head entry | **true** |

`scripts/discovery_cron.sh:85-90` authenticates with `POST /auth/login` using `AETHER_CRON_EMAIL` /
`AETHER_CRON_PASSWORD`, then calls `/auth/me`, `/agents/scout/run`, `/agents/fit-scorer/run` — **no
`/admin/*` route**. So any refusal keyed on the *password value* or on the *operator email* would have
401'd the 30-minute discovery timer and silently killed production job sourcing. This constrained the
design and is why the auth-layer refusal is keyed on the reserved identifier only (§3.3).

---

## 2. Design: fail-SAFE at boot, fail-CLOSED on privilege

Mid-task, test-author rewrote `test_blocker001_admin_overpermission.py` to encode the risk-officer's
BINDING ruling, which is stronger than "refuse the grant" and supersedes my initial approach. I
implemented **against that spec**, not against my own. The approved disposition is
**de-privilege, not de-boot** (ADR §3 R1/R2/R3, conditions C1–C6):

| Condition | Requirement | How this fix meets it |
|---|---|---|
| **C1** | must not raise out of `_lifespan` | `apply_admin_rotation()` contains **no `raise` at all**; `_lifespan` catches both admin exception types and continues, as a standing guarantee against a future re-introduction |
| **C2** | must not modify `passwordHash` | the degraded path writes exactly one column: `UPDATE "User" SET "isAdmin"=false,"updatedAt"=now()` |
| **C3** | must **explicitly** write `isAdmin=false`, not merely skip the grant | explicit `UPDATE`; production's row is already `isAdmin=true` from earlier boots, so skipping would be a no-op that reports success |
| **C4** | diagnostic names `AETHER_ADMIN_PASSWORD_HASH` + the matched denylist entry only | CRITICAL banner does exactly that; the configured hash value never appears |
| **C5** | the weak-hash test must assert de-privilege + successful boot | test-author's rewrite; all 12 of its tests pass |
| **C6** | post-conditions evaluated **before** commit | the whole disposition is decided in `_admin_credential_problem()` from the environment, before any write; grant/de-privilege happen inside the same transaction as the reclaim/demote; the old post-commit `raise` is gone |

### 2.1 Why fail-safe boot + fail-closed privilege is the correct pair

Refusing the *boot* and refusing the *grant* are not alternatives at the same level. The boot decision
governs every user; the privilege decision governs one row.

* **Boot must succeed.** The condition is a *live credential the operator has not rotated yet* — already
  true of the running environment, only a human can clear it, and it is re-evaluated on every start.
  Aborting converts a confidentiality problem into a total availability loss (ADR §2) and gains nothing.
* **Privilege must be revoked.** `isAdmin` is re-read from the row on every request
  (`app/middleware/auth.py`), so flipping the column de-privileges **already-issued tokens immediately**,
  including any an attacker holds. This is strictly stronger than refusing new logins.
* **The password must not be touched.** It is the owner's ordinary product login *and* the cron identity.
  Changing or refusing it would lock the owner out of their own data and kill scheduled sourcing.

**The distinction from `_guard_production_replay_mode` is documented in the code**, in
`app.main._lifespan`'s docstring, so a future reader does not "helpfully" make this fail-closed again:
that guard aborts on a **misconfiguration the operator sets deliberately in the deploy environment**
(`AETHER_LLM_MODE=replay`), where refusing to start costs nothing because such a deploy should never go
live. This one reacts to a **live, human-held credential**, where refusing to start costs everything and
fixes nothing.

---

## 3. Files changed

| File | Change |
|---|---|
| `apps/api/app/repositories/admin.py` | `_audit_admin_credential()` (pure audit, non-raising) + `_self_cancel_problem()` + `_admin_credential_problem()` (single, env-only disposition decision, not gated on `AETHER_ENV`); module-level degraded flag `_ADMIN_CREDENTIAL_DEGRADED` with `_record_admin_credential_state()` / `admin_credential_degraded()`; `weak_operator_credential_refused()`; `apply_admin_rotation()` restructured to grant-or-de-privilege inside one transaction with zero raises; `health_overview()` gains a `security` block. Removed: the raising `_guard_admin_credential_strength()` and the post-commit `raise`. |
| `apps/api/app/main.py` | `_lifespan` no longer re-raises `AdminCredentialSecurityError` / `AdminRotationConfigError`; logs CRITICAL and keeps serving. Docstring records why this must not be reverted to fail-closed. |
| `apps/api/app/routers/auth.py` | login folds `weak_operator_credential_refused(...)` into the existing constant-shaped 401 chain (same body, same failed-attempt counter — no enumeration signal). |
| `apps/api/tests/test_blocker001_restart_safety.py` | **new** — 5 regression pins, including an explicit scope pin that the discovery-cron login must keep working. |

`AdminCredentialSecurityError` / `AdminRotationConfigError` are retained (documented as no-longer-raised)
because `_lifespan` still catches them defensively and the BLOCKER-001 test module imports them.

### 3.1 What the degraded path now does, in order

1. Decide the disposition from the environment alone (weak password / non-bcrypt hash / `AETHER_ADMIN_EMAIL`
   == seeded demo identity) — before any write.
2. Publish the flag; log CRITICAL to both `logging` and stderr (systemd captures stderr regardless of
   handler configuration).
3. In one transaction: reclaim the reserved `admin` username from non-demo rows (ADR R4); demote the
   seeded demo row; then **revoke** `isAdmin` on the configured operator row (instead of granting).
4. Continue booting and serving.

### 3.2 Recovery is automatic

Rotation runs on every app construction. The first restart after the operator rotates
`AETHER_ADMIN_PASSWORD_HASH` to a strong, well-formed hash re-grants `isAdmin` with no code change
(ADR operator step O5). **[VERIFIED]** in §4.2 below.

### 3.3 Deliberately narrow scope of the auth-layer refusal

`weak_operator_credential_refused()` refuses **only** the reserved identifier `admin` with a denylisted
password, and only while degraded. It deliberately does **not** key on the password value or on
`AETHER_ADMIN_EMAIL`, because that is the discovery cron's credential (§1). This is defence-in-depth on
top of the ADR set (it holds even if a future edit drops the username reclaim); the privilege hole is
closed by the de-privilege write, not by this. The scope is pinned by a test so it cannot be widened
accidentally.

---

## 4. Verbatim proof

Both properties, one boot, production shape (`AETHER_ENV=production`, operator row pre-seeded to
production's actual state: `isAdmin=true`, `username='admin'`, `passwordHash` = bcrypt of the denylist
head entry), executed on the `aether_test` schema. **[VERIFIED] 2026-07-31T00:40Z**

### 4.1 Degraded boot

```
===== PROOF: PRODUCTION SHAPE, UNROTATED WEAK CREDENTIAL =====
PRE  isAdmin=True username='admin' passwordHash=$2b$12$5s2...
BOOT=BOOTED  GET /health -> 200
POST /auth/login  admin / <denylist head>            -> 401 'Invalid email or password'
POST /auth/login  <operator email> / <denylist head> -> 200   (discovery-cron path)
GET  /auth/me     with that token                    -> 200 isAdmin=False
GET  /admin/users with that token                    -> 403
GET  /admin/health with that token                   -> 403
POST isAdmin=False username=None passwordHash=$2b$12$5s2...
passwordHash UNCHANGED: True
degraded flag: True
health_overview()['security']: {'adminCredentialDegraded': True, 'remediation': 'The configured operator admin credential was refused, so the §14.7 rotation REVOKED administrator privilege instead of granting it, and the reserved demo login identifier is rejected. Account passwords were not changed. Rotate AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique password and restart aether-api; privilege is restored automatically on the next boot. Full detail is in the API log (search: BLOCKER-001).'}
```

CRITICAL diagnostics emitted on the same boot (stderr, verbatim):

```
CRITICAL: DEGRADED ADMIN CREDENTIAL — the API is starting NORMALLY, but administrator privilege has been
REVOKED from the configured operator row and the reserved demo login identifier is REJECTED, until an
operator fixes this. Every /admin/* route will return 403. The account's password is NOT changed:
ordinary login, the scheduled discovery cron and all normal users are unaffected. BLOCKER-001: refusing
to grant admin privilege to 'owner-6fd61f64@aether.io' — its AETHER_ADMIN_PASSWORD_HASH verifies the
known-weak password '<denylist head>'. An admin account can read every user's email address, change spend
caps and issue real refunds; a guessable password on it is a full compromise of the platform. Rotate
AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique password and restart.

CRITICAL: §14.7 rotation REVOKED isAdmin from 1 account(s) configured via AETHER_ADMIN_EMAIL because the
configured credential was refused (see the diagnostic above). Their password was NOT changed. /admin/*
will return 403 until AETHER_ADMIN_PASSWORD_HASH is rotated and the API restarted.
```

Reading the block above against the requirements:

* **boots** — `BOOT=BOOTED`, `GET /health -> 200` (pre-fix: `BOOT_ABORTED`).
* **weak credential cannot obtain admin** — row flipped `True -> False`; `/admin/users` and
  `/admin/health` both `403` for a session minted with that very credential.
* **published `admin`/`<denylist head>` cannot obtain the owner session** — `401`, identical body to any
  bad password, and the `admin` alias is gone (`username=None`).
* **`passwordHash` untouched** — `passwordHash UNCHANGED: True` (condition C2).
* **cron/discovery keeps working** — operator-email login `200`, `/auth/me` `200`. That is the entire auth
  dependency of `scripts/discovery_cron.sh`; it calls no `/admin/*` route, and its paywall bypass rides
  `AETHER_SYSTEM_RUN_SECRET`, not `isAdmin`.

### 4.2 Recovery after the operator rotates (O1 + restart)

```
===== PROOF: AFTER OPERATOR ROTATION (O1) + RESTART =====
BOOT=BOOTED  GET /health -> 200  isAdmin=True  degraded=False
```

---

## 5. Test results

Command (targeted only; the full suite was **not** run — ~35 min):

```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh \
  tests/test_blocker001_admin_overpermission.py tests/test_blocker001_restart_safety.py \
  tests/test_auth.py tests/test_gap_p6_admin.py -v"
```

| Run | Result |
|---|---|
| **Fail-before**, new pins vs. code at `7f82105` (2026-07-31T00:28Z) | **2 failed, 3 errored, 0 passed** — boot aborted, so the fixture rows leaked and cascaded |
| **Fail-before**, test-author's rewritten spec vs. `7f82105` (00:29Z) | **5 failed, 55 passed** (`..._forces_explicit_deprivilege...`, `..._malformed_hash...` ×2, `..._self_cancel_config...`, `..._no_raise_statement_follows_a_database_commit...`) |
| **Pass-after** (2026-07-31T00:37:55Z → 00:39:39Z) | **60 passed, 0 failed** |

The 8th test that previously failed on a mutually-unsatisfiable setup precondition no longer exists —
test-author replaced the module wholesale to encode the ADR. **Nothing in that file was modified by me.**

---

## 6. Residual risks and things the coordinator must decide

1. **BLOCKER-001 is NOT closed.** Per ADR §6.1 the honest residual stands verbatim: the *privilege* hole
   is closed, the *account* hole is not. The owner's ordinary account remains reachable with a
   publicly-derivable credential (its email is published in a public repo; the password is a top-tier
   default), and it is also the cron identity. Only operator steps **O1 + O2** (rotate
   `AETHER_ADMIN_PASSWORD_HASH` **and** `AETHER_CRON_PASSWORD` together) close it. No agent may do this.
2. **`AETHER_CRON_EMAIL` == `AETHER_ADMIN_EMAIL`, same weak password — confirmed.** I did **not** ship any
   refusal that would touch that login. If a future change refuses by password value or by operator
   email, scheduled discovery dies silently. `test_degraded_state_does_not_break_the_scheduled_discovery_login`
   exists specifically to fail loudly if someone tries.
   **Corollary for O1/O2:** rotating only the admin hash breaks the cron. They must move together.
3. **The two screen-tester agents using `admin`/`admin123` WILL break on deploy — action needed.**
   Verified in §4.1: (a) identifier `admin` → 401 (alias reclaimed + refusal); (b) operator email +
   that password still logs in, but `isAdmin=false`, so **every `/admin/*` screen returns 403**.
   Non-admin, data-rich screens remain testable via **email** login with the unchanged password. Their
   login recipe must be re-issued before deploy: use the email identifier, and expect no admin surfaces
   until the operator completes O1+O2 and the API restarts. Nothing changes until a deploy/restart —
   production is still running the pre-`7f82105` code (started 2026-07-30T12:27:09Z).
4. **`/admin/health` cannot be seen while degraded.** The field is correct and leak-free, but the route is
   `AdminUser`-gated and the disposition revokes the only admin (ADR §1 F5: production has exactly one
   admin row). It is useful to a second, independently-privileged admin and as a post-rotation
   confirmation. **The operative operator channel while degraded is the CRITICAL line in the API log.**
   I deliberately did **not** expose the flag on the unauthenticated `/health` endpoint — that would
   advertise to the internet that this host has a weak admin credential. A comment in
   `health_overview()` says so, to stop a future "fix".
5. **Deploy will write to production data.** First boot after deploy performs three single-column,
   reversible writes on the one affected row: `username` → `NULL`, and `isAdmin` → `false` (plus the demo
   demote, a no-op — the seeded demo account does not exist in production). Rollback SQL is in ADR §5.
   The pre-flight state capture required by ADR §5 has **not** been performed by me; it is a prerequisite
   for the deployer.
6. **Disposition is not gated on `AETHER_ENV`.** A weak/malformed operator hash de-privileges in every
   environment, deliberately (ADR §3 R3 warns against an `_is_production()` gate that relocates rather
   than removes a failure). Local/dev setups that relied on a weak `AETHER_ADMIN_PASSWORD_HASH` to obtain
   admin must use a strong hash. No test in the targeted set depended on the old behaviour; the full
   suite was not run, so an unrelated suite that sets a weak admin hash would surface this — none exists
   per `grep` of `apps/api/tests` (only `test_gap_p6_admin.py`, which uses a strong password).
7. **Not covered:** `AETHER_ADMIN_EMAIL` set while `AETHER_ADMIN_PASSWORD_HASH` is empty leaves the row's
   existing `isAdmin` untouched (pre-existing behaviour, outside the ADR's approved set). Flagged, not
   changed, to keep the diff inside the binding ruling.
8. **Not done, by instruction:** no push, no deploy, no service restart, no `.env` edit, no credential
   rotation, no sub-agents. The full pytest suite was not run.
