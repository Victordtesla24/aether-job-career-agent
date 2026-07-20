# DEPLOY-NF-final-pass-002 Log

**Deployment Date:** 2026-07-20
**Deployer:** MANUAL-VERIFICATION run

## Pre-Deployment State

- **Main Branch SHA:** c158729 (Merge fix/nf-final-pass-001)
- **Branch to Merge:** fix/nf-final-pass-002 @ 9ceb92f
- **Merge Commit:** 54c28e5 (Merge fix/nf-final-pass-002 (NF-final-pass-002))

## Merge Verification

```
$ git diff HEAD~1 HEAD --stat
 apps/api/app/routers/cover_letters.py     |  29 ++++
 apps/api/tests/test_cover006_camelcase.py | 254 ++++++++++++++++++++++++++++++
 2 files changed, 283 insertions(+)
```

Exactly 2 files changed (all in apps/api/, no web changes).

## Backend Gate Test - Full Serialized Suite

**Command Executed:**
```bash
cd apps/api && \
DATABASE_URL="$DATABASE_URL_TEST" \
AETHER_CREDENTIAL_KEY="X5-HScT0p0CLbLTSh0PJZ2Pa1NKvhlVJDJPj7hpEDqU=" \
AETHER_ASYNC_GENERATION=false \
flock /tmp/aether-pytest.lock python3 -m pytest -q -p no:xdist -o addopts=""
```

**Results:**
```
967 passed, 44 warnings in 1314.79s (0:21:54)
```

**Status:** PASS [VERIFIED-WITH-FRESH-EVIDENCE]
- Exit code: 0
- Passed: 967
- Failed: 0
- Duration: 21m 54s
- Warnings: 44 (benign deprecations: HTTP_422 rename, datetime.utcnow(), passlib)
- Log: /tmp/gate-final-pass-002.log

## Service Restart

**Service:** aether-api

**Restart Initiated:** 2026-07-20T13:33:04Z

**Status After Restart (5s):**
```
● aether-api.service - Aether API Server (FastAPI/Uvicorn)
     Loaded: loaded (/etc/systemd/system/aether-api.service; enabled; preset: enabled)
     Active: active (running) since Mon 2026-07-20 13:33:04 UTC; 5s ago
```

## Health Verification

**Endpoint 1: /api/health**
- URL: https://5cb5f0620.abacusai.cloud/api/health
- Status: HTTP 200
- Body: `{"status":"ok","version":"0.2.0"}`
- Timestamp: 2026-07-20T13:33:15Z

**Endpoint 2: /dashboard**
- URL: https://5cb5f0620.abacusai.cloud/dashboard
- Status: HTTP 200
- Content: HTML (Next.js dashboard)
- User-Agent: Mozilla/5.0
- Timestamp: 2026-07-20T13:33:15Z

**Health Verdict:** PASS

## Deployment Summary

| Metric | Value |
|--------|-------|
| Merge Commit | 54c28e5 |
| Files Changed | 2 (apps/api only) |
| Gate Result | 967 passed / 0 failed |
| Gate Duration | 21m 54s |
| Restart Time (UTC) | 2026-07-20T13:33:04Z |
| Health Check | PASS (200, 200) |
| Final Status | COMPLETE SUCCESS |

## Governance

- NON-NEGOTIABLE SEQUENCING: All steps executed in order
  1. Preconditions: VERIFIED (main clean, merge --no-ff)
  2. Full serialized backend gate: COMPLETED (967/0)
  3. No web changes: VERIFIED (all apps/api/)
  4. Restart aether-api: COMPLETED
  5. Health verification: PASSED
  6. Evidence logged: THIS FILE

- Gate Count Recording: BEFORE restart (governance entries 12-13)
- No push authorized (per instructions)
- Production URL healthy post-deployment

---

**Deployment Authority:** docs/delivery/DEPLOYMENT-RUNBOOK.md (followed exactly)
**Evidence Root:** uat/reports/evidence/manual-verification/
**Timestamp (UTC):** 2026-07-20T13:33:15Z

---

## Addendum — second (redundant) restart at 13:40:58Z

A parallel deployer worker, polling `/tmp/gate-final-pass-002.log` independently,
read and recorded the gate count a second time and issued its own restart before
discovering this log already existed. Recorded for timeline accuracy so the live
systemd state matches this file:

- **Gate final line (independently re-read from the log, ANSI-stripped):**
  `967 passed, 44 warnings in 1314.79s (0:21:54)` — identical to the count above;
  zero `failed`/`error` occurrences; log sha256 first16 `8038960c1002c2cc`.
  Count re-recorded at **2026-07-20T13:40:52Z**, BEFORE this second restart
  (sequencing preserved on both restarts; both occurred after gate completion
  ≈13:31:52Z).
- **Second restart:** `sudo systemctl restart aether-api` at **2026-07-20T13:40:58Z**
  (exit 0). Unit now `active (running)`, **Main PID 88327** — this is the PID an
  auditor will see; the 13:33:04Z restart above created the intermediate PID 84228.
- **Log window** (`/var/log/aether/api.log`; journald persists no files on this
  VM — the file log via the `logging.conf` drop-in is authoritative): graceful
  `Shutting down` 13:40:58Z → `Started server process [88327]` 13:40:59Z →
  `Application startup complete` 13:41:00Z. Post-restart window **clean** (zero
  error/traceback lines; a bcrypt `__about__` traceback and `temperature is
  deprecated` LLM-400 lines earlier in the file are all timestamped before
  13:40:58Z — old-process noise, not introduced by this deploy).
- **Health after second restart:** `GET /api/health` → **200**
  `{"status":"ok","version":"0.2.0"}`; `GET /dashboard/cover-letters`
  (browser UA) → **200**. (13:41Z)
- **No push** performed by this worker either.
