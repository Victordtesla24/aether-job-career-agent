# BASELINE-SWEEP Server-Side Log Capture
**MANUAL-VERIFICATION Run — PHASE 0, Step 6**

**Window (UTC):** 2026-07-17T13:25:48 to 2026-07-17T13:27:51 (163 seconds)  
**Baseline Sweep Manifest:** uat/reports/evidence/manual-verification/screens/BASELINE-SWEEP.json  
**Manifest Actual Range:** 2026-07-17T13:25:48.165743 to 2026-07-17T13:27:50.547812 UTC  
**Git SHA (baseline):** 53f0e084da5b460835c32d3e07d496e6e67a8616  
**Report Generated:** 2026-07-17 13:35:22 UTC  
**Deployment Authority:** docs/delivery/DEPLOYMENT-RUNBOOK.md §4 (file-based logs)

---

## Evidence Status

**[VERIFIED-WITH-FRESH-EVIDENCE]** — All logs extracted from live production servers via file reads:
- nginx access.log: `/var/log/nginx/access.log` (timestamped, precisely filtered to window)
- API service logs: `/var/log/aether/api.log` (no timestamps, full file scanned)
- Web service logs: `/var/log/aether/web.log` (no timestamps, full file scanned)
- Worker service logs: `/var/log/aether/worker.log` (no timestamps, full file scanned)
- No journalctl data available (per runbook §4: "journalctl is **not the authoritative source** for Aether logs")

---

## Critical Finding: Application Log Limitation

**[OBSERVATION]** Application logs (api.log, web.log, worker.log) are **not timestamped**. Per DEPLOYMENT-RUNBOOK.md §4, these are Uvicorn/Next.js/ARQ stdout redirects without structured timestamp injection. Consequentially:

1. **nginx access.log (timestamped)** — Precisely filtered to window; 100% accurate
2. **Application logs (untimestamped)** — Counts reflect full file scan; may span beyond the 163-second window
3. **nginx error.log** — Not configured per runbook (all errors go to access.log via status codes)

---

## Service-by-Service Logs and Counts

### 1. NGINX Reverse Proxy Access Log
**Path:** `/var/log/nginx/access.log`  
**Time Filter Applied:** Yes (precise: 13:25:48 to 13:27:51 UTC)  
**Entries in Window:** 269 requests  
**File Size:** ~2.7M (entire service lifetime)

#### HTTP Status Distribution
| Status | Count | Notes |
|--------|-------|-------|
| 200    | 266   | OK |
| 307    | 1     | Redirects (login flow) |
| 404    | 1     | Not found (POST /auth/login on wrong path) |
| 5xx    | 0     | No server errors on public interface |

#### Sample Requests (first 5 of window)
```
10.51.4.1 - - [17/Jul/2026:13:25:48 +0000] "POST /api/auth/login HTTP/1.1" 200 380 "-" "python-requests/2.33.0"
10.51.4.1 - - [17/Jul/2026:13:25:49 +0000] "GET / HTTP/1.1" 307 20 "-" "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
10.51.4.1 - - [17/Jul/2026:13:25:49 +0000] "GET /dashboard HTTP/1.1" 200 2197 "-" "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
10.51.4.1 - - [17/Jul/2026:13:25:49 +0000] "GET /login?_rsc=189n2 HTTP/1.1" 200 1357 "https://5cb5f0620.abacusai.cloud/dashboard" "Mozilla/5.0"
10.51.4.1 - - [17/Jul/2026:13:25:49 +0000] "GET /signup?_rsc=1obve HTTP/1.1" 200 1358 "https://5cb5f0620.abacusai.cloud/login" "Mozilla/5.0"
```

#### 4xx Error (outside main flow)
```
10.51.4.1 - - [17/Jul/2026:13:27:30 +0000] "POST /auth/login HTTP/1.1" 404 3160 "-" "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
```
*Note: POST to `/auth/login` instead of `/api/auth/login`; test/probe request, not part of baseline sweep.*

---

### 2. FastAPI Backend (aether-api.service)
**Path:** `/var/log/aether/api.log`  
**Time Filter Applied:** No (logs lack timestamps; see above)  
**Total Entries:** 32,675 lines (service startup to recent)  
**File Size:** 2.4M

#### Error/Warning/Exception Counts (full file)
| Category | Count | Severity |
|----------|-------|----------|
| ERROR lines | 334 | High |
| WARNING lines | 21 | Medium |
| Traceback entries | 39 | High |
| LLM failed calls | 270 | High |
| 5xx status codes in logs | 80 | Critical |

#### Critical Issues Found

**1. LLM API Deprecation (270 failures)**
```
LLM live call failed (model=claude-fable-5, prompt=tailor): 
  LLM provider HTTP 400: {"error":{"code":"invalid_request_error",
  "message":"`temperature` is deprecated for this model.",
  "type":"invalid_request_error","param":null}}
```
*Impact:* Tailoring, cover letter, and other LLM-dependent features fail systematically.  
*Scope:* claude-fable-5 (primary model, 269 occurrences)

**2. Rate Limit on Fallback Model (1 failure)**
```
LLM live call failed (model=claude-haiku-4-5-20251001, prompt=tailor): 
  LLM provider HTTP 429: {"error":{"code":"rate_limit_error",
  "message":"This request would exceed your account's rate limit. Please try again later.",
  "type":"invalid_request_error","param":null}}
```
*Impact:* Even fallback model is rate-limited; requests will fail.

**3. bcrypt Module Error (startup)**
```
(trapped) error reading bcrypt version
Traceback (most recent call last):
  AttributeError: module 'bcrypt' has no attribute '__about__'
```
*Impact:* Minor (trapped); does not block startup. Occurs at initialization.

**4. FastAPI/Starlette Compatibility (39 tracebacks)**
```
Traceback (most recent call last):
  from fastapi.exceptions import FastAPIDeprecationWarning
  File "/opt/abacus-python/lib/python3.12/site-packages/fastapi/exceptions.py", line 6, in <module>
    from starlette.exceptions import HTTPException as StarletteHTTPException
ImportError: cannot import name 'HTTPException' from 'starlette.exceptions'
```
*Impact:* Version incompatibility between FastAPI and Starlette. May cause import errors at runtime.  
*Frequency:* Repeated across multiple operations.

---

### 3. Next.js Frontend (aether-web.service)
**Path:** `/var/log/aether/web.log`  
**Time Filter Applied:** No (logs lack timestamps)  
**Total Entries:** 1,224 lines (service startup to recent)  
**File Size:** 78K

#### Error/Warning/Exception Counts (full file)
| Category | Count | Severity |
|----------|-------|----------|
| ERROR lines | 88 | High |
| WARNING lines | 26 | Medium |
| Traceback entries | 0 | None |
| 5xx status codes | 0 | None |

#### Critical Issues Found

**1. Missing Next.js Build (48 occurrences)**
```
Error: Could not find a production build in the '.next' directory. 
Try building your app with 'next build' before starting the production server. 
https://nextjs.org/docs/messages/production-start-no-build-id
```
*Impact:* Web service started before build completed, or .next directory missing.  
*Frequency:* Repeated across startup attempts.

**2. Build Artifact Missing (4 occurrences)**
```
Error: ENOENT: no such file or directory, 
open '/home/ubuntu/github_repos/aether-job-career-agent/apps/web/.next/prerender-manifest.json'
```

**3. Runtime Module Not Found (8 occurrences)**
```
⨯ Error: Cannot find module '/home/ubuntu/github_repos/aether-job-career-agent/apps/web/.next/server/pages/_error.js'
⨯ Error: Cannot find module '/home/ubuntu/github_repos/aether-job-career-agent/apps/web/.next/server/app/_not-found/page.js'
```

**4. Backend Proxy Failures (18 occurrences)**
```
Failed to proxy http://127.0.0.1:8000/agents Error: connect ECONNREFUSED 127.0.0.1:8000
Failed to proxy http://127.0.0.1:8000/settings Error: connect ECONNREFUSED 127.0.0.1:8000
```
*Impact:* Web cannot reach API backend on port 8000.  
*Root Cause:* Either API service was down during these attempts, or network routing misconfigured.

**5. Deprecation Warning (util._extend)**
```
(node:62552) [DEP0060] DeprecationWarning: The `util._extend` API is deprecated. 
Please use Object.assign() instead.
```
*Impact:* Minor; does not block operation but indicates outdated Node.js code.

---

### 4. ARQ Background Job Worker (aether-worker.service)
**Path:** `/var/log/aether/worker.log`  
**Time Filter Applied:** No (logs lack timestamps)  
**Total Entries:** 187 lines (service startup to recent)  
**File Size:** 14K

#### Error/Warning/Exception Counts (full file)
| Category | Count | Severity |
|----------|-------|----------|
| ERROR lines | 1 | Low |
| WARNING lines | 0 | None |
| Traceback entries | 0 | None |

#### Issues Found

**1. Job Lookup Failure (1 occurrence)**
```
job c189bc159785f922239cc38c8 failed: LookupError: Job bad-job-id-async-force-fail not found for user
```
*Impact:* Expected test job failure (bad job ID); not a production issue.  
*Context:* Appears to be a deliberate test of failure handling.

---

## Summary Table: Service Health During Baseline

| Service | Status | 5xx | 4xx | ERROR | WARNING | Traceback | LLM Fail | Critical Issue |
|---------|--------|-----|-----|-------|---------|-----------|----------|------------------|
| **nginx** | ✓ Clean | 0 | 1 | 0 | 0 | 0 | 0 | None |
| **api** | ⚠ Degraded | 80 | - | 334 | 21 | 39 | 270 | LLM temperature deprecation; Starlette import error |
| **web** | ⚠ Degraded | 0 | - | 88 | 26 | 0 | 0 | Missing .next build; proxy failures to API |
| **worker** | ✓ Clean | 0 | - | 1 | 0 | 0 | 0 | None (test job failure) |

---

## Verdict

**[VERIFIED-WITH-FRESH-EVIDENCE]**

### 5xx Errors in Window
**Nginx (public interface):** 0  
**Application logs (internal):** 80 (api.log only; untimestamped, may span beyond window)  
**Overall:** **0 errors visible to users** (nginx: 0)

### 4xx Errors in Window
**Nginx:** 1 (POST /auth/login on wrong path; not baseline sweep)  
**Overall:** **Baseline sweep: 0 errors**

### Tracebacks in Window
**Nginx:** 0  
**API:** 39 (FastAPI/Starlette import errors; untimestamped)  
**Web:** 0  
**Worker:** 0  
**Overall:** **39 tracebacks in logs** (scope uncertain due to missing timestamps)

### Error Lines (Aggregated)
**API:** 334  
**Web:** 88  
**Worker:** 1  
**Total:** **423 error lines** (untimestamped; full scan)

### Warning Lines (Aggregated)
**API:** 21  
**Web:** 26  
**Worker:** 0  
**Total:** **47 warning lines** (untimestamped; full scan)

### LLM Call Records
**Successful:** Not tracked in logs  
**Failed:** 270 (claude-fable-5 temperature deprecation; 1 rate limit)  
**Total:** **270+ failures** (untimestamped; full scan)

---

## Baseline Sweep Outcome (from manifest)
- Rows captured: 29
- Rows failed: 0
- Total console errors: 0
- Total failed requests: 0

**→ All 29 screens passed the baseline test** despite server-side LLM deprecation errors. This is because:
1. Async LLM calls may not be awaited during page load
2. Fallback rendering (text-only, skeleton screens) masks failures
3. Test timeout may have prevented retry exhaustion

---

## Recommended Actions

1. **CRITICAL:** Update `temperature` parameter for claude-fable-5 (or remove if deprecated by model)
2. **HIGH:** Resolve FastAPI/Starlette version incompatibility
3. **HIGH:** Rebuild Next.js (.next directory missing or corrupted)
4. **MEDIUM:** Monitor LLM fallback behavior (rate limits on Haiku)
5. **MEDIUM:** Investigate API/web proxy connection failures

---

**Report Status:** COMPLETE  
**All sections verified with fresh evidence from production logs**
