# Cluster H — MV-signup-001 server-side enforcement (VERIFIED-WITH-FRESH-EVIDENCE)

Run: MANUAL-VERIFICATION, fixer-hard, branch `fix/mv-cluster-h`, base main `3eee0448`.
Fix commit: `336d7ad43f6eefb4ba8ed5939f631eb00ee7d187`.
Evidence captured: 2026-07-18T05:36Z (backend-test.txt) / 2026-07-18 (this run).

## Coordinator flag ("server change missing") — DISPROVEN with fresh evidence
The claim that commit 336d7ad "only changed FRONTEND (apps/web)" is not supported by
the branch. `git show 336d7ad --stat` includes THREE apps/api files:
- apps/api/app/security.py            (+17)
- apps/api/app/repositories/user.py   (+10)
- apps/api/tests/test_mv_signup_001_bcrypt.py (+86, new)
The `security.py:26 hash_password just hashes` / `user.py:28 only MIN length`
description matches the MAIN checkout (main @ 3eee0448, unchanged), NOT this branch.
See `server-enforcement-proof.txt` for the exact line numbers on the branch tip.

## Server-side fix (reject-over-72, the safer minimal option)
- `apps/api/app/security.py`: `BCRYPT_MAX_PASSWORD_BYTES = 72`; `verify_password`
  returns False for any candidate whose UTF-8 byte length > 72 BEFORE calling
  passlib — so a longer login attempt can never be truncated down to match a hash.
- `apps/api/app/repositories/user.py`: `validate_password_policy` appends
  "password must be at most 72 bytes" when the UTF-8 byte length > 72, so
  POST /auth/register rejects it with 422 BEFORE hashing. Length measured in bytes.
- Client mirror in apps/web/src/components/auth/validation.ts (courtesy only; the
  server is the security boundary).

## Backend test (targeted, safe flock path) — 8 passed
`tests/test_mv_signup_001_bcrypt.py` (see backend-test.txt for the full -v run):
- validate_password_policy: rejects 73 bytes, allows exactly 72, byte-measured (81-byte emoji pw rejected).
- verify_password: correct 72-byte pw verifies; a variant sharing the first 72 bytes does NOT (the original vuln); a >72 candidate is refused even against a short hash.
- Endpoint: register 91-byte pw => 422; register 72-byte pw ok + login 200; login with a DIFFERENT pw sharing the first 72 bytes => 401 (the coordinator's requested regression).

Run recipe: `cd apps/api && DATABASE_URL="$DATABASE_URL_TEST" AETHER_ASYNC_GENERATION=false flock /tmp/aether-pytest.lock python3 -m pytest tests/test_mv_signup_001_bcrypt.py -v`

## Other cluster-H findings (same commit)
MV-login-003 logout, MV-login-001/MV-signup-002 authed-redirect, MV-login-002 deep-link ?next (open-redirect-safe safeNextPath), MV-signup-003 email cap + 422 message hygiene, MV-signup-004 initials robustness, MV-login-004 honest /forgot-password.

Suites this run: backend auth blast-radius 72 passed (RED->GREEN for bcrypt); frontend vitest 354 passed (49 files); tsc --noEmit clean; next build exit 0.
