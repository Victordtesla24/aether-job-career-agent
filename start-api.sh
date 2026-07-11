#!/bin/bash
export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api

# Load env vars safely - strip quotes
while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    # Remove surrounding quotes if present
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env

exec /opt/abacus-python/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
