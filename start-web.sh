#!/bin/bash
# pipefail: MV-system-001 pipes stdout/stderr through gawk below to prefix an
# ISO-8601 timestamp on every line; without pipefail the pipeline's exit
# status would always be gawk's (~always 0), silently defeating
# aether-web.service's `Restart=on-failure` crash detection.
set -o pipefail
# ML-runbook-001 (2026-07-22): `pnpm` resolves to the SYSTEM-INSTALLED
# /usr/bin/pnpm (a corepack symlink) via PATH fallthrough below — it is NOT
# an /opt/abacus-npm/bin npm global (that directory has no pnpm binary at
# all). /opt/abacus-npm/bin is listed first only for other npm-global tools;
# keep /usr/bin on this PATH or `pnpm start` below will fail to resolve.
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

# MV-system-001: Next.js's `next start` (no custom server) emits its own
# console lines with no timestamp at all, which made /var/log/aether/web.log
# un-scopable to a test/incident time window (journald is not used for this
# unit — see docs/delivery/DEPLOYMENT-RUNBOOK.md §4 for why). Prefix every
# stdout/stderr line with an ISO-8601 UTC timestamp via gawk (pre-installed,
# no new dependency); `fflush()` keeps `tail -f` live. This can no longer be
# a bare `exec` (a pipeline always needs the shell to stay alive to run both
# ends) — `set -o pipefail` above preserves pnpm/next's real exit code for
# systemd's Restart=on-failure.
pnpm start 2>&1 | gawk '{ print strftime("%Y-%m-%dT%H:%M:%SZ", systime(), 1) " " $0; fflush() }'
