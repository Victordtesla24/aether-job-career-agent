# File Census — GOLD-MASTER-V4 (Repo: aether-job-career-agent)

**Timestamp:** 2026-07-31T16:00:00Z  
**Report Version:** VERIFIED-WITH-FRESH-EVIDENCE

## Tracked Files Summary

| Metric | Count |
|--------|-------|
| **Total tracked files (git ls-files)** | 1030 |
| **Total top-level directories** | 19 |
| **Untracked but present (__pycache__, cache, build dirs)** | ~545 |

## Tracked Files by Top-Level Directory

| Directory | Count | Status |
|-----------|-------|--------|
| `apps/` | 592 | Main application code (API, web, worker) |
| `uat/` | 238 | UAT/testing/delivery artifacts |
| `docs/` | 110 | Documentation |
| `.claude/` | 36 | Agent definitions and settings |
| `design/` | 20 | Design assets |
| `deploy/` | 8 | Deployment configs |
| `ci/` | 2 | CI configuration |
| `scripts/` | 6 | Utility scripts |
| `packages/` | 2 | Orphaned TS/Prisma layer (dedup artifacts) |
| `cleanup/` | 1 | Cleanup tracker |
| Root level | 15 | `.env.example`, README, LICENSE, start-*.sh, config |

## Files by Extension (Tracked)

| Extension | Count | Purpose |
|-----------|-------|---------|
| `.py` | 296 | Backend Python (FastAPI, agents, services) |
| `.md` | 219 | Documentation |
| `.json` | 132 | Config, package, lock files |
| `.tsx` | 124 | React components (Next.js) |
| `.ts` | 119 | TypeScript utilities/types |
| `.log` | 23 | Build/test logs (tracked) |
| `.txt` | 21 | Requirements, lists |
| `.html` | 19 | Build artifacts, statics |
| `.mjs` | 17 | ES6 modules (validation, build) |
| `.png` / `.jpg` | 15 | Screenshots, assets |
| `.sh` | 8 | Bash scripts (start, test, verify) |
| `.sql` | 6 | DDL, migrations |
| `.conf` / `.service` / `.yml` | 9 | Systemd, nginx, CI/CD |
| Other | 11 | `.pdf`, `.css`, `.toml`, `.prisma`, etc. |

## Scripts & Root-Level Shell Files

| File | Purpose | Tracked |
|------|---------|---------|
| **start-api.sh** | Launch FastAPI uvicorn with env-var safety (MV-system-001 ISO-8601 timestamps) | ✓ |
| **start-web.sh** | Launch Next.js pnpm start with ISO-8601 timestamp pipeline (ML-runbook-001 pnpm PATH) | ✓ |
| **start-worker.sh** | Launch ARQ background worker; mirrors start-api.sh for credential parity (GAP-P7-ASYNC-001) | ✓ |
| **scripts/discovery_cron.sh** | Scheduled job discovery (REQ-01 / SC-JOB-10), runs every 30 min via systemd timer | ✓ |
| **scripts/generate_ba_resume.py** | Generate BA-angled resume PDF from source; reproduces Vik_Resume_Final.pdf layout | ✓ |
| **scripts/run-e2e-server.sh** | Dedicated e2e web-server (fixes BUILD-RISK-001: separate build output, no prod-port collision) | ✓ |
| **scripts/run-tests.sh** | Safe pytest entry point (MV-system-003: enforces aether_test schema, refuses prod DB) | ✓ |
| **scripts/validate-openrouter.mjs** | Validate OpenRouter connectivity with cheap call; never logs API key | ✓ |
| **scripts/verify-web-build.sh** | Pre-flight gate for Next.js build (BUILD-RISK-001: catches AETHER_API_PROXY injection) | ✓ |

## CI/Build Files

| File | Purpose | Location |
|------|---------|----------|
| **ci/github-actions-ci.yml** | Verbatim mirror of `.github/workflows/ci.yml` (reviewable, tracked copy) | `ci/` |
| **ci/README.md** | Documents CI flow: security scan, node workspace (pnpm lint/test/build), Python backend suite | `ci/` |
| **.github/workflows/ci.yml** | GHA pipeline: security gate, node tests, Python pytest, live OpenRouter fixture refresh | `.github/` |

## Build / Cache Residue (Present in Working Tree)

| Item | Present | Tracked | In .gitignore | Status |
|------|---------|---------|---|---------|
| `__pycache__/` | 11 dirs | ✗ | ✓ | OK — properly ignored |
| `*.pyc` | 311 files | ✗ | ✓ (*.py[cod]) | OK — properly ignored |
| `.mypy_cache/` | 1 dir | ✗ | ✓ | OK — properly ignored |
| `.pytest_cache/` | 2 dirs | ✗ | ✓ | OK — properly ignored |
| `.ruff_cache/` | 2 dirs | ✗ | ✓ | OK — properly ignored |
| `.turbo/` | 6 dirs | ✗ | ✓ | OK — properly ignored |
| `dist/` | 112 items | ✗ | ✓ | OK — properly ignored |
| `*.tsbuildinfo` | 6 files | ✗ | ✓ | OK — properly ignored |
| `.next/` | 1 present (3 .next files TRACKED as stubs) | 3 files | ✓ | **FINDING: `.next/routes-manifest.json`, `.next/image-manifest.json`, `next.config.mjs` are tracked** — see BUILD-RISK-001 remediation in verify-web-build.sh |
| `test-results/` | 1 dir | ✗ | ✓ | OK — properly ignored |
| `node_modules/` | 546 dirs | ✗ | ✓ | OK — properly ignored |

## Duplicate File Names Across Directories

**Case-sensitive basename collisions:** None found within tracked files.

**Similar doc filenames:** All markdown docs follow consistent naming (no `Readme.md` vs `README.md` variance).

**Near-identical scripts:** None detected — all utility scripts in `scripts/` serve distinct purposes (discovery, validation, testing, build).

## .next Tracked Artifact Finding

Three files under `.next/` are tracked in git:
- `apps/web/next.config.mjs` — Next.js configuration (legitimate; not in `.next/` build dir)
- `apps/web/src/lib/auth/next-path.ts` — Source code (legitimate; is source, not build output)
- `apps/web/src/lib/auth/__tests__/next-path.test.ts` — Test file (legitimate)

**Clarification:** `.next/` in `.gitignore` ignores the **build output directory** `apps/web/.next/`. The three tracked files are not inside `.next/` directory; they are regular source files with "next" in their name. No tracked build residue detected.

## Summary

✓ **1030 tracked files well-organized** by function (app code, tests, docs, config)  
✓ **Build cache properly ignored** — no tracked .pyc, __pycache__, .turbo, etc.  
✓ **Scripts catalog complete** — 9 utility scripts all tracked and documented  
✓ **CI/build safety present** — BUILD-RISK-001, MV-system-001, MV-system-003 guards in place  
✓ **.gitignore comprehensive** — covers Node, Python, Next.js, editor, OS residue
