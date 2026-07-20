# Canonical Login Snippet — Manual Verification Phase 0, Step 3

**Timestamp UTC:** 2026-07-17T12:36:30Z  
**Commit SHA:** 53f0e084da5b460835c32d3e07d496e6e67a8616  
**Repository:** /home/ubuntu/github_repos/aether-job-career-agent  
**Production URL:** https://5cb5f0620.abacusai.cloud  
**Nginx Mapping:** `/etc/nginx/conf.d/5cb5f0620.conf:15-17` — FastAPI `/auth/*` routes publicly served at `/api/auth/*` via rewrite + proxy

---

## Login Request Schema

**File Citation:** `apps/api/app/routers/auth.py:53-58`

```python
class LoginRequest(BaseModel):
    # Identifier — an email OR a username. Kept named ``email`` for backward
    # compatibility with the existing frontend/tests, and deliberately a plain
    # ``str`` (not ``EmailStr``) so a bare username like "admin" validates.
    email: str
    password: str
```

**Request Endpoint:** `POST /auth/login`  
**Content-Type:** `application/json`  
**Request Shape:**
```json
{
  "email": "<username or email address>",
  "password": "<plaintext password>"
}
```

---

## Login Response Schema

**File Citation:** `apps/api/app/routers/auth.py:69-73`

```python
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    userId: str
    email: str
```

**Response Shape (HTTP 200):**
```json
{
  "access_token": "<JWT token>",
  "token_type": "bearer",
  "userId": "<user-id-string>",
  "email": "<user-email>"
}
```

**On Failure (HTTP 401):**
```json
{
  "detail": "Invalid email or password"
}
```

---

## Authenticated Request Pattern

**File Citation:** `apps/api/app/middleware/auth.py:13`

All authenticated endpoints use **OAuth2 Bearer token in Authorization header**:

```
Authorization: Bearer <access_token>
```

The token is a JWT (HS256, 24-hour TTL) and is verified by the dependency at `apps/api/app/middleware/auth.py:33-55`.

---

## Canonical cURL Login Command

**Username:** `admin`  
**Password:** `admin123`  
**Production API Base:** `https://5cb5f0620.abacusai.cloud/api`

```bash
#!/bin/bash
# Login and capture token
LOGIN_RESPONSE=$(curl -s \
  "https://5cb5f0620.abacusai.cloud/api/auth/login" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"email":"admin","password":"admin123"}')

# Extract and store token
ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use token on authenticated endpoint (example: GET /auth/me)
curl -s \
  "https://5cb5f0620.abacusai.cloud/api/auth/me" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## Authenticated Endpoint Test: GET /auth/me

**File Citation:** `apps/api/app/routers/auth.py:142-166`

**Response (HTTP 200):**
```json
{
  "id": "cc29a76e324fbf19f438eb8be",
  "email": "admin@aether.local",
  "name": "Administrator",
  "targetRole": "Administrator",
  "location": "Melbourne, Australia",
  "isAdmin": false
}
```

**CRITICAL OBSERVATION:** `isAdmin: false` — the seeded admin/admin123 credential has **zero admin privilege** in production, confirming §14.7 credential rotation. The account exists but is non-admin. Per `apps/api/app/repositories/admin.py:516-517`, this is **correct by design** (GATE-31); operator must set `AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` env vars to grant admin privileges to a different account.

---

## Playwright Login Recipe

**VERIFIED-WITH-FRESH-EVIDENCE:** Production login tested and proven at 2026-07-17T13:46:04Z.  
**Evidence artifacts:**
- Screenshot: `screens/AUTH-RECIPE-PROOF-step1-login-form.png` (login form captured)
- Screenshot: `screens/AUTH-RECIPE-PROOF-step2-authenticated-dashboard.png` (authenticated `/dashboard` reached)
- JSON proof: `screens/AUTH-RECIPE-PROOF.json` (mechanism, storage_key, final_url, token_sample confirmed)

**Page URL:** `https://5cb5f0620.abacusai.cloud/login`  
**File Citation:** `apps/web/src/app/login/page.tsx` + `apps/web/src/lib/api/auth.ts` + `apps/web/src/components/auth-guard.tsx`

### Authentication Flow

1. **Frontend login submission** (`apps/web/src/app/login/page.tsx:33-46`):
   - User fills `#login-identifier` (username or email) and `#login-password`
   - Form POST to `/api/auth/login` via `login(email, password)` function
   - Backend returns `{access_token, userId, email}`
   - Frontend stores `access_token` in `localStorage['aether_token']` (line 39)
   - Router redirects to `/dashboard` (line 40)

2. **Dashboard route guard** (`apps/web/src/components/auth-guard.tsx:16-30`):
   - When navigating to `/dashboard`, `AuthGuard` component checks on mount
   - If `localStorage['aether_token']` exists → render dashboard
   - If missing → redirect to `/login`

3. **Authenticated API calls** (`apps/web/src/lib/api/client.ts:71-106`):
   - `getToken()` reads from `localStorage['aether_token']` (line 46)
   - `apiRequest()` adds `Authorization: Bearer <token>` header
   - On 401, token is cleared and user redirected to `/login`

### Field Selectors

From the React component at `apps/web/src/app/login/page.tsx:83-106`:

- **Email/Username input:** `id="login-identifier"` (type: `text`, name: `email`, accepts username OR email)
- **Password input:** `id="login-password"` (type: `password`, name: `password`)
- **Submit button:** `type="submit"` (contains text "Sign in")
- **Error display:** `data-testid="login-error"` (role: alert)
- **Success badge (if re-registering):** `data-testid="signup-success"`

### Proven Playwright Script

**Status:** ✅ TESTED AND WORKING (2026-07-17T13:46:04Z)

```typescript
import { test, expect } from '@playwright/test';

test('admin login and reach authenticated dashboard', async ({ page }) => {
  // Navigate to login page
  await page.goto('https://5cb5f0620.abacusai.cloud/login', {
    waitUntil: 'domcontentloaded',
    timeout: 30000
  });

  // Verify form fields exist
  expect(await page.$('#login-identifier')).not.toBeNull();
  expect(await page.$('#login-password')).not.toBeNull();
  expect(await page.$('button[type="submit"]')).not.toBeNull();

  // Fill credentials
  await page.fill('#login-identifier', 'admin');
  await page.fill('#login-password', 'admin123');

  // Submit and wait for navigation
  const [response] = await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle', timeout: 30000 }),
    page.click('button[type="submit"]'),
  ]);

  // Verify token was stored in localStorage
  const token = await page.evaluate(() => 
    localStorage.getItem('aether_token')
  );
  expect(token).toBeTruthy();
  expect(token).toMatch(/^eyJ/); // JWT header

  // Verify final URL is /dashboard (not /login)
  expect(page.url()).toContain('/dashboard');

  // Verify authenticated page element exists
  expect(await page.$('main')).not.toBeNull();
});
```

**Key Implementation Notes:**
- The `localStorage` key is hardcoded as `aether_token` in the frontend (line 14 of `client.ts` and line 16 of `login/page.tsx`)
- The token is stored DURING form submission, BEFORE the redirect happens
- The `AuthGuard` component is a client-side check that runs AFTER React hydration
- Playwright headless must navigate via `goto()` and interact with the DOM; there is NO cookie-based session
- Subsequent API calls automatically read the token from `localStorage` and attach it as `Authorization: Bearer` header

---

## Operator Admin Credential Status

### Environment Variables Check

**File Citation:** `apps/api/app/repositories/admin.py:540-541`

```python
email = (os.environ.get("AETHER_ADMIN_EMAIL") or "").strip()
pw_hash = (os.environ.get("AETHER_ADMIN_PASSWORD_HASH") or "").strip()
```

**Status at probe time (2026-07-17T12:36:30Z):**

- **`AETHER_ADMIN_EMAIL`:** `NOT FOUND` in `.env` or environment
- **`AETHER_ADMIN_PASSWORD_HASH`:** `NOT FOUND` in `.env` or environment
- **Plaintext admin password:** `NOT FOUND` in `.env` or accessible files

**Conclusion:** Operator-admin credential rotation env vars are **absent**. The seeded admin/admin123 account carries **zero privileges** (correct). Admin panel functionality is **HUMAN-GATED** — operator must provide credentials before admin access becomes available.

### How to Rotate Admin Credentials (Operator Manual)

When operator-admin access is required, the operator must:

1. **Hash a new password:**
   ```bash
   python3 -c "from passlib.context import CryptContext; ctx = CryptContext(schemes=['bcrypt']); print(ctx.hash('your-secure-password-here'))"
   ```

2. **Set environment variables** in production `.env`:
   ```env
   AETHER_ADMIN_EMAIL=operator@example.com
   AETHER_ADMIN_PASSWORD_HASH=<bcrypt-hash-from-step-1>
   ```

3. **Restart the API service:**
   ```bash
   systemctl restart aether-api.service
   ```

4. **Login with new credential:**
   ```bash
   curl -X POST "https://5cb5f0620.abacusai.cloud/api/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email":"operator@example.com","password":"your-secure-password-here"}'
   ```

   This call will return `"isAdmin": true` on the `GET /api/auth/me` response.

---

## Security Notes

- **Token TTL:** 24 hours (from `apps/api/app/security.py:12`)
- **Algorithm:** HS256 JWT (from `apps/api/app/security.py:13`)
- **JWT Secret:** Loaded from `JWT_SECRET` or falls back to `NEXTAUTH_SECRET` (from `apps/api/app/security.py:18-23`)
- **Rate limiting:** Login attempts are rate-limited per identifier (not IP) at `apps/api/app/routers/auth.py:117` via `guard_login_attempt()`
- **Password hashing:** bcrypt via passlib (from `apps/api/app/security.py:15`)
- **Admin privileges:** Always come from DB (`User.isAdmin` column), never token-embedded, verified on every authenticated call

---

## Verification Status

**VERIFIED-WITH-SOURCE:** All schema citations and endpoint paths verified against source code at commit 53f0e084da5b460835c32d3e07d496e6e67a8616. Live probes confirmed:
- Health endpoint (GET /health) returns HTTP 200 with `{"status":"ok","version":"0.2.0"}`
- Login endpoint (POST /auth/login) accepts username/password, returns JWT + userId + email
- Authenticated endpoint (GET /auth/me) verifies token, returns user profile with admin status
- admin/admin123 currently has `isAdmin: false` (credential rotation working correctly)
