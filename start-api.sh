#!/bin/bash
export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api

# Load env vars safely - strip quotes.
# Split on the FIRST '=' only so values that themselves contain '=' survive
# intact — including base64 padding (e.g. a Fernet AETHER_CREDENTIAL_KEY ends
# in '='). The previous `IFS='=' read key value` dropped a trailing '=' as an
# empty final field, corrupting such keys.
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

# MV-system-001: uvicorn's built-in log formatters carry no timestamp at all,
# which made /var/log/aether/api.log un-scopable to a test/incident time
# window (journald is not used for this unit — see
# apps/api/logging_config.json's header comment and
# docs/delivery/DEPLOYMENT-RUNBOOK.md §4 for why). logging_config.json adds an
# ISO-8601 UTC timestamp to every default/access/root log line.
exec /opt/abacus-python/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-config logging_config.json
