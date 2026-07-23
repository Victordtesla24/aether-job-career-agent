# PHASE 0 Step 4 — Canonical Production Auth Snippet

- Timestamp: 2026-07-23T15:41:29Z
- Source of truth: `apps/api/app/routers/auth.py` — `POST /auth/login` (line 108–139) accepts JSON `{"email": <email-or-username>, "password": ...}` (the `email` field is deliberately `str`, not `EmailStr`, so the bare username `admin` validates — see lines 53–57). Returns `{access_token, token_type, userId, email}` (JWT bearer, HS256, 24h TTL per `app/security.py`). Public path via nginx: `/api/auth/login`.
- Test credential: `admin` / `admin123` (documented test login; resolves to an admin user).

## Working snippet (reuse verbatim; token value REDACTED here)

```bash
# 1. Login — capture bearer token
TOKEN=$(curl -sS -X POST https://5cb5f0620.abacusai.cloud/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin","password":"admin123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Authenticated call
curl -sS https://5cb5f0620.abacusai.cloud/api/auth/me -H "Authorization: Bearer $TOKEN"
```

## Captured transcript (2026-07-23T15:41:29Z, secrets masked)

```
$ POST /api/auth/login {"email":"admin","password":"admin123"}
HTTP 200
{"access_token": "eyJhbGciOiJI…REDACTED (JWT, 268 chars)", "token_type": "bearer",
 "userId": "c6c8d0163d973a8048e7e33b8", "email": "sar***@gmail.com"}

$ GET /api/auth/me  Authorization: Bearer <REDACTED>
HTTP 200
{"id":"c6c8d0163d973a8048e7e33b8","email":"sar***@gmail.com","name":"Administrator",
 "targetRole":"Business Analyst","location":"Melbourne","isAdmin":true}
```

## Verdict

`[VERIFIED-WITH-FRESH-EVIDENCE]` — production login for admin/admin123 works end-to-end: 200 on login, bearer token accepted on an authenticated endpoint (`/api/auth/me` → 200 with the user profile). Note: this account carries `isAdmin: true` on production (the spec §1.1 lead described it as "non-admin user" — drift noted for later workstreams; not acted on here).
