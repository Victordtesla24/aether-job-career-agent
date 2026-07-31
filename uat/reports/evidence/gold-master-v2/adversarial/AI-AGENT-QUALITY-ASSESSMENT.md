# AI Agent Quality Assessment — GOLD-MASTER-V2 §3.3 (also closes Gate G-M)

**Date:** 2026-07-30 → 2026-07-31 (UTC timestamps below)
**Production:** https://5cb5f0620.abacusai.cloud
**Account used:** `admin` / `admin123` — OWNER account (isAdmin=true), the only account with real
production data (51 jobs, 74 applications, 32→36 stories after this probe). [VERIFIED-WITH-SOURCE]
**Method:** `curl` against the live API, bearer-token authenticated. No UI/browser used. No
third party was contacted; all output was inspected via API/PDF export only.

All claims below are tagged `[VERIFIED]` (backed by a captured request/response, quoted verbatim)
or `[INFERRED]` (my interpretation of verified evidence). No claim is asserted without one of these
tags.

---

## 0. Executive summary (read this first)

Four real, non-scripted agent runs were triggered against the live production API in a single
~7-minute monitoring window (23:53:30–00:00:04 UTC). The anti-fabrication architecture **works** —
in two of two fresh resume-tailoring runs, and in the one cover-letter run, **zero fabricated
claims were observed**; every substantive achievement in the generated cover letter traces
verbatim to the candidate's real story bank or résumé text. That is a genuine strength.

However, the assessment also surfaced one **severe, concrete, production-blocking defect** that
would embarrass and disqualify a real applicant, and a **major functional gap**: resume tailoring,
as currently guarded, produces **effectively zero net ATS-score movement** — it is not the
"tailoring loop toward 85" the product implies, it is a single-pass rewrite so conservative it
usually changes nothing at all.

**Would this be worthy of a paying customer today?** Cover-letter *content* quality: yes, with one
release-blocking identity bug fixed first. Resume tailoring: no — it does not do what its own UI
promises (move the ATS score toward the platform's own 85 target); today it is, at best, a
harmless no-op, and at worst a false sense of "your resume has been optimized" when nothing
changed.

---

## 1. Setup / trigger endpoints used

From `uat/reports/evidence/gold-master-v2/phase0/ROUTER-MATRIX.md` and
`apps/api/app/routers/agents.py` [VERIFIED-WITH-SOURCE]:

| Agent | Method + Path | Body |
|---|---|---|
| Resume tailoring | `POST /api/agents/tailor/run` | `{"job_id","resume_id"}` |
| Cover letter | `POST /api/agents/cover-letter/run` | `{"job_id","resume_id"?}` |
| Story extraction | `POST /api/agents/story-extractor/run` | `{}` (extracts from base résumé) |
| ATS score (read) | `GET /api/resumes/{resume_id}/ats?job_id=` | — |
| Poll async job | `GET /api/agents/jobs/{job_id}` | — |
| Agent run detail | `GET /api/agents/runs/{run_id}` | — |

`AETHER_ASYNC_GENERATION` is ON in production: `tailor/run` and `cover-letter/run` both return
`202 {"job_id","status":"enqueued"}` and must be polled via `/agents/jobs/{job_id}`.
`story-extractor/run` runs synchronously (200, ~12s). [VERIFIED]

Login: `POST /api/auth/login {"email":"admin","password":"admin123"}` → 200, bearer token. [VERIFIED]

---

## 2. Job selected

Two real production jobs were used (both fetched via `GET /api/jobs`):

- **Job A:** `c0fa013ab1789b46299ec7d11` — "Program Manager, Security GRC" @ Stripe.
  Baseline `fitScore=atsScore=36.33` (list) / `36.3` (live `/ats` recompute). [VERIFIED]
- **Job B:** `c0642f2dc8cbc53209d95421d` — "Senior Product Manager, Infrastructure Observability |
  Sweden | Remote" @ Grafana Labs. Baseline `atsScore=39.43` (list) / `38.4` (live recompute).
  [VERIFIED]

Résumé under test: base résumé `c16a1ba47a3823a9dcc24746b`, label "Uploaded — Vik_Resume_Final",
real candidate content (name "VIKRAM DESHPANDE", ATO/ANZ delivery-management background).
[VERIFIED]

---

## 3. Agent Run 1 & 2 — Resume Tailoring

### Run 1 — Job A (Stripe Security GRC)
- **AgentRun id:** `ca9ef6f9daaefdb31f20403a5` [VERIFIED]
- **BackgroundJob id:** `c61e73da03f0d8d327805f595`
- **Started/finished:** 2026-07-30T23:53:30.731Z → 23:54:56.063Z → **85.3s** latency [VERIFIED]
- **Result:** `changes: 0`. All 8 candidate bullets were **rejected** by the anti-fabrication
  guard. Verbatim message: *"No verifiable changes could be applied — every suggested edit was
  unsupported by your evidence, so your résumé is unchanged and you were not charged."*
  `costUsd: 0.0000` — confirmed not billed. [VERIFIED]
- **Root cause, confirmed by inspecting the guard's evidence corpus:** the word **"security"**
  does not appear anywhere in the candidate's résumé raw text (`base_resume.json` sections.raw_text
  — grepped, zero hits). [VERIFIED] The LLM repeatedly tried to append phrases like *"supporting
  security monitoring and compliance"* and *"for security-sensitive applications"* to real bullets
  — the guard correctly rejected all of them because the candidate's evidence never establishes
  cybersecurity/InfoSec work (only adjacent risk/compliance/governance work). **This is the guard
  working exactly as designed** — it declined to bluff a keyword match on a job the candidate is
  a genuine stretch for, rather than fabricate one. Good, verified anti-fabrication behavior.

### Run 2 — Job B (Grafana Labs Infra Observability, strong technical match)
- **AgentRun id:** `c3d97f1c4f98acfa5fcdab32e` [VERIFIED]
- **BackgroundJob id:** `c533b57adaf3cc9d0c2af3521`
- **Started/finished:** 23:55:47.911Z → 23:57:34.928Z → **107.0s** latency [VERIFIED]
- **Result:** `changes: 0` again, all 7 rewrites rejected, same honest no-op message, `costUsd:
  0.0000`. [VERIFIED]
- This job is a **strong technical fit** (candidate's résumé literally lists "Real-Time Telemetry"
  and "Kubernetes, Docker, Terraform, GCP/AWS" as skills; the job wants exactly that), yet still
  zero changes survived the guard. One rejected rewrite: *"Defined the **product** vision and
  owned the product backlog for cloud-native platform modernisations (**including Kubernetes**),
  ensuring 100% compliance…"* — this added a real, evidence-backed keyword (Kubernetes) but also
  swapped "technical vision" → "product vision", dropping a token that matches the job description
  (`jd_terms`). The guard's **ATS non-regression floor** (`resume_tailor.py` — a rewrite that drops
  ANY JD-matched token present in the original is rejected outright, with no allowance for a
  net-positive trade) throws out the whole bullet rather than keeping the Kubernetes addition.
  [VERIFIED-WITH-SOURCE, `apps/api/app/services/resume_tailor.py:2260-2269`] [INFERRED: this
  single-token-loss-rejects-the-whole-bullet design is the likely mechanical reason so many
  otherwise-reasonable rewrites are thrown away.]

### Historical context (not fresh runs, corroborating evidence)
Scanning the 200 most recent `AgentRun` rows (`GET /api/agents/runs?limit=200`), 7 `tailor` runs
appear in the last ~36 hours of production traffic: **5 produced `changes:0`, 2 produced
`changes:1`** (never more than 1 bullet out of 7–8 survives). [VERIFIED] For both `changes:1`
runs, `conversionMetrics` was captured directly in the AgentRun output, e.g.:

```json
"conversionMetrics": {
  "confidence": "model-estimated",
  "methodology": "Like-for-like ATS delta (shared context) × population baseline (2.5%)",
  "baselineATSScore": 40.69,
  "tailoredATSScore": 40.69,
  "estimatedConversionLift": "+0.0%"
}
```
(run `c4efdcdf5adc2d37f565a1e44`, and identically `baselineATSScore: 42.55 → tailoredATSScore:
42.55, +0.0%` for run `c5c091d22f897da2ad915698b`.) [VERIFIED] Pulling the actual diff for the
second of these (`GET /resumes/c2b64e20c8ff4e5b5a06b6745/diff`):

```
before: "Managed the delivery stream for a critical risk and compliance program, ensuring 100%
         regulatory adherence for major data initiatives."
after:  "Managed end-to-end delivery of a critical risk and compliance program, translating
         regulatory requirements into actionable plans and ensuring 100% adherence for major
         data initiatives."
```
[VERIFIED] This is a synonym-level rewording ("delivery stream"→"end-to-end delivery"), not a
keyword-coverage improvement — consistent with the ATS score staying pinned at the exact same
value to two decimal places.

### Model routing note
`resumeTailoring` is configured to `deepseek/deepseek-v4-pro` (`GET /agents/config`). [VERIFIED]
The historical `changes:1` runs report `"requestedModel": "deepseek/deepseek-v4-pro"` but
`"model": "qwen/qwen3-coder-next"` actually generated the content. [VERIFIED] This is documented,
intentional behavior in `llm_client.py` (a slow heavy-reasoning primary that can blow the request
budget falls back to a faster model so the request doesn't time out) — **not a bug** — but it does
mean the admin-visible "configured model" and the model that actually wrote the candidate's résumé
content can silently differ. [VERIFIED-WITH-SOURCE, `apps/api/app/services/llm_client.py:180-370`]

### Craft score: Resume Tailoring — **2/10**
The anti-fabrication guard itself deserves real credit (0 fabricated tokens observed across two
fresh runs and one historical diff). But as a *tailoring* feature it barely functions: 2 fresh
production runs + 5 of 7 recent historical runs = **7 of 7 recent runs either produced literally
no change, or a change that did not move the score at all**. A user cannot tell from the product
whether "Tailor" did anything meaningful — the UI has no visible signal that distinguishes "we
improved your résumé" from "we tried, and every proposed edit was thrown away." The
`noChangesApplied` honest-failure message is well-written, but it is currently the *typical*
outcome, not the exception.

---

## 4. Agent Run 3 — Cover Letter Generation (Job B, Grafana Labs)

- **AgentRun id:** `cecc7c9cd56e0bd38846110f8` [VERIFIED]
- **BackgroundJob id:** `ceb779b6611bb39629606bead`
- **Started/finished:** 23:58:37.821Z → 23:58:59.674Z → **21.4s** latency [VERIFIED]
- **Model:** `deepseek/deepseek-v4-pro` (matches configured model — no fallback this time).
  `tokensIn=13711, tokensOut=979, costUsd=0.006816`. [VERIFIED]
- **Cover-letter id:** `c15369eafaad7210d65151a6d`, status `draft`, `approvalRequired: true`
  (pending human approval — correct human-in-the-loop gate). [VERIFIED]
- **`flagged: []`** — the fabrication guard found nothing to reject.

### Verbatim output (PDF export, `pdftotext -layout` of `/cover-letters/{id}/pdf`)

```
  GAP-P7-DEF-B Probe 1785452243543
  sarkar.vikram@gmail.com

31 July 2026

Hiring Team
Grafana Labs
Re: Senior Product Manager, Infrastructure Observability | Sweden | Remote

Dear Hiring Team at Grafana Labs,

My background as a Business Analyst/Project Manager/Scrum Master is a direct match
for the Senior Product Manager, Infrastructure Observability | Sweden | Remote role at
Grafana Labs. My work architecting a COBOL/mainframe test-evidence automation
harness that cut evidence effort by ≈92% across 200+ SIT/E2E scenarios mirrors the
infrastructure observability challenge of simplifying complex monitoring experiences at
scale.

The role calls for transforming ideas and feedback into a product vision and roadmap,
curating user needs to inform engineering tradeoffs, and working closely with GTM on
differentiation. At the Australian Taxation Office I lead end-to-end delivery for the Agile
Kookaburras squad on the Payday Super reform program, owning sprint cadence, PI
Planning, and executive status reporting while convening a cross-discipline technical
war room that produced a binding automation recommendation in under three hours.
At ANZ I directed a program portfolio valued at over $5M, leading 5+ cross-functional
squads to deliver on-time releases, and facilitated workshops for 40+ GMs and
executives that improved decision-making efficiency and project clarity by >55% —
work that required the same blend of stakeholder alignment, evidence-based
prioritisation, and technical depth this role demands.

I am drawn to the challenge of charting the path forward for net-new product initiatives
like Host Monitoring while maintaining a strong roadmap for mature products, and to
the need for deep customer discovery and consensus-building across engineering
groups. My experience spans Kubernetes, GCP, and AWS, and I have built real-time
WebSocket telemetry servers handling 10k+ concurrent devices with P95 latency
under 200 ms, as well as an end-to-end Langfuse + Phoenix evaluation stack that
reduced LLM error-budget breaches by 38%. I would welcome a conversation about
how my background in delivery leadership, cloud-native infrastructure, and AI/ML
observability can contribute to the Infra O11y vision at Grafana Labs — I am available
for a call at your convenience.

Sincerely,
GAP-P7-DEF-B Probe 1785452243543
```

### 4a. Fabrication check — PASS (zero fabrication found)
Every substantive claim was cross-checked against the live Story Bank (`GET /api/stories`) and the
base résumé raw text:

| Claim in letter | Evidence source | Verified |
|---|---|---|
| "COBOL/mainframe test-evidence automation harness that cut evidence effort by ≈92% across 200+ SIT/E2E scenarios" | Story `c8f0bd084d35148040694a445` "Mainframe Test Automation at ATO – 92% Effort Reduction" + 4 near-duplicate stories | [VERIFIED] |
| "Agile Kookaburras squad on the Payday Super reform program … PI Planning" | Résumé raw_text bullet, verbatim | [VERIFIED] |
| "cross-discipline technical war room that produced a binding automation recommendation in under three hours" | Story `c436bca3c64452102624717c3` / `cfbf806089b7b3ef774c9ce5b`, near-verbatim phrase match | [VERIFIED] |
| "ANZ … program portfolio valued at over $5M, leading 5+ cross-functional squads" | Résumé raw_text bullet, verbatim | [VERIFIED] |
| "facilitated workshops for 40+ GMs and executives … decision-making efficiency and project clarity by >55%" | Résumé raw_text: *"Facilitated workshops for 40+ GMs and executives to align on strategy, improving decision-making efficiency and project clarity by >55%."* | [VERIFIED, exact match] |
| "real-time WebSocket telemetry servers handling 10k+ concurrent devices with P95 latency under 200 ms" | Story `cc2483c5a26734605083cbd86` "Real-Time WebSocket Telemetry Server – P95 Latency <200ms" | [VERIFIED] |
| "Langfuse + Phoenix evaluation stack that reduced LLM error-budget breaches by 38%" | Story `c3945828428254e0333f817ce` "LLM Evaluation Stack – 38% Fewer Error Budget Breaches" | [VERIFIED] |

**Fabrication verdict: none found.** Every number, employer, program name, and technology in this
letter traces to real résumé or story-bank content. This is a genuinely strong result for the
platform's central promise (truthfulness).

### 4b. SEVERE DEFECT — corrupted sender identity (release-blocking)
The letterhead **and** the sign-off both render the sender's name as:

```
GAP-P7-DEF-B Probe 1785452243543
```

instead of the real candidate's name ("Vikram Deshpande", per the résumé raw text). Root-caused
live: `GET /api/auth/me` on the OWNER account returns `"name": "GAP-P7-DEF-B Probe
1785452243543"` [VERIFIED] — this is leftover contamination from a past adversarial test probe
(`GAP-P7-DEF-B`, referenced in this repo's own prior Phase-7 adversarial run) that was written into
the real owner's live `User.name` field and never cleaned up. Every cover letter this account
generates — for a real job application — is signed with garbage instead of the candidate's name.
**If this letter were sent to a real employer, it would read as a broken or fraudulent
application and would be instantly disqualifying.** This is the single most serious quality defect
found in this assessment, and it sits entirely outside the LLM/fabrication-guard layer — it is a
plain data-hygiene bug in a shared identity field.

The same corrupted field also explains a second craft defect (below): `targetRole` for this user
is literally the string `"Business Analyst/Project Manager/Scrum Master"` — a job-search query,
not a professional title — and it is interpolated verbatim into the letter's opening sentence.

### 4c. Other concrete craft defects (cited exactly)
1. **Opening sentence reads like metadata, not prose:** *"My background as a Business
   Analyst/Project Manager/Scrum Master is a direct match for the Senior Product Manager,
   Infrastructure Observability | Sweden | Remote role at Grafana Labs."* Two problems in one
   sentence: (a) "Business Analyst/Project Manager/Scrum Master" is the raw `targetRole` search
   string, not how a professional would describe themselves in a cover letter opener; (b) the job
   title is quoted **including its scraped location suffix and pipe characters** ("| Sweden |
   Remote"), which no human writer would ever include in a sentence. Both are ingestion-data
   hygiene problems that leak into generated prose verbatim.
2. **No sender contact block beyond name+email** — no phone number, no city, despite the résumé
   having both (`+61 433 224 556`, Melbourne VIC). A complete business letter header would include
   them.
3. Otherwise the **business-letter structure is correct**: date ✅, recipient block with a "Re:"
   line ✅, salutation ✅, three body paragraphs (opening hook / evidence-matched body / vision +
   CTA) ✅, explicit call-to-action ("I would welcome a conversation… available for a call at your
   convenience") ✅, sign-off ✅ (name corrupted, but the slot is structurally present).
4. **Tone** is confident and specific, not boastful — no "results-driven"/"team player" filler
   clichés were observed. This matches the system prompt's explicit instruction against generic
   filler language, and it worked.

### Craft score: Cover Letter — **6/10**
Would be an 8–9/10 (strong, evidence-dense, well-structured, zero fabrication) if not for the
release-blocking identity corruption, which alone makes this output **unsendable** to a real
employer as-is. Content craft is good; identity-field data hygiene is broken.

---

## 5. Agent Run 4 — Story Extraction

- **AgentRun id:** `cffc35dfaa1cb1a522ea568cd` [VERIFIED]
- **Synchronous**, `duration_ms: 11951` → **12.0s** latency. **Model:** `qwen/qwen3-coder-next`
  (configured model for `storyExtraction` is `claude-haiku-4-5-20251001` — another
  configured-vs-actual model mismatch, same fallback mechanism as §3). `costUsd: 0.001816`.
  [VERIFIED]
- **Result:** `created: 4, dropped: 3` (dropped = exact-title duplicate, rejected by the dedup
  guard). [VERIFIED]

### Story quality (spot-checked one new story in full)
```json
{
  "title": "Recovery of Infeasible SIT Window for Payday Super Reform",
  "situation": "The SIT (System Integration Testing) window for the Payday Super reform program
                was mathematically infeasible, requiring 75+ hours of manual evidence per team
                against only 64 available hours.",
  "task": "Re-engineer the testing execution plan to make the SIT window achievable...",
  "action": "Architected and executed a six-day tiered test harness build with a formal go/no-go
             gate and a four-level contingency ladder. Collaborated cross-functionally in a
             technical war room convened under tight time pressure...",
  "result": "Converted the infeasible plan into a deliverable one, enabling on-time SIT execution
             and program continuity...",
  "metrics": {"Manual evidence per team": "75+ hours → achievable within 64-hour window"}
}
```
This is well-formed STAR content, properly quantified, evidence-grounded (matches the résumé's
SIT-window narrative). **No fabrication observed** — the content is real.

### MAJOR DEFECT — near-duplicate bloat, dedup guard too narrow
All 4 newly-created stories are **near-duplicates of stories that already existed** before this
run:
- New "Analytics Dashboard for Sprint Velocity & LLM-Retrospectives" — the story bank already had
  **4** near-identical "JIRA Analytics Dashboard…" entries before this run.
- New "Cloud-Native Core Banking Transformation – 30% Faster Delivery" — **4** near-identical
  "Cloud-Native Modernisation/Transformation at ANZ" entries already existed.
- New "Executive Re-Baselining of Test Capacity for Payday Super" — **4** near-identical
  "Executive…Re-baselining Test Capacity" entries already existed.
- New "Recovery of Infeasible SIT Window for Payday Super Reform" — **3** near-identical entries
  already existed (e.g. `c90b4e1ddc2928ed6c3273057`, wording ~95% identical to the new one above).

The dedup guard (`contentHash`, sha256 over exact byte content per Phase-0
`REFERENCE-GRAPH.md:Feature 3`) only catches **byte-identical** re-extractions; it dropped 3 of 7
candidates this run purely because their *titles* happened to be exact string repeats of prior
runs, but it let through 4 more stories that are semantically the same underlying achievement,
just reworded. The story bank went from 32 → 36 rows in this single run and is now, by my count,
**~9 distinct real achievements represented by ~36 rows** — roughly 4x redundancy. This directly
confirms and extends Phase 0's "no relevance scoring, dedup not verified" finding with a live,
reproducible failure: **re-running story extraction on an unchanged résumé keeps adding rows
instead of recognizing the underlying achievements are already captured.**

### Craft score: Story Bank — **5/10**
Per-story writing quality is genuinely good (specific, quantified, evidence-true). The score is
capped by the bloat defect: a feature that keeps duplicating a user's own achievements every time
it's re-run will make the story bank progressively less useful (harder to browse, more noise for
downstream tailoring/cover-letter selection) the longer the product is used.

---

## 6. ATS scoring reality check (Gates G-C / G-J)

- **Confirmed via `GET /analytics/ats-distribution`:** all 51 production jobs cluster in
  20–60, with the actual distribution `20-30: 1, 30-40: 24, 40-50: 25, 50-60: 1` — **zero jobs
  anywhere near the 85 target** `apps/api/app` §5.2 sets. [VERIFIED]
- **Did tailoring move the score? No — never, in every run inspected.**
  - Both fresh runs (Job A, Job B): 0 changes → no new resume version → score literally cannot
    move (no artifact exists to score). [VERIFIED]
  - The two most recent historical runs that DID produce a change (`changes:1`) both show
    `baselineATSScore == tailoredATSScore` to the decimal, `estimatedConversionLift: "+0.0%"`.
    [VERIFIED]
- **What's missing, exactly:** confirmed at the code level
  (`apps/api/app/services/resume_tailor.py:2083-2146`, `ResumeTailorService.tailor()`) — this is a
  **single LLM call, once, per invocation**. There is no loop, no re-scoring after the rewrite, no
  target-score parameter, no retry-until-threshold logic anywhere in the tailoring path. The only
  scoring-adjacent logic is a **non-regression floor** inside the validation guard (a rewrite that
  would *drop* a JD-matched keyword the original had is rejected) — this can only ever hold the
  score flat or (in principle) raise it by one accepted bullet; it cannot and does not drive the
  score upward toward any target. Phase 0's `REFERENCE-GRAPH.md` conclusion ("no score-aware
  loop exists") is confirmed exactly by this run of live evidence, and this assessment adds the
  concrete numbers Phase 0 didn't have: **0.0% observed uplift across every tailoring run
  inspected, live or historical.**
- **Realistic ceiling of the current implementation:** given (a) the single-pass, no-loop
  architecture, (b) a guard that rejects a whole bullet over one dropped token even when the
  bullet nets positive, and (c) most résumé/JD pairs in this account's real data sitting far
  outside the candidate's genuine keyword vocabulary (confirmed for Job A's "security" gap) — the
  realistic ceiling today is **low single-digit point movement at best, and 0 points in the
  common case**, nowhere near closing a ~40 → 85 gap. Reaching 85 would require an actual
  iterative, score-aware rewrite loop (generate → rescore → target missing high-value keywords →
  regenerate → re-validate), which does not exist in the current codebase.

---

## 7. Honest-failure check (item 8)

**PASS.** Both zero-change tailoring runs failed **honestly**: explicit `noChangesApplied: true`,
a clear human-readable message explaining why, `costUsd: 0.0000` (confirmed not billed for a
no-op), and no fabricated or canned content was substituted. This is exactly the "honest error"
behavior GOLD-MASTER-V2 asks for, and it worked correctly under live, adversarial-adjacent
conditions (candidate genuinely lacking "security" vocabulary for a security-titled role).
[VERIFIED]

---

## 8. AgentRun evidence for Gate G-M (≥3 real runs, clean window)

| # | Agent | AgentRun id | Started (UTC) | Finished (UTC) | Latency | Model | Cost | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | tailor | `ca9ef6f9daaefdb31f20403a5` | 23:53:30.731 | 23:54:56.063 | 85.3s | n/a (0 changes) | $0.0000 | completed |
| 2 | tailor | `c3d97f1c4f98acfa5fcdab32e` | 23:55:47.911 | 23:57:34.928 | 107.0s | n/a (0 changes) | $0.0000 | completed |
| 3 | coverLetter | `cecc7c9cd56e0bd38846110f8` | 23:58:37.821 | 23:58:59.674 | 21.4s | deepseek/deepseek-v4-pro | $0.0068 | completed |
| 4 | storyExtractor | `cffc35dfaa1cb1a522ea568cd` | 00:00:04.888 | 00:00:16.839 (createdAt + duration_ms) | 12.0s | qwen/qwen3-coder-next | $0.0018 | completed |

All 4 in a single clean 7-minute window (2026-07-30T23:53:30Z → 2026-07-31T00:00:17Z), plus two
automatic background-sweep runs (`fitScorer` `c5a076842b0007880412cea6b`, `scout`
`c8ff7a93ab9aaadca484442f1`) fired in the same window, confirming the scheduled board-sweep is
alive in production concurrently. **4 genuine, user/API-triggered runs ≥ the required 3.**
[VERIFIED]

---

## 9. Overall verdict

**Is this worthy of a paying customer today? Conditionally no — one blocking bug away from yes on
letters, and a real gap on tailoring.**

1. **Anti-fabrication architecture: genuinely strong.** Zero fabricated claims found across 4 live
   runs and 1 historical diff. The guard correctly declined to bluff a "security" keyword match
   the candidate doesn't have (Job A), and every number in the cover letter traced to real
   evidence. This is the platform's most important promise, and it held up under scrutiny.
2. **Resume tailoring: does not do what it implies.** 7 of 7 recent runs (2 fresh + 5 historical)
   moved the ATS score by exactly 0.0%. There is no score-aware loop; there was never going to be
   one at 40→85 without one. Users are not told this — the UI has no visible signal distinguishing
   "materially tailored" from "guard rejected everything, nothing changed."
3. **Cover letters: one release-blocking bug.** Content quality is genuinely good — specific,
   evidence-dense, correctly structured, zero fabrication, correct human-approval gate — but every
   letter is signed with a corrupted test-probe string (`GAP-P7-DEF-B Probe 1785452243543`)
   instead of the real candidate's name, in both the letterhead and the sign-off. This is a
   one-field data-hygiene fix (`User.name` for the owner account), not an LLM/prompt problem, and
   it is trivial to reproduce (`GET /api/auth/me`) — but as of this probe it is live in production
   and would sink a real application today.
4. **Story bank: real content, real bloat.** No fabrication; genuinely well-written STAR entries;
   but re-running extraction on an unchanged résumé keeps adding near-duplicate rows (32→36 in one
   run, ~4x redundancy on the underlying ~9 achievements) because dedup only catches exact-string
   repeats, not paraphrases.

**Would this improve a real candidate's interview odds?** The cover letter, once the name bug is
fixed, plausibly yes — it is specific and well-matched to the JD. The tailored résumé, as
currently shipped, plausibly **no** — in the common case it is byte-identical to the untailored
one, so it cannot move an ATS ranking or a human reader's impression at all.

---

## Compact JSON summary

```json
{
  "artifact": "uat/reports/evidence/gold-master-v2/adversarial/AI-AGENT-QUALITY-ASSESSMENT.md",
  "agent_runs": [
    {"agent": "tailor", "run_id": "ca9ef6f9daaefdb31f20403a5", "model": null, "latency_s": 85.3, "ok": true},
    {"agent": "tailor", "run_id": "c3d97f1c4f98acfa5fcdab32e", "model": null, "latency_s": 107.0, "ok": true},
    {"agent": "coverLetter", "run_id": "cecc7c9cd56e0bd38846110f8", "model": "deepseek/deepseek-v4-pro", "latency_s": 21.4, "ok": true},
    {"agent": "storyExtractor", "run_id": "cffc35dfaa1cb1a522ea568cd", "model": "qwen/qwen3-coder-next", "latency_s": 12.0, "ok": true}
  ],
  "job_tested": {"jobA": "c0fa013ab1789b46299ec7d11 (Stripe, Program Manager Security GRC)", "jobB": "c0642f2dc8cbc53209d95421d (Grafana Labs, Sr PM Infra Observability)"},
  "ats_before": {"jobA": 36.3, "jobB": 38.4},
  "ats_after": {"jobA": 36.3, "jobB": 38.4, "note": "0 changes applied in both fresh runs; historical changes:1 runs also show 0.0% movement (40.69->40.69, 42.55->42.55)"},
  "score_moved": false,
  "loop_iterates": false,
  "fabrication_detected": false,
  "fabrication_evidence": [],
  "craft_scores": {"resume": 2, "cover_letter": 6, "story": 5},
  "honest_failure_ok": true,
  "verdict": "Anti-fabrication guard is genuinely strong (0 fabrication across 4 live runs). Resume tailoring produces 0.0% ATS movement in 7/7 recent runs (no score-aware loop exists in code). Cover-letter content is specific and well-evidenced but is signed with a corrupted identity string (User.name = 'GAP-P7-DEF-B Probe 1785452243543') on both the letterhead and sign-off -- a release-blocking data-hygiene bug, confirmed live via GET /api/auth/me. Story extraction produces genuine, well-formed STAR content but re-extraction on an unchanged resume creates near-duplicate rows (32->36 in one run) because dedup only catches byte-identical repeats. Not yet worthy of a paying customer as-is; the identity bug and the tailoring no-loop gap are the two items standing between this and a credible product."
}
```
