# MODELS-LIVE — Final Report (G-11)

Date: 2026-07-24 · Deploy: `1443217` (prod `https://5cb5f0620.abacusai.cloud`) ·
Campaign ledger: `MODELS-LIVE-GAPS.json` (76 rows, 0 open) ·
Governance: `archive/MODELS-LIVE-GOVERNANCE-AUDIT.md` (ADR-ML-1..5)

## What shipped
Per-agent live OpenRouter model catalog: every LLM-backed agent card on
`/dashboard/agents` carries a searchable, budget-tier-grouped picker over the
live OpenRouter catalog; picked models persist per-agent and are honoured at
run time (no silent substitution — ADR-ML-4 proven-broken denylist + 422
validation); deterministic agents show an honest "fixed model" lock. Plus the
in-app "Connect with Anthropic (subscription)" OAuth flow (PKCE, encrypted
refresh, honest `needs_reauth`) and provider-routing/billing correctness.

## Gate adjudication (G-01..G-11), fresh evidence 2026-07-24
Evidence root: `uat/reports/evidence/launch-ready/models-live/` (this run) and
`uat/reports/evidence/models-live/` (campaign; bulk archived to S3 per W-D).

| Gate | Verdict | Fresh evidence |
|---|---|---|
| G-01 full catalog + picker | CLOSED | Fresh pull: app 333 vs upstream 343; delta of 10 fully accounted (5 ADR-ML-4 denylist ids + 5 unpriced `-1`-sentinel rows) — `adversarial-resample.md` |
| G-02 100% selectable/persisted | CLOSED (sampled) | 70/333 (21%, seed 20260724) PUT-selected on prod → **70/70 persisted**, original model restored — `selection-resample.json` |
| G-03 run sweep across provider families | CLOSED (sampled) | 6 live completions across 6 provider families (OpenAI/Google/DeepSeek/Meta/Anthropic/Z-AI) OK; stale id control honestly 404 upstream AND absent from app catalog — `adversarial-probe-transcripts.txt` (spend <$0.001) |
| G-04 screen matrix | CLOSED (sampled) | Campaign per-screen reports (archived, W-D) + this run's 16-route authed sweep: 0 console errors, 0 5xx — `../runtime/final-route-sweep.json` |
| G-05 zero placeholder | CLOSED | `../adversarial/placeholder-sweep.md` — 0 user-reachable placeholder/mock |
| G-06 clean observation window | CLOSED | `../runtime/final-observation-window.log` — ≥60 min, 0 hits |
| G-07 suites green | CLOSED | Fresh full suites this run — counts in `LAUNCH-READY-FINAL-REPORT.md` §G-H |
| G-08 1 branch / 0 PRs | CLOSED | `git ls-remote --heads origin` → main only; `gh pr list` → 0; stale local fix/ml-* branches verified-folded (ef7df30) and deleted this run |
| G-09 docs refreshed | CLOSED | README/model-catalog refresh + 12/12 claim spot-audit — `../adversarial/docs-spot-audit.md` |
| G-10 governance | CLOSED | `archive/MODELS-LIVE-GOVERNANCE-AUDIT.md` + `LAUNCH-READY-GOVERNANCE-AUDIT.md` |
| G-11 final report | CLOSED | This document |

## Findings
76 ledger rows: 49 VERIFIED-CLOSED, 18 VERIFIED-CLOSED-LIVE, 3
CONDITIONALLY-CLOSED (human-gated / informational), 2 CLOSED-NOT-A-DEFECT, 2
ACCEPTED-BY-OWNER (incl. `admin123` weak-login owner decision), 1
VERIFIED-GENUINE (independent authenticity review), 1 INVENTORY-READY
(dedup discovery record, consumed by W-C). **0 open.**

## Honest notes
- G-02/G-03/G-04 are closed on the launch-ready sampling floors (21% selection
  sample, 6-family probe, 16-route sweep), layered on the campaign's earlier
  full-population evidence — not a fresh exhaustive re-run of all 333 models.
- Catalog size moves with OpenRouter churn by design (357→333 across sweeps);
  the app never fabricates availability.
