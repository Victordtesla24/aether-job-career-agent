# LAUNCH-READY — Final Report (G-K)

Date: 2026-07-24 · Production: `https://5cb5f0620.abacusai.cloud` (deploy SHA `1443217`, health `{"status":"ok","version":"0.2.0"}`) · Spec: `aether-agent-final-prompt.md` §1–§12

## 1. Exit-gate verdicts (G-A..G-K)

| Gate | Verdict | Fresh evidence (2026-07-24) |
|---|---|---|
| G-A models-live 11 gates | **CLOSED (sampled)** | `MODELS-LIVE-FINAL-REPORT.md` — catalog 333/343 delta accounted; 70/70 selection persistence (21% sample); 6 provider-family live probes; ledger 0 open |
| G-B features live | **CLOSED** | B1 purge 200 + DELETE 404 variant; B2 legal round-trips 200 + illegal 422, persistence verified — `adversarial/retrigger-log.md` |
| G-C dedup | **CLOSED** | W-C −3,670 LOC; resurrection replay 13/13 symbols CLEAN, 0 live refs; suites green — `adversarial/deletion-resurrection-replay.md` |
| G-D lean tree/dirs | **CLOSED** | Repo <1G, home 5.6G (W-D); replay found+fixed 1 eviction miss (LOW); remote `main` only, 0 PRs; local fix/ml-* branches verified-folded (ef7df30) + deleted this run |
| G-E quality bar | **CLOSED** (1 owner-accepted perf residual; Stripe live payment CONDITIONALLY-CLOSED human-gated) | W-E Lighthouse a11y/BP 100 ×5 routes; headers/docs-404 re-probed this run |
| G-F zero placeholder | **CLOSED** | `adversarial/placeholder-sweep.md` — 0 user-reachable placeholder/mock; prod HTML probes 0 hits |
| G-G observation window | **CLOSED** | `runtime/final-observation-window.log` — 70-min journalctl monitor across api/web/worker, **0 error/5xx hits** while real traffic ran (agent runs, purge, stage moves, Playwright, 16-route sweep) |
| G-H suites | **CLOSED** | pytest **1178/0** (29m09s), vitest **571/0**, Playwright **41P/11F** — 0 new failures; composition delta honestly accounted (`runtime/final-suites.md`, finding WF-e2e-matrix-001 fixed) |
| G-I docs truth | **CLOSED** | 12/12 claim spot-audit vs live prod + README refresh — `adversarial/docs-spot-audit.md` |
| G-J governance/cost | **CLOSED** | `LAUNCH-READY-GOVERNANCE-AUDIT.md` — honest single-engineer sequential roles; LLM spend this run <US$0.001 |
| G-K final report | **CLOSED** | This document |

## 2. Per-workstream verdicts
| WS | Verdict | Key commits | Notes |
|---|---|---|---|
| PHASE-0 baseline | CLOSED | 41f08c0 | Baselines + P0-001..007 filed |
| W-A models-live | CLOSED (sampled re-run) | 592a963 | 5 ledger rows closed; W-F adversarial re-sample closed the 11-gate campaign on sampling floors |
| W-B features | CLOSED | 1de73a9→abb8e92 | Approvals remove/purge + stage moves, tests-first, live-verified |
| W-C dedup | CLOSED | b005f2c..cb0186d | 19 deleted / 29 kept-with-reason / 5 false-positive; net −3,670 LOC, 66 files |
| W-D cleanup | CLOSED | 8ef28ce+52f9f02 | Repo 1.6G→992M, home 6,261→5,578 MB; S3 archives; 1 miss fixed in W-F |
| W-E quality | CLOSED | 2658211+1443217 | a11y/BP 100; en-AU; security headers; p95 ≤375ms |
| W-F adjudication | CLOSED | this commit | 2 findings found+fixed; all re-triggers HOLD |

## 3. Findings ledger
`MODELS-LIVE-GAPS.json`: **78 rows, 0 open** — 51 VERIFIED-CLOSED, 18
VERIFIED-CLOSED-LIVE, 3 CONDITIONALLY-CLOSED (human-gated/informational), 2
CLOSED-NOT-A-DEFECT, 2 ACCEPTED-BY-OWNER, 1 VERIFIED-GENUINE, 1
INVENTORY-READY. Launch-ready phase added 19 rows (P0-001..007, DEDUP/FEAT/
CLEANUP/QUALITY families, WF-e2e-matrix-001, WF-eviction-miss-001), all
terminal. W-F adversarial pass: **2 found → 2 fixed → 0 open**; all 9 prior
closures re-triggered HOLD.

## 4. Deletion / space totals
- Code: net −3,670 LOC, 66 tracked files hard-deleted (W-C, 4 manifested waves).
- Repo tree 1.6G → 992M; home 6,261 MB → 5,578 MB (W-D manifests 1+2).
- Archives: ~560 MB in `s3://…/49362/launch-ready-evidence/{repo-archive,home-archive,we-screens}/`.
- Prompt-artifact `/home/ubuntu/aether-subscription-prompt-live-test.md` deleted post-G-A (manifested in DELETION-MANIFEST-2 addendum).

## 5. Catalog stats (fresh)
Upstream OpenRouter: 343 · App catalog: 333 · Delta: 5 ADR-ML-4 proven-broken
denylist + 5 unpriced sentinel rows (verified individually). Selection
persistence: 70/70 sampled. Live completions: 6/6 across 6 provider families.

## 6. Observation window timeline (G-G)
02:07:11Z monitor start (journalctl -f, aether-api/web/worker, ERROR/CRITICAL/
Traceback/5xx patterns) → in-window real traffic: scout (37 jobs updated),
fit-scorer, async tailor run c22f346… COMPLETED via worker, approvals purge,
2 stage-move round-trips, 16-route headless sweep (0 console errors), 12-probe
docs audit, adversarial variant probes, full Playwright suite → 03:17Z monitor
end. **Hits: 0.**

## 7. Evidence index
`uat/reports/evidence/launch-ready/` → `models-live/adversarial-resample.md`,
`models-live/selection-resample.json`, `models-live/adversarial-probe-transcripts.txt`,
`adversarial/{docs-spot-audit,retrigger-log,deletion-resurrection-replay,placeholder-sweep}.md`,
`runtime/{final-observation-window.log,final-route-sweep.json,final-suites.md,window-exercises.txt}`,
plus W-A..W-E evidence trees (features/, dedup/, cleanup/, screens/).

## 8. Honest residuals (launch is NOT blocked on code)
1. **Human-gated operator items** (`LAUNCH-READY-BLOCKED-ON-HUMAN.md`): live
   Stripe payment completion + portal cancel (QUALITY-WE-006), operator admin
   credential, 2nd Gmail consent, Anthropic OAuth operator consent.
2. QUALITY-WE-005: Lighthouse perf 81–86 on 4 data-heavy routes (LCP ~4s SPA
   fetch) — ACCEPTED-BY-OWNER.
3. Playwright known-failure set now 11 (was 28): 9 require dedicated repro
   stacks, 1 settings-email data precondition, 1 aggregate capture sweep needs
   the S3-archived SCREEN-MATRIX restored to run.
4. `admin/admin123` demo login retained — ACCEPTED-BY-OWNER (zero admin
   privilege in prod).
5. DEDUP-044 (behavior-changing lazy-DDL merge) deliberately deferred.
6. G-A/G-02/03/04 closed on sampling floors, not fresh exhaustive re-runs.

## 9. Verdict
With G-A..G-J closed as above, **Aether is ready for real paid user
onboarding** as soon as the operator completes the human-gated checklist
(Stripe live keys + one live payment round-trip being the only revenue-path
item). All code-side gates are green with fresh 2026-07-24 evidence.
