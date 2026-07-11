#!/bin/bash
export PATH="/opt/abacus-npm/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web

# Load env vars safely  
while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env

export NODE_ENV=production
exec pnpm start
