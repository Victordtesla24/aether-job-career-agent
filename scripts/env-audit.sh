#!/usr/bin/env bash
#
# env-audit.sh — idempotently audit/repair the production .env for the QA
# 2026-08-13 fix pack. NEVER prints secret values; only key names + status.
#
# Run ON THE PRODUCTION HOST:
#   bash scripts/env-audit.sh /path/to/.env        # audit + fix
#   AETHER_ENV_AUDIT_DRY_RUN=1 bash scripts/env-audit.sh /path/to/.env  # audit only
#
set -euo pipefail

ENV_FILE="${1:-/home/ubuntu/github_repos/aether-job-career-agent/.env}"
DRY_RUN="${AETHER_ENV_AUDIT_DRY_RUN:-0}"

[[ -f "$ENV_FILE" ]] || { echo "FATAL: $ENV_FILE not found" >&2; exit 1; }

# key=required_value ("" means: must exist and be non-empty, any value ok)
declare -A WANT=(
  [AETHER_ENV]="production"
  [AETHER_LLM_MODE]="auto"                 # never "replay" in production
  [AETHER_ASYNC_GENERATION]="true"
  [AETHER_BOARD_SWEEP_ENABLED]="true"      # continuous board sweep worker
  [AETHER_JOB_STALE_DAYS]="30"             # H-07: auto-archive stale jobs
  [AETHER_COVER_LETTER_TIER]="REASONING"   # C-03: primary tier (FAST retry is automatic)
)
declare -A WANT_NONEMPTY=(
  [AETHER_SYSTEM_RUN_SECRET]="generate"    # generated if missing
  [AETHER_MODEL_REASONING]="keep"
  [AETHER_MODEL_FAST]="keep"
)

get_val() { grep -E "^${1}=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

CHANGES=()
for key in "${!WANT[@]}"; do
  cur="$(get_val "$key")"
  want="${WANT[$key]}"
  if [[ "$cur" == "$want" ]]; then
    echo "OK      $key"
  else
    echo "FIX     $key (was: '${cur:-<unset>}' → '$want')"
    CHANGES+=("$key=$want")
  fi
done

for key in "${!WANT_NONEMPTY[@]}"; do
  cur="$(get_val "$key")"
  if [[ -n "$cur" ]]; then
    echo "OK      $key (set, value hidden)"
  elif [[ "${WANT_NONEMPTY[$key]}" == "generate" ]]; then
    echo "FIX     $key (unset → generating random secret)"
    CHANGES+=("$key=$(openssl rand -hex 32)")
  else
    echo "WARN    $key is UNSET — set it manually (model id, e.g. from apps/api/app/llm_client.py defaults)"
  fi
done

if [[ "${#CHANGES[@]}" -eq 0 ]]; then
  echo "No changes needed."
  exit 0
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN: ${#CHANGES[@]} change(s) NOT applied."
  exit 0
fi

# Atomic write: copy, patch, move back. Preserves everything else untouched.
TMP="$(mktemp)"
cp "$ENV_FILE" "$TMP"
for change in "${CHANGES[@]}"; do
  key="${change%%=*}"
  if grep -qE "^${key}=" "$TMP"; then
    # replace in place without echoing the value to logs
    python3 - "$TMP" "$key" "${change#*=}" <<'PY'
import sys
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).read().splitlines()
out = [f"{key}={val}" if l.startswith(f"{key}=") else l for l in lines]
open(path, "w").write("\n".join(out) + "\n")
PY
  else
    printf '%s\n' "$change" >> "$TMP"
  fi
done
chmod 600 "$TMP"
mv "$TMP" "$ENV_FILE"
echo "Applied ${#CHANGES[@]} change(s) to $ENV_FILE (chmod 600). Restart services to pick up:"
echo "  sudo systemctl restart aether-api aether-web aether-worker"
