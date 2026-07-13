# Phase 3 Gap Ledger
Generated: 2026-07-13 (iteration 1 in progress) | Production: https://5cb5f0620.abacusai.cloud

Discovery inputs: Playwright scout sweep of all 15 screens (0 console errors, 0 failed
requests, 0 placeholder strings, unauth redirect OK), 45-route API sweep, live agent
quality runs (tailor + cover letter) inspected against §10 output standards, static
forbidden-pattern scan (clean), and independent per-REQ audit agents.

## Summary
| Total | Open | Fixed (awaiting QA verify) | Verified Closed | Regressions |
|-------|------|---------------------------|-----------------|-------------|
| 10    | 0    | 10                        | 0               | 0           |

## Gap Records
| Gap ID | Type | Screen | Severity | Description | Code Ref | Iteration Fixed | Verified By | Evidence | Status |
|--------|------|--------|----------|-------------|----------|-----------------|-------------|----------|--------|
| GAP-P3-001 | G-QUALITY | /dashboard/cover-letters | HIGH | Generated letters used the §10.2-banned opener "I am writing to express my interest" (hardcoded), had no date line, no addressee block, no sign-off, and closed without a call-to-action | apps/api/app/agents/cover_letter_agent.py (was :80); PDF renderer made format-aware in apps/api/app/routers/cover_letters.py:480-510 | 1 | — | curls/quality-coverletter-run.json (letter text); test_cover_letter_agent.py::test_cover_letter_business_format | FIXED |
| GAP-P3-002 | G-BUG | /dashboard/resume | HIGH | Tailor validation accepted duplicate evidenceRefs — live tailored resume c4417074e8d5aa6c42d3067c5 stored two `bullet-10` rows (conflicting content) | apps/api/app/services/resume_tailor.py::_validate | 1 | — | curls/quality-tailor-diff.json + child resume bullets dump; test_guard_normalization.py::test_duplicate_evidence_ref_keeps_first_rewrite_only | FIXED |
| GAP-P3-003 | G-BUG | /dashboard/resume | MEDIUM | Tailored child version stored only the LLM-returned bullets — parent bullets not returned by the model silently vanished from the version | apps/api/app/services/resume_tailor.py::_validate (merge) | 1 | — | parent 8 bullets vs child 8-with-dup; test_guard_normalization.py::test_unreturned_bullets_survive_merge | FIXED |
| GAP-P3-004 | G-BUG | /dashboard/resume | MEDIUM | `changes` counted against bullets re-extracted from immutable base raw_text, not the selected parent's stored bullets — live run reported changes=8 while the diff endpoint showed 1 (UI told the user "8 changes applied") | apps/api/app/agents/tailor_agent.py::run (originals pass-through) | 1 | — | quality-tailor-run.json (changes:8) vs quality-tailor-diff.json (1 change) | FIXED |
| GAP-P3-005 | G-QUALITY | /dashboard/resume | MEDIUM | §10.1 violation: accepted rewrite dropped the only quantified outcome from a bullet ("Directed a program portfolio valued at over $5M…" → no figure) | apps/api/app/services/resume_tailor.py (quantified-outcome guard + SYSTEM_PROMPT) | 1 | — | quality-tailor-diff.json before/after; test_guard_normalization.py::test_rewrite_dropping_all_metrics_is_rejected | FIXED |
| GAP-P3-006 | G-DATA | /dashboard (Story Bank widget) | MEDIUM | Leftover Phase-2 test story "Audit reverify story" (0 metrics) was the newest Story row — rendered first under Latest Stories and eligible for agent consumption | production DB Story c80415ac26026a8c878626ddc | 1 | — | DELETE /api/stories/... → 204; GET /stories now 23 rows, 0 audit leftovers | FIXED (data) |
| GAP-P3-007 | G-MISSING | /dashboard (topbar, all screens) | MEDIUM | Wireframe topbar global search ("Search jobs, applications, agents…", design/screens/dashboard.html:58-61) absent — no search input anywhere in production shell | apps/web/src/components/topbar.tsx (SearchHit index + combobox) | 1 | — | scout dashboard controls.inputs=0; topbar-search.test.ts (5 tests) | FIXED |
| GAP-P3-008 | G-QUALITY | /dashboard (Market Pulse) | MEDIUM | Job Probability Score averaged only non-zero factors, silently excluding a genuinely measured 0% interview conversion (7 applied, 0 interviews) — headline inflated 46→62% | apps/api/app/routers/analytics.py (measured-factor mean) | 1 | — | curls/market-pulse.json factors [37,0,100,45] vs score 61; test_analytics.py::test_probability_counts_measured_zero_conversion | FIXED |
| GAP-P3-009 | G-QUALITY | /dashboard (Agent Activity) | LOW | SC-02-B requires last 10 AgentRun rows; page sliced to 5 with no documenting ADR | apps/web/src/app/dashboard/page.tsx:156 | 1 | — | scout-dashboard.png (5 rows) vs agent-runs.json (50 rows available) | FIXED |
| GAP-P3-010 | G-BUG | /dashboard (Market Pulse donut) | LOW | Unmapped job sources took fallback palette colors already claimed by mapped sources (Seek + Greenhouse both #FF6B35 — adjacent segments indistinguishable) | apps/api/app/routers/analytics.py (claimed-color-aware fallback) | 1 | — | curls/market-pulse.json duplicate colors; test_analytics.py::test_source_donut_colors_are_unique | FIXED |

## Verified No-Gap (checked and explicitly cleared)
| Item | Verdict |
|------|---------|
| `GET /jobs?status=saved` → 422 | NOT A GAP — UI's Saved tab filters client-side (jobs/page.tsx:268) and the API exposes a separate `saved` param; 422 is correct strict enum validation |
| Login prefill shows sarkar.vikram@gmail.com not demo@aether.dev | NOT A GAP — deliberate identity change (real workspace account), documented; swarm-prompt ground truth stale |
| LLM via direct Anthropic (not OpenRouter T1 ladder) | NOT A GAP — ADR-accepted deviation (D-0019/D-0020); §9.1-9.3 checks pass: valid model IDs, AETHER_LLM_MODE=auto, budget default 60s |
| REQ-01 SC-01-A..E | ALL PASS per independent audit agent (token 24h expiry verified live, unauth redirect verified, inline bad-password error verified) |
| Server log files | PRESENT — /var/log/aether/{api,web,discovery}.log live (§11 item resolved in an earlier phase) |
| Resume download 501 (§11) | RESOLVED in earlier session — GET /resumes/{id}/download returns real PDF (sweep: 200, application/pdf) |

_Remaining per-REQ audit results (REQ-03..REQ-15) pending from the audit swarm — this ledger updates in place._
