# BLOCKER-001 §15 STEP 2 — TESTS-FAIL-BEFORE

**Test file:** `apps/api/tests/test_blocker001_admin_overpermission.py` (rewritten in full this session)
**Binding inputs:** `docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md` (risk-officer BINDING ruling, conditions C1–C6), `uat/reports/evidence/gold-master-v2/blocker001/AUTH-CODE-MAP.md`
**Author role:** test-author only. No production code (`apps/api/app/**`) was written or edited by me at any point.

---

## 0. IMPORTANT — environment was not static during this session (read first)

This was a live multi-agent swarm session. `apps/api/app/repositories/admin.py`
and `apps/api/app/main.py` changed **twice** while I was authoring/running
tests, both times by other agents working the same area concurrently:

| # | State | How I know | My evidence |
|---|---|---|---|
| 1 | **Original REFUSED draft** (uncommitted working-tree changes, as described by ADR §1 F11 — re-raises `AdminCredentialSecurityError`/`AdminRotationConfigError`, aborts boot) | `git diff` read at session start, before writing any test | Run @ 00:23:38Z — `logs/tests-fail-before-20260731T002338Z.log` |
| 2 | **Committed fix, commit `7f82105`** ("fix(BLOCKER-001): close admin over-permission…") — implements C1/C2/C4 for R1/R2 (de-privilege-not-de-boot) plus an ADR-exceeding compensating auth-layer control, but **not** C3, **not** R3's de-privilege conversion, **not** C6 | `git log`, `git status --short` (clean for these 2 files), 3× repeated full-suite runs with identical results | `logs/tests-against-commit-7f82105-clean-20260731T002900Z.log` (verbatim transcript quotes) |
| 3 | **Unrelated, uncommitted, in-progress rewrite** by a third agent (386-line diff to `admin.py`, 64-line diff to `main.py`; a companion untracked file `apps/api/tests/test_blocker001_restart_safety.py` suggests a "restart safety" follow-up finding is being worked concurrently) — transiently contains a `NameError: name '_guard_admin_credential_strength' is not defined` regression | `git status --short`, `git diff --stat`, file mtimes advancing between my runs, direct pytest tracebacks | Run @ 00:34:45Z — `logs/tests-against-committed-fix-20260731T003445Z.log` |

Per my standing instructions I do not implement fixes and I do not keep
chasing a moving target (state 3 is another agent's active, incomplete edit —
re-running against it repeatedly would just capture more mid-edit noise, not
a decision-relevant result). **State 1 is the literal "before the fix"
evidence this task asked for. State 2 is additional, higher-value evidence
because it shows exactly which ADR conditions a real fix attempt still
misses — including one CONFIRMED LIVE-EXPLOITABLE end-to-end.** State 3 is
recorded for transparency only; no test conclusions are drawn from it beyond
"the environment is currently unstable."

All backend runs below were executed as:
```
flock /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_blocker001_admin_overpermission.py -v --tb=short
```
(never sourcing the repo-root `.env`), against `DATABASE_URL_TEST` (`aether_test` schema).

---

## 1. State 1 — original REFUSED draft (the literal fail-before baseline)

**Result: 10 failed, 2 passed** of 12 collected. Log: `logs/tests-fail-before-20260731T002338Z.log`.

| Test | Expected (approved) | Actual (draft) | Right reason? |
|---|---|---|---|
| `test_weak_credential_does_not_abort_boot[admin123\|admin\|password\|changeme]` (×4) | boot succeeds | `TestClient.__enter__` raised `AdminCredentialSecurityError`; my `_assert_boot_succeeds` converted it to `pytest.fail("C1/R1-R3 VIOLATION: app startup raised AdminCredentialSecurityError …")` | Yes — draft's `_guard_admin_credential_strength` raises in production and `main.py::_lifespan` re-raises, matching ADR §2's decisive finding verbatim |
| `test_weak_credential_forces_explicit_deprivilege_without_touching_password_hash` | row starts `isAdmin=true`, ends `isAdmin=false`; `passwordHash` unchanged | `apply_admin_rotation()` raised `AdminCredentialSecurityError` at step 0, **before touching any row** — precondition row unchanged (`isAdmin` still `True`) | Yes — exactly the "no-op leaves the hole wide open" mode C3 names |
| `test_weak_credential_logs_critical_diagnostic_naming_env_var_only` | stderr contains `AETHER_ADMIN_PASSWORD_HASH` + `CRITICAL`, never the raw hash | stderr **empty** — draft's production branch raises with no print at all | Yes |
| `test_malformed_hash_does_not_abort_boot_and_deprivileges[not-a-bcrypt-hash-at-all\|md5-crypt]` (×2) | boot succeeds, row de-privileged | same abort-boot failure as weak-hash case | Yes — same code path (`_guard_admin_credential_strength`'s non-bcrypt branch) |
| `test_self_cancel_config_deprivileges_instead_of_raising` | boot succeeds, seed row `isAdmin=false` | `AdminRotationConfigError` raised unconditionally, re-raised by `_lifespan`, boot aborts | Yes — ADR §3 R3's exact complaint ("raises unconditionally — not gated on `_is_production()`") |
| `test_no_raise_statement_follows_a_database_commit_in_apply_admin_rotation` | no `raise` after the last `conn.commit()` in `apply_admin_rotation` source | `raise AdminRotationConfigError(...)` found textually after the grant's `conn.commit()` | Yes — matches ADR §2.1 exactly (structural/white-box check; see §4 rationale below) |
| `test_healthy_credential_still_grants_admin_and_boot_succeeds` | PASS (regression pin) | **PASSED** | n/a — expected pass |
| `test_non_admin_gets_403_on_every_admin_route_pin` | PASS (regression pin) | **PASSED** | n/a — expected pass |

All 10 failures are for the reason the docstring predicted — none is a
"defect in the test" (no placeholder/fake-pass assertions; every failure
message names the exact ADR condition violated and quotes the observed
state).

---

## 2. State 2 — committed fix, commit `7f82105` (supplementary, high-value evidence)

**Result: 5 failed, 7 passed** of 12 collected, reproduced identically across
3 separate full-suite runs plus isolated single-test and two-test runs (no
flakiness once the code stopped changing under me). Verbatim quotes in
`logs/tests-against-commit-7f82105-clean-20260731T002900Z.log`.

| Test | Result vs. commit 7f82105 | Why |
|---|---|---|
| `test_weak_credential_does_not_abort_boot` (×4) | **PASSED** | `main.py::_lifespan` now catches `AdminCredentialSecurityError` non-fatally (logs CRITICAL, keeps serving) — C1 satisfied |
| `test_weak_credential_logs_critical_diagnostic_naming_env_var_only` | **PASSED** | commit prints a `"CRITICAL: DEGRADED ADMIN CREDENTIAL — …"` banner via `logging.critical` + stderr, naming `AETHER_ADMIN_PASSWORD_HASH`, never the raw hash — C4 satisfied |
| `test_weak_credential_forces_explicit_deprivilege_without_touching_password_hash` | **FAILED** | passwordHash is correctly untouched (C2 OK), but the row that started `isAdmin=true` (simulating ADR F5) is **still `isAdmin=true`** after rotation — the commit only *skips* the grant (step 3), it never issues an explicit `UPDATE "User" SET "isAdmin"=false` for the *configured* row. This is C3's named failure mode, confirmed, and **confirmed live-exploitable** — see §3 below. |
| `test_malformed_hash_does_not_abort_boot_and_deprivileges` (×2) | boot-succeeds half **passes**; de-privilege half **FAILS** | identical C3 gap as above, on the malformed-hash branch |
| `test_self_cancel_config_deprivileges_instead_of_raising` | **FAILED** | `apply_admin_rotation()` step 0 still raises `AdminRotationConfigError` unconditionally for `AETHER_ADMIN_EMAIL == _SEED_ADMIN_EMAIL`, and `main.py::_lifespan` **still re-raises it, aborting boot** — this is a *deliberate* choice in the commit (its own `_lifespan` docstring argues explicitly for keeping this one fatal), which directly contradicts the BINDING ADR ruling (§3 R3: "REFUSED as currently written… Must be converted to: refuse the grant, force isAdmin=false, log, continue") |
| `test_no_raise_statement_follows_a_database_commit_in_apply_admin_rotation` | **FAILED** | the same post-commit `raise AdminRotationConfigError(...)` dead-code pattern (ADR §2.1 / C6) is present unchanged in the commit |
| `test_healthy_credential_still_grants_admin_and_boot_succeeds` | **PASSED** | happy path unaffected |
| `test_non_admin_gets_403_on_every_admin_route_pin` | **PASSED** | unaffected, as expected |

### 3. Live end-to-end confirmation of the C3 gap (not just a DB-column check)

To make sure the C3 failure above reflects a genuine exploit and not merely
an internal-state assertion, I ran a one-off, standalone verification (not
part of the committed suite) against commit 7f82105:

1. Create a user row, set `isAdmin=true` directly (simulating ADR F5 — "already `isAdmin=true` from a previous boot").
2. Run `apply_admin_rotation()` with `AETHER_ADMIN_EMAIL=<that row's email>`, `AETHER_ADMIN_PASSWORD_HASH=bcrypt("admin123")`, `AETHER_ENV=production`. It raises `AdminCredentialSecurityError` (refuses the *grant*) — but the row is untouched.
3. `POST /auth/login {"email": "<that row's email>", "password": "admin123"}` → **HTTP 200**, valid bearer token.
4. `GET /auth/me` → **`isAdmin: true`**.
5. `GET /admin/users` → **HTTP 200** (full user PII listing).

This is BLOCKER-001's original exploit, reproduced end-to-end against the
committed fix, via the **email** identifier rather than the reserved `admin`
username. Commit 7f82105 adds a compensating login-time control
(`weak_operator_credential_refused`) that *would* have blocked this if the
identifier had been the literal string `admin` — but its own `SCOPE` comment
says it deliberately does **not** cover the `AETHER_ADMIN_EMAIL` address
itself (to avoid breaking the discovery cron, which authenticates via that
same email+password per ADR F3). The ADR's own severity-escalation section
(§1.2) explicitly anticipated this exact substitution: *"the attacker simply
substitutes the email address printed in the public repo."*

**This is not a test bug.** It is the single most likely way to get R1 wrong,
named by the ADR itself, reproduced against the actual committed fix.

---

## 4. Note on `test_no_raise_statement_follows_a_database_commit_in_apply_admin_rotation` (white-box test)

This is the one structural (source-inspection) test in the file rather than a
black-box behavioural one — documented deliberately in its docstring. The
exact ordering bug ADR §2.1 describes (`admin_id in demoted_ids` checked
*after* `conn.commit()`) is only reachable through the self-cancel
configuration, which is *already* intercepted earlier by step 0's
unconditional `AETHER_ADMIN_EMAIL == seed` check — so no external input this
suite can construct reaches the buggy branch today. C6 requires it fixed
anyway as defence against a future edit to either email predicate (the code's
own comment names this risk). A source-order assertion — "no `raise`
statement appears after the function's last `conn.commit()`" — is therefore
the smallest honest way to pin the property, written generically (any commit,
any raise) so it does not presume how the fix restructures the code.

---

## 5. Prohibited-pattern self-check

* No `pytest.skip`/`xfail` used to dodge a hard case.
* No mock/stub of `apply_admin_rotation`, `_guard_admin_credential_strength`, or the DB — every assertion runs the real function against the real `aether_test` Postgres schema.
* The literal `admin123` (and other denylist entries) appear only as rejection-test input, exactly as scoped by the task brief — never asserted as a stored/working credential.
* No secret VALUE is logged anywhere in this file or this report; hashes are truncated to 8 chars where shown in assertion messages.
* `git commit --no-verify`, force-push, and self-approval were not used — this session made **no commits** (see final report).

---

## 6. Summary counts (per the literal task ask — "prove the fail-before state")

* **Test file:** `apps/api/tests/test_blocker001_admin_overpermission.py`
* **Tests total:** 12
* **State 1 (original REFUSED draft) — failing:** 10, **passing:** 2 (both expected regression pins)
* **State 2 (committed fix 7f82105, supplementary) — failing:** 5, **passing:** 7
* Every failure in both states is for the ADR-condition-specific reason documented above, not a test defect.
