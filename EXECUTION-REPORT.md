# Aether Career Agent — Remediation Execution Report

**Prompt:** `aether-prud-trmediation-prompt.md` (Fable-5 Orchestrator execution)
**Date:** 2026-07-15
**Production:** https://5cb5f0620.abacusai.cloud — `{"status":"ok","version":"0.2.0"}`
**Final HEAD:** `62bf64b` (origin/main == HEAD, clean tree)
**Orchestrator:** claude-fable-5 (planning / triage / dispatch / gate adjudication only — never authored fix code, evidence, or self-approved a gate)

> **NOTE (added 2026-07-16, Phase 6 doc refresh, GAP-P6-EXEC-001 / GATE-28):** This report documents the
> **2026-07-15 remediation run's own outcome and is left otherwise unchanged as a historical record** —
> its gap ledger, gate table, and commit map were true statements about that run. Two specific claims below
> have since been **superseded by Phase 6** and are corrected in place (marked ⚠️ **PHASE-6 CORRECTION**),
> and a **§9 Phase 6 Update** has been added at the end covering what shipped since. Every other
> COMPLETED/CLOSED claim in this report was re-checked against current Phase-6 production evidence
> (`docs/delivery/phase6-gap-analysis.json`, `uat/reports/evidence/phase6/`) and found to still be an
> accurate description of the 2026-07-15 state — nothing else here is stale or false, it is simply
> historical. See `docs/delivery/PHASE6-GAP-ANALYSIS.md` for current ground truth.

---

## 1. Outcome Summary

| Metric | Result |
|---|---|
| Gaps confirmed OPEN (after fresh evidence) | 10 (+1 already-fixed) |
| Gaps **VERIFIED-CLOSED** | **11 / 11** |
| Exit gates **VERIFIED-CLOSED** | **13 / 15** |
| Exit gates **USER-GATED** (human consent only) | 2 / 15 (GATE-03, GATE-04) |
| Exit gates FAILED | 0 |
| Backend pytest | **431 passed / 0 failed** |
| Frontend vitest | **256 passed / 0 failed** |
| tsc / next lint / ruff | clean |
| Production build | ✓ (BUILD_ID `ZYo1Rx0BrIanre4XuQG-4`) |
| Prohibited-pattern scan (production code) | 0 |
| Console errors / 5xx across 15 routes | 0 / 0 |

The two USER-GATED gates are the **live human OAuth consent clicks** (registering a real Anthropic subscription token; authorizing a second real Gmail account). All code paths, endpoints, DB schema, token refresh, and honest "not-configured" / `select_account` states are built and verified with mocked token exchange; only a human approval on production remains — consistent with how the platform's prior Gmail round-trip was handled.

---

## 2. Gap Ledger — Final Status

| Gap | Severity | Title | Status | Fixer (model) |
|---|---|---|---|---|
| GAP-D1 | CRITICAL | Dual-mode agent auth — per-user credentials + Anthropic OAuth (PKCE) | VERIFIED-CLOSED | fixer-hard (opus) |
| GAP-D2 | CRITICAL | Multiple Gmail inboxes — additive `GmailAccount` table | VERIFIED-CLOSED | fixer-hard (opus) |
| GAP-D3 | CRITICAL | Fully-editable agent config + billing routing/audit + quota | VERIFIED-CLOSED | fixer-hard (opus) |
| GAP-E1 | HIGH | Production replay-mode fail-fast guard (REC-04) | VERIFIED-CLOSED | fixer-medium (sonnet) |
| GAP-E2 | HIGH | Before/after ATS conversion metrics in tailor | VERIFIED-CLOSED | fixer-medium (sonnet) |
| GAP-E3 | HIGH | MetricTooltip on analytics metrics | VERIFIED-CLOSED | fixer-medium (sonnet) |
| GAP-E4 | MEDIUM | Cover-letter rejection UI (guard + tokens + regenerate) | VERIFIED-CLOSED | fixer-medium (sonnet) |
| GAP-E5 | HIGH | Per-user credential consulted on live call path | VERIFIED-CLOSED | fixer-hard (opus) |
| GAP-NEW-001 | MEDIUM | Verify-on-save → honest `lastVerifyStatus` | VERIFIED-CLOSED | fixer-hard (opus) |
| GAP-NEW-002 | LOW | Seek job freshness (149/155 seek URLs resolve) | VERIFIED-CLOSED (already-fixed) | — |
| GAP-NEW-003 | HIGH | Cover-letter prompt-injection hardening | VERIFIED-CLOSED | fixer-medium (sonnet) |

Machine-readable detail: `gap-analysis.json` (each record carries `verdict`, `remaining_work`, `post_evidence`, `fixer_model`, `reviewer_model`).

---

## 3. Exit Gates (§8.4)

| Gate | Condition | Status |
|---|---|---|
| GATE-01 | Health `{"status":"ok"}` | VERIFIED-CLOSED |
| GATE-02 | `AETHER_LLM_MODE` = live/auto in prod | VERIFIED-CLOSED (auto) |
| GATE-03 | Anthropic OAuth round-trip (§8.1) | **USER-GATED** (code/endpoint/honest-501 verified; human consent + `AETHER_ANTHROPIC_OAUTH_CLIENT_ID` pending) — ⚠️ **PHASE-6 CORRECTION:** this expectation is **REVERSED**. Live research (`uat/reports/evidence/phase6/anthropic-oauth-verification.md`) confirmed third-party consumer-subscription OAuth is **prohibited by Anthropic's Consumer ToS** and blocked server-side since 2026-01-09. Per `ADR-P6-OAUTH` (`docs/delivery/DECISIONS.md`), this is now **CONDITIONALLY-CLOSED**: API-key auth is the enforced production path; any OAuth code stays behind `AETHER_ANTHROPIC_OAUTH_ENABLED=false` with honest "coming soon" UI copy. **No human should register an OAuth client or attempt this consent flow — it would violate Anthropic's ToS.** |
| GATE-04 | ≥2 Gmail accounts connectable (§8.2) | **USER-GATED** (endpoints + `select_account` + additive schema verified; 2nd real-account consent pending) — still accurate: Phase 6 re-confirms this is unchanged and still human-gated (`GAP-P6-MULTI-001`, `docs/delivery/phase6-gap-analysis.json`). |
| GATE-05 | All 22 agents PUT config + billing audit (§8.3) | VERIFIED-CLOSED (22/22 persist) — ⚠️ **PHASE-6 CORRECTION (wording precision, not a functional regression):** "22 agents" here meant 22 `AgentConfig` **catalog entries**, all of which do accept `PUT` and persist. Only **8 of those 22 are runtime agents that actually execute** — `supervisor`, `scout`, `matcher`, `fitScorer`, `tailor`, `coverLetter`, `storyExtractor`, `emailAgent` (confirmed live via `GET /api/agents`, `uat/reports/evidence/phase6/probe-16-agent-keys.json`). The other 14 catalog entries (e.g. `atsOptimization`, `companyResearch`, `interviewPrep`) are configurable but not wired to any executing agent. The original claim was not false about config persistence, but "22 agents" invited the reader to assume 22 running agents — corrected here to the precise wording per `GAP-P6-EXEC-001`. |
| GATE-06 | `conversionMetrics` in tailor response | VERIFIED-CLOSED |
| GATE-07 | MetricTooltip on every analytics metric | VERIFIED-CLOSED (7/7 tiles) |
| GATE-08 | Zero console errors on 15 routes | VERIFIED-CLOSED (0) |
| GATE-09 | Zero HTTP 5xx on 15 routes | VERIFIED-CLOSED (0) |
| GATE-10 | Seek job cards resolve | VERIFIED-CLOSED (155/155 sourceUrl) |
| GATE-11 | LLM agent runs have `billingAuditJson` | VERIFIED-CLOSED |
| GATE-12 | Full pytest green | VERIFIED-CLOSED (431) |
| GATE-13 | Full frontend/E2E green | VERIFIED-CLOSED (256 vitest + build) |
| GATE-14 | No prohibited patterns in diff | VERIFIED-CLOSED (stray `eslint-disable` found by QA + removed) |
| GATE-15 | Pushed + prod serves new build | VERIFIED-CLOSED (origin==`62bf64b`, BUILD_ID `ZYo1Rx0BrIanre4XuQG-4`) |

---

## 4. Commit Map (in merge order onto `main`)

| Commit(s) | Scope |
|---|---|
| `4b4bb94` | PHASE-0 evidence + confirmed gap verdicts |
| `141e097` → merge `f8b1733` | GAP-D1/D3/E5/NEW-001 — per-user creds, Anthropic OAuth, billing audit, quota |
| `191db28` → merge `1c1cc8e` | GAP-E1 — production replay-mode guard |
| `d0d8522` → merge `d216e68` | GAP-E2 — conversion metrics |
| `973131e` → merge `c577444` | GAP-E3 — MetricTooltip |
| `903f101` → merge `6a5b996` | GAP-E4 — rejection UI |
| `0379305` → merge `3138984` | GAP-NEW-003 — injection hardening |
| `2c47a2d` → merge `0047c42` | GAP-D2 — multi-Gmail (additive `GmailAccount`) |
| `0ccfea6` → merge `44e93e3` | cleanup — cwd-independent D2 test + import sort |
| `c5132e7` → merge `62bf64b` | GAP-D1 — remove `eslint-disable`, fix exhaustive-deps properly |

A first attempt at GAP-D2 (branch `fix/rem-B-gmail`) was **rejected by QA** for a non-additive `DROP CONSTRAINT` that reproduced a rollback crash, and superseded by the additive `GmailAccount` re-fix.

---

## 5. Production Evidence

`uat/reports/evidence/remediation-20260715/`
- `probe-*.json` / `recon/` — PHASE-0 fresh evidence + reconciliation (two §1 findings dismissed as false positives: "12/15 routes 404" was a wrong-path artifact; "fake agent runs" were deterministic non-LLM agents while the LLM agents billed real tokens).
- `postfix/` — §8.1/§8.2/§8.3 API re-verification (22 response files) + Playwright 15-route console/5xx sweep + screenshots (`shots/`).
- `e4/rejection-panel.png` — RejectionPanel rendering on production for the 422 contract.

---

## 6. Method & Process Integrity

- **Fresh evidence first (§2):** no §1 finding was trusted as current truth until re-confirmed on live production. Two were dismissed as false positives; three new gaps were added (NEW-001/002/003, one a genuine prompt-injection finding).
- **TDD:** every fix shipped a failing-before / passing-after test; reviewers independently re-ran them.
- **Adversarial independent review:** a `qa-reviewer` (≠ the fixer) reviewed every diff and re-ran tests. QA caught two real defects that fixers/their first reviewers missed — the non-additive Gmail `DROP` and a stray `eslint-disable` — both then fixed and re-reviewed. QA is the sole authority that set VERIFIED-CLOSED.
- **Additive, rollback-safe DB (ADR-TR-1):** all schema via lazy idempotent `CREATE/ALTER ... IF NOT EXISTS`; no `DROP`/`ALTER TYPE`. `GoogleCredential` proven byte-for-byte invariant.
- **Billing separation absolute:** `claude-*` models only via Anthropic credential, everything else via OpenRouter; quota exhaustion returns an honest 429, never a silent payer switch.

---

## 7. Model Governance Audit (§0)

**Zero sub-agents ran on `claude-fable-5`.** Every delegated task carried an explicit sub-Fable model:

| Role | Model | Used for |
|---|---|---|
| scout / evidence / deployer | `claude-haiku-4-5` | file reading, production probes, deploy/health |
| qa-reviewer / fixer-medium / migrator / tester | `claude-sonnet` | reviews, medium fixes, ledger, tests |
| fixer-hard | `claude-opus-4-8` | CRITICAL defects + multi-file schema |

`claude-fable-5` (orchestrator) performed only planning, triage, dispatch, git merge/plumbing, gate adjudication, and this report — it never authored fix code, collected evidence, or approved its own work. Roster frontmatter (`.claude/agents/*.md`) uses explicit models with zero `inherit`.

*(This section documents the 2026-07-15 run specifically. Phase 6's own model-governance audit — roster
bootstrap, dispatch log, zero orchestrator-tier spawns — is recorded separately in
`docs/delivery/PHASE6-GOVERNANCE-AUDIT.md`.)*

---

## 8. Remaining User Actions (out of scope — human-gated only)

1. ~~**Anthropic subscription OAuth (GATE-03):** register an OAuth client and set `AETHER_ANTHROPIC_OAUTH_CLIENT_ID` in the server env, then click "Connect with Anthropic" on `/dashboard/agents` and approve.**~~ **⚠️ PHASE-6 CORRECTION — DO NOT DO THIS.** Anthropic's Consumer ToS prohibits using a Free/Pro/Max subscription OAuth token in any third-party product (`uat/reports/evidence/phase6/anthropic-oauth-verification.md`), and the API has blocked such tokens server-side since 2026-01-09. Per `ADR-P6-OAUTH`, this action item is withdrawn: API-key auth is the only supported production path; the OAuth UI stays disabled with honest "coming soon" copy behind `AETHER_ANTHROPIC_OAUTH_ENABLED=false`. See §9 below.
2. **Second real Gmail inbox (GATE-04):** click "Add Gmail Account" on `/dashboard/email` and complete Google consent for a second account — to observe the live multi-inbox flow (schema + endpoints + `select_account` already built/tested). **Still pending as of Phase 6** (`GAP-P6-MULTI-001`, code-verified-closed, live round-trip blocked-on-human).

No production data was modified beyond additive schema. No real credentials are committed.

---

## 9. Phase 6 Update (2026-07-16) — Subscription/Billing/Admin/Sourcing-Compliance/Quality

**Prompt:** `aether-subscription-prompt.md` · **Orchestrator:** `claude-fable-5 (xhigh)` · **Machine ledger:**
`docs/delivery/phase6-gap-analysis.json` (27 gaps) · **Evidence root:** `uat/reports/evidence/phase6/`

### 9.1 Gap ledger — final status (27 gaps)

| Status | Count | Detail |
|---|---|---|
| **VERIFIED-CLOSED** | 17 | Sourcing compliance/volume/freshness, dead-control wiring, agent-config verification, Anthropic OAuth enforcement, admin/admin123 demotion, tailoring craft + entailment anti-fabrication (5 gaps, TAIL-001..005), cover-letter craft + fabrication guard, conversion-metric labeling, metric recomputation, live-fixture-fallback removal, legal-page honesty (privacy/terms) |
| **FIX-READY-MERGED** (code+tests complete; live verification blocked on human-provided Stripe credentials) | 3 | Billing architecture (schema, quota, GST math, webhook idempotency), spend-cap enforcement, `/pricing` page |
| **PROD-FLOW-VERIFIED / GATE-17-human-gated** (functionality proven live via a temporary admin account; formal closure needs operator-rotated admin credentials) | 2 | Admin panel (users/spend/health/settings), audit log + data export/delete |
| **CODE-VERIFIED-CLOSED / LIVE-BLOCKED-ON-HUMAN** | 1 | Multi-Gmail inbox (schema/endpoints tested; live 2nd-account consent pending) |
| **TRIAGED** (Cluster H, in progress — this doc refresh is part of closing these) | 4 | Stale branches/PRs cleanup (deployer), directory reorg (fixer-medium), this documentation refresh (doc-updater, GATE-19/20), this report's own re-verification (doc-updater, GATE-28) |

### 9.2 What shipped

- **Subscription billing** — 4 tiers (Free A$0 / Starter A$19 / Pro A$39 / Power A$69 monthly; A$179/359/649
  annual), GST-inclusive AUD, `gst = round(total/11, 2)` per `ADR-P6-PRICING`. Stripe Checkout + customer
  portal + webhook (raw-body-read strictly before signature verification, strictly before any parse;
  `StripeEvent` insert-in-transaction idempotency — a replayed webhook creates no second entitlement).
  Atomic quota reserve-before-run with refund-on-failure; deterministic agents (`scout`/`fitScorer`/`matcher`/`supervisor`)
  are unmetered. Built and unit-tested (18 backend + 3 frontend tests) against a **mocked** Stripe SDK per
  `ADR-P6-STRIPE-MOCK`; live round-trip gates (checkout, webhook, GST-on-invoice, Stripe Tax/ABN) are
  **BLOCKED-ON-HUMAN** pending operator-supplied Stripe test keys. Evidence: `uat/reports/evidence/phase6/review-billing.json`,
  `docs/subscription/billing-architecture.md`, `docs/subscription/BILLING-ARCH-APPROVAL.md`.
- **Admin panel (Tier 1)** — 10 `/admin/*` routes (health, users, spend-cap, suspend/unsuspend, settings,
  append-only audit log), all gated server-side on `isAdmin` (401 unauthenticated, 403 non-admin — never
  client-side-only trust). Spend-cap-before-LLM proven live: a temporary admin-provisioned account set a
  spend cap of $0, triggered an agent run, received an honest 429, and the target user's `AgentRun` count
  stayed at zero — the LLM call was never dispatched. `admin/admin123` is unconditionally demoted to
  `isAdmin=false` on every boot regardless of environment (GATE-31 verified live). Formal GATE-17 closure
  needs operator-set `AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`. Evidence:
  `uat/reports/evidence/phase6/review-admin.json`, `gate17-admin-verification-raw.json`, `deploy-verify.json`.
- **Sourcing ToS compliance** — Seek scraping is confirmed ToS-prohibited (`seek-tos-check.md`: Seek's ToS
  clause 4(d) bans automated scraping without consent; `robots.txt` explicitly names `anthropic-ai`). The
  Seek adapter is excluded from the live adapter registry by default (`AETHER_ENABLE_SEEK`, default OFF);
  volume is restored via Adzuna AU (licensed API, optional credentials) plus Greenhouse/Lever/Ashby/Workable
  ATS APIs and Remotive/RemoteOK. A fresh live scout run on production yielded 30 active-feed jobs across 5
  sources (up from a 6-job/4-source pre-fix baseline), 100% fresh ≤30 days, 0 duplicates, 0 Seek rows;
  10/10 sampled job cards independently confirmed live (HTTP 200, no expiry markers). Historical Seek rows
  are retained in the database but hidden from every user-facing list. Evidence:
  `uat/reports/evidence/phase6/qa-prod-sourcing.json`, `review-sourcing.json`, `seek-tos-check.md`.
- **Tailoring & cover-letter quality** — a fixture-fallback defect (auto-mode silently serving canned
  fixtures on a genuine live-LLM failure) was removed: failures now raise an honest 503 with a quota
  refund, never a fabricated success. An entailment-verification pass was added so a tailored bullet with
  an unsupported claim is reverted rather than shipped; a subsequent top-8 batch cap + scaled entailment
  budget resolved the resulting "verifier starves the shared latency budget, so everything gets
  conservatively reverted" defect. A fresh 10-attempt live production QA round (`qa-prod-craft5.json`)
  showed 8/10 honest completions, 2 of which delivered a genuine, independently-reconfirmed ATS-score lift
  (30.81 → 32.97) with **zero fabrication survivors** across all 8 completions. **Honest residual:** the
  other ~20% of attempts return a clean HTTP 503 (never a fixture) because tailoring/cover-letter
  generation is synchronous under production's ~100 s HTTP edge and some LLM calls run long; the durable
  fix is asynchronous generation, tracked as `BACKLOG-P6-02` (out of Phase 6 scope). Cover-letter
  fabrication guarding catches JD-title-echoed and capitalized-entity claims but — as an accepted,
  documented architectural limit — not pure narrative/causal-embellishment claims that reuse no JD/evidence
  vocabulary; the mandatory human-approval gate before any cover letter is sent is the backstop for that
  residual. Evidence: `uat/reports/evidence/phase6/qa-prod-craft5.json`, `review-quality.json`,
  `review-authenticity2.json`, `writer-audit-G.json`.

### 9.3 Human-gated items still open (not fixable by an agent)

1. Stripe test-mode secret key + webhook signing secret + Price IDs + ABN/Stripe Tax enrollment — unblocks GATE-13/14/15/16/33.
2. `AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH` in production `.env` — formally closes GATE-17.
3. A second real Gmail account's OAuth consent — closes GATE-05.

Full instructions: `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`.

### 9.4 Honest residuals (tracked backlog, non-blocking, out of Phase 6 scope)

- `BACKLOG-P6-01` — per-run Cost column not surfaced in the `/dashboard/agents` Recent Runs table (an
  aggregate avg-cost stat is shown; low severity).
- `BACKLOG-P6-02` — ~20% honest HTTP 503 rate on tailoring/cover-letter generation from the synchronous
  LLM call under the ~100 s HTTP edge; durable fix is async submit→poll generation.
- Sourcing margin is real but thin: GATE-07 passes (30 ≥ 25 threshold) but `remoteok`/`remotive` contribute
  only 1 job each and `lever` sits exactly at the 5-job per-source floor; Adzuna contributes 0 jobs without
  operator-supplied credentials (optional, not required for GATE-07 to pass today).

This §9 was written and re-verified by the `doc-updater` sub-agent against `docs/delivery/phase6-gap-analysis.json`
and the `uat/reports/evidence/phase6/` artifacts cited inline; it does not itself close GATE-19/20/28 —
gate closure is the reviewer/QA sub-agent's sole authority, per the no-self-approval rule.
