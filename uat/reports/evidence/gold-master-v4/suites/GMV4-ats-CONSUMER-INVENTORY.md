# GMV4-ats-002 — EXHAUSTIVE consumer inventory of the degraded-ATS defect class

Author: `fixer-hard` (opus), §22 STEP 3 ROUND 4, per ESC-002.
Repo: /home/ubuntu/github_repos/aether-job-career-agent. HEAD `b69481f`.
Written 2026-08-01, **BEFORE any edit of this round** (ESC-002 mandate (a)).

Greps run over `apps/api/app` and `apps/web/src` (tests excluded from the fix
surface but scanned) for: `semantic_similarity`, `semanticSimilarity`,
`semantic_path`, `semanticPath`, `semantic_degraded`, `semanticDegraded`,
`scoringDegraded`, `baselineDegraded`, `tailoredDegraded`, `conversionMetrics`,
`baselineATSScore`, `tailoredATSScore`, `estimatedConversionLift`, `fitScore`,
`ats_score`, `atsScore`, `overall`, `culture_fit`, `cultureFit`, `north_star`,
`ATSScore`, `sem_trusted`, `_DEGRADED_SEMANTIC`.

## Trust rule
`ATSScore.semantic_path in ("local","hf_api")` = genuine. Everything else
("degraded", "untracked", unknown, absent) = NOT a measurement.
`overall = 0.4*keyword + 0.4*semantic + 0.2*experience` — so **`overall` is
itself 40% placeholder when semantic is degraded**, and every value derived
from `overall` inherits contamination. Contamination is transitive; this
inventory traces it to 3 hops.

## Contamination graph (the thing rounds 1-3 never drew)
```
semantic (placeholder 50.0 when degraded)
├─1─ ATSScore.overall                     (40% contaminated)
│    ├─2─ ATSScore.requires_review        (overall < REVIEW_THRESHOLD)
│    ├─2─ jobs.py "Role Alignment" dim    (= overall)          ← LEAK
│    ├─2─ jobs.py "Career Growth" dim     (0.6*sen + 0.4*ovr)  ← LEAK
│    ├─2─ jobs.py "North Star Align"      (0.6*ovr + 0.4*sem)  flagged
│    ├─2─ resumes.py /ats "overall"       → resume/page.tsx:605 (note-flagged)
│    ├─2─ tailor_agent baseline/tailoredATSScore → estimatedConversionLift
│    │    └─3─ jobs/page.tsx:570-572 → job.fitScore            ← LEAK (round 3)
│    │         └─4─ MatchRing 1125/1286, apply gate 1632, row 1847
│    └─2─ fit_scorer.py:65 → DB Job.fitScore / Job.atsScore    ← LEAK (new)
│         └─3─ every list/board/analytics/offer/notification read (below)
├─1─ jobs.py "Industry Match"             flagged
├─1─ jobs.py "Culture Fit"                flagged
├─1─ jobs.py risk "Domain overlap"        withheld when untrusted
├─1─ jobs.py narrative                    branch-flagged
└─1─ tailoring_loop per-iteration guard   flagged (any_degraded)
```

## Row inventory
`file:line | symbol | reads number? | checks path? | renders to user? | verdict`

### Backend — source of truth
- `services/ats_engine.py:54-60` | `_DEGRADED_SEMANTIC_SCORE` | def | n/a | no | SAFE (source)
- `services/ats_engine.py:127-159` | `ATSScore.semantic_path` | def | n/a | no | SAFE (source)
- `services/ats_engine.py:282-317` | `ATSEngine.score` | writes | sets path | no | SAFE
- `services/ats_engine.py:355-390` | `_semantic_similarity_detailed` | writes | sets path | no | SAFE

### Backend — consumers
- `routers/resumes.py:179-189` | `semantic_similarity`+`semantic_path`+`semantic_degraded` | y | y (whitelist) | via UI | SAFE
- `routers/resumes.py:184` | `"overall"` | y | ships path alongside | via UI | SAFE (client must gate; it does, by note)
- `routers/resumes.py:194` | `requires_review` | y | NO | not rendered | N-A (no consumer; see UNSURE-2)
- `routers/jobs.py:304-325` | `sem`,`sem_path`,`sem_trusted` | y | y (whitelist) | — | SAFE
- `routers/jobs.py:342` | dim "Industry Match" | y | y | y | SAFE
- `routers/jobs.py:344` | dim "Culture Fit" | y | y | y | SAFE
- `routers/jobs.py:349` | dim "North Star Align" | y | y | y | SAFE
- **`routers/jobs.py:343`** | dim **"Role Alignment"** = `overall` (40% placeholder) | y | **NO** | y | **UNGUARDED-2**
- **`routers/jobs.py:329,347`** | dim **"Career Growth"** = `0.6*seniority+0.4*overall` | y | **NO** | y | **UNGUARDED-2**
- `routers/jobs.py:365,368-378` | risk row + narrative | y | y | y | SAFE
- `routers/jobs.py:401` | `semanticDegraded` | flag | y | y | SAFE
- `agents/tailor_agent.py:124-130` | `baseline/tailoredDegraded`, `scoringDegraded` | y | y (whitelist) | via UI | SAFE
- `agents/tailor_agent.py:519-520` | `requires_review` OR scoringDegraded | y | y | via UI | SAFE
- `services/tailoring_loop.py:185-228` | `semanticPath`, `any_degraded` | y | y (deliberate `== "degraded"`, proven prod-safe round 3) | via UI | SAFE — DO NOT CHANGE
- **`agents/fit_scorer.py:65`** | `update_fit_score(id, score.overall, score.overall)` | y | **NO** | y (persisted, then everywhere) | **UNGUARDED-3 — provenance DESTROYED at write; no column exists to carry it**
- `repositories/job.py:412-416` | `update_fit_score` | writes | no param exists | — | UNGUARDED-3 (same defect, writer side)
- `routers/agents.py:989,2371` | `"conversionMetrics": None` | no | n/a | n/a | N-A
- `routers/agents.py:2380` | pass-through | no | n/a | n/a | SAFE
- `workers/tasks.py:235` | `"conversionMetrics": None` | no | n/a | n/a | N-A

### Backend — downstream readers of the DB `fitScore`/`atsScore` (all inherit UNGUARDED-3)
`routers/analytics.py:157-159,397,470,708` (avg fit, ATS histogram) ·
`routers/applications.py:30` · `routers/workspaces.py:59,243` ·
`services/offers.py:119-147` · `agents/matcher_agent.py:47-56` ·
`agents/notification_agent.py:367-387,433` · `agents/company_research_agent.py:206,257` ·
`agents/learning_feedback_agent.py:109,155-167` · `workers/board_sweep.py:143,224,394,515,531`.
Verdict for all: **N-A-PENDING** — none can check provenance because none is
persisted. Fixing them is meaningless until UNGUARDED-3's storage gap is closed.

### Frontend
- `lib/api/resumes.ts:51-70` | `ConversionMetrics` (numbers + 3 optional flags, siblings) | type | optional flags = fail-open | — | **STRUCTURAL WEAKNESS** (the shape that permitted the round-3 leak)
- `lib/api/jobs.ts:34-35` | `fitScore`,`atsScore` nullish | type | no flag exists | y | UNGUARDED-3 (type has nowhere to put it)
- `app/dashboard/resume/page.tsx:217` | `semanticTrusted` whitelist | y | y | y | SAFE
- `app/dashboard/resume/page.tsx:223` | `conversionDegraded` | y | y | y | SAFE
- `app/dashboard/resume/page.tsx:393,397,405` | before/after/lift | y | y (em-dash) | y | SAFE
- `app/dashboard/resume/page.tsx:605` | `ats.overall` headline | y | NO inline check, but co-located `semantic-degraded-note` (:643) explicitly says "the overall score above should be treated as directional" | y | SAFE-BY-NOTE (ADR "flagged")
- `app/dashboard/resume/page.tsx:615` | `ats.semantic_similarity` | y | y | y | SAFE
- `app/dashboard/jobs/page.tsx:227` | RadarChart floor | y | y | y | SAFE
- `app/dashboard/jobs/page.tsx:505-506` | `insightsSemanticTrusted` whitelist | y | y | y | SAFE
- `app/dashboard/jobs/page.tsx:1333-1364` | dimension grid badge/em-dash | y | y (`d.degraded`) | y | SAFE **but only as strong as the server's `degraded` keys → UNGUARDED-2 defeats it for 2 rows**
- `app/dashboard/jobs/page.tsx:1372-1379` | honest note | flag | y | y | **PARTIALLY FALSE** — names only "Industry Match, Culture Fit and North Star Align", affirmatively excluding the 2 rows of UNGUARDED-2
- **`app/dashboard/jobs/page.tsx:570-572`** | `out.conversionMetrics.tailoredATSScore` → `job.fitScore` | y | **NO** | y | **UNGUARDED-1 (round-3 finding)**
- `app/dashboard/jobs/page.tsx:1125,1286,1632,1847` | `job.fitScore` renders (card ring, detail ring, **apply-confirmation gate**, list row) | y | no flag exists | y | UNGUARDED-1 downstream + UNGUARDED-3 downstream
- `app/dashboard/page.tsx:151-154,373-379` | avg fit + per-job fit | y | no | y | UNGUARDED-3 downstream
- `app/dashboard/applications/page.tsx:917-923,1096-1110` | `fitScore`/`atsScore` chips | y | no | y | UNGUARDED-3 downstream
- `components/applications/tracker-lib.ts:220-253` | fit/ats maps | y | no | y | UNGUARDED-3 downstream
- `components/offers/OfferCard.tsx:91-99` + `offers-lib.ts:142` | `fitScore` (null ⇒ "Pending") | y | no | y | UNGUARDED-3 downstream
- `lib/api/workspaces.ts:343` | `fitScore` | y | no | y | UNGUARDED-3 downstream
- `components/agents/Orchestration.tsx`, `lib/agents-feedback.ts`, `components/dashboard/feed.ts`, `app/dashboard/agents/page.tsx:280`, `app/dashboard/jobs/page.tsx:257,386,701,958-961` | agent NAME "fitScorer" / sort key / filter only | no | n/a | no number claim | N-A

## UNGUARDED COUNT BEFORE THIS ROUND'S FIX
**3 distinct defects** (`UNGUARDED-1`, `UNGUARDED-2`, `UNGUARDED-3`), spanning
**7 primary sites** (`jobs/page.tsx:570-572`; `jobs/page.tsx:1372` note;
`jobs.py:343`; `jobs.py:329/347`; `fit_scorer.py:65`; `repositories/job.py:412`;
`lib/api/jobs.ts:34-35`) and **~24 downstream render/aggregate sites**, of which
21 are unreachable-by-design until UNGUARDED-3's storage gap is closed.
Round 3 was handed 1 of these 3.

## UNSURE — filed, not guessed
**UNSURE-1 — UNGUARDED-3 remediation shape.** ADR-GMV4-001 permits "withheld
OR flagged".
 (A) *Withhold*: `FitScorerAgent` refuses to persist an untrusted score, leaving
     `fitScore` NULL; every downstream site already renders NULL honestly
     ("Pending"/"unscored"/"—"). Zero schema change, zero deploy risk.
     **But** `board_sweep.py:143,224,394,515` gates the autopilot on
     `fitScore IS NOT NULL`, so a degraded window would silently HALT the
     autopilot — repeating precisely the pipeline-killing mistake ADR-GMV4-001
     ¶1 cites (`FabricationError`, commit `56552e0`) as already paid for.
 (B) *Flag*: persist provenance next to the number — additive
     `Job."fitScoreDegraded" boolean` (+ lazy idempotent DDL, Prisma schema,
     serializer, `lib/api/jobs.ts`, ~10 render sites). ADR-compliant, keeps the
     autopilot alive, but is a schema change requiring `migrator` + a deploy,
     neither of which this round is authorised to do (brief: "Do NOT commit.
     Do NOT deploy.").
 Round-4 action: (B) is the ADR-correct shape; it is **filed for orchestrator
 ruling + a migrator dispatch**, NOT guessed at here. Nothing in this round
 hides it: it is the largest item in this inventory.
**UNSURE-2 — `resumes.py:194 requires_review`.** Derived from contaminated
 `overall`, but currently has NO frontend consumer, so it renders nothing
 false today. Left untouched rather than pre-emptively changed.
**UNSURE-3 — the `"unattested"` arm of `ConversionImpact`.** The round-2 rule
 ("an absent flag must read as NOT measured") is implemented for
 `semantic_path` and for `dimensions[].degraded` (fail-closed). It is NOT
 implemented for `conversionMetrics`, because five TRACKED vitest fixtures
 supply `conversionMetrics` with numbers and NO provenance keys and assert the
 numbers render:
   `app/dashboard/jobs/__tests__/tailor-score-refresh.test.tsx:92`
   `app/dashboard/resume/__tests__/conversion-banner.test.tsx:65`
   `__tests__/dashboard/resume-conversion-tooltip.test.tsx:71` (CONVERSION_METRICS)
   `__tests__/dashboard/resume-tailor-score-warning.test.tsx:113` and `:153`
 Failing closed there would turn all five RED, and §0.4 forbids the fixer
 touching tests. Both interpretations:
  (A) *Fail closed now* — strictly correct, matches the round-2 rule, breaks
      the 650-test vitest baseline this round is required to keep green.
  (B) *Three states* — `"measured"` / `"degraded"` / `"unattested"`, numbers
      present on the first two. IMPLEMENTED. `"unattested"` is unreachable
      from the live API (`tailor_agent.py::_compute_conversion_metrics` always
      emits all three flags [VERIFIED — read at HEAD b69481f]), so production
      is two-state; it exists only so legacy/mocked payloads are not
      relabelled as claiming "measured".
 To reach (A): `test-author` adds explicit `scoringDegraded/baselineDegraded/
 tailoredDegraded: false` to those five fixtures, then `"unattested"` collapses
 into `"degraded"` in `conversionImpactFrom` (one branch). Filed, not guessed.

---

## ROUND-4 OUTCOME (appended after the fix; the counts above are PRE-fix)
- **UNGUARDED-1 — FIXED.** `jobs/page.tsx` `startTailoring` now reads through
  `conversionImpactFrom`; a degraded run WITHHOLDS the score (`fitScore: null`)
  and FLAGS it (`fitScoreNotMeasured`), surfaced at the detail ring
  (`fit-score-not-measured-note`) and the apply gate
  (`gate-fit-not-measured-badge`).
- **UNGUARDED-2 — FIXED.** `jobs.py` "Role Alignment" and "Career Growth" now
  carry provenance; the panel note no longer names only three dimensions.
- **UNGUARDED-3 — NOT FIXED, ESCALATED** (see UNSURE-1). Needs an additive
  `Job."fitScoreDegraded"` column + orchestrator ruling. It is the single
  largest remaining hole in this defect class and is deliberately visible here
  rather than quietly omitted.
- **STRUCTURAL GUARD — ADDED.** `apps/web/src/lib/scoring/provenance.ts`
  (discriminated unions + fail-closed normalisers) and
  `jobs.py::_dimension(..., *, degraded)` (keyword-only, no default).
  Teeth proven: `GMV4-ats-002-round4-guard-teeth-*.txt`.
