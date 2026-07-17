# PHASE-7 — MODEL GOVERNANCE AUDIT (GATE-26)

**Date:** 2026-07-17
**Prepared by:** doc-updater (claude-sonnet-4), compiling the `qa` sub-agent's independent governance
verification. `qa` (claude-sonnet-4) is the artifact author and sole verifying authority for this
audit's underlying findings per `aether-subscription-prompt.md` §0.3 ("Only the `qa` sub-agent may
set status VERIFIED-CLOSED") and §7 (GATE-26 owner: `qa`); doc-updater performs no independent
verification here and asserts nothing beyond what the cited artifacts already state.
**Evidence root:** `uat/reports/evidence/phase7/`
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Production:** https://5cb5f0620.abacusai.cloud

---

## 1. Headline statement

**Zero orchestrator-tier (`fable-5` / `opus-4-8`) sub-agent spawns occurred during the Phase-7 run.**
[VERIFIED-WITH-SOURCE]

Evidence:
- `uat/reports/evidence/phase7/step1-governance-verification.json` — direct filesystem inspection of
  every `.claude/agents/*.md` file in both `/home/ubuntu/.claude/agents/` (17 files) and the repo's
  `.claude/agents/` (20 files). Verdict: `"PASS"`. `inherit_violations: []`, `orchestrator_tier_violations: []`.
  No file contains `model: inherit` (`grep -r 'inherit'` = zero hits) and no file contains an
  orchestrator-tier model value (`fable`, `claude-fable-5`, `opus-4-8`, `claude-opus-4-8` —
  `grep -rniE 'fable|opus-4-8'` on `model:` lines = zero hits). The only textual matches for "fable"
  anywhere in either directory are body-text references to "fable-5 approval" as the orchestrator's
  gate-approval authority (in `arch.md`, `billing-arch.md`, `doc-updater.md`, `deployer.md`,
  `researcher.md`) — not a model self-assignment.
- `uat/reports/evidence/phase7/probe-p7-05c-governance-grep.txt` — the mandated repo-wide governance
  grep (`spawn.*fable|model.*fable|claude-fable-5`, per §7's Governance-audit recipe, line 330 of the
  operator prompt) returned `EXIT:1` (grep's no-match exit code): **zero matches**, i.e. a clean scan.

No governance kill/respawn event was ever triggered (§0.1: "Any sub-agent found running at
orchestrator tier … is a CRITICAL GOVERNANCE VIOLATION: kill immediately, log to
`PHASE7-GOVERNANCE-AUDIT.md`"). This document contains no such log entry because none occurred.

---

## 2. Sub-agent roster (§0.2) — verified model assignment

All 11 mandated roster files exist in both `/home/ubuntu/.claude/agents/` and
`<repo>/.claude/agents/` with `model:` frontmatter matching exactly, single `model:` line per file, no
duplicates (`step1-governance-verification.json`, `verification_method: "Direct filesystem inspection
via ls/grep on both agent directories"`). [VERIFIED-WITH-SOURCE]

| Agent | Tier | Model | home dir | repo dir |
|---|---|---|---|---|
| scout | T3 | `claude-haiku-4-5` | ok | ok |
| evidence | T3 | `claude-haiku-4-5` | ok | ok |
| log-tailer | T3 | `claude-haiku-4-5` | ok | ok |
| deployer | T3 | `claude-haiku-4-5` | ok | ok |
| fixer-medium | T2 | `claude-sonnet-4` | ok | ok |
| reviewer | T2 | `claude-sonnet-4` | ok | ok |
| qa | T2 | `claude-sonnet-4` | ok | ok |
| migrator | T2 | `claude-sonnet-4` | ok | ok |
| doc-updater | T2 | `claude-sonnet-4` | ok | ok |
| fixer-hard | T1 | `claude-opus-4` | ok | ok |
| arch | T1 | `claude-opus-4` | ok | ok |

No `model: inherit` in any of the 11 files. No orchestrator-tier value in any of the 11 files.

**Extra/legacy files present beyond the 11-agent roster** (`billing-arch.md`, `infra-discovery.md`,
`qa-reviewer.md`, `researcher.md`, `tester.md`, `writer-audit.md` in both dirs; `deploy.md`,
`doc-audit.md`, `fixer.md` repo-only): none use `inherit` or an orchestrator-tier value — all use
either fully-versioned tier aliases (e.g. `claude-opus-4`, `claude-haiku-4-5`) or bare tier aliases
(`sonnet`, `haiku`, `opus`). `qa`'s own adjudication: these are **not governance violations** per the
two enumerated prohibitions, though the bare-alias naming is inconsistent with the roster's
fully-versioned convention — flagged as a hygiene item only, not a finding. [VERIFIED-WITH-SOURCE]

No HTML comments (`grep '<!--'` = zero hits) and no remap/switch/override instruction language in any
agent file body — the Phase-5-style embedded-remap residue that governance audits in prior phases
specifically screen for is absent from this roster. [VERIFIED-WITH-SOURCE]

---

## 3. Separation of duties — author ≠ reviewer ≠ qa, per gap

§0.3: "Author ≠ Reviewer ≠ QA ≠ Evidence for every gap. Reviewer and QA must be different instances
from the fixer." Verified below for the 5 gaps that reached implementation in Phase-7. All three roles
were confirmed as distinct instances for every gap, cited directly from the gap record
(`phase7-gap-analysis.json`) and the review/qa artifacts. [VERIFIED-WITH-SOURCE unless noted]

| Gap | Fixer (role / model) | Reviewer (instance) | QA (instance) | Distinct? |
|---|---|---|---|---|
| GAP-P7-DEF-A | `fixer-hard`, `claude-opus-4` | `claude-sonnet-4`, "reviewer sub-agent" — `review-def-a.json`, verdict PASS (1 cycle) | `claude-sonnet-4`, "qa, fresh instance" — `step10-cluster1-gates.json` (GATE-02..06 VERIFIED-CLOSED) | Yes — different tier (opus fixer vs. sonnet reviewer/qa) and different named instances |
| GAP-P7-DEF-B | `fixer-medium`, `claude-sonnet-4` | Cycle 1: `claude-sonnet-4` reviewer — `review-def-b.json`, verdict **FAIL**. Cycle 2: `claude-sonnet-4`, explicitly "**FRESH instance**, … independent from cycle-1 reviewer and from the fixer" — `review-def-b-cycle2.json`, verdict PASS | `claude-sonnet-4`, "qa … fresh instance distinct from all fixers" — `step10-cluster2-gates.json` (GATE-07/08/09; see §5 below) | Yes — cycle-2 reviewer explicitly self-declared distinct from both the cycle-1 reviewer and the fixer; qa distinct from both |
| GAP-P7-DEF-B-PERSIST¹ | Not explicitly tagged with a role in any evidence artifact; single-file, low-risk persistence fix consistent with the `fixer-medium` complexity band (no arch blueprint, no fable-5 approval record was required, unlike the two `fixer-hard`/CRITICAL gaps) — `[INFERRED-FROM-PROMPT]`, not independently confirmed by a labeled artifact | `claude-sonnet-4`, "reviewer …, fresh instance, not the fixer" — `review-def-b-persist.json`, verdict PASS | `claude-sonnet-4` — `journey-j2-persist-aether-local.json` (GATE-07 re-verify, verdict PASS); qa-instance not explicitly self-labeled in this specific artifact, `[INFERRED-FROM-PROMPT]` from its J2-journey naming convention shared with the qa-authored `step10-cluster2-gates.json` | Reviewer explicitly confirmed distinct from fixer; fixer/qa identity inferred, not directly source-tagged |
| GAP-P7-DISCOVERY-001 | `fixer-medium`, `claude-sonnet-4` | `claude-sonnet-4`, "different instance from fixer" — `review-discovery.json`, verdict PASS (1 cycle) | `claude-sonnet-4`, "qa … fresh instance distinct from all fixers" — `step10-cluster2-gates.json` → `DISCOVERY_DURABILITY`, verdict VERIFIED-CLOSED | Yes |
| GAP-P7-ASYNC-001 | `fixer-hard`, `claude-opus-4` | Cycle 1: `claude-sonnet-4`, "fresh instance, not the fixer" — `review-async.json`, verdict **FAIL**. Cycle 2: `claude-sonnet-4`, explicitly "fresh instance — **not the fixer, not the cycle-1 async reviewer**" — `review-async-cycle2.json`, verdict PASS. (A further merge-integration review, `review-async-merge.json`, "fresh-instance-claude-sonnet-4", verdict PASS, covered the `fix/p7-async` ↔ `main` merge.) | `claude-sonnet-4`, "qa, fresh instance" — `step10-cluster1-gates.json` (GATE-11/12/13 VERIFIED-CLOSED) | Yes — every review cycle self-declares a fresh instance distinct from the fixer and from every prior reviewer cycle |

¹ GAP-P7-DEF-B-PERSIST is a real production defect discovered by `qa` during Phase-7 verification
(§5 below) — a silent no-op on the settings-email UPDATE statement, pre-existing and unrelated to
DEF-B's own fix. It is not present as a formal gap object in `phase7-gap-analysis.json` (which
predates its discovery); it is documented here from the review artifact and commit history because the
task instruction named it as one of the 5 gaps requiring separation-of-duties disclosure.

**Verdict: author ≠ reviewer ≠ qa held on every one of the 5 gaps**, with 4 of 5 gaps having every role
explicitly self-identified in its evidence artifact as a distinct instance; DEF-B-PERSIST's fixer role
is inferred rather than source-confirmed (flagged above, not concealed).

---

## 4. Escalation ladder (§0.4)

> "2 consecutive REVIEW-FAILs on one gap → escalate fixer one tier up: `haiku → sonnet → opus-4 →
> fable-5 adjudicates approach` (fable-5 never writes code). Hard cap at opus-4 for implementation."

**The escalation ladder was NOT triggered on any gap.** [VERIFIED-WITH-SOURCE]

Two gaps received exactly one REVIEW-FAIL, each followed by one bounded re-fix that then passed —
never two *consecutive* fails on the same fixer, so no tier escalation was warranted or applied:

- **GAP-P7-DEF-B:** `review-def-b.json` (cycle 1) — FAIL, 4 blocking findings (wholesale `.local`
  opening via global `SPECIAL_USE_DOMAIN_NAMES` mutation, register-surface scope creep, missing
  sharp-edge guard test). `fixer-medium` re-fixed in place (commit `7a27284`, exact-domain allowlist
  design). `review-def-b-cycle2.json` — PASS, all 4 findings closed, verified live against the actual
  shipped function. Fixer tier stayed at `sonnet-4` throughout (no escalation to `opus-4`).
- **GAP-P7-ASYNC-001:** `review-async.json` (cycle 1) — FAIL, 4 blocking findings (non-atomic
  double-refund TOCTOU, unconditional terminal-state UPDATE enabling free-run resurrection, user-wide
  refund delta over/under-refunding, advisory-lock id collision with `ensure_admin_user_columns`).
  `fixer-hard` re-fixed in place (commit `df0bda5`, atomic CTE refund + status-guarded terminal
  transitions + per-job scoped refund + new lock id). `review-async-cycle2.json` — PASS, all 4 findings
  (B1–B4) closed, re-verified with concurrency tests. Fixer tier stayed at `opus-4` throughout (already
  at the top of the non-orchestrator ladder; no further escalation possible or needed).

GAP-P7-DEF-A, GAP-P7-DEF-B-PERSIST, and GAP-P7-DISCOVERY-001 each passed review on the first cycle —
zero REVIEW-FAILs, so the ladder was never a consideration for them.

---

## 5. Model-tier routing table

| Tier | Model | Roles | Work performed in Phase-7 |
|---|---|---|---|
| T3 (cheapest) | `claude-haiku-4-5` | scout, evidence, log-tailer, deployer | Infra inventory (`step2-infra-check.txt`), probe/curl/screenshot evidence collection (the `probe-p7-*` / `journey-*` artifact set), log tailing, git commit/push/deploy/health-check steps (`deploy-persist.txt`) |
| T2 | `claude-sonnet-4` | fixer-medium, reviewer, qa, migrator, doc-updater | DEF-B fix + DEF-B-PERSIST fix + DISCOVERY-001 fix (fixer-medium band); every diff review (`review-*.json`); all production verification/gate-closure (`step10-*-gates.json`, `journey-*` verdicts); this document and `PHASE7-BLOCKED-ON-HUMAN.md` |
| T1 (hard cap) | `claude-opus-4` | fixer-hard, arch | DEF-A dual-mode credential implementation (`PHASE7-DEFECT-A-BLUEPRINT.md` → commit `5271516`); ASYNC-001 background-job architecture + implementation (`PHASE7-ASYNC-BLUEPRINT.md` → commits `d3caf89`/`06d3b7b`/`67088cb`/`df0bda5`); both blueprints required and received fable-5 approval before any fixer-hard code was written (`phase7-gap-analysis.json`, `fix_spec` fields: "APPROVED by fable-5 2026-07-17") |
| Orchestrator (prohibited from spawning) | `claude-fable-5` (xhigh) | Plans, triages, adjudicates, approves blueprints/merges — never writes code, never spawns itself as a sub-agent | 0 spawns (§1) |

---

## 6. Governance incidents

**NONE.** [VERIFIED-WITH-SOURCE — `step1-governance-verification.json`, `probe-p7-05c-governance-grep.txt`]

No kill/respawn event logged. No `inherit` usage. No orchestrator-tier sub-agent spawn. No
self-approved gate (every reviewer/qa artifact reviewed above is explicitly identified as a distinct
instance from the fixer it is grading, and `qa` alone set every `VERIFIED-CLOSED` status cited in this
document). The one honesty-relevant incident on record in the evidence root is unrelated to model
governance: `step10-cluster1-gates.json`'s `incident_disclosure` notes that a `qa` health-check Bash
command inadvertently printed the full Claude Code OAuth token value to that session's own tool-output
transcript (not to any persisted artifact — confirmed via grep across the evidence directory) during
GATE-02 verification; it is a secret-handling disclosure, not a model-governance violation, and is
recorded here only for completeness since it lives in the same evidence set this audit draws from.

---

## 7. Verdict

**GATE-26: CLEAN.**

Zero orchestrator-tier sub-agent spawns, zero `inherit` usages, exact roster-model conformance on all
11 mandated agents, author≠reviewer≠qa held on every one of the 5 implemented gaps, and the
escalation ladder was correctly available but never needed (no gap reached 2 consecutive
REVIEW-FAILs on the same fixer).
