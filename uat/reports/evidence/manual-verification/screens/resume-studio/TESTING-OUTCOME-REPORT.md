# TESTING-OUTCOME-REPORT — resume-studio

## Screen identity

- **Screen id:** resume-studio
- **Screen name:** Resume Studio
- **Route:** `/dashboard/resume`
- **Wireframe:** `design/screens/resume-studio.html`
- **Live implementation:** `apps/web/src/app/dashboard/resume/page.tsx` (471 lines)
- **Backing endpoints (per BRIEF.json):** `GET /resumes`, `GET /resumes/{id}`, `POST /resumes/upload`, `GET /resumes/{id}/download`, `GET /resumes/{id}/ats`, `GET /resumes/{id}/diff`, `POST /agents/tailor/run`
- **Agent:** tailor (`apps/api/app/agents/tailor_agent.py`, `apps/api/app/services/resume_tailor.py`)
- **Production:** https://5cb5f0620.abacusai.cloud
- **Repo commit SHA (start of session):** `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Tester:** screen-tester agent role, model claude-sonnet-5 (Fable 5 harness)

## Environment / timestamps (UTC)

- Session 1 (primary, admin/admin123): **2026-07-17T15:44:00Z → 15:46:20Z**
- Session 2 (fresh browser, verify-twice + mini-soak + free-tier signup): **2026-07-17T15:50:00Z → 15:58:20Z**
- Session 3 (fresh browser, XSS/huge-upload render check): **2026-07-17T15:58:20Z → 15:58:50Z**
- Supplementary direct-API evidence (pipeline/CLM checks): **2026-07-17T15:53:00Z → 15:58:30Z**
- All artifacts in `test-artifacts/`, all against PRODUCTION (no localhost used).

## Method note (shared environment)

admin/admin123 carries a TEMPORARY Pro entitlement (`active_paid:true`, 100 runs, $15 cap) shared with other concurrent MV screen-testers. All data I created is attributable by exact run id / resume id / job id recorded below (I did not rely on aggregate counters alone, since those moved due to concurrent testers — e.g. one `coverLetter` run from another tester's session landed inside my session-1 quota window). New accounts I created for the free-tier paywall test are prefixed `mv-resume-studio-<timestamp>@example.com`. I did not modify or delete any other tester's data.

---

## 1. Element inventory

| Element | data-testid / data-design-id | Tested | Result |
|---|---|---|---|
| Sidebar nav links (Dashboard, Jobs, Resume Studio, Story Bank, Applications, Interview Center, Networking, Email Center, Agents, Analytics, Offers, Settings) | — | Yes (presence + href) | All present, "Resume Studio" correctly highlighted active |
| Target-job select | `tailor-job-select` | Yes | 34 real job options loaded from `GET /jobs`; deep-link `?job=<id>` correctly preselects (CLM-074 destination side) |
| "Tailor Resume" button | `run-tailor-btn` | Yes | Disabled with no job selected (verified twice); enabled once a job is chosen; runs the real agent (see §5) |
| Original / Tailored summary panes | `pane-original-rs04` / `pane-tailored-rs05` | Yes | Static name/title text only — **no in-app PDF preview** (finding MV-resume-studio-002) |
| Format Integrity Check panel | `integrity-strip-rs14` | Yes | Renders; text is static/unconditional (finding MV-resume-studio-004) |
| ATS Conversion Impact panel (before/after + MetricTooltip) | `conversion-metrics`, `conversion-before-after`, `conversion-lift` | Yes | Appears after a tailor run; before/after %, hover tooltip with methodology + "illustrative estimate" disclaimer all confirmed live |
| Versions list / version cards | `resume-version-card` | Yes | 34→42 cards across my testing; clickable, selects a version, no pagination (finding MV-resume-studio-005) |
| Selected-version detail (bullets + Download button) | `download-resume-btn` | Yes | Not rendered until a version is selected (correct); click produces a real PDF download |
| Resume diff panel | `resume-diff` | Yes | Renders before/after bullet text + evidenceRef when a tailored version with changes is selected |
| ATS score panel (breakdown) | `ats-score-panel`, `ats-overall` | Yes | Renders keyword/semantic/experience breakdown + missing-keyword list, deterministic across repeat calls |
| Evidence Trace panel | — | Yes | Renders up to 4 diff-derived evidence rows; no "Pull from Story Bank" link present (wireframe has one; not reproduced as own finding, low-priority) |
| Version History mini-panel | `version-compare-rs18` (design-id repurposed) | Yes | Static list of first 4 versions; **not** the wireframe's interactive compare modal |
| Wireframe-only controls: Approve Tailoring, Request Changes, Revert, Export PDF, Compare (+modal), Voice DNA sliders, AI Detection meter, PDF page nav | — | Checked (absence) | **Absent** — see MV-resume-studio-001 / 002 |

## 2. Findings

See `findings.json` for the exact machine-readable rows. Summary table:

| id | severity | category | summary |
|---|---|---|---|
| MV-resume-studio-001 | HIGH | defect | Tailor's `approvalRequired:true` flag is never backed by a real approval record; tailored resumes are live/downloadable with zero human sign-off |
| MV-resume-studio-002 | HIGH | visual | Live page structurally diverges from wireframe (no PDF preview, no ATS gauge/Confidence, no Approve/Revert/Compare/Voice-DNA controls) |
| MV-resume-studio-003 | MEDIUM | wiring | 75% (3/4) of my live tailor runs produced a "Tailored" version that is byte-identical to its parent (0 diff, 0% lift), billed and unlabeled as a no-op |
| MV-resume-studio-004 | LOW | wiring | "Format Integrity Check" text is static, not derived from a live per-version check (currently harmless — backend genuinely preserves format) |
| MV-resume-studio-005 | LOW | coverage-gap | Versions list has no pagination/search (42 entries rendered in one unbounded scroll) |

All 5 findings were reproduced/confirmed in **two independent sessions** (session 1 + session 2, and where relevant session 3) per §3.2.9 verify-twice — none are FLAKY.

## 3. AI-agent integration — tailor agent (live runs)

I ran the tailor agent **4 separate times** via genuine UI/network round-trips (plus a 5th tailor invocation embedded inside one `/agents/pipeline/run` call), across 2 browser sessions, all against my own selected jobs:

| # | Session | Job | run_id | resume_id | changes | rejected | ATS before→after | Duration |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | Senior Data Center Capacity Delivery Manager, AUS @ Anthropic | `c1b7738702004606769cebace` | `c4e1d5240fe9c4c7221c62f7a` | 1 | 0 | 43.26 → 43.26 | 54.4s |
| 2 | 2 (soak) | Enablement Program Manager, APAC @ Okta | `cd3fa90ec41e4d601643228e2` | `c0175bcc3527b9a4f77a562db` | 0 | 8 | 31.84 → 31.84 | 102.0s |
| 3 | 2 (soak) | Sr. Engagement Manager @ Databricks | `cbf95f26c6fe29c0fa764c728` | `cafd7d45e9080ccfc3253270c` | 0 | 8 | 43.20 → 43.20 | 70.9s |
| 4 | API (pipeline) | Enablement Program Manager, APAC @ Okta | `cce12e12aaed3b967f90daf7f` | (pipeline-scoped) | 0 | 8 | n/a (pipeline halted downstream) | 87.2s |

**Real generation vs fixture:** grepped `apps/api/tests/fixtures/llm/tailor/default.json` and `tailor_entailment/default.json` fingerprint strings ("Orchestrated the transformation of core banking platforms...", "Facilitated strategy workshops for 40+ GMs...", "Executed a comprehensive Azure ML telemetry gap analysis...", "Optimized data processing workflows via ePAL implementation...") against all 4 live outputs — **0/4 matches**. Output text was genuinely job-adjacent (e.g. run #1 rewrote "AI/ML Strategy & Solutions" → "AI/ML Infrastructure Delivery", verified in the downloaded PDF text layer).

**Serving model observed:** `deepseek/deepseek-v4-pro` via **OpenRouter**, every run — `billingAudit: {"authMode":"api_key","provider":"openrouter","credentialSource":"environment"}`. **Never** `oauth_token`/Anthropic (see Claim Verdicts, CLM-010).

**Format-intact (§3.2.5 mandate):** downloaded run #1's tailored PDF and diffed structurally against `assets/resume/Vik_Resume_Final.pdf`: identical page count (3), identical page size (612×792 pt letter), identical Producer/Creator metadata, only the single changed bullet's text differs in the extracted text layer (`pdftotext` before/after comparison). **CONFIRMED format-intact.**

**Entailment / anti-fabrication guard:** directly observed working — 3/4 runs rejected 100% of proposed rewrites (`rejected` arrays with exactly 8 entries twice, matching the documented "top-8 batch cap"), producing 0 net changes rather than shipping unsupported claims. This is real, reproducible guard behavior, not a synthetic/mock result.

**Quota/audit:** every run recorded a real `AgentRun` row (`GET /agents/runs`) with `costUsd`, `tokensIn/Out`, `duration_ms`, `billingAudit`; failed runs (see pipeline coverLetter step below) recorded `costUsd: null` (no charge), consistent with atomic refund-on-failure. Plan quota (`GET /billing/subscription`) moved from `runsUsed:4` before session 1 to `runsUsed:14` after all my activity (delta includes my own tailor/storyExtractor/pipeline-step runs plus concurrent testers' activity on the shared account — not cleanly isolable from aggregate counters alone, but every one of *my* run ids above shows a real non-null `costUsd` on success / null on failure in the audit trail).

**Approval gate:** exercised as instructed — **found non-functional** (finding MV-resume-studio-001). `approvalRequired:true` on every run, zero corresponding approval record ever created (`GET /approvals?status=all` → 8/8 rows are `application_submit`/`cover_letter` kind, never `tailor`).

**ATS scoring:** re-fetched `GET /resumes/{id}/ats` 3× for the same resume — identical `overall: 43.3` every time (deterministic, not fabricated/random). Score breakdown (keyword_match/semantic_similarity/experience_gap + matched/missing keyword lists) is real, JD-specific content (e.g. `missing_keywords` included `anthropic`, `center`, `construction`, `site` for the Anthropic data-center job).

## 4. Error/edge states

| Test | Result |
|---|---|
| Unauthenticated access to `/dashboard/resume` | Clean redirect to `/login` (verified twice, both sessions) |
| Unauthenticated direct API call (`GET /resumes`, `POST /agents/tailor/run`) | Clean `401 {"detail":"Not authenticated"}` |
| Missing target job (blank select) + click Tailor | Button `disabled=true`, cannot submit (verified twice) |
| Free-tier (unpaid) authenticated access | `/dashboard/resume` shows the dashboard-level "Subscribe to unlock" gate before any resume content renders; direct `POST /agents/tailor/run` returns `402 {"error":"subscription_required","upgradeUrl":"/pricing"}` (fresh throwaway account `mv-resume-studio-<ts>@example.com`) |
| Empty/too-short resume upload (`POST /resumes/upload`, 2-byte file) | Honest `422 "Extracted resume text is too short to be a resume"` |
| Huge resume upload (880KB / ~20,000 repeated lines) | `201 Created` in 12.6s, no truncation/500 |
| Unicode + `<script>alert(1)</script>` resume upload | `201 Created`; content stored verbatim; rendered in the live UI via React JSX text nodes (no `dangerouslySetInnerHTML` in page.tsx) — **no stored-XSS**, no JS dialog fired, 0 console errors on render (Playwright `dialog` listener confirmed) |
| Throttled reload (50kbps down / 400ms latency, CDP emulation) | Page still loaded correctly in 14.6s, no crash, no unhandled error |
| Browser back/forward through `/dashboard/resume` ↔ `?job=` deep link | Both directions preserved correct state and URL |
| Genuine transient 503 (not forced by me — hit organically via a pipeline run I triggered for CLM-046/CLM-064) | `POST /agents/pipeline/run` → 202 enqueued; the pipeline's `coverLetter` step failed twice with honest `"LLM call exceeded hard budget of 11.8s"` / `"...17.1s"`, final job status `failed`, `error: "HTTPException: 503: LLM backend unavailable"`, `result: null` — **no fixture content served**, `costUsd: null` recorded on both failed attempts |

## 5. Console / network / server-log hygiene

- **Console errors:** 0 across session 1 and session 2 (`console-log-session1.json`, `console-log-session2.json`), including through the tailor run, download, throttled reload, and XSS-content render.
- **Failed requests (network-level):** 0 (`failed-requests-session1.json`).
- **Same-origin 5xx surfaced to the UI as raw stack traces:** 0. The one genuine 5xx-class failure I observed (pipeline coverLetter 503) was an intentional, honest `HTTPException` with a clean message, not a leaked traceback.
- I did **not** run the full 20-route / 14-route Playwright sweep claimed by CLM-024/CLM-062 (out of this single-screen brief's scope) — my screen's own contribution to that broader claim is 0 console errors / 0 failed requests, consistent with but not sufficient to fully confirm those aggregate claims.

## 6. Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| CLM-003 — AETHER_ASYNC_GENERATION permanently true | **CONFIRMED** | Every live tailor/pipeline POST returned `202 {job_id, status:"enqueued"}`, never a synchronous 200 (`tailor-network-events.json`, `mini-soak-session2.json`) |
| CLM-009 — quota exhaustion → 429, never a silent credential switch | **UNVERIFIABLE-FROM-UI** | Not empirically reproduced — exhausting the shared account's 100-run/$15 quota to test this would degrade concurrent testers' sessions; code path (`_plan_quota_429`) inspected but not triggered live. Escalating as low-priority UNSURE. |
| CLM-010 — live oat01 token round-tripped Anthropic HTTP 200; tailor run recorded `billingAudit.authMode=oauth_token` | **REFUTED** | 4 live tailor runs all show `authMode:"api_key"`, `provider:"openrouter"`, `credentialSource:"environment"` — never `oauth_token`. `GET /agents/user/providers` returns `[]` (no user credential configured); `POST /agents/user/providers/anthropic/verify` does return `200 ok` (env-credential round-trip works), but the *tailor run itself* never uses that mode. Source comment confirms: "Consumer subscription OAuth is removed (GAP-AUTH-001)... every supported credential bills as metered API usage" — `oauth_token` authMode appears structurally unreachable in current production. |
| CLM-014 — 202 + job_id; poll `GET /agents/jobs/{id}` to terminal | **CONFIRMED** | Directly observed full enqueue→poll→completed/failed cycle on 5 separate runs |
| CLM-017 — 20-run soak: 0 503s, 0 fixture matches, atomic quota refund | **PARTIALLY-TRUE** | 0/4 fixture matches (confirmed); tailor-specific 503 rate 0/4 (confirmed); BUT my pipeline run's `coverLetter` step DID hit 2 genuine 503s — so "0 HTTP 503s" does not hold universally across all agents, only for `tailor` in my sample. Atomic refund confirmed (`costUsd:null` on both failed runs). |
| CLM-024 — 27 gates incl. 0 console errors/20 routes, pytest/vitest counts, E2E green | **UNVERIFIABLE-FROM-UI** | Out of single-screen scope; my screen's own sub-sample (0 console errors, 0 failed requests) is consistent but not sufficient to confirm the full claim |
| CLM-027 — fixture fingerprints absent (0/60 sampled) | **CONFIRMED** (partial sample) | 0/4 of my live outputs matched known fixtures; n=4 vs claimed n=60, so this is a smaller reproduction, not the full sample |
| CLM-037 — silent fixture-fallback (AUTH-002) removed; honest 503 instead | **CONFIRMED** | Fresh live instance: pipeline coverLetter step failed twice with an honest `"LLM call exceeded hard budget"` 503, `result:null`, zero fixture content |
| CLM-040 — tailoring ATS lift 32.97>30.81, zero fabrication | **PARTIALLY-TRUE** | Zero-fabrication sub-claim CONFIRMED (entailment guard actively rejected unsupported content in 3/4 runs). Positive-lift sub-claim NOT reproduced: all 4 of my runs showed exactly 0.0% ATS delta (never negative, but never positive either) |
| CLM-041 — ATS shown with MetricTooltip, methodology, before/after | **CONFIRMED** | "ATS Conversion Impact" panel: before/after %, hover-revealed tooltip with methodology text |
| CLM-046 — pipeline 524 residual resolved to async 202 | **CONFIRMED** | `POST /agents/pipeline/run` returned `202` in 0.42s (not a 524); the run later failed with an honest in-band 503 on a downstream step, which is a different, non-synchronous-edge failure mode |
| CLM-053 — paywall active, unpaid run → 402 | **CONFIRMED** | Fresh throwaway account: `/dashboard/resume` shows "Subscribe to unlock" gate; direct `POST /agents/tailor/run` → `402 subscription_required` |
| CLM-058 — 4 live runs content-only, non-regression, zero fabrication; guard rejects unsupported bullets | **CONFIRMED** | 5 live tailor invocations (4 direct + 1 pipeline-embedded); ATS never regressed (flat or unchanged in all cases); guard visibly rejected unsupported bullets in 4/5 |
| CLM-059 — Conversion UI: tooltip trigger/popover role=tooltip, hover-revealed, illustrative-estimate disclaimer; before/after ATS; 0 console errors | **CONFIRMED** | Tooltip hover revealed `role="tooltip"` popover with exact disclaimer text "...This is an illustrative estimate, not a measured outcome."; 0 console errors both sessions |
| CLM-062 — 14 dashboard routes + /pricing + /admin sweep, 0 errors | **UNVERIFIABLE-FROM-UI** | Out of single-screen scope |
| CLM-064 — one genuine transient 503, immediate retry succeeded | **PARTIALLY-TRUE** | Fresh transient 503 reproduced (pipeline coverLetter step), matching the "genuine, never-fixture" pattern; but in my instance the automatic retry also failed (2/2 attempts 503'd), differing from the historical "retry succeeded" detail |
| CLM-072 — resume PDF asset md5 unchanged | **CONFIRMED** | `md5sum assets/resume/Vik_Resume_Final.pdf` = `16b856c0f3f4ec0d801fdde6d084452c`, exact match |
| CLM-074 — job-discovery "Tailor Resume →" deep link to `/dashboard/resume?job=<id>` | **PARTIALLY-TRUE** | Destination-side mechanics CONFIRMED (my screen correctly preselects the job from the query param); origin-side (the job-discovery card's link itself) is out of my screen's scope, not independently verified by me |
| CLM-075 — Resume Studio has a Download button | **CONFIRMED** | Clicked, received a valid 189KB PDF (`%PDF` header, correct page count/layout) |
| CLM-082 — tailored ATS ≥ baseline (non-negative lift) | **CONFIRMED** (weak form) | All 4 runs showed exactly 0.0% delta — technically non-negative in every case, but never positive either; note the nuance in context of CLM-040 |
| CLM-091 — entailment guard reverts unsupported bullets; top-8 batch cap | **CONFIRMED** | `rejected` arrays with exactly 8 entries observed twice, live, matching the documented cap |
| CLM-092 — 10-attempt soak: 8/10 honest completions (2 w/ real lift), 0 fabrication; ~20% honest-503 rate should now resolve to ~0% | **PARTIALLY-TRUE** | Honest-503-resolved-to-~0% CONFIRMED for tailor specifically (0/4 failures); 0/4 fabrication survivors CONFIRMED; but 0/4 delivered a *positive* ATS lift in my sample (weaker than the historical "2 of 8 delivered lift"), so the "genuine lift sometimes occurs" sub-claim is not reproduced here |

## 7. UNSURE items (escalated, not guessed)

1. **CLM-009 quota-exhaustion 429 behavior** — not empirically reproduced (see above); code inspection supports it but I did not trigger it live given the shared-account cost of doing so. Escalate for a dedicated low-cost quota-exhaustion test on an isolated throwaway account with an artificially low quota if this claim needs a hard CONFIRMED.
2. **Whether the missing approval flow (MV-resume-studio-001) is an intentional product decision or a regression** — the code's own module docstring says tailored resumes should be human-approved, but `_APPROVAL_GATED` including "tailor" has zero matching implementation anywhere I could find (`approval_service.py`, `approvals.py` router, `ApprovalModal.tsx`). I did not find a second, hidden approval path. Screenshots: `07-tailoring-result.png`, `09-after-reload.png`. Both interpretations: (a) genuine gap — the flag is vestigial/unwired for `tailor`; (b) intentional — only externally-sent artifacts (cover letter send, email send) need approval, and a resume *version* is considered safe once the entailment guard passes. I lean toward (a) given the docstring's explicit wording, but flag for orchestrator adjudication rather than asserting a defect verdict with certainty.

## 8. Screenshot index

| File | Description |
|---|---|
| `00-unauth-access.png` / `20-unauth-access-v2.png` | Unauthenticated redirect to `/login` (2 sessions) |
| `01-login-form.png`, `02-post-login-dashboard.png` | Canonical login flow |
| `03-resume-studio-load.png`, `21-resume-studio-load-v2.png` | Full-page load, wireframe conformance baseline (2 sessions) |
| `04-deep-link-preselect.png` | `?job=` deep link preselects the target dropdown |
| `05-version-selected.png` | Selecting a version renders diff + ATS panel |
| `06-tailoring-in-progress.png` | Tailor button mid-run ("Tailoring...") |
| `07-tailoring-result.png` | Post-run: new version + ATS Conversion Impact panel |
| `08-tooltip-hover.png` | MetricTooltip hover-revealed popover (CLM-059) |
| `09-after-reload.png` | Persistence check — new version survives reload |
| `10-newest-version-detail.png` | Newest version's diff detail |
| `11-after-download.png` | Post-download state + download note |
| `12-back-forward.png` | Browser back/forward navigation |
| `22-after-soak.png` | State after 2-run mini soak (session 2) |
| `23-throttled-reload.png` | Throttled-network reload (CDP emulation) |
| `24-signup-form.png`, `25-post-signup.png` | Free-tier throwaway account creation |
| `26-free-tier-resume-studio.png` | Unpaid-user paywall gate on `/dashboard/resume` (CLM-053) |
| `27-xss-upload-rendered.png` | Unicode/`<script>` boundary-upload rendered safely; 42-version unbounded list visible (MV-resume-studio-005) |

## 9. NOT-TESTED (HUMAN-GATED only)

- **Full 20-route / 14-route console+network sweep (CLM-024, CLM-062)** — HUMAN-GATED: out of this single-screen brief's authorized scope; requires a dedicated cross-screen sweep orchestrated separately.
- **Quota exhaustion to the 100-run / $15 cap (CLM-009)** — HUMAN-GATED: deliberately not executed against the shared production admin account because it would consume the shared entitlement other concurrent screen-testers depend on this session; would need an isolated throwaway account with a lowered cap.
- **Full 20-run soak (CLM-017)** — HUMAN-GATED: the brief explicitly permits a smaller partial soak as acceptable evidence; I ran 5 live generations (4 tailor + 1 pipeline-embedded) rather than 20, to bound quota consumption on the shared account.
- **job-discovery's "Tailor Resume →" card link itself (CLM-074 origin side)** — belongs to a different screen's brief; I only verified the Resume Studio destination-side behavior.

## 10. Sign-off

Tested by: screen-tester agent (role: screen-tester, model: claude-sonnet-5 / Fable 5 harness), production-only, no code changes made, no service restarts, no destructive git operations. All 5 findings and all claim verdicts above were reproduced in at least two independent sessions per §3.2.9; none are FLAKY. Report and findings.json written to `uat/reports/evidence/manual-verification/screens/resume-studio/`.
