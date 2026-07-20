# DEPLOY-MV-system-008 — Merge & Live Verification

**Timestamp (this run):** 2026-07-20T03:08:26Z  
**Deployer:** Claude Fable 5 (DEPLOYER agent)

## 1. Merge Details

**Before state:** main @084e04b (clean, no staged changes)  
**Branch merged:** fix/mv-system-008-cron-logging @b08b502  
**Merge commit:** e182571  
**Merge command:** `git merge --no-ff` with message "Merge fix/mv-system-008-cron-logging (MV-system-008)" + Co-Author footer  
**Verification:** `git merge-tree 084e04b b08b502` returned clean hash (no conflicts)

## 2. Diff Verification

**Command:** `git diff --stat HEAD~1..HEAD`

```
 apps/api/tests/shell/test_discovery_cron_logging.sh | 124 +++++++++++++++++++++
 scripts/discovery_cron.sh                           |  11 +-
 2 files changed, 134 insertions(+), 1 deletion(-)
```

**Result:** PASS — exactly 2 files changed; scope matches review artifact (scripts/discovery_cron.sh + new test file).

## 3. Shell Test Execution

**Command:** `bash /home/ubuntu/github_repos/aether-job-career-agent/apps/api/tests/shell/test_discovery_cron_logging.sh`  
**Execution time:** 2026-07-20T03:08:19Z (inside test, calling unreachable endpoint 127.0.0.1:1)

**Output:**

```
--- http_call exit code: 1 ---
--- captured stdout (what a real caller's $(...) would receive) ---

--- log file contents (/tmp/tmp.yRjJnBt6AW/discovery.log) ---
curl: (7) Failed to connect to 127.0.0.1 port 1 after 0 ms: Couldn't connect to server
[discovery-cron 2026-07-20T03:08:19Z] FATAL: GET http://127.0.0.1:1/mv-system-008-unreachable -> HTTP 000: 
---
PASS (a): FATAL line landed in the log file
PASS (b): captured stdout is clean -- no FATAL contamination
RESULT: PASS
```

**Verification:** PASS — both assertions pass, confirming:
- (a) FATAL message reaches the log file (via stderr redirect, not swallowed by command substitution)
- (b) captured stdout is clean (no pollution from log())

## 4. Systemd Unit Confirmation

**Command:** `systemctl cat aether-discovery.service | grep -A 2 'ExecStart'`

**Output:**

```
ExecStart=/home/ubuntu/github_repos/aether-job-career-agent/scripts/discovery_cron.sh

# /etc/systemd/system/aether-discovery.service.d/logging.conf
```

**Verification:** PASS — ExecStart points directly to the merged repo path. The merge is immediately live for the next firing; no systemctl restart/daemon-reload needed (script-only change, unit file unchanged).

## 5. Live Verification — Manual Firing

**Manual trigger:** `sudo systemctl start aether-discovery.service`  
**Trigger time (UTC):** 2026-07-20T03:08:26Z  
**Service exit status:** exit code 1 (expected failure — see step 6 outcome)  
**Service exit time (UTC):** 2026-07-20T03:08:51Z

### 5a. Firing Log Excerpt (Timestamped)

**Lines from `/var/log/aether/discovery.log` for the manual firing window (2026-07-20T03:08-03:09):**

```
[discovery-cron 2026-07-20T03:08:30Z] scout run: query='Senior Technical Program Manager' location='Melbourne, AU'
[discovery-cron 2026-07-20T03:08:50Z] scout: {"status":"accepted","persisted":0,"updated":41,"errors":["wellfound: AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden"],"per_source":[{"source":"greenhouse","fetched":15,"persisted":0,"updated":15,"error":null,"status":"ok"},{"source":"lever","fetched":9,"persisted":0,"updated":9,"error":null,"status":"ok"},{"source":"ashby","fetched":15,"persisted":0,"updated":15,"error":null,"status":"ok"},{"source":"workable","fetched":0,"persisted":0,"updated":0,"error":null,"status":"ok"},{"source":"adzuna","fetched":0,"persisted":0,"updated":0,"error":null,"status":"skipped"},{"source":"remotive","fetched":1,"persisted":0,"updated":1,"error":null,"status":"ok"},{"source":"remoteok","fetched":1,"persisted":0,"updated":1,"error":null,"status":"ok"},{"source":"wellfound","fetched":0,"persisted":0,"updated":0,"error":"AdapterFetchError: Wellfound public listings unavailable: HTTP Error 403: Forbidden","status":"error"},{"source":"linkedin","fetched":0,"persisted":0,"updated":0,"error":null,"status":"skipped"},{"source":"indeed","fetched":0,"persisted":0,"error":null,"status":"skipped"}]}
[discovery-cron 2026-07-20T03:08:51Z] FATAL: POST http://127.0.0.1:8000/agents/fit-scorer/run -> HTTP 422: {"detail":"Add your resume before scoring jobs against it."}
```

### 5b. Outcome Verification

**Firing outcome:** HONEST FAILURE (expected behavior)

1. **Login:** Account restored (prior firing at 01:30Z was on unfixed script; current firing on fixed script)
2. **Scout run:** Executed and logged timestamped start + completion (both logged)
3. **Fit-scorer:** Attempted HTTP POST to `/agents/fit-scorer/run` endpoint
4. **Endpoint response:** HTTP 422 (not found account state) — **logged as FATAL line** (the critical evidence)
5. **Log presence:** FATAL line **is present** in `/var/log/aether/discovery.log` (proof that stderr redirect is working)
6. **Exit code:** Non-zero (failure), captured by systemd, triggering the unit's Failed state

**Summary:** The fixing is verified live. The FATAL diagnostic that was previously swallowed by the `$(http_call ...)` command substitution now survives to the log file via stderr, proving MV-system-008 is closed and MV-system-006 (prior missing logs) is resolved.

## 6. Timer Schedule

**Command:** `systemctl list-timers aether-discovery.timer`

**Output:**

```
NEXT                         LEFT LAST                        PASSED UNIT                   ACTIVATES
Mon 2026-07-20 03:30:16 UTC 21min Mon 2026-07-20 03:00:29 UTC      - aether-discovery.timer aether-discovery.service
```

**Next scheduled firing:** 2026-07-20T03:30:16Z (UTC)

## Summary

| Step | Result | Evidence |
|------|--------|----------|
| Merge pre-check | PASS | git merge-tree clean |
| Merge --no-ff | PASS | Commit e182571 created |
| Diff verification | PASS | 2 files, 134 insertions(+), 1 deletion(-) |
| Shell test | PASS | FATAL logged, stdout clean |
| Systemd ExecStart | PASS | Points to repo path /home/ubuntu/github_repos/aether-job-career-agent/scripts/discovery_cron.sh |
| Manual firing | PASS | Service ran, FATAL logged at 2026-07-20T03:08:51Z |
| Timer schedule | OK | Next firing 2026-07-20T03:30:16Z |

**Closure:** MV-system-008 (cron logging stderr redirect) verified live. MV-system-006 (missing discovery logs) now resolved — FATAL diagnostics survive to log file and are timestamped.

**No push performed. No service restarts (aether-api/web/worker untouched). No other branches touched.**
