#!/bin/bash
# Aether ARQ worker launcher (GAP-P7-ASYNC-001). Mirrors start-api.sh EXACTLY so
# the worker resolves the identical repo-root .env credentials/budgets/DATABASE_URL
# with zero drift (the same first-'='-split parser preserves base64 padding and
# quoted values that systemd's simpler EnvironmentFile parser can mangle).
export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api

# Load env vars safely - strip quotes. Split on the FIRST '=' only so values that
# themselves contain '=' survive intact (e.g. base64 padding, redis URLs).
while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env

# S-3 — this process's slice of the hosted 25-connection cap (see
# apps/api/app/db.py ``_DEFAULT_POOL_MAX``): API 12 + worker 4 = 16, leaving 9
# for scripts/psql/migrations. The worker runs at most `max_jobs=3` concurrent
# jobs plus 3 cron ticks, so 4 pooled connections is its working set. Exported
# AFTER the .env loop so an explicit value in .env still wins.
export AETHER_DB_POOL_MAX="${AETHER_DB_POOL_MAX:-4}"

# QA-FAIL-02: arq's own CLI configures ONLY the `arq` logger and leaves the
# root logger at WARNING with no handler, so application `logger.info(...)`
# calls (e.g. the admin-free-fallback audit marker in llm_client.py) never
# reach worker.log even though arq's own INFO lines make the log look
# healthy. --custom-log-dict wires app/workers/logging_config.py's LOG_CONFIG,
# which adds an ISO-8601 UTC timestamped INFO root handler (matching
# apps/api/logging_config.json's MV-system-001 format) while keeping arq's
# own logging single-emission (see that module's docstring for why).
exec /opt/abacus-python/bin/arq app.workers.settings.WorkerSettings --custom-log-dict app.workers.logging_config.LOG_CONFIG
