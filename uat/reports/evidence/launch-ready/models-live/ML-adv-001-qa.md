# ML-adv-001 — QA of monitor-tail.sh fix (FIXED-AWAITING-QA → re-fixed → VERIFIED)

- QA pass: 2026-07-23T16:39Z–16:42Z (Workstream A ledger-close)
- Script under test: `uat/reports/evidence/models-live/runtime/monitor-tail.sh` (evidence dir, gitignored by design — `evidence/` in .gitignore; fix therefore has no commit SHA, matching the row's original fixCommits note)
- Log source: real live logs `/var/log/aether/{api,web,worker,discovery}.log`. Per DEPLOYMENT-RUNBOOK §4, journalctl is NOT the log sink for aether units — re-confirmed fresh: `journalctl -u aether-api.service -n 5` → "No journal files were found". QA therefore ran against the authoritative live log files.

## 1. Original breakage signature GONE (delimiter fix confirmed)
```
LINE='2026-07-23T16:27:00Z INFO: 1.2.3.4:0 - "GET /jobs HTTP/1.1" 500 Internal Server Error'
echo "$LINE" | perl -ne "print if /$ERROR_PATTERN/"   → rc=255  (old /.../ form still broken — signature reproduced)
echo "$LINE" | perl -ne "print if m{$ERROR_PATTERN}"  → rc=0    (m{} delimiter fix works for MATCHING)
```

## 2. QA FAILED the awaiting-QA fix — new defect found (opposite direction)
The fixed `matches_error()` piped perl's OUTPUT to /dev/null and returned perl's EXIT CODE — but `perl -ne "print if m{...}"` exits 0 whether or not the regex matched:
```
echo "hello no match" | perl -ne "print if m{ERROR}" >/dev/null 2>&1; echo $?   → 0  (false positive)
```
Consequence observed on the real instrument: the monitor captured EVERY line — `live-matches.log` had grown to **14,212 lines** of overwhelmingly clean INFO/200 traffic (false-positive flood). A monitor that flags everything flags nothing → row could NOT move to VERIFIED as-was.

## 3. Fix applied (in-place, evidence-dir script)
`matches_error()` now uses `printf '%s\n' "$line" | grep -qP "$ERROR_PATTERN"` — `grep -P` verified available on this host, and its exit status IS the match status. Pattern unchanged.

## 4. Pass-after — real live-log lines through the fixed matcher
```
api-sample.txt (tail -200 /var/log/aether/api.log):    matched=1   not-matched=199
web-sample.txt (tail -100 web.log):                    matched=0   not-matched=100
worker-sample.txt (tail -50 worker.log):               matched=0   not-matched=50
cross-check: grep -cP "$ERROR_PATTERN" api-sample.txt → 1  (loop and grep agree)
matched line (genuine signature): 2026-07-23T16:31:01Z WARNING: scout: wellfound adapter failed: AdapterFetchError: ... HTTP Error 403: Forbidden
clean control: '... "GET /agents HTTP/1.1" 200 OK' → rc=1 (no match)
```

## 5. End-to-end capture check on the LIVE monitor
- Flooded log quarantined → `live-matches.log.false-positive-flood-20260723T*` (preserved, not deleted); fresh empty `live-matches.log`.
- Monitor restarted: new PID 19097 (`monitor.pid`), running.
- Injected into /var/log/aether/api.log (sudo tee -a), clearly marked synthetic:
  - `... INFO: QA-ML-adv-001 synthetic CONTROL line (clean, must NOT be captured)` → **NOT captured** ✅
  - `... ERROR: QA-ML-adv-001 synthetic capture check ERROR (not a real incident; monitor QA)` → **captured**: `[/var/log/aether/api.log] [2026-07-23T16:42:26Z] ... ERROR: QA-ML-adv-001 ...` ✅
- tail -F startup backlog lines from discovery.log containing genuine `error`/`AdapterFetchError` tokens were also captured (correct per pattern semantics).

## Verdict
Original breakage (perl rc=255, zero capture) is gone; the awaiting-QA fix's own defect (capture-everything) is found, fixed and proven; live capture leg now works with correct selectivity. → **VERIFIED-CLOSED-LIVE** (instrument-level; the G-06 clean observation window remains a separate campaign item).
