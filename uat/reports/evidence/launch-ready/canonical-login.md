# PHASE 0 Step 4 — Canonical Production Auth Snippet

> **REDACTED 2026-07-31 (BLOCKER-001, GOLD-MASTER-V2 phase 0).** This artifact previously published a
> *working production admin credential verbatim* in a public repository, as a "reuse verbatim"
> snippet. The password literal has been removed and replaced with environment variables. The
> findings recorded below are unchanged — in particular the `isAdmin: true` observation, which is
> corroborating evidence for BLOCKER-001. Root cause and fix:
> `uat/reports/evidence/gold-master-v2/phase0/BLOCKER-admin-overpermission-verification.md` and
> `uat/reports/evidence/gold-master-v2/phase0/BLOCKER-001-fix-report.md`. The credential itself
> remains in this repository's git history; only the operator's rotation of
> `AETHER_ADMIN_PASSWORD_HASH` closes that exposure.

- Timestamp: 2026-07-23T15:41:29Z
- Source of truth: `apps/api/app/routers/auth.py` — `POST /auth/login` (line 108–139) accepts JSON `{"email": <email-or-username>, "password": ...}` (the `email` field is deliberately `str`, not `EmailStr`, so a bare username validates — see lines 53–57). Returns `{access_token, token_type, userId, email}` (JWT bearer, HS256, 24h TTL per `app/security.py`). Public path via nginx: `/api/auth/login`.
- Test credential: supplied at run time via `LOGIN_EMAIL` / `LOGIN_PASSWORD` (repo-root `.env`, gitignored). **Never hardcode it here.** At capture time the identifier used was the bare username `admin`; that alias no longer resolves to the owner account — the §14.7 rotation now reclaims it (BLOCKER-001 / D2), so use the operator's email address.

## Working snippet (reuse verbatim; credentials come from the environment)

```bash
# Credentials from the environment — never inline them into this file.
: "${LOGIN_EMAIL:?set LOGIN_EMAIL (see repo-root .env)}"
: "${LOGIN_PASSWORD:?set LOGIN_PASSWORD (see repo-root .env)}"

# 1. Login — capture bearer token
TOKEN=$(curl -sS -X POST https://5cb5f0620.abacusai.cloud/api/auth/login \
  -H 'Content-Type: application/json' \
  --data-binary "$(LOGIN_EMAIL="$LOGIN_EMAIL" LOGIN_PASSWORD="$LOGIN_PASSWORD" \
      python3 -c 'import json,os;print(json.dumps({"email":os.environ["LOGIN_EMAIL"],"password":os.environ["LOGIN_PASSWORD"]}))')" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Authenticated call
curl -sS https://5cb5f0620.abacusai.cloud/api/auth/me -H "Authorization: Bearer $TOKEN"
```

## Captured transcript (2026-07-23T15:41:29Z, secrets masked)

```
$ POST /api/auth/login {"email":"<REDACTED-IDENTIFIER>","password":"<REDACTED>"}
HTTP 200
{"access_token": "eyJhbGciOiJI…REDACTED (JWT, 268 chars)", "token_type": "bearer",
 "userId": "c6c8d0163d973a8048e7e33b8", "email": "sar***@gmail.com"}

$ GET /api/auth/me  Authorization: Bearer <REDACTED>
HTTP 200
{"id":"c6c8d0163d973a8048e7e33b8","email":"sar***@gmail.com","name":"Administrator",
 "targetRole":"Business Analyst","location":"Melbourne","isAdmin":true}
```

## Verdict

`[VERIFIED-WITH-FRESH-EVIDENCE]` — production login worked end-to-end at capture time: 200 on login, bearer token accepted on an authenticated endpoint (`/api/auth/me` → 200 with the user profile). Note: this account carries `isAdmin: true` on production (the spec §1.1 lead described it as "non-admin user" — drift noted for later workstreams; not acted on here).

**2026-07-31 follow-up:** that "drift noted, not acted on" line is the earliest recorded sighting of BLOCKER-001. The bare demo identifier resolving to an `isAdmin: true` owner account was the defect, not drift.
