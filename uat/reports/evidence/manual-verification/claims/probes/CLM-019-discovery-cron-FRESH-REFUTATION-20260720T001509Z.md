# CLM-019 fresh probe: aether-discovery.timer live status

**Probe timestamp (UTC):** 2026-07-20T00:15:09Z
**Method:** systemctl status/list-timers on production host (per DEPLOYMENT-RUNBOOK.md §1, §4) + grep of /var/log/aether/api.log (authoritative per runbook §4, "Journalctl NOT USED")

## Findings

1. `systemctl is-active aether-discovery.timer` → `active`; `list-timers` shows it firing every 30 min as designed (Last: 2026-07-20T00:00:54Z, 12 min before probe).
2. `systemctl status aether-discovery.service` → **`failed (Result: exit-code)` since 2026-07-20T00:00:54Z**, `ExecStart=.../scripts/discovery_cron.sh (code=exited, status=1/FAILURE)`.
3. `/var/log/aether/api.log` (grep `127.0.0.1.*auth/login`) shows the discovery-cron's own login calls (source IP 127.0.0.1, matching `discovery_cron.sh`'s `$API/auth/login` call against the local API) returning **401 Unauthorized on every attempt from 2026-07-18T23:00:26Z through 2026-07-20T00:00:54Z** (timestamped portion of the log, continuous every ~30 min, 0 successes in that window) — 123 total 401 lines from 127.0.0.1 to /auth/login found in the full (partially untimestamped, pre-restart) log.
4. `/var/log/aether/discovery.log` (the script's own StandardOutput/StandardError log target) has **not been appended to since 2026-07-18T00:31:18Z** — i.e. the script is failing before it reaches even its own `log "FATAL: ..."` line inside `http_call()`, OR the append is not landing (root cause not fully diagnosed; out of scope to debug further without further env exposure).
5. Root cause hypothesis (not confirmed via any secret-exposing command): `docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md` records the production DB was wiped 2026-07-18 and states "user will re-signup as sarkar.vikram@gmail.com" (the discovery-cron's default `AETHER_CRON_EMAIL`). The timing (last discovery.log success 2026-07-18T00:31Z, first timestamped cron 401 at 2026-07-18T23:00:26Z, i.e. after the wipe) is consistent with that account no longer existing / no longer matching `LOGIN_PASSWORD` post-wipe, causing every scheduled discovery run to fail at the very first step (login) — meaning scout/fit-scorer have NOT actually run via the unattended cron for >24h even though the timer itself fires on schedule.

## Verdict impact

**CLM-019** ("The aether-discovery.timer cron fires unattended and completes end-to-end with the system-run header present, with zero 402s and zero exit-22 failures") is **REFUTED** as of this probe: the timer fires (that part holds) but the triggered service has been failing outright (HTTP 401 at login, before the system-run header / paywall-bypass logic is ever reached) on every attempt for at least the last ~25.5 hours of timestamped log coverage. This is a fresh, previously-unfiled defect (searched `docs/delivery/MANUAL-VERIFICATION-GAPS.json` for "discovery-cron"/"aether-discovery"/"discovery.timer"/"discovery.service" — zero existing findings). Flagged for orchestrator to instantiate a new finding.

No secrets were logged in this artifact (only counts, timestamps, and HTTP status codes).
