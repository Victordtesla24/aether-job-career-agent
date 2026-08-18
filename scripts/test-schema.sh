#!/usr/bin/env bash
# TEST-PAR-1 — per-wave test-schema provisioning (parallel test gate).
#
# WHY THIS EXISTS
# ---------------
# Every pytest battery in the program used to serialise behind
# `flock /tmp/aether-pytest.lock` because ALL runs shared ONE `aether_test`
# schema: the suite's `TRUNCATE ... CASCADE` fixture deletes every other
# concurrent run's rows mid-test. Batteries take 10-20 minutes, so waves
# queued single-file — the dominant program bottleneck.
#
# The hosted DB role has NO CREATEDB (per-database isolation is impossible)
# but it CAN CREATE SCHEMA. So each wave gets its OWN schema, provisioned
# here with the SAME structure the suite needs, and runs its batteries
# concurrently with every other wave:
#
#   scripts/test-schema.sh provision pa            # -> aether_test_pa
#   AETHER_TEST_SCHEMA=aether_test_pa \
#     flock /tmp/aether-pytest-pa.lock scripts/run-tests.sh -q
#   scripts/test-schema.sh drop pa                 # when the wave is done
#
# HOW `provision` BUILDS THE SCHEMA
# ---------------------------------
# The suite's structure is NOT reproducible from one artefact: the base
# tables are Prisma-managed (packages/db/src/schema.prisma), a dozen more
# arrive from apps/api/migrations/*.sql, and others are created lazily at
# runtime by repositories (`CREATE TABLE IF NOT EXISTS`). The one place all
# of that is already reconciled is the live template schema itself, so this
# script clones its STRUCTURE (pg_dump --schema-only, zero rows) into the new
# schema and records provenance. No production schema is ever read or
# written: the template is an aether_test* schema, and every target name is
# validated before a connection is opened.
#
# IDEMPOTENT: `provision` on an already-provisioned schema is a no-op (it
# checks the provenance marker table). It never drops anything implicitly —
# a non-empty schema with no provenance marker is REFUSED, not clobbered, so
# a wave can never silently destroy another wave's in-flight run.
#
# SAFETY: both verbs refuse any target outside `aether_test_*`, including
# production (`aether`), `public`, and the legacy SHARED `aether_test`
# itself. `drop` can therefore never remove the shared schema or prod.
#
# Usage:
#   scripts/test-schema.sh provision <wave|aether_test_wave>
#   scripts/test-schema.sh drop      <wave|aether_test_wave>
#   scripts/test-schema.sh list
#
# Environment:
#   DATABASE_URL_TEST            (required) resolved exactly like
#                                run-tests.sh — env first, then repo-root
#                                .env, never by sourcing it.
#   AETHER_TEST_TEMPLATE_SCHEMA  (optional) structure template; default
#                                `aether_test`. Must itself be an isolated
#                                test schema.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

#: Kept in lockstep with run-tests.sh's TEST_SCHEMA_REGEX and conftest.py's
#: _TEST_SCHEMA_PATTERN — except that a WAVE schema must carry a suffix, so
#: the legacy shared `aether_test` is not a valid target for this script.
WAVE_SCHEMA_REGEX='^aether_test_[a-z0-9][_a-z0-9]*$'
TEST_SCHEMA_REGEX='^aether_test([_a-z0-9]+)?$'

#: Names that must NEVER be accepted, in suffix position or full-name
#: position, however they are spelled in the argument.
PROTECTED_NAMES=(aether aether_test public postgres information_schema pg_catalog pg_toast)

#: Provenance marker written into every schema this script provisions. Its
#: presence is what makes `provision` idempotent, and its absence is what
#: makes the script refuse to touch a schema it did not create.
MARKER_TABLE='_aether_test_provenance'

usage() {
  cat >&2 <<'USAGE'
usage: scripts/test-schema.sh provision <wave|aether_test_wave>
       scripts/test-schema.sh drop      <wave|aether_test_wave>
       scripts/test-schema.sh list

  provision  create aether_test_<wave> (CREATE SCHEMA IF NOT EXISTS) and clone
             the template schema's structure into it. Idempotent.
  drop       DROP SCHEMA aether_test_<wave> CASCADE. Refuses any other name.
  list       list the per-wave test schemas that currently exist.
USAGE
}

refuse() {
  echo "REFUSING: $1" >&2
  exit 2
}

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

# Turn the user's argument into a fully-qualified wave schema name, or refuse.
resolve_target() {
  local arg="${1-}" candidate name
  [[ -z "$arg" ]] && refuse "no schema/suffix given (empty argument)."

  for name in "${PROTECTED_NAMES[@]}"; do
    if [[ "$arg" == "$name" ]]; then
      refuse "'$arg' is a protected schema — this helper only ever creates or
drops per-wave 'aether_test_<wave>' schemas, never production ('aether'),
'public', or the legacy SHARED 'aether_test'."
    fi
  done

  if [[ "$arg" == aether_test* ]]; then
    candidate="$arg"
  else
    candidate="aether_test_$arg"
  fi

  if [[ ! "$candidate" =~ $WAVE_SCHEMA_REGEX ]]; then
    refuse "'$arg' does not name a per-wave test schema (resolved to
'$candidate'). It must match $WAVE_SCHEMA_REGEX — lowercase letters, digits
and underscores only, e.g. 'pa' -> aether_test_pa."
  fi
  printf '%s' "$candidate"
}

# Resolve DATABASE_URL_TEST WITHOUT sourcing .env (a production DATABASE_URL
# in that file must never enter this shell) — same contract as run-tests.sh.
resolve_admin_dsn() {
  # `local -` snapshots the shell options and restores them when the function
  # returns, so the `set -f` below cannot leak noglob into the rest of the run.
  local - url="${DATABASE_URL_TEST:-}"
  if [[ -z "$url" && -f "$ENV_FILE" ]]; then
    url="$(grep -E '^DATABASE_URL_TEST=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
    url="${url%\"}"; url="${url#\"}"
    url="${url%\'}"; url="${url#\'}"
  fi
  [[ -z "$url" ]] && fail "DATABASE_URL_TEST is not set (checked env and $ENV_FILE)."

  # Verify the DSN's own schema param is an isolated test schema before using
  # its credentials at all — the same fail-closed posture as run-tests.sh.
  # `set -f` (scoped by the `local -` in this function's declaration below)
  # disables PATHNAME EXPANSION during the split: without it a file named
  # `schema=aether_test` in the caller's cwd completes the pair
  # `schema=aether*` into an accepted value, and this helper would go on to
  # use a PRODUCTION-pointing DSN's credentials to CREATE/DROP schemas.
  local query pair value='' count=0
  set -f
  case "$url" in
    *\?*) query="${url#*\?}" ;;
    *) query='' ;;
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
  unset IFS
  [[ $count -ne 1 ]] && fail "DATABASE_URL_TEST must carry exactly one 'schema=' query param."
  if [[ ! "$value" =~ $TEST_SCHEMA_REGEX ]]; then
    refuse "DATABASE_URL_TEST resolves to schema='$value', which is not an
isolated test schema — refusing to use its credentials to create or drop
schemas. See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md."
  fi

  # psycopg2/psql do not understand Prisma's ?schema= param: strip the whole
  # query string and pin the schema explicitly per statement instead.
  printf '%s' "${url%%\?*}"
}

resolve_template() {
  local template="${AETHER_TEST_TEMPLATE_SCHEMA:-aether_test}"
  if [[ ! "$template" =~ $TEST_SCHEMA_REGEX ]]; then
    refuse "AETHER_TEST_TEMPLATE_SCHEMA='$template' is not an isolated test
schema — refusing to clone structure from it."
  fi
  printf '%s' "$template"
}

psql_q() {
  # -X: ignore ~/.psqlrc; -A -t: bare values; ON_ERROR_STOP: never half-apply.
  psql "$ADMIN_DSN" -X -v ON_ERROR_STOP=1 -A -t -c "$1"
}

cmd_provision() {
  local target="$1" template
  template="$(resolve_template)"
  ADMIN_DSN="$(resolve_admin_dsn)"

  local template_exists
  template_exists="$(psql_q "SELECT count(*) FROM pg_namespace WHERE nspname = '$template'")"
  [[ "$template_exists" == "1" ]] || fail "template schema '$template' does not exist."

  psql_q "CREATE SCHEMA IF NOT EXISTS \"$target\"" >/dev/null

  local marker_exists
  marker_exists="$(psql_q "SELECT count(*) FROM information_schema.tables
      WHERE table_schema = '$target' AND table_name = '$MARKER_TABLE'")"
  if [[ "$marker_exists" == "1" ]]; then
    local provisioned
    provisioned="$(psql_q "SELECT provisioned_at || ' from ' || template_schema
        FROM \"$target\".\"$MARKER_TABLE\" ORDER BY provisioned_at DESC LIMIT 1")"
    echo "[test-schema.sh] $target already provisioned ($provisioned) — no-op."
    return 0
  fi

  local table_count
  table_count="$(psql_q "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$target'")"
  if [[ "$table_count" != "0" ]]; then
    refuse "$target already contains $table_count table(s) but has no
'$MARKER_TABLE' provenance marker — this script did not create it, and it may
be another wave's in-flight schema. Refusing to modify it. If it is genuinely
stale: scripts/test-schema.sh drop ${target#aether_test_}"
  fi

  local ddl_file
  ddl_file="$(mktemp -t aether-test-schema-XXXXXX.sql)"
  # shellcheck disable=SC2064  # expand $ddl_file now, not at trap time
  trap "rm -f '$ddl_file'" RETURN

  # Structure only — never a single row of data — from the template schema.
  pg_dump "$ADMIN_DSN" \
    --schema-only --no-owner --no-privileges --no-comments --no-tablespaces \
    -n "$template" \
    | sed -e "s/\\b${template}\\b/${target}/g" \
          -e "s/^CREATE SCHEMA ${target};/CREATE SCHEMA IF NOT EXISTS ${target};/" \
    > "$ddl_file"

  [[ -s "$ddl_file" ]] || fail "pg_dump produced no DDL for template '$template'."

  local ddl_sha
  ddl_sha="$(sha256sum "$ddl_file" | cut -d' ' -f1)"

  psql "$ADMIN_DSN" -X -q -v ON_ERROR_STOP=1 --single-transaction -f "$ddl_file" >/dev/null

  psql "$ADMIN_DSN" -X -q -v ON_ERROR_STOP=1 --single-transaction >/dev/null <<SQL
CREATE TABLE IF NOT EXISTS "$target"."$MARKER_TABLE" (
  "id"              bigserial PRIMARY KEY,
  "provisioned_at"  timestamptz NOT NULL DEFAULT now(),
  "template_schema" text        NOT NULL,
  "ddl_sha256"      text        NOT NULL,
  "provisioned_by"  text        NOT NULL
);
INSERT INTO "$target"."$MARKER_TABLE"
  ("template_schema","ddl_sha256","provisioned_by")
VALUES ('$template', '$ddl_sha', 'scripts/test-schema.sh');
SQL

  local created
  created="$(psql_q "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$target'")"
  echo "[test-schema.sh] provisioned $target from $template — $created tables (ddl sha256 ${ddl_sha:0:12})."
  echo "[test-schema.sh] run batteries with:"
  echo "  AETHER_TEST_SCHEMA=$target flock /tmp/aether-pytest-${target#aether_test_}.lock scripts/run-tests.sh -q"
}

cmd_drop() {
  local target="$1"
  ADMIN_DSN="$(resolve_admin_dsn)"
  psql_q "DROP SCHEMA IF EXISTS \"$target\" CASCADE" >/dev/null
  echo "[test-schema.sh] dropped $target (if it existed)."
}

cmd_list() {
  ADMIN_DSN="$(resolve_admin_dsn)"
  echo "[test-schema.sh] per-wave test schemas:"
  psql "$ADMIN_DSN" -X -v ON_ERROR_STOP=1 -c "
    SELECT n.nspname AS schema,
           (SELECT count(*) FROM information_schema.tables t
             WHERE t.table_schema = n.nspname) AS tables
      FROM pg_namespace n
     WHERE n.nspname ~ '$WAVE_SCHEMA_REGEX'
     ORDER BY n.nspname"
}

main() {
  local verb="${1-}"
  case "$verb" in
    provision|drop)
      if [[ $# -lt 2 ]]; then
        refuse "'$verb' needs a wave suffix or an aether_test_<wave> schema name."
      fi
      local target
      target="$(resolve_target "$2")"
      "cmd_$verb" "$target"
      ;;
    list)
      cmd_list
      ;;
    ""|-h|--help|help)
      usage
      exit 1
      ;;
    *)
      echo "unknown verb: $verb" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
