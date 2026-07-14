#!/bin/bash
export PATH="/opt/abacus-npm/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web

# Load env vars safely - strip quotes.
# Split on the FIRST '=' only so values containing '=' (e.g. base64 padding)
# survive intact; the previous IFS='=' parser dropped a trailing '='.
while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    # Remove surrounding quotes if present
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env

export NODE_ENV=production
exec pnpm start
