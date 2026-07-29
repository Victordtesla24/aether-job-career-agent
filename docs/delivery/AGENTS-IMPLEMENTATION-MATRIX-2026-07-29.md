# Agents Implementation Matrix + Wave-4 Build Plan — 2026-07-29

Operator mandate: implement ALL agents shown on the Agents screen ("Submission, Salary … etc."), zero regression, zero quality drop, honest capability only.
Ground truth: `uat/reports/evidence/models-live/agent-catalog-inventory-2026-07-29.json` (byte-exact catalog extraction) + `real-agent-contract-file-line-index-2026-07-29.md` (new-agent contract, file:line). Scout verified @ HEAD e050d8e.

## State: 22 cards = 10 active (7 real classes; fitScorer powers 3 cards; supervisor pipeline-only) + 12 planned (backend None).

## ADR-AG-1 (orchestrator ruling, binding): implement all 12 planned cards at their HONEST capability ceiling.
Where the current card tip overpromises vs. existing integrations, the implementation ships the honest scope AND corrects the card copy in the same change. No fake success paths, no simulated integrations, degradation honest per existing conventions (coverLetterUnavailable-style shapes). Six cards need copy corrections (no browser automation / external web research / market data feeds / Calendar OAuth / adaptive-ML / push channel exists):

| card | honest implemented scope (per inventory §3) |
|---|---|
| submission | Validate submission-gate readiness → compile package (tailored resume + cover letter + answers) → mark submitted in-app → surface the job's real apply URL for the human step. NO claimed auto-form-filling. |
| companyResearch | Synthesis over the user's OWN discovered postings for that company (+LLM narrative, quality-gated); low-confidence flag on 1 posting. |
| marketTrends | Trends within the user's own discovery feed (keyword shifts, remote mix, postings/week); "not enough data" below threshold. |
| scheduling | Draft time-proposal reply text on interview-stage threads; no calendar read/write claimed. |
| learningFeedback | Read-only outcomes report (status × tailoring/fit correlations); no adaptive-learning claim. |
| notification | Real email digests (status changes, new matches) to the user via their CONNECTED GMAIL (GmailService.send, approval-gated like emailAgent); honest 409 when Gmail not connected. |

Fully buildable as-promised: compliance (surface existing guard verdicts), salaryIntelligence (own-corpus salary aggregation), interviewPrep (STAR+R grounded; revives the dead GET /interviews/prep screen), recruiterOutreach (Contact-scoped outbound via the proven emailAgent pattern), reference (Contact + additive stage field), sentimentAnalysis (thin agent over the triage LLM call).

## Build order (wave-4, AFTER wave-3 commits — agents.py is contended)
- 4A (opus): aggregation family — compliance, salaryIntelligence, marketTrends, companyResearch, learningFeedback(report) + their catalog/callable/tier wiring + copy fixes. Mostly deterministic (unmetered) + optional gated LLM narrative.
- 4B (opus): interviewPrep (REASONING, metered) — StoryEntry-grounded Q&A + writes the AgentRun rows /interviews/prep already consumes.
- 4C (opus): outreach family — recruiterOutreach, reference (additive Contact field via migrator conventions), sentimentAnalysis, notification (Gmail digest), scheduling (draft-only) — all approval-gated sends via the emailAgent pattern.
- 4D (sonnet): submission agent (gate-validated packaging + in-app submit + apply URL) + card copy corrections bundle + FE: planned→active card transitions need no FE change (server-driven status), but verify AgentConfigGrid renders run/model controls correctly for each newly-active card.
Each: test-first, cross-model adversarial review, full gates, single deploy, per-agent live verification on production (run each new agent once as admin; verify honest degradation paths for missing deps).

## Sequencing/state (as of ~09:3xZ)
- Wave-2 DEPLOYED @ main 07c0f6e (note: commit 8d87227's message says llm-only but contains ALL 11 wave-2 files — the stash-recovery had pre-staged the full index; content complete + reviewed, message imperfect).
- QA #2 running (live free-fallback proof, autopilot, email latency, feed honesty).
- Wave-3 in-fix: W3-A story-dedup re-land + GAP-P4-002 + servedByModel audit + clock hardenings (agents.py contended — wave-4 blocked on this); W3-B submit race + tailored-at-creation; W3-C gmail hardenings + NTH-05 pin + NTH-5 copy.
- Clock-skew sweep: complete, 0 HIGH/MED (2 LOW hardenings folded into W3-A).
- Hermes collision: re-occurred 09:02-09:06 (story-dedup WIP re-applied mid-commit; snapshotted + reverted; deploy #3 clean). W3-A absorbs Hermes intent. OPERATOR still must decide single-orchestrator-per-repo.
