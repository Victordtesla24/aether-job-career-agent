#!/usr/bin/env bash
# Refuses to start a service whose environment would fabricate results.
# Wired as systemd ExecStartPre — a violating env therefore CANNOT boot.
set -uo pipefail
ENVF="${1:?usage: runtime_env_guard.sh <env-file>}"
fail=0
chk() { # key  forbidden-regex  message
  local v; v=$(grep -E "^$1=" "$ENVF" | tail -1 | cut -d= -f2- | tr -d "\"'")
  if [ -n "$v" ] && printf '%s' "$v" | grep -qiE "$2"; then
    echo "INTEGRITY VIOLATION: $1=$v — $3" >&2; fail=1
  fi
}
chk AETHER_LLM_MODE            '^(replay|fixture|mock|fake)$' "serves canned LLM output instead of live model calls"
chk AETHER_DISCOVERY_FIXTURES  '^(1|true|yes|on)$'            "serves recorded job data instead of live discovery"
chk AETHER_DRY_RUN             '^(1|true|yes|on)$'            "simulates side effects instead of performing them"
chk AETHER_DISCOVERY_FIXTURE_DIR '.+'                         "fixture directory configured — live discovery disabled"
if grep -qiE '^(DATABASE_URL|AETHER_REDIS_URL)=.*(hosteddb\.reai\.io|5cb5f0620)' "$ENVF"; then
  echo "INTEGRITY VIOLATION: environment still points at decommissioned Abacus infrastructure" >&2; fail=1
fi
[ "$fail" -eq 0 ] && echo "integrity: environment clean ($ENVF)"
exit $fail
