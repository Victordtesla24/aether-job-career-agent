# Governance: Admin Panel Access — Human-Gated Credential Rotation

**Timestamp UTC:** 2026-07-17T12:35:20Z  
**Probe Authority:** Evidence Sub-Agent (Phase 0, Step 3)  
**Status:** HUMAN-GATED

---

## Finding

The Aether production system has **no operator-admin credential configured**. Both required environment variables for admin credential rotation are **absent**:

| Environment Variable | Status | Purpose |
|---|---|---|
| `AETHER_ADMIN_EMAIL` | **NOT FOUND** | Operator admin email address |
| `AETHER_ADMIN_PASSWORD_HASH` | **NOT FOUND** | Operator admin password (bcrypt hash only, never plaintext) |

**Source Verification:**
- `.env` file check: `grep -E "AETHER_ADMIN_EMAIL\|AETHER_ADMIN_PASSWORD_HASH" .env` → NO MATCHES
- Environment check: `env \| grep -E "AETHER_ADMIN_EMAIL\|AETHER_ADMIN_PASSWORD_HASH"` → NO MATCHES
- Code implementation: `apps/api/app/repositories/admin.py:540-541` loads both from `os.environ`

---

## Current Admin State

The seeded demo credential (`admin` / `admin123`) **exists but carries zero admin privilege**:

```json
{
  "id": "cc29a76e324fbf19f438eb8be",
  "email": "admin@aether.local",
  "isAdmin": false,
  "suspended": false
}
```

**Why:** The `apply_admin_rotation()` function (§14.7, `apps/api/app/repositories/admin.py:513-557`) runs on every API startup and **always demotes** the seeded credential to `isAdmin=false` (line 532-536). It only grants admin to an environment-configured account IF both env vars are present and non-empty (line 542). Since they are absent, no admin exists.

**This is correct by design (GATE-31).** The seeded credential must never hold privileges; the operator must explicitly provision admin access via env vars.

---

## Impact

**Admin screens are blocked for all users:**

1. **No plaintext admin password available:** The demo password `admin123` is NOT stored; user records hold bcrypt hashes only. Brute-force recovery is impractical.

2. **Seeded credential cannot be promoted:** The rotation logic unconditionally demotes the seeded account on every startup. Even if an admin manually granted it privileges via SQL, the next restart would remove them.

3. **Operator action required:** To unblock admin access, the operator must:
   - Choose an admin email
   - Generate a bcrypt hash of a secure password
   - Set both as environment variables
   - Restart `aether-api.service`

---

## What the Operator Must Provide

**The operator must supply both of the following to enable admin access:**

### 1. Administrator Email Address

- Typical value: `ops@company.com`, `administrator@example.com`, or similar
- No constraints; any RFC 5322–valid email
- This account will be created/updated in the database on API startup

### 2. Operator Admin Password (Bcrypt Hash)

- **NEVER** provide plaintext password — only the bcrypt hash
- **How to generate:**
  ```bash
  python3 -c "from passlib.context import CryptContext; ctx = CryptContext(schemes=['bcrypt']); print(ctx.hash('your-chosen-password'))"
  ```
- Example output: `$2b$12$N9qo8uLOickgx2ZMRZoMye...` (60-character string)
- Store this exact value in `AETHER_ADMIN_PASSWORD_HASH`

---

## Setup Instructions (Operator)

1. **Generate bcrypt hash of the secure password you choose:**
   ```bash
   python3 -c "from passlib.context import CryptContext; ctx = CryptContext(schemes=['bcrypt']); print(ctx.hash('MySecureAdminPassword123'))"
   ```
   Copy the output (e.g., `$2b$12$...`).

2. **Update production `.env`** in `/home/ubuntu/github_repos/aether-job-career-agent/.env`:
   ```env
   AETHER_ADMIN_EMAIL=ops@company.com
   AETHER_ADMIN_PASSWORD_HASH=$2b$12$...
   ```

3. **Restart the API:**
   ```bash
   sudo systemctl restart aether-api.service
   ```

4. **Verify admin access:**
   ```bash
   curl -X POST "http://127.0.0.1:8000/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email":"ops@company.com","password":"MySecureAdminPassword123"}'
   ```
   Expected response includes `"isAdmin": true`.

5. **Login to admin panel:**
   - Visit `https://5cb5f0620.abacusai.cloud/admin`
   - Sign in with operator email and password
   - Admin screens should now be accessible

---

## Blocking Rationale

This setup is **intentionally blocked** to enforce security:

- **No hardcoded defaults:** The system refuses to operate with a demo admin account
- **Explicit operator action required:** Setup is not automatic, preventing accidental exposure
- **Secret rotation possible:** Operator can change the hash at any time by updating env vars + restarting
- **Audit trail:** All admin actions are logged to `AdminAuditLog` table (verified via schema check)

---

## References

- **Admin rotation code:** `apps/api/app/repositories/admin.py:513-557`
- **Admin schema:** `apps/api/migrations/0023_admin.sql`
- **Security guide:** `docs/subscription/admin-guide.md`
- **Deployment runbook:** `docs/delivery/DEPLOYMENT-RUNBOOK.md`

---

## Sign-Off

This artifact confirms that **operator-provided admin credentials are required to enable admin access**. The system is functioning correctly by refusing to serve an admin interface without explicit operator provisioning.

**Gate Status:** HUMAN-GATED — awaiting operator credential provisioning.
