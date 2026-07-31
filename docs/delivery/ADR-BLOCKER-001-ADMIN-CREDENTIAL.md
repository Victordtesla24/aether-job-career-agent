# ADR-BLOCKER-001 — Admin credential over-permission: binding risk ruling

**Status:** BINDING (risk-officer adjudication, GOLD-MASTER-V2 §0.2 / §13.2)
**Adjudicator:** risk-officer sub-agent (sole approver of destructive/risky changes)
**Date:** 2026-07-31
**Subject:** BLOCKER-001 — production admin privilege granted behind a known-weak, publicly-derivable credential
**Production:** https://5cb5f0620.abacusai.cloud
**Repo:** /home/ubuntu/github_repos/aether-job-career-agent @ `297946d` (working tree dirty — see §1 F11)

> **Secrets discipline:** no credential value appears in this document. The weak password is referenced
> only as *the denylist head entry* = `app.repositories.admin._KNOWN_WEAK_ADMIN_PASSWORDS[0]`.
> Environment variables are referenced by NAME only.

---

## 1. Ground truth — re-verified first-hand, prior testimony NOT trusted

Every fact below was established by me directly on 2026-07-31, not read from a prior report.

| # | Fact | How verified |
|---|---|---|
| **F1** | `AETHER_ENV` = `production` in the repo-root `.env`, so `admin._is_production()` returns `True` on the live box. | parsed `.env` |
| **F2** | `AETHER_ADMIN_PASSWORD_HASH` is a real bcrypt hash (60 chars, cost 12) and **verifies the denylist head entry**. | `app.security.verify_password` against the live value |
| **F3** | `AETHER_CRON_EMAIL` **==** `AETHER_ADMIN_EMAIL` (owner's gmail.com mailbox), and `AETHER_CRON_PASSWORD` **verifies the same hash** and is *itself* the denylist head entry. **Cron and admin share one credential.** | computed booleans |
| **F4** | `LOGIN_PASSWORD` does **not** verify the hash and is **not** on the denylist → it is **stale**. `scripts/discovery_cron.sh:49` falls back to it when `AETHER_CRON_PASSWORD` is unset; that fallback would 401 today. | computed booleans |
| **F5** | Prod DB (`aether` schema, read-only txn): **7 users; exactly 1 `isAdmin` row** — the owner (gmail.com), `username='admin'`, `suspended=false`, and its `passwordHash` is **byte-identical** to `AETHER_ADMIN_PASSWORD_HASH`. The seeded demo account `admin@aether.local` **does not exist** in production. | `psycopg2`, `set_session(readonly=True)` |
| **F6** | `aether-api.service`: `Restart=on-failure`, `RestartSec=5`. | `/etc/systemd/system/aether-api.service` |
| **F7** | **The GitHub repo `Victordtesla24/aether-job-career-agent` is PUBLIC** (`isPrivate:false`), and `scripts/discovery_cron.sh:30` hardcodes the owner's admin email as a shipped default. **The admin identity is publicly published.** | `gh repo view` |
| **F8** | `isAdmin` is resolved **live from the DB on every request** (`middleware/auth.py:49-54`, `get_auth_context`) — it is **not** a JWT claim. | source read |
| **F9** | Login throttling **already exists**: 5 failures / 15-min window, keyed on the identifier, in-process memory (`app/rate_limit.py:43-44`). | source read |
| **F10** | `TOKEN_TTL` = 24h, flat for all users, HS256, **stateless — no revocation list** (`app/security.py:11-12`). | source read |
| **F11** | The working tree **already contains an uncommitted fix** (`admin.py` +255 lines, `main.py` +36) that **raises `AdminCredentialSecurityError` and aborts boot** on a weak hash in production. | `git diff` |
| **F12** | `test_blocker001_admin_overpermission.py` collects **8 tests** (4 are parametrizations of the rotation-refusal case) — consistent with the claimed "7 failed / 1 passed"; the 1 pre-fix pass is `test_login_rate_limiting_already_exists_pin`, correctly pinning behavior that already existed. | `pytest --collect-only` |

### 1.1 Prior-testimony adjudication

| Claim | Verdict |
|---|---|
| `AETHER_ADMIN_PASSWORD_HASH` is a bcrypt hash of the weak literal | **CONFIRMED** (F2) |
| `AETHER_CRON_EMAIL`/`AETHER_CRON_PASSWORD` bcrypt-match the same hash | **CONFIRMED** (F3) |
| Test file: 7 failed / 1 passed pre-fix | **CONFIRMED as plausible and structurally correct** (F12) |
| Orchestrator's live exploit (login → `isAdmin:true` → `/admin/users` leaks 7 users) | **CONFIRMED at the data layer** (F5: exactly one admin row, weak hash, 7 users) |

### 1.2 Severity escalation the prior testimony missed

F7 is new and material. The prior reports treated this as "a weak password". It is worse:
the **identity** (`AETHER_ADMIN_EMAIL`) is published in a public GitHub repository, and the
**password** is the single most-guessed default string in existence. Both halves of the
credential are effectively public. Removing the `admin` username alias — the headline of the
existing draft fix — therefore buys **almost nothing**, because the attacker simply substitutes
the email address printed in the public repo.

---

## 2. THE DECISIVE FINDING — the already-written fix would take production down

**I refused to verify this by deploying, because the verification would itself be the outage.**
Instead I executed the guard in isolation against the live configuration:

```
_guard_admin_credential_strength(AETHER_ADMIN_EMAIL, AETHER_ADMIN_PASSWORD_HASH)
with AETHER_ENV=production
  -> RAISED AdminCredentialSecurityError
```

Chain of consequence, every link established by F1/F2/F6/F11:

1. `apply_admin_rotation()` calls the guard at step 0 (`admin.py:754-755`).
2. The guard raises in production (proven above — deterministic and **memoized**, so it fails identically on every retry).
3. `main.py::_lifespan` deliberately **re-raises** `AdminCredentialSecurityError` (the new `except` split).
4. A lifespan-startup exception makes uvicorn log *"Application startup failed. Exiting."* and exit non-zero.
5. `Restart=on-failure` + `RestartSec=5` → **permanent crash loop. Production down, hard, with no self-recovery.**

This is precisely the outcome the run charter names as unacceptable. The draft fix converts a
confidentiality breach into a total availability loss, and it does so *on the very next deploy*,
silently, because nothing in the deploy path evaluates the guard before restarting the service.

**The design error is the choice of failure mode, not the detection logic.** The detection
(`_weak_password_matching`, the bcrypt-prefix check, the denylist) is sound, well-documented and
worth keeping. Only the *disposition* is wrong: it refuses **the boot** when it should refuse
**the grant**.

### 2.1 A second, independent defect in the same draft

`apply_admin_rotation()` commits the `isAdmin=true` grant at `admin.py:827` and only *then*
evaluates the self-cancel post-condition at `admin.py:833-839`, which raises. That ordering
produces the worst possible combination: **the privilege is already persisted AND the app
refuses to boot.** A post-condition that fires after its own commit is not a safety net.
Any approved implementation must evaluate it before committing, or inside the transaction.

---

## 3. Rulings on the remediation set

Ranked by (security value delivered NOW) ÷ (blast radius). Each carries an explicit outage,
owner-lockout and cron verdict.

### R1 — De-privilege on weak credential: *refuse the grant, not the boot* — **rank 1**

**APPROVED-WITH-CONDITIONS**

In production, when the configured admin credential verifies a denylist entry: do **not** grant
`isAdmin=true`; instead **force `isAdmin=false`** on that row, leave `passwordHash` untouched,
emit an unmissable stderr diagnostic, and **continue booting**.

| Question | Answer |
|---|---|
| Locks out the owner? | **No — not from the product.** Their password is unchanged, so ordinary login, their own data, billing and agent runs all keep working. They lose only `/admin/*`, and only until they rotate. |
| Breaks cron / system paths? | **No.** Verified: `discovery_cron.sh` authenticates as the owner via `/auth/login` (password unchanged, F3) and calls only `/auth/login`, `/auth/me`, `/agents/scout/run`, `/agents/fit-scorer/run` — **no `/admin/*` endpoint**. Its paywall bypass rides `AETHER_SYSTEM_RUN_SECRET` (`routers/agents.py:692`), not `isAdmin`. |
| Production outage risk? | **None.** Boot always completes; this branch removes the only new abort path. |
| Effective against tokens already issued to an attacker? | **Yes, immediately.** By F8 `isAdmin` is re-read from the DB on every request, so flipping the column instantly de-privileges every live session — including the 24h token the orchestrator minted during verification. This is the strongest property of R1 and the reason it outranks everything else. |

**Conditions (all mandatory):**
- **C1** — the weak-credential path MUST NOT raise out of `_lifespan`. Remove `AdminCredentialSecurityError` from the re-raise tuple in `main.py`, or stop raising it for this case.
- **C2** — MUST NOT modify `passwordHash`. Changing it is what would lock the owner out and break cron.
- **C3** — MUST explicitly `UPDATE "User" SET "isAdmin"=false` for the configured admin email. **Merely *skipping* the grant is a no-op against production**, because F5 shows the row is *already* `isAdmin=true` from previous boots. An implementation that only early-returns leaves the hole wide open while reporting success. This is the single most likely way to get R1 wrong.
- **C4** — the diagnostic must name the variable **`AETHER_ADMIN_PASSWORD_HASH`** and the matched denylist entry only; never the hash, never the live password.
- **C5** — `test_rotation_refuses_known_weak_admin_password_hash` (4 params) must be rewritten to assert *de-privilege + successful boot*, not to assert a raise. Leaving it asserting a raise would pin the outage behavior into the suite.
- **C6** — the post-condition at `admin.py:833-839` must be evaluated **before** the commit (§2.1).

**What could go wrong with R1 (adversarial self-review):**
- If the operator rotates the credential but the deploy does not restart the API, the row stays `isAdmin=false` and the owner reports "admin is broken". Mitigation: the rotation runs on every app construction, so a restart fixes it — this must be in the operator instructions (§4, O5).
- R1 leaves the **owner's ordinary account** reachable with a publicly-derivable credential. R1 closes the *privilege* hole, not the *account* hole. It must never be reported as full closure of BLOCKER-001.
- A future edit that reintroduces an early-`return` in place of the explicit `false` write silently reopens the hole with green tests unless C3 has its own regression test asserting the column flips from `true`.

### R2 — Malformed (non-bcrypt) hash: same treatment — **rank 2**

**APPROVED-WITH-CONDITIONS** (conditions C1–C4 apply identically)

`admin.py:158-171` currently raises in production when `AETHER_ADMIN_PASSWORD_HASH` is not
bcrypt-shaped. That is the same outage class as §2 and is *more* likely to fire than R1 — it is
exactly the mistake an operator makes **while performing the rotation we are about to ask them to
perform** (pasting a plaintext password into the hash variable).

- Locks out owner? Yes, from `/admin` only — and correctly, since no verifiable admin credential exists.
- Breaks cron? No (same reasoning as R1).
- Outage? None once C1 is applied. **Unacceptable outage risk if left as-is.**

**Adversarial:** the correct failure direction is "no admin" rather than "no service", but it means
a botched rotation yields *silently* no admin access. The stderr line must be loud and the operator
runbook must include the verification step in O5.

### R3 — `AdminRotationConfigError` (self-cancel guard) must also stop aborting boot — **rank 3**

**REFUSED as currently written; APPROVED in de-privilege form**

This one raises **unconditionally — not gated on `_is_production()`** (`admin.py:756-764`). It is
unreachable today (I verified `AETHER_ADMIN_EMAIL` != the seed identity), but a single operator
typo — setting `AETHER_ADMIN_EMAIL` to the demo address during the rotation — would crash-loop
production with no weak password involved at all. A guard that turns a config typo into a total
outage is not acceptable in a service with `Restart=on-failure`.

Must be converted to: refuse the grant, force `isAdmin=false`, log, continue.

### R4 — Reclaim the `admin` username alias (D2) — **rank 4**

**APPROVED** (single `UPDATE`, nullable `UNIQUE` column, additive-safe)

- Locks out owner? Only the *identifier* `admin`. Email login is unaffected. F5 confirms the row keeps its email identity.
- Breaks cron? **No** — cron uses `AETHER_CRON_EMAIL` (an email), never the alias.
- Outage? No.

**Condition:** it MUST NOT be reported as closing BLOCKER-001, and MUST NOT be listed ahead of R1
in any status document. **Adversarial:** by F7 the owner's email is published in a public repo, so
this closes one of two equally-public identifiers and the attacker trivially uses the other. Its
real value is defence-in-depth and hygiene, not remediation. Approving it while implying it fixes
the blocker would be a dishonest closure.

### R5 — Tighten what `GET /admin/users` discloses — **rank 5, deprioritized**

**APPROVED-WITH-CONDITIONS**

`list_users` (`admin.py:404-414`) returns, for every user: email, name, `isAdmin`, `suspended`,
`createdAt`, `lastLoginAt`, plan, subscription status, LLM spend and run count. Data minimization
here is legitimate on its own merits.

- Locks out owner? No. Breaks cron? No. Outage? No — **but real product-regression risk:** the admin UI in `apps/web` consumes these fields, so changing the response shape can break admin screens.

**Conditions:** may only be undertaken **after** R1 is deployed and verified; MUST be preceded by a
frontend consumer check; and MUST NOT be counted toward BLOCKER-001 closure.

**Adversarial:** this is the most seductive item on the list and the least useful. An attacker
holding `isAdmin` does not need `/admin/users` — they can reach every other `/admin/*` route
(suspend accounts, alter spend caps, issue refunds). Masking emails on one endpoint while the
privilege itself is intact is security theater. Ranked last deliberately.

### R6 — Shorten admin token TTL — **REFUSED**

**REFUSED as a BLOCKER-001 remediation.** Four independent reasons:

1. **Redundant.** By F8, `isAdmin` is read live from the DB per request, so R1 already revokes admin power on *existing* tokens instantly. TTL adds nothing this hole needs.
2. **Cannot do what it appears to do.** JWTs here are stateless with no revocation list (F10); shortening `TOKEN_TTL` affects only *newly minted* tokens. Every token already issued — including any an attacker holds — remains valid for its original 24h regardless.
3. **Collateral damage.** `TOKEN_TTL` is global. Shortening it logs out all ordinary users more often — a real UX regression on the eve of paid onboarding — and risks expiring the cron session mid-run.
4. **The admin-specific variant is worse.** Distinguishing admin tokens would require putting `isAdmin` into the JWT claims, replacing today's always-fresh DB read with a stale claim — which would *destroy* the property that makes R1 effective.

Refused on merit, not merely deprioritized.

### R7 — Login throttling / lockout — **NO ACTION APPROVED (already exists)**

Nothing to implement: F9 confirms 5 failures / 15 min, keyed on identifier, already live and
already pinned by `test_login_rate_limiting_already_exists_pin`.

**Adversarial — and this matters:** throttling is **irrelevant to this defect**. The attacker does
not guess; by F2+F7 they *know* both halves of the credential. A rate limiter does not impede a
single correct login. Listing "login throttling" as a BLOCKER-001 mitigation in any report would
be materially misleading and I will treat it as a governance finding.

*Separate, non-blocking observation for the ledger:* the limiter is in-process memory, so it resets
on every restart and does not span workers. Real weakness, out of scope here, not a blocker.

---

## 4. Deferred to the operator (§18 OPERATOR-HELD — the only legitimate non-closure)

`AETHER_ADMIN_PASSWORD_HASH` is operator-held. **No agent may rotate it.** These items are the
residual and they are what keeps G-P closed.

**O1 — Rotate `AETHER_ADMIN_PASSWORD_HASH`.** Generate a bcrypt hash of a strong, unique password
(not derived from the product name, not on any default list) and replace the value in the
repo-root `.env`:

```bash
python3 -c "from passlib.context import CryptContext; \
print(CryptContext(schemes=['bcrypt']).hash(input('new admin password: ')))"
```

Paste the **`$2b$…` output** — never the password itself — into `AETHER_ADMIN_PASSWORD_HASH`.

**O2 — Rotate `AETHER_CRON_PASSWORD` IN LOCKSTEP. This is the step that will be forgotten.**
F3 proves cron and admin share one credential. `AETHER_CRON_PASSWORD` must be set to the
**plaintext** of the same new password whose hash goes into `AETHER_ADMIN_PASSWORD_HASH`. If only
the admin hash is rotated, `discovery_cron.sh` starts returning 401 and **scheduled job discovery
dies silently** — a failure mode this codebase has already suffered once (see the 48h outage noted
at `scripts/discovery_cron.sh:31-40`).

**O3 — Resolve stale `LOGIN_PASSWORD`.** F4: it no longer matches the account. Because
`discovery_cron.sh:49` falls back to it, leaving it stale arms a confusing future failure. Update
it to the new password or remove it.

**O4 — Treat this as a *disclosed* credential, not merely a weak one.** The identity was published
in a **public** GitHub repo (F7) and the password is a top-tier default, on an internet-facing host
holding 7 real users' data. The operator should assume possible unauthorized access, and decide
whether to notify. Also consider removing the hardcoded owner email default at
`scripts/discovery_cron.sh:30` from the public repository.

**O5 — Verify after rotating (required):** restart the API (`sudo systemctl restart aether-api`),
confirm it comes up healthy, then confirm the admin grant was *restored* — the R1 de-privilege
reverses itself automatically on the first boot with a strong credential, because rotation runs on
every app construction. If `/admin/*` still 403s, the new hash is still failing the guard: check
the stderr log for the `AETHER_ADMIN_PASSWORD_HASH` diagnostic (most likely a plaintext pasted
into the hash variable — see R2).

---

## 5. Rollback procedure for the approved set (R1, R2, R3, R4)

All approved changes are **code-only plus one reversible column write**. No migration, no schema
change, no data destruction, no history rewrite. Nothing on the §1.4 PROTECTED / §6.2
DO-NOT-TOUCH lists is touched.

**Pre-flight (mandatory, before deploying the approved set):**
```bash
# Capture the exact pre-change privilege state for the single admin row (F5).
# Read-only. Store under uat/reports/evidence/gold-master-v2/governance/.
#   SELECT id, username, "isAdmin", "suspended" FROM "User" WHERE "isAdmin" OR username='admin';
```
Record the returned `id`, `username` and `isAdmin` values. That triplet **is** the rollback state.

**Rollback — code (restores previous behavior entirely):**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
git revert --no-edit <approved-commit-sha>     # or: git checkout HEAD~1 -- \
  apps/api/app/repositories/admin.py apps/api/app/main.py
sudo systemctl restart aether-api
curl -fsS https://5cb5f0620.abacusai.cloud/api/health   # must return healthy
```

**Rollback — data (restores the admin grant and the alias):**
```sql
-- Reverses R1/R3 de-privilege and R4 alias reclaim for the one affected row.
UPDATE "User" SET "isAdmin"=true,  "updatedAt"=now() WHERE "id"='<recorded-id>';
UPDATE "User" SET "username"='admin', "updatedAt"=now() WHERE "id"='<recorded-id>';
```
Both are single-row, additive-safe writes to existing nullable/boolean columns. `username` is a
nullable `UNIQUE` column and no other row can hold `admin` after R4, so the restore cannot conflict.

**Caveat that must be stated when exercising rollback:** rolling back **reopens BLOCKER-001**. It
restores admin privilege behind the known-weak, publicly-derivable credential. Rollback is
justified only to recover from an unforeseen availability failure, and only until the operator
completes O1+O2 — never as a way to restore admin convenience.

**Rollback is NOT required for the crash-loop scenario**, because the approved set removes it. If
the *rejected* draft (F11) is ever deployed by mistake, recovery is: set `AETHER_ENV` to a
non-production value to get the service up, then immediately revert the code and restore
`AETHER_ENV=production`. Record any such action as a governance incident.

---

## 6. G-P verdict — may the run declare "ready for real paid user onboarding"?

# NO.

**G-P is REFUSED while `AETHER_ADMIN_PASSWORD_HASH` remains unrotated.** This holds even after the
full approved set (R1–R4) is deployed and verified.

Reasoning, stated as precisely as the evidence supports:

- With **R1 deployed**, BLOCKER-001 is genuinely and substantially downgraded: no account holds
  `isAdmin`, every `/admin/*` route returns 403, and every already-issued token loses admin power
  immediately (F8). **Other users' PII is no longer reachable through this defect.** That is a real
  reduction, not a paper one, and it is achievable now without the operator.
- What remains is **not** nothing: the owner's ordinary account still has a publicly-derivable
  credential (F2+F7) on an internet-facing host. That account is also the **cron identity** (F3)
  and the **recovery path** for the whole platform. An attacker taking it gets the owner's own data
  and the ability to drive agent runs and spend.
- "Ready for real paid user onboarding" is an assertion that other people's money and data are safe
  under a named accountable owner. An owner account whose password is a top-tier default, whose
  email is published in a public repository, and which cannot be locked down by any agent, does not
  support that assertion at the standard this gate is meant to enforce.

**G-P may be declared only after O1 + O2 are confirmed complete and verified per O5.** No agent can
close it; this is the §18 operator-held class of non-closure, correctly invoked.

### 6.1 The honest residual statement (verbatim — must be used unaltered)

> BLOCKER-001 is **partially remediated and NOT closed.** The code-side privilege hole is closed:
> production refuses to grant administrator privilege to a credential matching a known-weak
> password, no account currently holds `isAdmin`, and all `/admin/*` routes — including the user
> list that exposed 7 users' email addresses, plans and spend — return 403 to every caller,
> retroactively including sessions issued before the fix.
>
> The underlying credential has **NOT** been rotated. Rotation is operator-held (§18) and cannot be
> performed by any agent. Until the operator completes it, the owner's account remains reachable
> with a publicly-derivable credential — its email address is published in a public GitHub
> repository and its password is a common default. That account is also the scheduled-discovery
> identity. The exposure is now limited to the owner's own account and no longer extends to other
> users' data, but it is a live exposure on an internet-facing production host.
>
> Because the credential was live on a public-internet host serving real user data, it must be
> treated as **disclosed**, not merely weak. Prior unauthorized access cannot be excluded from the
> available evidence.
>
> **This system is NOT certified ready for real paid user onboarding (G-P) until
> `AETHER_ADMIN_PASSWORD_HASH` and `AETHER_CRON_PASSWORD` are rotated together and verified.**

---

## 7. Governance record

- **Adjudicator:** risk-officer sub-agent. I did **not** author any remediation and I did not
  execute any of them — the working-tree draft (F11) was authored by another agent before I was
  engaged, and I am ruling on it, not on my own work. Implementation belongs to a fixer; the
  production column write belongs to the janitor/deployer under this approval.
- **Sub-agents spawned:** none (serial work only, per standing rules).
- **Writes performed by me:** this file only. No production source, `.env`, or `.claude/agents` was
  modified.
- **Production contact:** read-only throughout — one read-only DB transaction
  (`set_session(readonly=True)`) and static file reads. I deliberately did **not** deploy the draft
  fix to test the crash loop, and did **not** exercise the live admin login, because both would
  have caused the harm under adjudication.
- **§1.4 PROTECTED / §6.2 DO-NOT-TOUCH:** nothing in the approved set touches either list. No
  deletions, no migrations, no history-touching git operations were requested or approved.
- **UNSURE items:** none. Every question posed was resolved by direct evidence.
- Mirror this ruling to `uat/reports/evidence/gold-master-v2/governance/`.

**Two governance findings raised against prior/pending reporting:**
1. Reporting R4 (`admin` alias removal) as closing BLOCKER-001 would be a dishonest closure (§3, R4).
2. Reporting R7 (login throttling) as a BLOCKER-001 mitigation would be materially misleading —
   it pre-existed and is irrelevant to a known credential (§3, R7).
