# GOLD-MASTER-V2 §15 — `POST /auth/register` 500 on NUL byte in password

Status: **FIXED**. Evidence timestamp: 2026-07-31T15:20:12Z (this document).

## 1. Root cause

`POST /auth/register` 500'd whenever the `password` field contained a NUL
byte (`\x00`). Verbatim traceback tail from production (finding, filed as
`ML-SIGNUP-001`, previously misrecorded as "fixed at HEAD, deployment lag" —
it was **live**):

```
File "apps/api/app/routers/auth.py", line 98, in register
    body.email, hash_password(body.password), name=body.name
File "apps/api/app/security.py", line 37, in hash_password
    return _pwd_context.hash(password)
...
passlib.exc.PasswordValueError: bcrypt does not allow NULL bytes in password
```

`RegisterRequest.password` is a plain `str` field with no NUL-byte check.
`register()` passed it straight to `hash_password()`, which called
`_pwd_context.hash(password)` with no `try`/`except` at all. passlib's bcrypt
backend (`passlib/handlers/bcrypt.py::_norm_digest_args`) explicitly checks
for a NUL byte and raises `passlib.exc.PasswordValueError` — deliberately,
per its own comment ("especially important to forbid NULLs for bcrypt, since
many backends... silently truncate the password at first NULL"). Nothing
caught it, so it propagated to FastAPI's default handler as an unhandled 500
with a full traceback.

### Why the existing DB-cursor NUL-byte guard missed it

`app/db.py::_NulByteGuardCursor` protects the DB cursor path — it inspects
values immediately before they go into a SQL query. A password is **never**
passed to the DB as a raw string: it is hashed by bcrypt first
(`hash_password`), and bcrypt raises **before** `UserRepository().create(...)`
ever executes a query. The only thing that ever reaches the cursor is the
already-computed bcrypt digest (which cannot contain a NUL byte — it's a
`$2b$...` ASCII string). So this endpoint was structurally unreachable by that
guard, by design, not by omission — it's the wrong layer for a value that
never becomes a query parameter.

The `email` field, by contrast, is `EmailStr`: Pydantic's own email validator
rejects a NUL byte with a clean 422 before the handler runs at all, which is
why the *same* request shape with the NUL in `email` already returned 422 —
only the `password` field lacked the equivalent check.

## 2. Every `hash_password()` / `verify_password()` call site

```
apps/api/app/routers/auth.py:98    hash_password(body.password)          -- register, HTTP-reachable
apps/api/app/routers/auth.py:158   verify_password(body.password, ...)   -- login, HTTP-reachable
apps/api/app/repositories/admin.py:159  verify_password(candidate, pw_hash)  -- weak-credential audit
apps/api/scripts/seed_demo.py:83   hash_password(password)               -- seed-script self-check
apps/api/scripts/seed_demo.py:123  hash_password(_admin_password())      -- seed-script admin row
apps/api/scripts/seed_demo.py:175  hash_password(_demo_password())       -- seed-script demo row
```

No dedicated password-change or password-reset router/endpoint exists in this
codebase (confirmed by `grep -rn "reset.*password\|change.*password" apps/api/app`
and `grep -rln "passwordHash" apps/api/app` — only `auth.py`, `security.py`,
`repositories/user.py`, `repositories/admin.py` touch credential material at
all; no `resumes`/`profile`/`account`-style router has a password field).

**Covered by this fix:**
- `auth.py:98` (register / `hash_password`) — was the live 500; now 422
  (fixed at the `RegisterRequest` validation layer; `hash_password` itself is
  also hardened as defense-in-depth).
- `auth.py:158` (login / `verify_password`) — **already safe before this
  change** (see §3); now pinned with explicit regression tests so it cannot
  silently regress.

**Not code-changed (already safe / not attacker-reachable), with reasoning:**
- `admin.py:159` (`_weak_password_matching`) — the `candidate` argument is
  always one of a small hardcoded Python-literal list
  (`_KNOWN_WEAK_ADMIN_PASSWORDS`), never externally-supplied input; it cannot
  contain a NUL byte regardless of this fix. Still exercised transitively:
  `verify_password`'s hardening covers it for free.
- `scripts/seed_demo.py` (all three call sites) — the password value comes
  from an environment variable (`ADMIN_PASSWORD`) or a hardcoded demo
  constant, set by the operator at deploy time, not by an HTTP request; POSIX
  environment variables cannot themselves contain a NUL byte (C strings are
  NUL-terminated), so this is not a live attack surface. `hash_password`'s new
  defense-in-depth check covers these calls too — if one somehow got a NUL
  byte, they now raise a clear `ValueError` instead of a bare bcrypt crash,
  which is the correct behaviour for a script-level misconfiguration (fail
  loud and clear, not a silent fallback).

## 3. The seam chosen, and why

Two changes, deliberately at two different layers, mirroring the **existing**
precedent in this exact file for `MV-signup-001` / `BCRYPT_MAX_PASSWORD_BYTES`
(72-byte truncation guard), which already uses the same two-layer pattern:

### 3a. Primary seam — `app/repositories/user.py::validate_password_policy`

```python
if "\x00" in password:
    problems.append("password must not contain a NUL byte")
```

This is the **same function** already wired into `RegisterRequest`'s
`password` `field_validator` in `auth.py` (alongside the length/digit/max-byte
checks). Adding the NUL-byte check here means:
- The request is rejected at **Pydantic validation time**, before the handler
  body ever runs — `hash_password()` never sees a NUL byte via the register
  endpoint at all.
- The contract for `password` is now consistent with how `EmailStr` already
  behaves for `email`: a clean, honest 422 with a specific message, never a
  500 from a downstream library exception.
- §13.1 compliance: this is **not** a new per-endpoint check bolted onto the
  router — it is one line added to the single existing shared policy function
  that already backs the one endpoint (`register`) that sets a password. No
  scattering.

### 3b. Defense-in-depth seam — `app/security.py::hash_password`

```python
if "\x00" in password:
    raise ValueError("password must not contain a NUL byte")
```

`hash_password()` is a shared library function with callers **outside** the
`RegisterRequest` validation boundary (the seed script, and any future
caller). Per the task's explicit alternative framing ("inside `hash_password()`
itself so EVERY caller is protected") and the codebase's own established
precedent — `verify_password()` already carries an analogous defense-in-depth
guard for the >72-byte case, justified in its docstring exactly this way —
this closes the same class of gap for `hash_password()`, at the same single
function-level seam, not scattered per-caller. Without it, any caller that
bypasses `RegisterRequest` would still hit a bare, undocumented
`passlib.exc.PasswordValueError`; with it, they get one clear, intentional
`ValueError` instead.

This raise can never fire via the register endpoint in production (§3a
already filters it upstream) — it is pure defense-in-depth, verified directly
by a unit test that calls `hash_password()` itself (bypassing the HTTP layer)
rather than relying on the router to exercise it.

### 3c. No change needed — `app/security.py::verify_password` (login)

Investigated and confirmed **already safe** before this fix:

```python
try:
    return _pwd_context.verify(password, password_hash)
except ValueError:
    return False
```

`passlib.exc.PasswordValueError` (raised for a NUL byte at *verify* time too)
IS a `ValueError` subclass — Python confirms this directly:

```
>>> passlib.exc.PasswordValueError.__mro__
(<class 'passlib.exc.PasswordValueError'>, <class 'ValueError'>, <class 'Exception'>, <class 'BaseException'>, <class 'object'>)
```

So a NUL byte in a *login* password candidate was already caught by the
existing `except ValueError: return False` and treated as an ordinary wrong
password (401), never a 500. Only added a documentation comment plus explicit
regression tests (`TestLoginNulBytePassword`,
`test_verify_password_returns_false_for_a_nul_byte_candidate`) pinning this
behaviour, so a future narrowing of that `except` clause (e.g. someone
"tightening" it to catch a more specific exception type) cannot silently
reintroduce a 500 on the login path without failing a test.

## 4. Positive tests — legitimate passwords still work

`TestLegitimatePasswordsStillWork::test_register_then_login_round_trip` in
`apps/api/tests/test_gm2_s15_signup_nul_byte_500.py` proves a full
register→login round trip for every case, guarding explicitly against the
over-broad-guard failure mode this campaign already shipped once (refusing
real people's surnames):

| label | password | result |
|---|---|---|
| unicode-accents | `Pässwörd123` | PASS |
| unicode-cjk | `密码Test123` | PASS |
| emoji | `Rocket🚀Pass1` | PASS |
| spaces | `correct horse battery 9` | PASS |
| max-length-72-bytes | `A1` + 68×`x` (70 ASCII bytes) | PASS |
| punctuation | `P@ss!w0rd#123$` | PASS |
| apostrophe-surname-shaped | `O'Brien2024` | PASS |

All 7 registered and logged in successfully (verbatim pytest output below).

## 5. Verbatim before/after

### Before (RED) — proved failing prior to any fix

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_signup_nul_byte_500.py -v"
...
app/routers/auth.py:98: in register
    body.email, hash_password(body.password), name=body.name
app/security.py:37: in hash_password
    return _pwd_context.hash(password)
...
passlib/handlers/bcrypt.py:516: PasswordValueError
E           passlib.exc.PasswordValueError: bcrypt does not allow NULL bytes in password
=========================== short test summary info ============================
FAILED tests/test_gm2_s15_signup_nul_byte_500.py::TestRegisterNulBytePassword::test_nul_byte_in_password_is_422_not_500
FAILED tests/test_gm2_s15_signup_nul_byte_500.py::TestRegisterNulBytePassword::test_no_user_row_is_created_for_a_rejected_nul_byte_password
================== 2 failed, 12 passed, 6 warnings in 11.85s ===================
```

(The other 12 collected tests already passed before the fix — including the
login-path and `verify_password`-unit tests, confirming §3c's "already safe"
finding independently of the fix below.)

### After (GREEN)

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_signup_nul_byte_500.py -v"
...
tests/test_gm2_s15_signup_nul_byte_500.py::TestRegisterNulBytePassword::test_nul_byte_in_password_is_422_not_500 PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestRegisterNulBytePassword::test_nul_byte_only_password_is_422_not_500 PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestRegisterNulBytePassword::test_no_user_row_is_created_for_a_rejected_nul_byte_password PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLoginNulBytePassword::test_login_with_nul_byte_password_is_401_not_500 PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLoginNulBytePassword::test_login_unknown_identifier_with_nul_byte_password_is_401_not_500 PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestHashPasswordDefenseInDepth::test_hash_password_raises_a_clean_value_error_not_a_bare_bcrypt_crash PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestHashPasswordDefenseInDepth::test_verify_password_returns_false_for_a_nul_byte_candidate PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[unicode-accents-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[unicode-cjk-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[emoji-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[spaces-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[max-length-72-bytes-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[punctuation-...] PASSED
tests/test_gm2_s15_signup_nul_byte_500.py::TestLegitimatePasswordsStillWork::test_register_then_login_round_trip[apostrophe-surname-shaped-...] PASSED
======================= 14 passed, 6 warnings in 10.74s ========================
```

### Direct HTTP evidence — response body, no traceback leak

```
STATUS 422
BODY {"detail":[{"type":"value_error","loc":["body","password"],"msg":"Value error, password must not contain a NUL byte","input":"Pass word1","ctx":{"error":{}}}]}
```

### Required regression suites — all green together, one invocation

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gm2_s15_signup_nul_byte_500.py tests/test_auth.py tests/test_blocker001_admin_overpermission.py tests/test_blocker001_restart_safety.py tests/test_gm2_s15_placeholder_name_false_positives.py -v"
...
================== 85 passed, 6 warnings in 68.61s (0:01:08) ===================
```

Also re-ran the sibling `MV-signup-001` bcrypt-72-byte suite (same
`validate_password_policy`/`hash_password`/`verify_password` functions
touched) for extra safety, not in the mandated list but directly adjacent to
the diff:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_mv_signup_001_bcrypt.py -v"
...
======================== 8 passed, 6 warnings in 3.67s =========================
```

All claims above are
[VERIFIED-WITH-FRESH-EVIDENCE — command output captured 2026-07-31T15:06–15:20Z,
this document].

## 6. Files changed

- `apps/api/app/repositories/user.py` — `validate_password_policy`: +1 check
  (NUL byte), +comment.
- `apps/api/app/security.py` — `hash_password`: +1 check (NUL byte) +
  docstring-style comment; `verify_password`: comment only (no behaviour
  change — already safe).
- `apps/api/tests/test_gm2_s15_signup_nul_byte_500.py` — new test file (14
  tests: 3 register-NUL, 2 login-NUL, 2 unit-level `hash_password`/
  `verify_password`, 7 legitimate-password round trips).

No DB schema change. No scope creep — no other endpoint, guard, or behaviour
touched.
