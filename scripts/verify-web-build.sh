#!/usr/bin/env bash
# Pre-flight gate for the Next.js production build (BUILD-RISK-001).
#
# INCIDENT (2026-07-31, GOLD-MASTER-V2 W-K):
# `apps/web/next.config.mjs` resolves the `/api/*` rewrite upstream from a
# BUILD-TIME environment variable:
#
#     const apiOrigin = process.env.AETHER_API_PROXY ?? "http://127.0.0.1:8000";
#
# A build produced while `AETHER_API_PROXY=http://127.0.0.1:8090` was exported
# (the Playwright e2e harness runs `pnpm run build` directly inside the live
# `apps/web` tree — see `playwright.config.ts` `webServer.command`) baked
# `http://127.0.0.1:8090` into `.next/routes-manifest.json`. Nothing listens on
# :8090, so EVERY `/api/*` request would have failed.
#
# The failure was latent, not visible: `next start` reads its rewrite table
# from the BUILT `routes-manifest.json` (`getRoutesManifest()` in
# `next/dist/server/next-server.js`) and does NOT re-evaluate `next.config.mjs`
# at boot. The already-running server therefore kept serving the correct
# in-memory :8000 table while the on-disk artefact pointed at a dead port —
# so production looked perfectly healthy right up until the next restart, at
# which point every API call in the app would have broken at once. Correcting
# the environment alone does NOT fix it; only a rebuild does.
#
# This gate makes that state unable to reach a restart. Run it AFTER
# `pnpm build` and BEFORE `systemctl restart aether-web.service`.
#
# The expected upstream is HARDCODED below and is deliberately NOT read from
# `AETHER_API_PROXY` — a gate that trusted the same environment that poisoned
# the build would validate the poison. Pass an explicit argument to override
# for non-production use.
#
# Usage:
#   scripts/verify-web-build.sh                          # expect http://127.0.0.1:8000
#   scripts/verify-web-build.sh http://127.0.0.1:9000    # explicit override
#
# Exit codes:
#   0  manifest is safe to serve
#   1  manifest is wrong / missing / build incomplete  -> DO NOT RESTART
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_DIR="${REPO_DIR}/apps/web"
NEXT_DIR="${WEB_DIR}/.next"

# Must match the `?? "..."` fallback in apps/web/next.config.mjs and the
# production nginx rule (`location /api/ -> FastAPI :8000`).
EXPECTED_UPSTREAM="${1:-http://127.0.0.1:8000}"

fail() {
    echo ""
    echo "=============================================================="
    echo "WEB BUILD PRE-FLIGHT GATE: FAIL"
    echo "=============================================================="
    echo "$@"
    echo ""
    echo "DO NOT restart aether-web.service. Restarting now would take the"
    echo "whole app down: every /api/* call would be proxied to the wrong"
    echo "upstream, and the symptom (all API calls fail) looks nothing like"
    echo "the cause (a stale build artefact)."
    echo ""
    echo "Remedy — rebuild from a clean environment, then re-run this gate:"
    echo "    cd ${WEB_DIR}"
    echo "    rm -rf .next"
    echo "    env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build"
    echo "    ${SCRIPT_DIR}/verify-web-build.sh"
    echo "=============================================================="
    exit 1
}

echo "[web-build-gate] repo:     ${REPO_DIR}"
echo "[web-build-gate] expected: ${EXPECTED_UPSTREAM}"

# --- Check 0: the invoking environment must not be able to poison the NEXT build.
if [[ -n "${AETHER_API_PROXY:-}" && "${AETHER_API_PROXY}" != "${EXPECTED_UPSTREAM}" ]]; then
    fail "AETHER_API_PROXY is exported in this shell as '${AETHER_API_PROXY}',
which does not match the expected upstream '${EXPECTED_UPSTREAM}'.
Any 'pnpm build' run from this shell bakes that value into
.next/routes-manifest.json. Unset it before building."
fi

# --- Check 1: a complete production build actually exists.
for required in "${NEXT_DIR}/routes-manifest.json" "${NEXT_DIR}/required-server-files.json" "${NEXT_DIR}/BUILD_ID"; do
    [[ -f "${required}" ]] || fail "Missing build artefact: ${required}
There is no complete production build in ${NEXT_DIR}."
done
[[ -d "${NEXT_DIR}/static" ]] || fail "Missing ${NEXT_DIR}/static — the client asset
directory was not produced. The build did not complete."

# --- Check 2: every /api/* rewrite destination in every manifest that carries
#     one must point at the expected upstream.
python3 - "${NEXT_DIR}" "${EXPECTED_UPSTREAM}" <<'PY' || fail "routes-manifest / required-server-files assertion failed (see above)."
import json
import sys
from pathlib import Path

next_dir = Path(sys.argv[1])
expected = sys.argv[2]
problems = []
checked = 0


def walk(node, path, origin):
    """Yield every (json-path, destination) pair under an arbitrary rewrite shape.

    Next serialises rewrites either as a bare list or as
    {beforeFiles, afterFiles, fallback}; required-server-files.json nests the
    same structures under `config` and `_originalRewrites`. Walking generically
    means a future Next upgrade that changes the shape cannot silently skip the
    assertion.
    """
    if isinstance(node, dict):
        if "source" in node and "destination" in node:
            yield (origin, path, node["source"], node["destination"])
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}", origin)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]", origin)


for name in ("routes-manifest.json", "required-server-files.json"):
    manifest_path = next_dir / name
    data = json.loads(manifest_path.read_text())
    for origin, path, source, destination in walk(data, "$", name):
        if not str(source).startswith("/api"):
            continue
        # Redirects/rewrites that stay same-origin (no scheme) are not proxies.
        if "://" not in str(destination):
            continue
        checked += 1
        if not str(destination).startswith(expected + "/") and str(destination) != expected:
            problems.append(f"  {origin} {path}\n    source      = {source}\n    destination = {destination}")

if checked == 0:
    print("[web-build-gate] FAIL: found NO absolute /api/* rewrite destination to check.")
    print("[web-build-gate] The rewrite in apps/web/next.config.mjs did not make it into")
    print("[web-build-gate] the build. Refusing to pass a gate that verified nothing.")
    sys.exit(1)

if problems:
    print(f"[web-build-gate] FAIL: {len(problems)} /api/* rewrite(s) do not target {expected}:")
    for problem in problems:
        print(problem)
    sys.exit(1)

print(f"[web-build-gate] OK: {checked} /api/* rewrite destination(s) target {expected}")
PY

# --- Check 3: no stray absolute upstream on any other port anywhere in the
#     server manifests (belt and braces against a shape this script's walker
#     has not learned about yet).
STRAY="$(grep -oh 'http://127\.0\.0\.1:[0-9]\{2,5\}' \
    "${NEXT_DIR}/routes-manifest.json" "${NEXT_DIR}/required-server-files.json" 2>/dev/null \
    | sort -u | grep -v "^${EXPECTED_UPSTREAM}$" || true)"
if [[ -n "${STRAY}" ]]; then
    fail "Unexpected loopback upstream(s) found in the build manifests:
${STRAY}
Only ${EXPECTED_UPSTREAM} is allowed."
fi

echo "[web-build-gate] OK: BUILD_ID $(cat "${NEXT_DIR}/BUILD_ID")"
echo "[web-build-gate] PASS — build is safe to serve; restart authorised."
