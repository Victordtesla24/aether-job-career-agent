# EXECUTION REPORT — PHASE 7 (Adversarial Audit + Remediation)

**Orchestrator:** `claude-fable-5` (xhigh), decision-points only — no source authored, no probes run, no gate self-approved by the orchestrator.
**Date:** 2026-07-17 · **Production:** https://5cb5f0620.abacusai.cloud (health `{"status":"ok","version":"0.2.0"}`)
**Local main HEAD at report time:** `c07e06d` (+ this report commit) · **Prompt executed:** `/home/ubuntu/aether-subscription-prompt.md` (Phase-7)

Companion documents: `PHASE7-CLAIM-LEDGER.md`, `PHASE7-GAP-ANALYSIS.md` (+ `phase7-gap-analysis.json`), `PHASE7-GOVERNANCE-AUDIT.md`, `PHASE7-BLOCKED-ON-HUMAN.md`. Evidence root: `uat/reports/evidence/phase7/`.

---

## 1. Outcome

The Phase-6 report was placed under full adversarial re-audit (15 fresh production probes, no prior claim trusted). **No Phase-6 claim was REFUTED-and-left-standing**: of 21 audited claims, 10 CONFIRMED, 8 PARTIALLY-TRUE (all dispositioned), 2 raw-REFUTED but **0 unresolved** (one → a fixed gap, one a dismissed false hypothesis), 1 UNVERIFIABLE.

Five defects were remediated end-to-end (TDD → cross-model review → deploy → live production re-verification) plus three follow-on gaps found *during* the work:

| Gap | Severity | Result |
|---|---|---|
| GAP-P7-DEF-A — Claude Code OAuth token (`sk-ant-oat01-`) rejected | CRITICAL | VERIFIED-CLOSED live |
| GAP-P7-DEF-B — settings email 422 on reserved-TLD | CRITICAL | VERIFIED-CLOSED live |
| GAP-P7-DEF-B-PERSIST — settings email save was a silent no-op (found by QA) | HIGH | VERIFIED-CLOSED live |
| GAP-P7-ASYNC-001 — `/pipeline/run` timeout / ~20% sync-503 | CRITICAL | VERIFIED-CLOSED live |
| GAP-P7-DISCOVERY-001 — paywall broke the discovery cron (found in probe) | HIGH | VERIFIED-CLOSED live |
| GAP-P7-DIR-001 — duplicate-doc consolidation | MEDIUM | VERIFIED-CLOSED |
| GAP-P7-DOCS-001 — docs refresh | MEDIUM | VERIFIED-CLOSED |
| GAP-P7-WEBLOG-001 — web-log webpack noise (no live impact) | LOW | VERIFIED-CLOSED |
| GAP-P7-VERIFY-COVER — cover-letter craft re-verify | LOW | VERIFIED-CLOSED |
| GAP-P7-FIXTURE-TRACKING — stray untracked runtime fixture | LOW | VERIFIED-CLOSED |

Four pre-seeded gaps were **rejected on fresh evidence** (not fabricated work): FIXTURE-001 (0/60 fixture fingerprints in prod), SRC-001 (33 jobs/5 sources, floor exceeded), REPO-001 (already 1 branch/0 PRs), NONPROD-001 (0 suspicious; replay-guard present).

---

## 2. What shipped (the material fixes)

- **Dual-mode Anthropic credential.** Console API key (`sk-ant-api03-`, `x-api-key`) OR Claude Code OAuth token (`sk-ant-oat01-`). **A live probe corrected the §14 blueprint:** oauth tokens require `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20` (x-api-key returns 401) — verified against the operator's real token (`claude-code-token-verification.md`). Token written to repo-root `.env` as `CLAUDE_CODE_OAUTH_TOKEN` (atomic, 600, never logged). Quota-exhaustion raises an explicit 429 — **no silent fallthrough to API-key billing** (adversarially audited). `ADR-P7-01` records the operator override of the prior OAuth-prohibited stance.
- **Internal-email allowlist + persistence.** `AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS` (default `aether.local`) via an **exact-domain** allowlist — a first attempt that opened all `*.local` was caught in review and rejected (`sub.aether.local` now correctly 422s). Separately, QA found the settings UPDATE never persisted email at all; fixed and re-verified with GET + direct-DB proof.
- **Async background generation (ARQ + Redis).** New `apps/api/app/workers/`, `BackgroundJob` table, `202 + GET /api/agents/jobs/{job_id}` polling, `aether-worker.service`, loopback Redis. Quota reserve-at-enqueue / refund-on-failure made **atomic and idempotent** after review caught 4 concurrency defects (double-refund, free-run race, over-refund, lock collision). **20-run production soak: 0/20 HTTP-503.** `AETHER_ASYNC_GENERATION` is now permanently **ON**, which eliminates the ~20% synchronous-503 problem that was Phase-6's top residual.
- **Discovery-cron paywall exemption.** The Phase-6 paywall was silently 402-ing the platform's own sourcing cron (it runs as a free-plan account). Fixed with a scoped `X-Aether-System-Run` shared-secret header (`AETHER_SYSTEM_RUN_SECRET`), constant-time compared, limited to `scout`/`fitScorer` only, audited (`systemRun=true`); a non-exempt agent with a valid secret still 402s. `ADR-P7-05`. Verified by an **unattended native timer fire** observed live.

---

## 3. Exit-gate matrix (27 core gates)

All 27 core gates **VERIFIED-CLOSED** by the independent `qa` role on the live production URL with fresh evidence (GATE-25 = this document; GATE-22 confirmed by the STEP-13 push below).

| Gate | Verdict | Gate | Verdict |
|---|---|---|---|
| 01 health | ✅ | 15 claim-ledger 0-refuted | ✅ |
| 02 oat01 accepted+stored+test | ✅ | 16 0 console errors (20 routes) | ✅ |
| 03 api03 mode unchanged | ✅ | 17 0 same-origin 5xx | ✅ |
| 04 garbage→422 both formats | ✅ | 18 0 non-prod code | ✅ |
| 05 billing authMode logged | ✅ | 19 pytest green (676) | ✅ |
| 06 no quota fallthrough | ✅ | 20 vitest green (297) | ✅ |
| 07 settings aether.local 200+persist | ✅ | 21 Playwright E2E green | ✅ |
| 08 garbage email 422 | ✅ | 22 repo 1 branch / 0 PRs | ✅ (post-push) |
| 09 reserved-TLD migrated/allowlisted | ✅ | 23 dir consolidation | ✅ |
| 10 sourcing ≥2 src ×5 fresh | ✅ | 24 docs updated | ✅ |
| 11 async 202 | ✅ | 25 this report | ✅ |
| 12 20-run soak 0×503 | ✅ | 26 governance audit clean | ✅ |
| 13 quota refund on failure | ✅ | 27 BLOCKED-ON-HUMAN updated | ✅ |
| 14 fixture absent (0/60) | ✅ | | |

**Conditionally-closed (human-gated — code+test+mock only, never faked):** GATE-18b Stripe billing (H-01/02/03), GATE-22b two Gmail consents (H-05), GATE-10b Adzuna (H-06, optional — sourcing floor already exceeded without it).

---

## 4. Governance (GATE-26 — clean)

Zero orchestrator-tier (`fable-5`/`opus-4-8`) sub-agent spawns — roster verification PASS (`step1-governance-verification.json`) + clean grep (`probe-p7-05c-governance-grep.txt`). Model-tier routing held: haiku (scout/evidence/log-tailer/deployer/infra-discovery) · sonnet (fixer-medium/reviewer/qa/migrator/doc-updater) · opus (fixer-hard/arch). **Author ≠ reviewer ≠ QA on every gap** (distinct instances, cross-model). The escalation ladder was available but never triggered: DEF-B and ASYNC each took exactly one review-fail → one bounded re-fix → pass. Full detail: `PHASE7-GOVERNANCE-AUDIT.md`.

Notable review saves (the process working): the DEF-B `*.local` over-opening, the four async refund/concurrency defects, and the async↔discovery merge-conflict integration were all caught by a reviewer/QA distinct from the fixer — none reachable by the fixer's own green suite.

---

## 5. Key commit trail (local `main`, pushed to origin at STEP-13)

`4eeb68d` docs(phase7) → `d2df452` def-a → `9e60664` def-b → `63bb514` discovery → `22f976e` async (conflict-resolved) → `431dfbd` def-b-persist → `01852ab` redis-config-fix → `c07e06d` dir-cleanup → doc-refresh + this report.

---

## 6. BLOCKED-ON-HUMAN (unchanged Phase-6 carry-overs — never faked)

| # | Item | Status |
|---|---|---|
| H-01/02/03 | Stripe account + test keys + webhook secret + 6 Price IDs + ABN/Tax | BLOCKED |
| H-04 | `AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH` in prod `.env` | BLOCKED |
| H-05 | Two Gmail OAuth consents (multi-inbox) | BLOCKED |
| H-06 | Adzuna creds | OPTIONAL (sourcing floor exceeded without it) |
| H-07 | Operator Claude Code `sk-ant-oat01-` token | **SATISFIED** (live-verified end-to-end, GATE-02) |

Exact env-var names + setup steps: `PHASE7-BLOCKED-ON-HUMAN.md`.

---

## 7. Honest residuals & security notes

- **Async is ON.** The Phase-6 top residual (~20% synchronous-503, `/pipeline/run` timeout) is resolved by the async path; a transient sync-503 can still occur only on the legacy synchronous route, which the flag now bypasses.
- **Security incidents (all LOW, logged):** (1) the operator's `sk-ant-oat01-` token and (2) test/prod `DATABASE_URL`s were each echoed into a QA sub-agent's `/tmp` session transcript via diagnostic `grep`s. **Neither is in any committed file, artifact, or pushable path** (verified by interior-slice scan; git history holds only the format prefix). The token's resting place in `.env` (600, gitignored) is by design for the worker. **Rotate the token and DB credentials only if this session's transcripts are shared externally.** Detail: `SEC-P7-token-exposure.md`.
- **Prompt-injection attempt (flagged, not acted on):** a message impersonating the user, containing only an unsolicited external URL (`horizon.srv1356245.hstgr.cloud/...`), appeared inside one sub-agent's context. The sub-agent correctly refused to fetch it; the orchestrator did not fetch it and treats it as hostile.
- **Worktree-race hardening:** the shared ledger JSON was twice clobbered by a stale sub-agent write; it was rebuilt from durable evidence and the orchestrator became its sole writer. No gate verdict rests on a clobbered value.

---

## 8. Final verification

- Production health: `curl -sf https://5cb5f0620.abacusai.cloud/api/health` → `{"status":"ok","version":"0.2.0"}`.
- Services active: `aether-api`, `aether-web`, `aether-worker`, `redis-server`.
- Backend 676 pytest / 0 fail (clean-worktree isolated), frontend 297 vitest / 0 fail, tsc + build clean.
- Repo: local `main` only, origin `refs/heads/main` only, 0 open PRs.
