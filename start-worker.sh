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

exec /opt/abacus-python/bin/arq app.workers.settings.WorkerSettings
