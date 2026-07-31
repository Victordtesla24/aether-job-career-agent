# BLOCKER-001: Authentication Defect Code Map

**Defect:** POST /api/auth/login {"email":"admin","password":"admin123"} → 200; GET /api/auth/me → isAdmin:true; GET /api/admin/users → 200 returning 7 user rows including PII.

**Verification Date:** 2026-07-31T00:05Z (production)

---

## 1. POST /auth/login Handler — Identifier Resolution

**File:** `apps/api/app/routers/auth.py` [VERIFIED]

### Login endpoint (lines 108-139)
- **Route:** `/login` POST [VERIFIED-line-108]
- **Request model:** `LoginRequest` [VERIFIED-line-53]
  - Field `email: str` (plain str, NOT EmailStr, so "admin" is valid) [VERIFIED-line-57]
  - Field `password: str` [VERIFIED-line-58]
  - **Comment:** "Identifier — an email OR a username" [VERIFIED-line-54]

### Identifier resolution (line 118)
```python
user = UserRepository().get_by_username_or_email(body.email)
```
[VERIFIED-line-118]

### UserRepository.get_by_username_or_email() (lines 114-134 in `apps/api/app/repositories/user.py`)

**SQL Query (lines 127-132):**
```sql
SELECT {_USER_COLUMNS} FROM "User"
WHERE "email" = %s OR lower("username") = lower(%s)
ORDER BY ("email" = %s) DESC LIMIT 1
```
[VERIFIED-lines-127-132]

**Behavior [VERIFIED]:**
- Exact email match, OR case-insensitive username match
- If BOTH match (one user's email, another's username), exact email WINS (ORDER BY DESC)
- Returns first matching row or None

**How "admin" identifier resolves [VERIFIED]:**
1. Looks for `email = 'admin'` → no match (seed account is `admin@aether.local`)
2. Looks for `lower(username) = lower('admin')` → MATCHES if any User row has `username='admin'` or `username='Admin'` etc.
3. The seed account is created with `username='admin'` at line 121 in `apps/api/scripts/seed_demo.py` [VERIFIED-line-121]
4. If seed account is NOT demoted properly, `get_by_username_or_email('admin')` returns the seed User row

---

## 2. Password Verification

**File:** `apps/api/app/security.py` [VERIFIED]

### Password verification (lines 40-52)
```python
def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        return False
```
[VERIFIED-lines-40-52]

**Key facts [VERIFIED]:**
- Uses `passlib.context.CryptContext` with scheme `'bcrypt'` (line 25) [VERIFIED-line-25]
- Calls `_pwd_context.verify(password, password_hash)` — standard bcrypt verification [VERIFIED-line-49]
- **NO special handling for AETHER_ADMIN_PASSWORD_HASH or environment-based fallback** [VERIFIED]

### Where AETHER_ADMIN_PASSWORD_HASH is used [VERIFIED]

**File:** `apps/api/app/repositories/admin.py`

**`apply_admin_rotation()` function (lines 714-842)** [VERIFIED]

The `AETHER_ADMIN_PASSWORD_HASH` env var is:
- Read at line 751: `pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()` [VERIFIED-line-751]
- Validated at line 755: `_guard_admin_credential_strength(email, pw_hash)` (checks if known-weak) [VERIFIED-line-755]
- **Inserted into User row** at line 824 in an `ON CONFLICT DO UPDATE` statement [VERIFIED-line-824]
  ```python
  INSERT INTO "User" (...,"passwordHash",...)
  VALUES (...,%s,...)
  ON CONFLICT ("email") DO UPDATE SET
  "passwordHash"=EXCLUDED."passwordHash",...
  ```
  [VERIFIED-lines-819-823]

**CRITICAL:** The rotation does NOT replace User.passwordHash via login verification — it writes the hash DIRECTLY to the DB during app startup.

---

## 3. isAdmin Resolution

**File:** `apps/api/app/middleware/auth.py` [VERIFIED]

### Token verification (lines 33-55)
```python
def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict[str, Any]:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR from None
    
    user_id = payload.get("userId") or payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_ERROR
    
    user = UserRepository().get_auth_context(user_id)  # ← LIVE DB READ
    if user is None:
        raise _CREDENTIALS_ERROR
    if user.get("suspended"):
        raise _SUSPENDED_ERROR
    user["isAdmin"] = bool(user.get("isAdmin"))
    return user
```
[VERIFIED-lines-33-55]

### isAdmin determination (line 54)
```python
user["isAdmin"] = bool(user.get("isAdmin"))
```
[VERIFIED-line-54]

**Key fact:** `isAdmin` is read from the User table row, NOT from a JWT claim [VERIFIED]

### get_auth_context() method (lines 81-98 in `apps/api/app/repositories/user.py`)
```python
def get_auth_context(self, user_id: str) -> dict[str, Any] | None:
    ensure_admin_user_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_USER_COLUMNS}, "isAdmin", "suspended" '
                'FROM "User" WHERE "id" = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None
```
[VERIFIED-lines-81-98]

**Behavior [VERIFIED]:**
- On EVERY authenticated request, the middleware calls `get_auth_context(user_id)`
- This triggers a LIVE database read of the User row
- The `isAdmin` column value is retrieved fresh from the DB
- **isAdmin is NOT cached in the JWT or any token — it is always live**

### JWT structure (lines 55-65 in `apps/api/app/security.py`)
```python
def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "userId": user_id,
        "email": email,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)
```
[VERIFIED-lines-55-65]

**Observed:** JWT contains only `sub`, `userId`, `email`, `iat`, `exp` — NO `isAdmin` claim [VERIFIED]

### Token TTL (lines 11-12 in `apps/api/app/security.py`)
```python
TOKEN_TTL = timedelta(hours=24)
JWT_ALGORITHM = "HS256"
```
[VERIFIED-lines-11-12]

**Token TTL:** 24 hours [VERIFIED]

---

## 4. AETHER_CRON_EMAIL / AETHER_CRON_PASSWORD Consumers

**File:** `scripts/discovery_cron.sh` [VERIFIED]

### Discovery cron script (lines 1-118)

**Email resolution (line 30):**
```bash
EMAIL="${AETHER_CRON_EMAIL:-sarkar.vikram@gmail.com}"
```
[VERIFIED-line-30]

**Password resolution (line 49):**
```bash
PASSWORD="${AETHER_CRON_PASSWORD:-${LOGIN_PASSWORD:-}}"
```
[VERIFIED-line-49]

**Login call (lines 85-86):**
```bash
LOGIN_RESP=$(http_call POST "$API/auth/login" \
  "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
```
[VERIFIED-lines-85-86]

**Bearer token use (line 90):**
```bash
ME=$(http_call GET "$API/auth/me" "" -H "Authorization: Bearer $TOKEN")
```
[VERIFIED-line-90]

**Subsequent agent calls (lines 110-117):**
- POST /agents/scout/run — uses Bearer token [VERIFIED-line-110]
- POST /agents/fit-scorer/run — uses Bearer token [VERIFIED-line-115]

### What breaks if credential stops granting admin [VERIFIED]:

1. **Scout run (line 110):** Calls POST `/agents/scout/run` with the Bearer token
   - If the account is NOT admin (but user exists), the call succeeds — scout is NOT admin-gated
   - Scout has NO admin dependency [VERIFIED]

2. **Fit-scorer run (line 115):** Calls POST `/agents/fit-scorer/run` with the Bearer token
   - Fit-scorer is NOT admin-gated [VERIFIED]

3. **The cron does NOT call any /admin/* endpoints** [VERIFIED]

**Conclusion:** The discovery cron's functionality does NOT depend on the login being admin. It only needs a valid user account with saved `targetRole`/`location`. However, if the account is deleted or suspended, it will fail.

### Systemd unit configuration [VERIFIED]

**Referenced in documentation:**
- `docs/delivery/DEPLOYMENT-RUNBOOK.md` mentions `aether-discovery.service` and `aether-discovery.timer` [VERIFIED]
- Script is invoked from systemd's `ExecStart=` with `.env` loaded [VERIFIED-discovery_cron.sh-lines-19-27]
- Environment variables like `AETHER_CRON_EMAIL` / `AETHER_CRON_PASSWORD` come from:
  1. Repo-root `.env` file (loaded by script) [VERIFIED-line-19]
  2. Systemd unit Environment= (would override .env) [VERIFIED-line-18-comment]

---

## 5. Rate Limiting / Throttling / Lockout on POST /auth/login

**File:** `apps/api/app/rate_limit.py` [VERIFIED]

### Rate limiter configuration (lines 42-48)
```python
#: Login: at most 5 FAILED attempts per identifier per 15-minute window.
DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_LOGIN_WINDOW_SECONDS = 15 * 60.0

#: Register: at most 3 attempts per email per 1-hour window.
DEFAULT_REGISTER_MAX = 3
DEFAULT_REGISTER_WINDOW_SECONDS = 60 * 60.0
```
[VERIFIED-lines-42-48]

### Login rate limiter (lines 212-229)
```python
def guard_login_attempt(request: Request, identifier: str) -> None:
    """429 when this identifier has already hit its failed-login cap."""
    limiter: SlidingWindowRateLimiter | None = getattr(
        request.app.state, "login_rate_limiter", None
    )
    if limiter is None:
        return
    key = normalize_identifier(identifier)
    if limiter.is_blocked(key):
        _raise_429(
            limiter.retry_after(key),
            "Too many failed login attempts for this account. "
            "Please wait and try again.",
        )
```
[VERIFIED-lines-212-229]

### In login endpoint (lines 117-131 in `apps/api/app/routers/auth.py`)
```python
guard_login_attempt(request, body.email)
user = UserRepository().get_by_username_or_email(body.email)
if (
    user is None
    or not user.get("passwordHash")
    or not verify_password(body.password, user["passwordHash"])
):
    record_login_failure(request, body.email)
    raise HTTPException(status_code=401, detail="Invalid email or password")
reset_login_failures(request, body.email)
```
[VERIFIED-lines-117-131]

### Rate limiter design (lines 1-31)
- Keyed on **normalized submitted identifier** (email or username), NOT client IP [VERIFIED-lines-6-7]
- Counts only FAILED attempts [VERIFIED-line-24-comment]
- Successful login resets the counter [VERIFIED-lines-131 + comment-24]
- Default: 5 failures per 15 minutes per identifier [VERIFIED-line-43]
- Configurable via `AUTH_LOGIN_MAX_FAILURES` / `AUTH_LOGIN_WINDOW_SECONDS` [VERIFIED-lines-175-184]

**Present and active:** YES [VERIFIED]

---

## 6. AdminUser Dependency — Endpoints and Non-Admin Behavior

**File:** `apps/api/app/middleware/auth.py` [VERIFIED]

### AdminUser dependency (lines 61-70)
```python
def get_admin_user(current_user: CurrentUser) -> dict[str, Any]:
    """Admin-only dependency: 403 for any non-admin."""
    if not current_user.get("isAdmin"):
        raise _ADMIN_ERROR
    return current_user

AdminUser = Annotated[dict[str, Any], Depends(get_admin_user)]
```
[VERIFIED-lines-61-70]

### Endpoints using AdminUser (from `apps/api/app/routers/admin.py`)

| Route | Method | Handler | AdminUser? | Lines |
|-------|--------|---------|-----------|-------|
| `/health` | GET | `admin_health()` | YES | [VERIFIED-line-42] |
| `/users` | GET | `admin_list_users()` | YES | [VERIFIED-line-49] |
| `/users/{user_id}` | GET | `admin_user_detail()` | YES | [VERIFIED-line-62] |
| `/users/{user_id}/spend-cap` | POST | `admin_set_spend_cap()` | YES | [VERIFIED-line-113] |
| `/users/{user_id}/suspend` | POST | `admin_suspend_user()` | YES | [VERIFIED-line-128] |
| `/users/{user_id}/unsuspend` | POST | `admin_unsuspend_user()` | YES | [VERIFIED-line-138] |
| `/spend` | GET | `admin_spend()` | YES | [VERIFIED-line-157] |
| `/settings` | GET | `admin_get_settings()` | YES | [VERIFIED-line-162] |
| `/settings` | POST | `admin_update_settings()` | YES | [VERIFIED-line-166] |

[VERIFIED in apps/api/app/routers/admin.py lines 1-180]

### Non-admin behavior [VERIFIED]
- Any route with `AdminUser` dependency returns 403 Forbidden if `current_user.get("isAdmin")` is False
- Auth (401) is enforced by the `get_current_user` chain FIRST, so an anonymous caller never sees 403
- **All /admin/* routes are gated.** No public admin endpoints exist. [VERIFIED]

---

## 7. Startup Guard Pattern — Production Replay Mode

**File:** `apps/api/app/main.py` [VERIFIED]

### _guard_production_replay_mode (lines 93-118)
```python
def _guard_production_replay_mode() -> None:
    """Fail fast if a production deploy would silently serve LLM fixtures.
    
    AETHER_LLM_MODE defaults to replay, which is correct for local
    dev/tests but must never reach production.
    Non-production replay mode only prints a warning.
    """
    mode = get_mode()
    env = os.environ.get("AETHER_ENV", "development").strip().lower()
    if mode != "replay":
        return
    if env == "production":
        raise RuntimeError(
            "§REC-04: AETHER_LLM_MODE=replay is not permitted when "
            "AETHER_ENV=production — this would silently serve canned LLM "
            "fixtures instead of real model output. Set AETHER_LLM_MODE to "
            "'auto', 'live', or 'record' for production deploys."
        )
    print(
        "WARNING: AETHER_LLM_MODE=replay — serving canned LLM fixtures, not "
        "live model output. This is expected in development/tests only; it "
        "must never be used in production (§REC-04).",
        file=sys.stderr,
    )
```
[VERIFIED-lines-93-118]

### _guard_production_discovery_fixtures (lines 121-154)
```python
def _guard_production_discovery_fixtures() -> None:
    """Fail fast if a production deploy would serve discovery fixtures."""
    fixture_dir = os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR", "").strip()
    if not fixture_dir:
        return
    env = os.environ.get("AETHER_ENV", "development").strip().lower()
    if env == "production":
        raise RuntimeError(
            "§REC-05: AETHER_DISCOVERY_FIXTURE_DIR is set while "
            "AETHER_ENV=production — this would silently serve canned job "
            "discovery fixtures instead of live job-board data. Unset "
            "AETHER_DISCOVERY_FIXTURE_DIR for production deploys."
        )
    print(..., file=sys.stderr)
```
[VERIFIED-lines-121-154]

### _lifespan context manager (lines 157-197)
```python
@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply §14.7 admin-credential rotation on app load."""
    from app.repositories.admin import (
        AdminCredentialSecurityError,
        AdminRotationConfigError,
        apply_admin_rotation,
    )
    
    try:
        apply_admin_rotation()
    except (AdminCredentialSecurityError, AdminRotationConfigError):
        # Never swallow: booting anyway means serving behind an admin login
        # that is known to be compromised or self-cancelling.
        print(
            "FATAL: §14.7 admin credential rotation refused the configured "
            "operator admin — refusing to start. See the error below.",
            file=sys.stderr,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — infra hiccups must not break boot
        print(
            f"WARNING: §14.7 admin credential rotation skipped at startup: {exc}",
            file=sys.stderr,
        )
    yield
```
[VERIFIED-lines-157-197]

### Guard pattern shape [VERIFIED]
1. **Check condition** (e.g., `AETHER_LLM_MODE == 'replay'`)
2. **If production (`AETHER_ENV == 'production'):**
   - RAISE RuntimeError (app startup FAILS)
3. **Else (non-production):**
   - Print WARNING to stderr, continue
4. **Production security errors ABORT boot.** Infra errors degrade gracefully.

### _is_production() function (lines 113-119 in `apps/api/app/repositories/admin.py`)
```python
def _is_production() -> bool:
    """Whether this process is running as production (AETHER_ENV)."""
    return os.environ.get("AETHER_ENV", "development").strip().lower() == "production"
```
[VERIFIED-lines-113-119]

**Mirrors `main.py` identical logic** [VERIFIED]

---

## 8. Seed/Demo Account Creation Path

**File:** `apps/api/scripts/seed_demo.py` [VERIFIED]

### Seeded admin account (lines 57-60)
```python
# Admin account seeded for the platform owner (login-by-username feature).
ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@aether.local"
ADMIN_NAME = "Administrator"
```
[VERIFIED-lines-57-60]

### seed_admin_user() function (lines 93-136)
```python
def seed_admin_user() -> str:
    """Idempotently upsert the ``admin`` user; return its id."""
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "User"'
                ' WHERE lower("username") = %s OR "email" = %s',
                (ADMIN_USERNAME, ADMIN_EMAIL),
            )
            existing = cur.fetchone()
            if existing:
                return existing[0]
            admin_id = new_id()
            cur.execute(
                'INSERT INTO "User"'
                ' ("id", "email", "username", "name", "passwordHash", "updatedAt")'
                ' VALUES (%s, %s, %s, %s, %s, NOW())'
                ' ON CONFLICT ("email") DO NOTHING RETURNING "id"',
                (
                    admin_id,
                    ADMIN_EMAIL,
                    ADMIN_USERNAME,
                    ADMIN_NAME,
                    hash_password(_admin_password()),
                ),
            )
            inserted = cur.fetchone()
        conn.commit()
    if inserted:
        print(f"seeded admin user {ADMIN_EMAIL} (username={ADMIN_USERNAME})")
        return inserted[0]
    # A concurrent seeder won the email conflict; return the existing row.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" WHERE "email" = %s', (ADMIN_EMAIL,))
            row = cur.fetchone()
    return row[0] if row else admin_id
```
[VERIFIED-lines-93-136]

### Password resolution (lines 63-90)
```python
def _admin_password() -> str:
    """Resolve the admin seed password from ADMIN_PASSWORD — no default."""
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not password:
        raise SystemExit(
            "ADMIN_PASSWORD must be set (as an env var, or in the repo-root "
            ".env) to seed the admin user's password. Refusing to fall back to "
            "a hardcoded default credential (BLOCKER-001)."
        )
    if _weak_password_matching(hash_password(password)) is not None:
        raise SystemExit(
            "ADMIN_PASSWORD is on the known-weak denylist "
            "(app.repositories.admin._KNOWN_WEAK_ADMIN_PASSWORDS). Refusing to "
            "seed an admin account with a guessable password (BLOCKER-001). "
            "Choose a strong, unique password."
        )
    return password
```
[VERIFIED-lines-63-90]

### seed_admin_user() is called in main() (line 171)
```python
if __name__ == "__main__":
    main()
    ...
    seed_admin_user()
```
[VERIFIED-line-171]

### Seed account is SEPARATE from apply_admin_rotation() [VERIFIED]
- `seed_demo.py::seed_admin_user()` creates `admin@aether.local` with `username='admin'` and the hashed password
- This script is run ONCE at setup time (not on every app load)
- `apply_admin_rotation()` runs on EVERY app startup and **demotes the seed account** to `isAdmin=false` [VERIFIED-admin.py-lines-795-799]

---

## 9. §14.7 Admin Credential Rotation — Seed Account Demotion

**File:** `apps/api/app/repositories/admin.py` [VERIFIED]

### apply_admin_rotation() function (lines 714-842)

**Step 1: Reclaim reserved demo username (lines 774-788)**
```python
cur.execute(
    'UPDATE "User" SET "username"=NULL,"updatedAt"=now() '
    'WHERE lower("username")=%s AND lower("email")<>%s '
    'RETURNING "id"',
    (_SEED_ADMIN_USERNAME, _SEED_ADMIN_EMAIL),
)
reclaimed = [row[0] for row in cur.fetchall()]
```
[VERIFIED-lines-781-788]

**Purpose:** Clear `username='admin'` from ANY account that is NOT the seed email [VERIFIED]

**Step 2: Demote the seeded demo account (lines 790-801)**
```python
cur.execute(
    'UPDATE "User" SET "isAdmin"=false,"updatedAt"=now() '
    'WHERE lower("email")=%s RETURNING "id"',
    (_SEED_ADMIN_EMAIL,),
)
demoted_ids = [row[0] for row in cur.fetchall()]
```
[VERIFIED-lines-795-801]

**Purpose:** Set `isAdmin=false` on the `admin@aether.local` account [VERIFIED]

**Step 3: Grant configured operator admin (lines 814-827)**
```python
if email and pw_hash:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","isAdmin",'
                '"suspended","updatedAt") VALUES (%s,%s,%s,true,false,now()) '
                'ON CONFLICT ("email") DO UPDATE SET '
                '"passwordHash"=EXCLUDED."passwordHash","isAdmin"=true,'
                '"suspended"=false,"updatedAt"=now() RETURNING "id"',
                (new_id(), email, pw_hash),
            )
            admin_id = cur.fetchone()[0]
        conn.commit()
```
[VERIFIED-lines-815-827]

**Purpose:** If `AETHER_ADMIN_EMAIL` and `AETHER_ADMIN_PASSWORD_HASH` are set, create/update that user with `isAdmin=true` [VERIFIED]

### Known-weak password audit (lines 122-141)
```python
def _weak_password_matching(pw_hash: str) -> Optional[str]:
    """The known-weak password pw_hash verifies, or None if it is safe."""
    if pw_hash in _WEAK_HASH_AUDIT_CACHE:
        return _WEAK_HASH_AUDIT_CACHE[pw_hash]
    match: Optional[str] = None
    for candidate in _KNOWN_WEAK_ADMIN_PASSWORDS:
        if verify_password(candidate, pw_hash):
            match = candidate
            break
    if len(_WEAK_HASH_AUDIT_CACHE) >= _WEAK_HASH_AUDIT_CACHE_MAX:
        _WEAK_HASH_AUDIT_CACHE.clear()
    _WEAK_HASH_AUDIT_CACHE[pw_hash] = match
    return match
```
[VERIFIED-lines-122-141]

### Known-weak password list (lines 55-70)
```python
_KNOWN_WEAK_ADMIN_PASSWORDS: tuple[str, ...] = (
    "admin123",      # ← THE EXACT WEAK PASSWORD FOUND ON PRODUCTION
    "admin",
    "password",
    "changeme",
    "admin1234",
    "administrator",
    "password123",
    "letmein",
    "123456",
    "12345678",
    "qwerty",
    "secret",
    "aether",
    "aether123",
)
```
[VERIFIED-lines-55-70]

### Guard function (lines 143-191)
```python
def _guard_admin_credential_strength(email: str, pw_hash: str) -> None:
    """Fail fast if the configured operator admin uses a known-weak password."""
    if not pw_hash.startswith(_BCRYPT_PREFIXES):
        message = "BLOCKER-001: AETHER_ADMIN_PASSWORD_HASH is not a bcrypt hash..."
        if _is_production():
            raise AdminCredentialSecurityError(message)
        print(f"WARNING: {message}", file=sys.stderr)
        return
    
    weak = _weak_password_matching(pw_hash)
    if weak is None:
        return
    message = (
        "BLOCKER-001: refusing to grant admin privilege to "
        f"{email!r} — its AETHER_ADMIN_PASSWORD_HASH verifies the known-weak "
        f"password {weak!r}. An admin account can read every user's email "
        "address, change spend caps and issue real refunds; a guessable "
        "password on it is a full compromise of the platform. Rotate "
        "AETHER_ADMIN_PASSWORD_HASH to a bcrypt hash of a strong, unique "
        "password and restart."
    )
    if _is_production():
        raise AdminCredentialSecurityError(message)
    print(
        f"WARNING: {message} (AETHER_ENV is not 'production', so rotation "
        "continues — this WOULD abort a production boot.)",
        file=sys.stderr,
    )
```
[VERIFIED-lines-143-191]

---

## Summary Table: Code Path Claims

| # | Claim | File:Line | Verification |
|---|-------|-----------|--------------|
| 1.1 | POST /login endpoint exists | auth.py:108 | [VERIFIED] |
| 1.2 | LoginRequest.email is plain str (not EmailStr) | auth.py:57 | [VERIFIED] |
| 1.3 | Identifier resolved via get_by_username_or_email() | auth.py:118 | [VERIFIED] |
| 1.4 | Query: email OR lowercase username match | user.py:129 | [VERIFIED] |
| 1.5 | Email match wins if both exist | user.py:130 | [VERIFIED] |
| 1.6 | Seed account created with username='admin' | seed_demo.py:121 | [VERIFIED] |
| 2.1 | verify_password() uses bcrypt _pwd_context | security.py:49 | [VERIFIED] |
| 2.2 | NO special admin password handling in login | security.py:40-52 | [VERIFIED] |
| 2.3 | AETHER_ADMIN_PASSWORD_HASH written to DB at startup | admin.py:824 | [VERIFIED] |
| 2.4 | apply_admin_rotation() runs in _lifespan on every boot | main.py:182 | [VERIFIED] |
| 3.1 | isAdmin is read from User table, NOT JWT claim | middleware/auth.py:54 | [VERIFIED] |
| 3.2 | get_auth_context() does live DB read | user.py:94 | [VERIFIED] |
| 3.3 | isAdmin retrieved fresh on every authenticated request | middleware/auth.py:49 | [VERIFIED] |
| 3.4 | Token TTL is 24 hours | security.py:12 | [VERIFIED] |
| 3.5 | JWT has no isAdmin claim | security.py:55-65 | [VERIFIED] |
| 4.1 | Discovery cron reads AETHER_CRON_EMAIL | discovery_cron.sh:30 | [VERIFIED] |
| 4.2 | Discovery cron reads AETHER_CRON_PASSWORD | discovery_cron.sh:49 | [VERIFIED] |
| 4.3 | Cron calls POST /auth/login | discovery_cron.sh:85 | [VERIFIED] |
| 4.4 | Cron calls scout/fit-scorer with token | discovery_cron.sh:110,115 | [VERIFIED] |
| 4.5 | Cron does NOT call /admin/* endpoints | discovery_cron.sh:85-117 | [VERIFIED] |
| 4.6 | Cron .env loaded fresh on every run | discovery_cron.sh:19-27 | [VERIFIED] |
| 5.1 | Rate limiter present on login | rate_limit.py:212-229 | [VERIFIED] |
| 5.2 | Keyed on normalized identifier, not IP | rate_limit.py:223 | [VERIFIED] |
| 5.3 | Counts only FAILED attempts | rate_limit.py:24-comment | [VERIFIED] |
| 5.4 | Default: 5 failures / 15 min per identifier | rate_limit.py:43 | [VERIFIED] |
| 5.5 | Successful login resets counter | auth.py:131 | [VERIFIED] |
| 6.1 | AdminUser dependency gates all /admin/* routes | middleware/auth.py:61-70 | [VERIFIED] |
| 6.2 | Non-admin gets 403 Forbidden | middleware/auth.py:65 | [VERIFIED] |
| 6.3 | GET /admin/users requires AdminUser | admin.py:49 | [VERIFIED] |
| 6.4 | GET /admin/health requires AdminUser | admin.py:42 | [VERIFIED] |
| 7.1 | _guard_production_replay_mode exists | main.py:93-118 | [VERIFIED] |
| 7.2 | Production raises, non-production warns | main.py:106-118 | [VERIFIED] |
| 7.3 | _guard_production_discovery_fixtures exists | main.py:121-154 | [VERIFIED] |
| 7.4 | apply_admin_rotation calls guarded | main.py:182-191 | [VERIFIED] |
| 7.5 | Security errors abort boot, infra errors degrade | main.py:183-196 | [VERIFIED] |
| 8.1 | ADMIN_USERNAME = "admin" | seed_demo.py:58 | [VERIFIED] |
| 8.2 | ADMIN_EMAIL = "admin@aether.local" | seed_demo.py:59 | [VERIFIED] |
| 8.3 | seed_admin_user() creates account with username/email | seed_demo.py:113-125 | [VERIFIED] |
| 8.4 | seed_admin_user() is idempotent | seed_demo.py:94 | [VERIFIED] |
| 8.5 | _admin_password() reads ADMIN_PASSWORD env | seed_demo.py:76 | [VERIFIED] |
| 8.6 | _admin_password() refuses weak passwords | seed_demo.py:83-89 | [VERIFIED] |
| 9.1 | Step 1: reclaim username='admin' from non-seed | admin.py:781-788 | [VERIFIED] |
| 9.2 | Step 2: demote seed account to isAdmin=false | admin.py:795-801 | [VERIFIED] |
| 9.3 | Step 3: grant env-configured admin if set | admin.py:815-827 | [VERIFIED] |
| 9.4 | Known-weak list includes "admin123" | admin.py:56 | [VERIFIED] |
| 9.5 | Guard raises in production for weak hash | admin.py:185-186 | [VERIFIED] |

---

## Compact JSON Summary

```json
{
  "defect": "POST /api/auth/login {email:admin, password:admin123} succeeds; GET /api/auth/me returns isAdmin:true; GET /api/admin/users returns 7 users with PII",
  "verified_date": "2026-07-31T00:05Z",
  "questions_answered": {
    "1_login_identifier_resolution": {
      "handler_file": "apps/api/app/routers/auth.py:108-139",
      "lookup_method": "UserRepository.get_by_username_or_email()",
      "lookup_file": "apps/api/app/repositories/user.py:114-134",
      "sql_logic": "WHERE email=%s OR lower(username)=lower(%s), ORDER BY exact_email DESC",
      "how_admin_resolves": "username='admin' matches seed account (seed_demo.py:121)",
      "no_alias": "No special case for literal 'admin' — treated as any username"
    },
    "2_password_verification": {
      "function": "verify_password()",
      "file": "apps/api/app/security.py:40-52",
      "library": "passlib.context.CryptContext scheme=bcrypt",
      "aether_admin_password_hash_location": "apps/api/app/repositories/admin.py:751 (read), 824 (written to DB)",
      "written_where": "User.passwordHash column via apply_admin_rotation step 3",
      "written_when": "Every app startup in _lifespan context manager",
      "no_special_login_handling": "Login always uses User.passwordHash from DB, never env var directly",
      "applies_to_seed_account": "Seed account's hash is set by seed_demo.py, then immediately demoted by apply_admin_rotation step 2"
    },
    "3_isAdmin_resolution": {
      "determination_file": "apps/api/app/middleware/auth.py:49-54",
      "source": "Live database read from User table (NOT JWT claim)",
      "method": "get_auth_context(user_id) queries User.isAdmin column",
      "method_file": "apps/api/app/repositories/user.py:81-98",
      "when_read": "Every authenticated request (on GET/POST that use CurrentUser dependency)",
      "jwt_claim": "No isAdmin claim in JWT payload",
      "jwt_file": "apps/api/app/security.py:55-65",
      "token_ttl": "24 hours (TOKEN_TTL = timedelta(hours=24))",
      "ttl_file": "apps/api/app/security.py:12",
      "live_every_request": true
    },
    "4_aether_cron_credentials": {
      "email_consumer": "scripts/discovery_cron.sh:30",
      "password_consumer": "scripts/discovery_cron.sh:49",
      "login_call": "scripts/discovery_cron.sh:85-86 (POST /auth/login)",
      "agents_called": ["POST /agents/scout/run (line 110)", "POST /agents/fit-scorer/run (line 115)"],
      "bearer_token_used": true,
      "admin_endpoints_called": false,
      "what_breaks_if_not_admin": "Nothing. Cron only needs a valid user account. Scout and fit-scorer are NOT admin-gated. Discovery does NOT depend on isAdmin.",
      "systemd_reload_required": "NO (script reads .env fresh on every 30-min timer fire)",
      "why_safe": "Cron calls zero /admin/* endpoints; isAdmin status is irrelevant to scout/fit-scorer"
    },
    "5_rate_limiting": {
      "present": true,
      "location": "apps/api/app/rate_limit.py:212-229",
      "type": "Sliding window, identifier-keyed",
      "default_limit": "5 failed attempts per 15 minutes per identifier",
      "configurable": "AUTH_LOGIN_MAX_FAILURES / AUTH_LOGIN_WINDOW_SECONDS env vars",
      "keying": "Normalized submitted identifier (email or username), NOT client IP",
      "counted": "FAILED attempts only; successful login resets counter",
      "gating": "Before credential check (line 117 in auth.py, before get_by_username_or_email)",
      "response_on_block": "429 Too Many Requests with Retry-After header"
    },
    "6_adminuser_dependency": {
      "definition_file": "apps/api/app/middleware/auth.py:61-70",
      "protected_endpoints": [
        "GET /admin/health",
        "GET /admin/users",
        "GET /admin/users/{user_id}",
        "POST /admin/users/{user_id}/spend-cap",
        "POST /admin/users/{user_id}/suspend",
        "POST /admin/users/{user_id}/unsuspend",
        "GET /admin/spend",
        "GET /admin/settings",
        "POST /admin/settings"
      ],
      "non_admin_response": "403 Forbidden (after 401 auth chain runs first)",
      "admin_only_surface": "ALL /admin/* endpoints require AdminUser",
      "what_non_admin_sees": "403 on every /admin/* route (no leakage of data)"
    },
    "7_startup_guard_pattern": {
      "guard_1_file": "apps/api/app/main.py:93-118",
      "guard_1_name": "_guard_production_replay_mode()",
      "guard_1_check": "AETHER_LLM_MODE == 'replay' && AETHER_ENV == 'production'",
      "guard_1_action_prod": "raise RuntimeError (boot fails)",
      "guard_1_action_nonprod": "print WARNING, continue",
      "guard_2_file": "apps/api/app/main.py:121-154",
      "guard_2_name": "_guard_production_discovery_fixtures()",
      "guard_2_check": "AETHER_DISCOVERY_FIXTURE_DIR set && AETHER_ENV == 'production'",
      "guard_2_action_prod": "raise RuntimeError (boot fails)",
      "guard_2_action_nonprod": "print WARNING, continue",
      "admin_rotation_guard_file": "apps/api/app/main.py:182-191",
      "admin_rotation_guard_check": "apply_admin_rotation()",
      "security_errors": "AdminCredentialSecurityError, AdminRotationConfigError — RAISED, abort boot",
      "infra_errors": "Other Exceptions — WARNING logged, app continues",
      "is_production_check_file": "apps/api/app/repositories/admin.py:113-119",
      "is_production_logic": "AETHER_ENV.strip().lower() == 'production'"
    },
    "8_seed_account_creation": {
      "script": "apps/api/scripts/seed_demo.py",
      "username": "admin (line 58)",
      "email": "admin@aether.local (line 59)",
      "name": "Administrator (line 60)",
      "password_env_var": "ADMIN_PASSWORD",
      "password_resolution_file": "seed_demo.py:63-90",
      "password_policy": "Refuses known-weak passwords; refuses no default (must be set)",
      "function": "seed_admin_user() at line 93",
      "idempotency": "Checks if account exists first; reuses if found",
      "insertion_method": "ON CONFLICT (email) DO NOTHING (line 117)",
      "when_created": "Standalone script run at setup time (python scripts/seed_demo.py)",
      "when_demoted": "Every app startup by apply_admin_rotation() step 2",
      "seed_account_never_admin": "Demoted to isAdmin=false on every boot (admin.py:795-801)",
      "interaction_with_rotation": "apply_admin_rotation() is SEPARATE and LATER — seeds account is never privileged post-startup"
    }
  },
  "root_cause_chain": {
    "step_1": "Seed account created with username='admin', email='admin@aether.local' via seed_demo.py",
    "step_2": "apply_admin_rotation() step 1 reclaims username='admin' from NON-SEED accounts, leaving seed account with it",
    "step_3": "apply_admin_rotation() step 2 DEMOTES seed account to isAdmin=false (line 795-801)",
    "vulnerability": "If demotion fails to execute, or seed account was somehow re-privileged, login via username='admin' would return isAdmin=true",
    "defect_hypothesis": "One of: (a) seed account's isAdmin was manually set back to true in DB post-demotion, (b) apply_admin_rotation step 2 failed to run, (c) a NEW admin with email/username pattern made the 'admin' identifier resolve to a privileged row"
  },
  "evidence_artifacts": [
    "apps/api/app/routers/auth.py (login handler)",
    "apps/api/app/repositories/user.py (identifier resolution)",
    "apps/api/app/middleware/auth.py (isAdmin live read)",
    "apps/api/app/security.py (password verification)",
    "apps/api/app/repositories/admin.py (rotation logic, guard functions)",
    "apps/api/app/main.py (startup guards, _lifespan)",
    "apps/api/app/rate_limit.py (rate limiting)",
    "apps/api/scripts/seed_demo.py (seed account creation)",
    "scripts/discovery_cron.sh (cron authentication)"
  ]
}
```
