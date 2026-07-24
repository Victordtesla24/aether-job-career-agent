# W-D CLEANUP REPORT — professional file management (spec §6)

Date: 2026-07-24 · Workstream: W-D · Protocol: §6.1 propose → manifest → execute → verify (no history rewrite, no force-push)

## Space reclaimed

| Scope | Before | After | Notes |
|---|---|---|---|
| Repo working tree (incl. .git, node_modules) | 1.6G | 999M | uat/ prior-phase evidence 489M + legacy evidence/ 8M + caches (~57M: .turbo 37M, .mypy_cache 19M, .pytest_cache/.ruff_cache/dist/tsbuildinfo/egg-info) evicted |
| Repo .git (residual) | 63M | 63M | HONEST NOTE: unchanged — evicted blobs remain in history by design (NO history rewrite per spec). |
| /home/ubuntu total | 6261M | 5578M | includes the repo shrink; home-level stale dirs ~137M archived+deleted |

## Manifests (this directory)

- `DELETION-MANIFEST-1.json` — repo (18 items: uat eviction 1212 tracked files, evidence/, 2 >200KB binaries → S3 pointers, caches, .env.bak-predeploy, docs/delivery consolidation, .gitignore hardening)
- `DELETION-MANIFEST-2.json` — home (11 items: 25 scratch scripts, 4 AGENTS.md backups, 3 superseded prompts, 23 doc/pdf exports, 5 stale dirs, claude_oauth_line.txt, 4 scratch id files)

## S3 archives (bucket/path only)

Repo archive (s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/repo-archive/):
- `uat-prior-phase.tar.gz` (433.6MB — all uat/ except launch-ready + reports/.gitignore)
- `evidence-legacy.tar.gz` (6.9MB)
- `launch-ready-binaries/FEAT-B1-approvals-remove-ui.png` (229KB), `launch-ready-binaries/FEAT-B2-move-menu-ui.png` (214KB) — replaced in-tree by `.s3-pointer.md` notes

Home archive (s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/home-archive/):
- `aether_wireframe_verification.tar.gz` (105.5MB), `aether_audit_evidence.tar.gz` (12.8MB), `aether_gap_audit_2026-07-12.tar.gz` (6.0MB), `aether-cleanup-mv.tar.gz`, `uat.tar.gz`, `prompt-doc-pdf-exports.tar.gz` (1.1MB)

## Deleted vs archived vs kept

**Archived-to-S3-then-deleted:** repo uat/ prior-phase contents (1212 tracked + untracked evidence dirs), repo evidence/, 2 launch-ready PNGs >200KB (pointers left), 5 home stale dirs, 23 home .docx/.pdf prompt exports.

**Deleted (no archive):** repo caches/build residue (regenerable), `.env.bak-predeploy` (shredded after verifying `.env` present + services active + prod health 200; contents never printed), 25 home scratch scripts, 4 `AGENTS.md.bkp.*`, 3 superseded prompt .md files, `claude_oauth_line.txt` (quiet secret scan: 2 pattern-matching lines counted, contents never printed, shredded — NEVER archived per spec), 3 `.stripe-*.txt`, `github_repos/clientid_ctx.txt`, untracked auto-generated .pdf/.docx siblings inside launch-ready (24).

**Kept in place (repo):** `uat/reports/evidence/launch-ready/` (active evidence, 25 tracked files + new pointers/manifests), `uat/reports/.gitignore`, docs/delivery keep-set (runbook, DECISIONS, both incidents, MODELS-LIVE-GAPS.json, LAUNCH-READY-STATE.json, PROGRESS, both traceability docs, ADR-MV-02, approved `ML-agents-cred-002-BLUEPRINT.md`), `.env`, `deploy/`, `design/`.

**Moved (repo):** 38 superseded docs/delivery artifacts → `docs/delivery/archive/` (indexed by `archive/README.md`); case-twin resolution: unapproved draft `ML-AGENTS-CRED-002-BLUEPRINT.md` archived, ADR-ML-2-approved lowercase twin stays active.

## Census items intentionally NOT touched

- All PROTECTED items: dotfiles/dot-dirs, `skills/`, `Uploads/`, `Projects/`, `hermes/`, `aether-brand/` (nginx-LIVE), `aether-setup/`, `aether-subscription-prompt-live-test.md`, `Uploads/aether-agent-final-prompt.md`, repo `.env`/`deploy/`/`design/`.
- `/home/ubuntu/aether-agent-final-prompt.md` — duplicate of the PROTECTED Uploads canonical, but not in the spec's deletion list → kept.
- `/home/ubuntu/OpenRouter-Custom-Router-Config.docx` — standalone doc with no .md sibling (not a duplicate export) → kept (also captured in the S3 export tar).
- Current prompt-source `.md` files at home (AETHER_*, PERPLEXITY_*, ADVERSARIAL_*, prompt2-*) — canonical sources, kept.
- Root strays `gap-analysis.json` / `gap_analysis_report.md` / `EXECUTION-REPORT.md` — already absent (removed in a prior phase) → no-op.
- Worktrees/stale branches — already purged in Phase 0 (see `worktree-purge.md`); review-worktree dir no longer exists.

## Verification

- pnpm build exit 0 → `aether-web` restarted immediately (runbook §0.3); services aether-api/web/worker all active; prod `/api/health` 200; web `/` 307→dashboard.
- Vitest: **567 passed / 0 failed (81 files)** — matches baseline 567.
- Pytest (via `flock /tmp/aether-pytest.lock scripts/run-tests.sh`): **1173 passed / 0 failed, 65 warnings, 29m01s** — matches baseline 1173.
- Commit `8ef28ce` pushed (repo sweep); final W-D closure commit follows this report.
