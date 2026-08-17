#!/usr/bin/env bash
# Safe entrypoint for the backend pytest suite (MV-system-003 + TEST-PAR-1).
#
# INCIDENT (2026-07-18, docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md):
# a deploy step ran `source ../../.env && pytest`, which put the PRODUCTION
# DATABASE_URL (schema=aether) into the pytest process environment. The
# suite's table-truncation fixture then wiped the production database.
#
# This script is the ONLY sanctioned way to run the backend test suite:
#   * It reads DATABASE_URL_TEST from the repo-root .env (or an already
#     exported DATABASE_URL_TEST) and exports it as BOTH DATABASE_URL and
#     DATABASE_URL_TEST for the pytest child process.
#   * It REFUSES to run at all (exit 1) unless the resolved DSN's `schema=`
#     query param — parsed as a real query parameter, never matched as a
#     substring — is an ISOLATED TEST SCHEMA, i.e. it matches
#     ^aether_test([_a-z0-9]+)?$ : the legacy shared `aether_test` or a
#     per-wave `aether_test_<wave>`. Production (`aether`), `public`, an
#     absent/empty/ambiguous schema param and every look-alike are refused
#     before pytest even starts, independent of the in-process guard in
#     apps/api/tests/conftest.py (belt and suspenders — either layer alone
#     stops the wipe).
#   * It NEVER sources the repo-root .env wholesale into the environment,
#     so a production DATABASE_URL in .env can never leak into the test
#     process via this script.
#
# ---------------------------------------------------------------------------
# TEST-PAR-1 — PARALLEL TEST GATE (per-wave schema + per-wave lockfile)
# ---------------------------------------------------------------------------
# The whole program used to serialise every pytest battery behind
#   flock /tmp/aether-pytest.lock scripts/run-tests.sh ...
# because ALL runs shared the single `aether_test` schema and their
# `TRUNCATE ... CASCADE` fixtures deleted each other's rows. The DB role has
# no CREATEDB (per-database isolation is impossible) but it CAN CREATE
# SCHEMA — so a wave isolates itself with its OWN schema and its OWN lock:
#
#   # once per wave (idempotent; creates aether_test_<wave> from the
#   # template schema's structure):
#   scripts/test-schema.sh provision <wave>
#
#   # every battery in that wave (concurrent with other waves):
#   AETHER_TEST_SCHEMA=aether_test_<wave> \
#     flock /tmp/aether-pytest-<wave>.lock scripts/run-tests.sh -q
#
#   # when the wave is finished:
#   scripts/test-schema.sh drop <wave>
#
# CONVENTION (follow it and waves never collide):
#   * per-wave schema   : aether_test_<wave>          (lowercase/digits/_ )
#   * per-wave lockfile : /tmp/aether-pytest-<wave>.lock
#   * <wave> is the wave/worktree slug, e.g. `pa`, `r1_integrity`.
# The legacy default — no AETHER_TEST_SCHEMA, `flock /tmp/aether-pytest.lock`,
# schema `aether_test` — is unchanged and still correct; runs in distinct
# schemas do not need to hold each other's lock.
#
# HOST BUDGET (measured 2026-08-17, uat/reports/evidence/models-live/test-par-1/
# NOTE-battery-B-oom.txt): per-wave schemas remove the CORRECTNESS
# serialisation, NOT the RAM one. This host has ~8 GB and NO swap, and the
# web/api services hold a large share of it while a suite runs.
# What was actually MEASURED (do not extrapolate past these):
#   * a full suite reaches ~1.5 GB RSS mid-run and was OOM-killed at
#     2.18 GB anon-rss (exit 137, kernel oom-killer, dmesg captured);
#   * THREE concurrent FULL suites did NOT fit — one was OOM-killed;
#   * TWO concurrent TARGETED batteries (~190 tests each) alongside a third
#     agent's full suite ran green with room to spare (PROOF-3WAY-*.txt).
# The safe concurrency for FULL suites on this host has NOT been established;
# treat >1 concurrent full suite as unproven and check `free -m` first.
# Targeted per-wave batteries are the tested-safe way to parallelise.
#
# AETHER_TEST_SCHEMA (optional) rewrites the resolved DSN's `schema=` param so
# a wave never has to handle the raw, secret-bearing DSN itself. The override
# goes through the SAME fail-closed gate as the .env value — it is not a way
# around it.
#
# Usage:
#   scripts/run-tests.sh [pytest args...]
#
# Examples:
#   scripts/run-tests.sh                          # whole suite, legacy schema
#   scripts/run-tests.sh tests/test_auth.py -q    # one file
#   AETHER_TEST_SCHEMA=aether_test_pa scripts/run-tests.sh -q   # wave "pa"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
ENV_FILE="$REPO_ROOT/.env"

#: The ONLY schema shape the destructive suite may ever target: the legacy
#: shared `aether_test`, or a per-wave `aether_test_<wave>`. Anchored and
#: character-class restricted — kept in lockstep with
#: apps/api/tests/conftest.py's `_TEST_SCHEMA_PATTERN`.
TEST_SCHEMA_REGEX='^aether_test([_a-z0-9]+)?$'

refuse() {
  echo "REFUSING TO RUN: $1" >&2
  echo "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md." >&2
  exit 1
}

# Extract the DSN's `schema=` query parameter as a REAL query parameter.
# Prints the value on stdout; exit status 1 = no schema param, 2 = more than
# one (ambiguous — psycopg2/Prisma would disagree about which one wins, so it
# is refused rather than guessed). Deliberately does NOT url-decode: an
# encoded value (e.g. `aether_test%20pa`) is not a plain schema name and must
# fail the pattern rather than be normalised into one.
#
# `local -` + `set -f` (restored automatically when the function returns)
# disable PATHNAME EXPANSION for the split. Without it, splitting an unquoted
# `$query` on IFS='&' also globs each pair, so a file named
# `schema=aether_test` in the caller's working directory would silently
# complete the pair `schema=aether_test*` into an ACCEPTED value — a
# fail-OPEN gate whose verdict depends on the caller's cwd, and a banner that
# then names a schema the exported DSN does not actually carry.
schema_param_of() {
  local - url="$1" query pair value='' count=0
  set -f
  case "$url" in
    *\?*) query="${url#*\?}" ;;
    *) return 1 ;;
  esac
  query="${query%%#*}"
  local IFS='&'
  for pair in $query; do
    case "$pair" in
      schema=*)
        count=$((count + 1))
        [[ $count -eq 1 ]] && value="${pair#schema=}"
        ;;
    esac
  done
  [[ $count -eq 0 ]] && return 1
  [[ $count -gt 1 ]] && return 2
  printf '%s' "$value"
}

# Replace the DSN's `schema=` value with $1 (used by AETHER_TEST_SCHEMA).
# `local -` + `set -f`: same no-globbing requirement as schema_param_of —
# here a glob-expanded pair would REWRITE the DSN handed to pytest.
with_schema_param() {
  local - url="$1" new_schema="$2" base query out='' pair
  set -f
  case "$url" in
    *\?*) base="${url%%\?*}"; query="${url#*\?}" ;;
    *) base="$url"; query='' ;;
  esac
  local IFS='&'
  for pair in $query; do
    case "$pair" in
      schema=*) continue ;;
      "") continue ;;
    esac
    out="${out:+$out&}$pair"
  done
  out="${out:+$out&}schema=$new_schema"
  printf '%s?%s' "$base" "$out"
}

# Resolve DATABASE_URL_TEST WITHOUT sourcing the whole .env file (which would
# also export the production DATABASE_URL into this shell).
resolved_test_url="${DATABASE_URL_TEST:-}"
if [[ -z "$resolved_test_url" && -f "$ENV_FILE" ]]; then
  resolved_test_url="$(grep -E '^DATABASE_URL_TEST=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  # Strip surrounding quotes, same convention as the other .env parsers in
  # this repo (start-api.sh / conftest.py's _load_root_env).
  resolved_test_url="${resolved_test_url%\"}"; resolved_test_url="${resolved_test_url#\"}"
  resolved_test_url="${resolved_test_url%\'}"; resolved_test_url="${resolved_test_url#\'}"
fi

if [[ -z "$resolved_test_url" ]]; then
  echo "REFUSING TO RUN: DATABASE_URL_TEST is not set (checked env and $ENV_FILE)." >&2
  echo "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md." >&2
  exit 1
fi

# Optional per-wave retarget (TEST-PAR-1). Gated by the SAME pattern below.
schema_override="${AETHER_TEST_SCHEMA:-}"
if [[ -n "$schema_override" ]]; then
  if [[ ! "$schema_override" =~ $TEST_SCHEMA_REGEX ]]; then
    refuse "AETHER_TEST_SCHEMA='$schema_override' is not an isolated test schema.
Must match $TEST_SCHEMA_REGEX (e.g. aether_test, aether_test_pa) — refusing to
point the destructive test suite at it."
  fi
  resolved_test_url="$(with_schema_param "$resolved_test_url" "$schema_override")"
fi

set +e
resolved_schema="$(schema_param_of "$resolved_test_url")"
schema_status=$?
set -e

case "$schema_status" in
  1) refuse "DATABASE_URL_TEST carries no '?schema=' query param.
The destructive test suite has no verifiable, isolated target without it." ;;
  2) refuse "DATABASE_URL_TEST carries MORE THAN ONE 'schema=' query param.
Which one wins is ambiguous — refusing rather than guessing." ;;
esac

if [[ ! "$resolved_schema" =~ $TEST_SCHEMA_REGEX ]]; then
  refuse "DATABASE_URL_TEST resolves to schema='$resolved_schema', which is not
an isolated test schema. It must match $TEST_SCHEMA_REGEX — the legacy shared
'aether_test' or a per-wave 'aether_test_<wave>' (see scripts/test-schema.sh).
Refusing to risk running the destructive test suite against any other schema."
fi

echo "[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=$resolved_schema — safe to proceed."

export DATABASE_URL="$resolved_test_url"
export DATABASE_URL_TEST="$resolved_test_url"

cd "$API_DIR"
exec python3 -m pytest "$@"
