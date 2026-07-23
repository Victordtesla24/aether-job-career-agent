# PHASE 0 Step 2 — Runbook Verification (docs/delivery/DEPLOYMENT-RUNBOOK.md vs live reality)

- Timestamp: 2026-07-23T15:40Z–15:52Z (all checks executed fresh in THIS run)
- Method: every operational claim/command in the runbook executed or inspected against the live host. Secrets never printed (masked/existence checks only).

## Command/claim → verdict

| # | Runbook claim / command | Result | Verdict |
|---|---|---|---|
| 1 | `systemctl is-active aether-api aether-web aether-worker redis-server` → all active | all `active`; `aether-discovery.timer` also `active` | VERIFIED |
| 2 | `systemctl is-enabled` all four services → enabled | all `enabled` | VERIFIED |
| 3 | Unit files at `/etc/systemd/system/aether-{api,web,worker,discovery}.service` + `aether-discovery.timer` | all exist | VERIFIED |
| 4 | ExecStart = repo `start-api.sh` / `start-web.sh` / `start-worker.sh` / `scripts/discovery_cron.sh` | exact match | VERIFIED |
| 5 | WorkingDirectory: repo root (api/web), `apps/api` (worker) | exact match | VERIFIED |
| 6 | Logging overrides `/etc/systemd/system/aether-{api,web}.service.d/logging.conf`; worker append lines inside its unit | all present | VERIFIED |
| 7 | Start scripts + `scripts/run-tests.sh` + `scripts/discovery_cron.sh` exist and are executable | all present, `-rwxrwxr-x` | VERIFIED |
| 8 | pnpm provenance: `/usr/bin/pnpm`, NOT `/opt/abacus-npm/bin` | `which pnpm` → `/usr/bin/pnpm`; `/opt/abacus-npm/bin/pnpm` → No such file | VERIFIED |
| 9 | Logs file-based in `/var/log/aether/` (api/web/worker/discovery), ISO-8601 timestamps on api.log lines | all four files present, growing; api.log line prefix `2026-07-23T15:31:11Z INFO:` | VERIFIED |
| 10 | journalctl NOT authoritative ("No journal files were found") | `journalctl -u aether-api.service` → "No journal files were found" | VERIFIED |
| 11 | nginx conf `/etc/nginx/conf.d/5cb5f0620.conf` matches documented server block; `sudo nginx -t` passes | conf content functionally identical (comment wording differs trivially); nginx -t OK; `aether-brand.conf` present and untouched | VERIFIED |
| 12 | Redis drop-in `/etc/redis/redis.conf.d/aether.conf` | exists (dir requires sudo to list — root-owned; minor omission, noted, not repaired as command still works with sudo) | VERIFIED |
| 13 | `gh auth status` → Victordtesla24, scopes gist/read:org/repo/workflow | exact match (token masked) | VERIFIED |
| 14 | Tracked `deploy/aether-{api,web,worker}.service*` functionally identical to live units | `diff` (comments stripped) → identical for all three | VERIFIED |
| 15 | Pre-deploy check `grep -E '^AETHER_LLM_MODE=' .env` must be auto/live | `AETHER_LLM_MODE=auto` | VERIFIED |
| 16 | Health check `curl -H 'Host: 5cb5f0620.vm.internal' http://localhost/api/health` | 200 `{"status":"ok","version":"0.2.0"}` (see runtime/health-probe.md) | VERIFIED |
| 17 | Build commands exist: root `pnpm build` (turbo), `apps/web` scripts `build`/`start`/`test` (vitest)/`e2e` (playwright); `pip install -r requirements.txt` viable (`pip` = `/opt/abacus-python/bin/pip`, py3.12) | all present in package.json/PATH | VERIFIED |
| 18 | `pnpm --dir apps/web build` (Quick Reference) — `--dir` flag valid | `pnpm --dir apps/web run` resolves scripts | VERIFIED |
| 19 | Discovery timer `OnCalendar=*:00/30` | exact match | VERIFIED |
| 20 | Rollback steps (git log/reset/revert, rebuild, restart) — commands syntactically valid against this repo; not executed (destructive) | dry inspection only | VERIFIED (non-destructive check) |
| 21 | Live process entrypoints: uvicorn `app.main:app` on 8000, `next-server` on 3000, `arq app.workers.settings.WorkerSettings` | `pgrep -af` (self-excluding patterns per §0.2 rule) confirms all three | VERIFIED |
| 22 | §2 API "Actual Entrypoint" / start-script snippet: `uvicorn ... --port 8000` (no `--log-config`) | live `start-api.sh` line 28 ends `--log-config logging_config.json` (MV-system-001) | **DRIFTED → REPAIRED** |
| 23 | §2 Web start-script snippet: `exec pnpm start` (no pipefail/gawk) | live `start-web.sh` uses `set -o pipefail` + `pnpm start 2>&1 \| gawk '{...strftime...}'` (MV-system-001) | **DRIFTED → REPAIRED** |
| 24 | §9 sample `gh pr list` output shows 3 OPEN PRs (dated 2026-07-16) | current: **zero** open PRs — the output is explicitly dated historical evidence, not a command drift | VERIFIED (dated example; no repair needed) |

## Drift found and repaired (runbook changed to match reality — reality untouched)

The §4/MV-system-001 section correctly *described* the timestamped-logging changes, but the §2
"Start Script Details" snippets and the API "Actual Entrypoint" line were never synced and still
showed the pre-MV-system-001 scripts. Repaired in this run:

1. API Actual Entrypoint + snippet now include `--log-config logging_config.json` (matches live `start-api.sh` line 28).
2. Web Actual Entrypoint + snippet now include `set -o pipefail` and the `pnpm start 2>&1 | gawk '{ print strftime("%Y-%m-%dT%H:%M:%SZ", systime(), 1) " " $0; fflush() }'` pipe (matches live `start-web.sh`).
3. "Last Updated" header bumped to 2026-07-23 with a pointer to this evidence file.

No live system change was made; deploy commands in §5 remain valid as written.

`[VERIFIED-WITH-FRESH-EVIDENCE]` — 22/24 checks verified as documented; 2 drifted doc snippets repaired to match reality.
